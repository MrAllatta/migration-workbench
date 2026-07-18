"""Coda corpus pipeline adapter.

Implements the :class:`~profiler.pipeline.base.CorpusPipeline` protocol for
Coda data sources.  The adapter encapsulates all provider-specific API
interactions (Coda table listing, column metadata, row fetching, page canvas
export) while delegating the shared orchestration, scoring, and
artifact-naming conventions to the base pipeline machinery.

The entry point is :meth:`CodaCorpusAdapter.run`, which mirrors the
legacy :func:`~profiler.tools.coda_corpus.run_coda_corpus` signature
and phase lifecycle.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import requests
from django.core.management.base import CommandError

from connectors.coda_source import (
    column_has_formula,
    formula_text,
    get_doc,
    list_columns,
    list_rows,
    rows_to_grid,
)
from profiler.management.commands.profile_coda_table import summarize_coda_table
from profiler.pipeline.base import CorpusPipeline
from profiler.pipeline.utils import make_slug, write_json
from profiler.tools.coda_corpus import (
    auto_select_tables,
    build_coda_table_index,
    build_canvas_artifact_for_doc,
    collect_relationship_edges_from_summary,
    derive_column_candidates,
    enrich_coda_columns,
    enrich_table_row_counts,
    finalize_relationship_summary,
    load_coda_docs_from_config,
    list_tables_for_config,
    select_tables_from_inventory,
    apply_table_selection_overrides,
)

logger = logging.getLogger(__name__)


class CodaCorpusAdapter(CorpusPipeline):
    """Coda-specific adapter for the corpus profiling pipeline.

    Args:
        session: Authenticated :class:`requests.Session` for the Coda API.
        resume_from_table_selection: Skip to deep profiling using an existing
            table selection file.
        stop_before_deep: Stop after table selection without entering the
            deep profile phase.
    """

    def __init__(
        self,
        *,
        session: requests.Session,
        resume_from_table_selection: bool = False,
        stop_before_deep: bool = False,
    ) -> None:
        self.session = session
        self.resume_from_table_selection = resume_from_table_selection
        self.stop_before_deep = stop_before_deep

    # ------------------------------------------------------------------
    # Phase 1 — Discovery
    # ------------------------------------------------------------------

    def discover(self, config: dict[str, Any]) -> dict[str, Any]:
        """Enumerate sources and containers via Coda doc inspection.

        Args:
            config: Parsed corpus configuration dict.

        Returns:
            Discovery payload with doc list and table metadata.
        """
        doc_entries = load_coda_docs_from_config(self.session, config)
        discovery_docs: list[dict[str, Any]] = []
        for display_name, doc_id in doc_entries:
            doc_meta_full = get_doc(self.session, doc_id)
            tables = list_tables_for_config(self.session, doc_id, config)
            tables = enrich_table_row_counts(self.session, doc_id, tables)
            discovery_docs.append(
                {
                    "name": display_name,
                    "doc_id": doc_id,
                    "doc_meta": {
                        "id": doc_meta_full.get("id"),
                        "name": doc_meta_full.get("name"),
                        "updatedAt": doc_meta_full.get("updatedAt"),
                        "docSize": doc_meta_full.get("docSize"),
                    },
                    "tables": tables,
                }
            )
        return {"docs": discovery_docs}

    # ------------------------------------------------------------------
    # Phase 2 — Indexing
    # ------------------------------------------------------------------

    def build_index(
        self, discovery: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any]:
        """Filter and organize discovery results into a canonical index.

        Args:
            discovery: Output from :meth:`discover`.
            config: Parsed corpus configuration dict.

        Returns:
            Index payload with base_tables and views split.
        """
        discovery_docs = discovery.get("docs", [])
        return build_coda_table_index(discovery_docs)

    # ------------------------------------------------------------------
    # Phase 3 — Broad profile
    # ------------------------------------------------------------------

    def broad_profile(
        self, index: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any]:
        """Fetch column metadata for every base table.

        Args:
            index: Output from :meth:`build_index`.
            config: Parsed corpus configuration dict.

        Returns:
            Broad-profile payload with enriched table metadata.
        """
        base_tables = index.get("base_tables", [])
        broad_tables: list[dict[str, Any]] = []
        for bt in base_tables:
            try:
                cols = list_columns(self.session, bt["doc_id"], bt["table_id"])
            except Exception as exc:  # noqa: BLE001
                broad_tables.append(
                    {**bt, "columns": None, "error": f"{type(exc).__name__}: {exc}"}
                )
                continue
            broad_tables.append(
                {
                    **bt,
                    "columns": [
                        {
                            "id": c.get("id"),
                            "name": c.get("name"),
                            "format_type": (c.get("format") or {}).get("type"),
                            "has_formula": column_has_formula(c),
                            "formula_preview": (
                                (formula_text(c)[:200] + "\u2026")
                                if len(formula_text(c)) > 200
                                else formula_text(c)
                            ),
                        }
                        for c in cols
                    ],
                    "column_count": len(cols),
                    "error": None,
                }
            )
        return {"tables": broad_tables}

    # ------------------------------------------------------------------
    # Phase 4 — Selection
    # ------------------------------------------------------------------

    def select(
        self,
        broad_profile: dict[str, Any],
        index: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Score, shortlist, auto-select, and apply overrides for Coda tables.

        Args:
            broad_profile: Output from :meth:`broad_profile`.
            index: Output from :meth:`build_index`.
            config: Parsed corpus configuration dict.

        Returns:
            Selection payload including ``approved_tables`` mapping.
        """
        base_tables = index.get("base_tables", [])
        broad_tables = broad_profile.get("tables", [])
        table_auto_limit = int(config.get("table_auto_limit", 5))

        # Backfill columnCount for scoring
        for bt in base_tables:
            match = next(
                (b for b in broad_tables if b.get("table_id") == bt.get("table_id")),
                None,
            )
            if match and match.get("column_count") is not None:
                bt["columnCount"] = match.get("column_count")

        table_score_heuristics = (config.get("heuristics") or {}).get(
            "table_score"
        ) or {}
        shortlist = select_tables_from_inventory(
            base_tables,
            table_score_heuristics=table_score_heuristics,
        )

        if self.resume_from_table_selection:
            approved_tables = self._load_table_selection(
                Path(config["_out_dir"]), config["_date_stamp"]
            )
            overrides = None
        else:
            heuristic_tables = auto_select_tables(shortlist, per_doc=table_auto_limit)
            overrides = config.get("table_selection_overrides")
            approved_tables = apply_table_selection_overrides(
                heuristic_tables, overrides
            )

        return {
            "approved_tables": approved_tables,
            "shortlist": shortlist,
            "overrides": overrides,
        }

    def _load_table_selection(
        self,
        out_dir: Path,
        date_stamp: str,
    ) -> dict[str, list[str]]:
        """Load hand-edited table selection from disk.

        Args:
            out_dir: Output directory for artifacts.
            date_stamp: Timestamp suffix.

        Returns:
            ``{doc_name: [table_name, ...]}`` mapping.

        Raises:
            CommandError: If the selection file is missing or malformed.
        """
        table_selection_path = out_dir / f"table_selection_{date_stamp}.json"
        if not table_selection_path.exists():
            raise CommandError(
                f"--resume-from-table-selection requires existing "
                f"{table_selection_path}; none found"
            )
        try:
            existing = json.loads(
                table_selection_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as exc:
            raise CommandError(
                f"Could not parse {table_selection_path}: {exc}"
            ) from exc
        approved_tables = existing.get("approved_tables")
        if not isinstance(approved_tables, dict) or not all(
            isinstance(k, str)
            and isinstance(v, list)
            and all(isinstance(t, str) for t in v)
            for k, v in approved_tables.items()
        ):
            raise CommandError(
                f"{table_selection_path} must contain 'approved_tables' "
                "as dict[str, list[str]]"
            )
        return approved_tables

    # ------------------------------------------------------------------
    # Phase 5 — Deep profile
    # ------------------------------------------------------------------

    def deep_profile(
        self,
        selection: dict[str, Any],
        index: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Detailed per-table analysis via Coda API calls.

        Args:
            selection: Output from :meth:`select`.
            index: Output from :meth:`build_index`.
            config: Parsed corpus configuration dict.

        Returns:
            Deep-profile payload with per-table results, column candidates,
            and relationship edges.
        """
        approved_tables = selection["approved_tables"]
        discovery_docs = selection.get("_discovery_docs", [])
        max_rows_deep = int(config.get("max_rows_deep", 500))
        column_score_heuristics = (config.get("heuristics") or {}).get(
            "column_score"
        ) or {}
        deep_dir = Path(config["_out_dir"]) / "deep"

        name_to_doc_id = {d["name"]: d["doc_id"] for d in discovery_docs}
        deep_results: list[dict[str, Any]] = []
        candidate_columns: list[dict[str, Any]] = []
        relationship_edges: list[dict[str, Any]] = []

        for doc_display_name, table_names in approved_tables.items():
            doc_id = name_to_doc_id.get(doc_display_name)
            if not doc_id:
                continue
            tables_in_doc = (
                next(
                    (
                        d["tables"]
                        for d in discovery_docs
                        if d["name"] == doc_display_name
                    ),
                    [],
                )
                or []
            )
            doc_title = doc_id
            try:
                doc_title = get_doc(self.session, doc_id).get("name") or doc_id
            except Exception:  # noqa: BLE001
                pass

            for table_name in table_names:
                match_tb = next(
                    (
                        t
                        for t in tables_in_doc
                        if t.get("name") == table_name
                        or t.get("id") == table_name
                    ),
                    None,
                )
                if not match_tb:
                    deep_results.append(
                        {
                            "doc_name": doc_display_name,
                            "table_name": table_name,
                            "exit_code": 1,
                            "error": "table not found in discovery",
                            "out_json": None,
                        }
                    )
                    continue
                tid = match_tb.get("id")
                if not tid:
                    continue
                try:
                    columns = list_columns(self.session, doc_id, tid)
                    rows = list_rows(
                        self.session, doc_id, tid, max_rows=max_rows_deep
                    )
                    grid = rows_to_grid(columns, rows)
                    summary = summarize_coda_table(
                        doc_title,
                        str(tid),
                        str(match_tb.get("name") or tid),
                        columns,
                        rows,
                        grid,
                        focus_col=None,
                        table_meta=match_tb,
                    )
                    slug_doc = make_slug(doc_display_name)
                    slug_tb = make_slug(str(match_tb.get("name") or tid))
                    out_path = deep_dir / f"{slug_doc}_{slug_tb}.json"
                    write_json(
                        out_path,
                        {
                            "summary": summary,
                            "columns_raw": columns,
                            "rows_sample": rows[:50],
                        },
                    )
                    deep_results.append(
                        {
                            "doc_name": doc_display_name,
                            "table_name": str(match_tb.get("name") or tid),
                            "out_json": str(out_path),
                            "exit_code": 0,
                            "error": None,
                        }
                    )
                    candidate_columns.extend(
                        derive_column_candidates(
                            doc_name=doc_display_name,
                            table_name=str(match_tb.get("name") or tid),
                            summary=summary,
                            column_score_heuristics=column_score_heuristics,
                        )
                    )
                    relationship_edges.extend(
                        collect_relationship_edges_from_summary(
                            doc_display_name,
                            doc_id,
                            str(tid),
                            str(match_tb.get("name") or tid),
                            summary,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    deep_results.append(
                        {
                            "doc_name": doc_display_name,
                            "table_name": str(
                                match_tb.get("name") or table_name
                            ),
                            "out_json": None,
                            "exit_code": 1,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

        return {
            "deep_results": deep_results,
            "candidate_columns": candidate_columns,
            "relationship_edges": relationship_edges,
        }

    # ------------------------------------------------------------------
    # Phase 6 — Column candidates
    # ------------------------------------------------------------------

    def derive_columns(
        self, deep_results: dict[str, Any], config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Extract and score column candidates from deep profile results.

        Args:
            deep_results: Output from :meth:`deep_profile`.
            config: Parsed corpus configuration dict.

        Returns:
            List of column candidate dicts.
        """
        # Columns are already derived during deep_profile for Coda.
        return deep_results.get("candidate_columns", [])

    # ------------------------------------------------------------------
    # Phase 6b — Column enrichment
    # ------------------------------------------------------------------

    def enrich_columns(self, columns: list[dict[str, Any]]) -> None:
        """Enrich column candidates in-place with Coda-specific metadata.

        Args:
            columns: Column candidate dicts to mutate in-place.
        """
        enrich_coda_columns(columns)

    # ------------------------------------------------------------------
    # Phase 7 — Canvas (Coda-specific optional phase)
    # ------------------------------------------------------------------

    def build_canvas(
        self,
        config: dict[str, Any],
        discovery_docs: list[dict[str, Any]],
        out_dir: Path,
        date_stamp: str,
    ) -> Path | None:
        """Export page plain text from all discovered docs (Coda-specific).

        Args:
            config: Parsed corpus configuration dict.
            discovery_docs: Discovery payload docs list.
            out_dir: Output directory.
            date_stamp: Timestamp suffix.

        Returns:
            Path to the canvas artifact, or ``None`` if canvas is disabled.
        """
        canvas_cfg = config.get("canvas")
        if not isinstance(canvas_cfg, dict) or not canvas_cfg.get("enabled"):
            return None
        doc_entries = [
            (d["name"], d["doc_id"]) for d in discovery_docs if d.get("doc_id")
        ]
        canvas_docs_payload: list[dict[str, Any]] = []
        for display_name, doc_id in doc_entries:
            canvas_docs_payload.append(
                build_canvas_artifact_for_doc(
                    self.session, display_name, doc_id, canvas_cfg
                )
            )
        canvas_path = out_dir / f"coda_canvas_{date_stamp}.json"
        write_json(
            canvas_path,
            {"generated_at": date_stamp, "docs": canvas_docs_payload},
        )
        return canvas_path

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def run(
        self,
        config: dict[str, Any],
        out_dir: Path,
        date_stamp: str,
    ) -> dict[str, str]:
        """Execute the full Coda corpus pipeline and return artifact paths.

        Mirrors the legacy :func:`~profiler.tools.coda_corpus.run_coda_corpus`
        signature minus the session argument (it's stored on the adapter
        instance).

        Args:
            config: Parsed corpus configuration dict.
            out_dir: Directory where JSON artifacts are written.
            date_stamp: Timestamp suffix for artifact filenames.

        Returns:
            dict[str, str]: Mapping from artifact role to file path.
        """
        docs = config.get("docs") or []
        if not docs:
            from workbench.exceptions import command_error

            raise command_error(
                "Config must include a non-empty 'docs' list.",
                action="Add 'docs': [{'name': 'My Doc', 'doc_id': '...'}] "
                "to the corpus config.",
                check_id="PROFILER-CODA-002",
            )

        discovery_path = out_dir / f"coda_discovery_{date_stamp}.json"
        index_path = out_dir / f"coda_table_index_{date_stamp}.json"
        broad_path = out_dir / f"coda_broad_profile_{date_stamp}.json"
        shortlist_path = out_dir / f"table_shortlist_{date_stamp}.json"
        table_selection_path = out_dir / f"table_selection_{date_stamp}.json"

        # Discovery
        discovery = self.discover(config)
        discovery_docs = discovery["docs"]
        write_json(discovery_path, discovery)

        # Index
        index = self.build_index(discovery, config)
        index_payload = {
            "generated_from": discovery_path.name,
            **index,
        }
        write_json(index_path, index_payload)

        # Broad profile
        broad = self.broad_profile(index, config)
        broad_tables = broad["tables"]
        write_json(
            broad_path,
            {"generated_from": index_path.name, "tables": broad_tables},
        )

        config_with_meta = dict(config)
        config_with_meta["_out_dir"] = str(out_dir)
        config_with_meta["_date_stamp"] = date_stamp

        selection = self.select(broad, index, config_with_meta)
        approved_tables = selection["approved_tables"]
        shortlist = selection["shortlist"]

        write_json(
            shortlist_path,
            {
                "generated_from": broad_path.name,
                "candidate_count": len(shortlist),
                "selected": shortlist,
            },
        )

        selection_overrides = selection["overrides"]
        payload: dict[str, Any] = {
            "policy": (
                "heuristic table selection (table_selection_overrides applied)"
                if selection_overrides
                else "heuristic table selection"
            ),
            "approved_tables": approved_tables,
        }
        if selection_overrides:
            payload["overrides_applied"] = selection_overrides
        write_json(table_selection_path, payload)

        artifacts: dict[str, str] = {
            "discovery": str(discovery_path),
            "index": str(index_path),
            "broad_profile": str(broad_path),
            "table_shortlist": str(shortlist_path),
            "table_selection": str(table_selection_path),
        }
        if self.stop_before_deep:
            return artifacts

        # Deep profile
        deep = self.deep_profile(
            {
                "approved_tables": approved_tables,
                "_discovery_docs": discovery_docs,
            },
            index,
            config_with_meta,
        )
        deep_results = deep["deep_results"]
        candidate_columns = deep["candidate_columns"]
        relationship_edges = deep["relationship_edges"]

        deep_coverage_path = out_dir / f"coda_deep_coverage_{date_stamp}.json"
        write_json(
            deep_coverage_path,
            {
                "job_count": len(deep_results),
                "success_count": sum(
                    1 for row in deep_results if row["exit_code"] == 0
                ),
                "failure_count": sum(
                    1 for row in deep_results if row["exit_code"] != 0
                ),
                "results": deep_results,
            },
        )

        # Enrichment
        self.enrich_columns(candidate_columns)

        # Relationship summary
        relationship_path = (
            out_dir / f"coda_relationship_summary_{date_stamp}.json"
        )
        write_json(
            relationship_path,
            finalize_relationship_summary(relationship_edges),
        )

        # Canvas (optional Coda-specific phase)
        canvas_path = self.build_canvas(
            config, discovery_docs, out_dir, date_stamp
        )

        # Column deduplication and final selection
        column_min_score = int(config.get("column_min_score", 3))
        deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
        for candidate in candidate_columns:
            key = (
                candidate["doc_name"],
                candidate["table_name"],
                candidate["proposed_canonical_field"],
            )
            previous = deduped.get(key)
            if previous is None or candidate["priority_score"] > previous["priority_score"]:  # noqa: E501
                deduped[key] = candidate

        selected_columns = sorted(
            [
                row
                for row in deduped.values()
                if row["priority_score"] >= column_min_score
            ],
            key=lambda row: (
                -row["priority_score"],
                row["doc_name"],
                row["table_name"],
                row["proposed_canonical_field"],
            ),
        )

        column_shortlist_path = (
            out_dir / f"column_shortlist_{date_stamp}.json"
        )
        write_json(
            column_shortlist_path,
            {
                "generated_from": deep_coverage_path.name,
                "candidate_count": len(deduped),
                "selected_count": len(selected_columns),
                "selected": selected_columns,
            },
        )

        column_selection_path = (
            out_dir / f"column_selection_{date_stamp}.json"
        )
        write_json(
            column_selection_path,
            {
                "policy": "auto-approved columns above min score",
                "selected_count": len(selected_columns),
            },
        )

        out: dict[str, str] = {
            "discovery": str(discovery_path),
            "index": str(index_path),
            "broad_profile": str(broad_path),
            "table_shortlist": str(shortlist_path),
            "table_selection": str(table_selection_path),
            "deep_coverage": str(deep_coverage_path),
            "relationship_summary": str(relationship_path),
            "column_shortlist": str(column_shortlist_path),
            "column_selection": str(column_selection_path),
        }
        if canvas_path is not None:
            out["canvas"] = str(canvas_path)
        return out
