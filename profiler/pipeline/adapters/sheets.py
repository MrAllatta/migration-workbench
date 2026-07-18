"""Google Sheets corpus pipeline adapter.

Implements the :class:`~profiler.pipeline.base.CorpusPipeline` protocol for
Google Drive / Sheets data sources.  The adapter encapsulates all
provider-specific API interactions (Drive folder tree walks, Sheets tab
grid fetches, HTTP 429 retry logic) while delegating the shared
orchestration, scoring, and artifact-naming conventions to the base
pipeline machinery.

The entry point is :meth:`SheetsCorpusAdapter.run`, which mirrors the
legacy :func:`~profiler.tools.cohort_corpus.run_cohort_corpus` signature
and phase lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from django.core.management.base import CommandError
from googleapiclient.errors import HttpError

from profiler.management.commands.profile_drive_folder import walk_folder
from profiler.management.commands.profile_tab import (
    fetch_tab_grid,
    list_tabs,
    summarize_tab,
)
from profiler.pipeline.base import CorpusPipeline
from profiler.pipeline.selection import (
    apply_tab_selection_overrides,
    auto_select_tabs,
)
from profiler.pipeline.utils import (
    make_slug,
    normalize_column_heuristics as _normalize_column_heuristics,
    write_json,
)
from profiler.tools.cohort_corpus import (
    DEFAULT_WORKBOOK_ID_PATTERN,
    DEFAULT_YEAR_PATTERN,
    _corpus_regex_from_config,
    build_cohort_corpus_index,
    derive_column_candidates,
    enrich_computed_fields,
    enrich_entity_groupings,
    enrich_fk_candidates,
    enrich_import_key_candidates,
    select_tabs_from_inventory,
    _render_corpus_summary,
)
from profiler.tools.domain_context import (
    DomainContext,
    deduplicate_index_records,
    has_meaningful_vocabulary,
    load_domain_context,
)

logger = logging.getLogger(__name__)


class SheetsCorpusAdapter(CorpusPipeline):
    """Sheets-specific adapter for the corpus profiling pipeline.

    Args:
        drive_service: Authenticated Google Drive API service object.
        sheets_service: Authenticated Google Sheets API service object.
        resume_from_tab_selection: Phase 3 resume mode.
        resume_from_broad: Phase 2 resume mode.
        stop_before_deep: Stop after tab selection, skip deep profiling.
        skip_existing_deep: Reuse cached deep profile files.
        folder_id: Google Drive folder id for discovery.
    """

    def __init__(
        self,
        *,
        drive_service: Any,
        sheets_service: Any,
        resume_from_tab_selection: bool = False,
        resume_from_broad: bool = False,
        stop_before_deep: bool = False,
        skip_existing_deep: bool = False,
        folder_id: str | None = None,
    ) -> None:
        self.drive_service = drive_service
        self.sheets_service = sheets_service
        self.resume_from_tab_selection = resume_from_tab_selection
        self.resume_from_broad = resume_from_broad
        self.stop_before_deep = stop_before_deep
        self.skip_existing_deep = skip_existing_deep
        self.folder_id = folder_id

    # ------------------------------------------------------------------
    # Phase 1 — Discovery
    # ------------------------------------------------------------------

    def discover(self, config: dict[str, Any]) -> dict[str, Any]:
        """Enumerate sources and containers via Drive folder tree walk.

        Args:
            config: Parsed corpus configuration dict.

        Returns:
            Discovery payload with folder tree and spreadsheet listings.
        """
        folder_id = self.folder_id
        if folder_id is None:
            raise CommandError(
                "A Drive folder_id is required for the Sheets corpus pipeline. "
                "Provide folder_id in the corpus config or via --folder-id."
            )
        include_tabs = not bool(config.get("discovery_no_tabs"))
        tree = walk_folder(
            self.drive_service,
            self.sheets_service,
            folder_id,
            include_tabs=include_tabs,
            max_depth=config.get("max_depth"),
        )
        return {
            "id": folder_id,
            "name": config.get("folder_name") or folder_id,
            **tree,
        }

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
            Index payload with in-scope workbook records.
        """
        in_scope_codes = set(config.get("in_scope_workbooks") or [])
        workbook_id_re = _corpus_regex_from_config(
            config, "workbook_id_regex", DEFAULT_WORKBOOK_ID_PATTERN
        )
        year_re = _corpus_regex_from_config(config, "year_regex", DEFAULT_YEAR_PATTERN)
        records = build_cohort_corpus_index(
            discovery,
            in_scope_codes,
            workbook_id_re=workbook_id_re,
            year_re=year_re,
        )
        return {"records": records}

    # ------------------------------------------------------------------
    # Phase 3 — Broad profile
    # ------------------------------------------------------------------

    def broad_profile(
        self, index: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any]:
        """Lightweight metadata scan of each in-scope spreadsheet.

        Args:
            index: Output from :meth:`build_index`.
            config: Parsed corpus configuration dict.

        Returns:
            Broad-profile payload with tab inventory rows.
        """
        index_records = index["records"]
        inventory_rows: list[dict] = []
        broad_results: list[dict] = []
        for record in index_records:
            spreadsheet_id = record["spreadsheet_id"]
            try:
                tabs = list_tabs(self.sheets_service, spreadsheet_id)
                broad_results.append(
                    {
                        "year": record["year"],
                        "workbook_code": record["workbook_code"],
                        "spreadsheet_id": spreadsheet_id,
                        "spreadsheet_name": record["spreadsheet_name"],
                        "tab_count": len(tabs),
                        "exit_code": 0,
                        "error": None,
                    }
                )
                for tab in tabs:
                    inventory_rows.append(
                        {
                            "spreadsheet_id": spreadsheet_id,
                            "sheet_id": tab["sheet_id"],
                            "rows": tab["rows"] or 0,
                            "cols": tab["cols"] or 0,
                            "tab_title": tab["title"],
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                broad_results.append(
                    {
                        "year": record["year"],
                        "workbook_code": record["workbook_code"],
                        "spreadsheet_id": spreadsheet_id,
                        "spreadsheet_name": record["spreadsheet_name"],
                        "tab_count": 0,
                        "exit_code": 1,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "results": broad_results,
            "inventory_rows": inventory_rows,
        }

    # ------------------------------------------------------------------
    # Phase 4 — Selection
    # ------------------------------------------------------------------

    def select(
        self,
        broad_profile: dict[str, Any],
        index: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Score, shortlist, auto-select, and apply overrides.

        Args:
            broad_profile: Output from :meth:`broad_profile`.
            index: Output from :meth:`build_index`.
            config: Parsed corpus configuration dict.

        Returns:
            Selection payload including ``approved_tabs`` mapping.
        """
        index_records = index["records"]
        inventory_rows = broad_profile["inventory_rows"]
        heuristics_config = config.get("heuristics") or {}
        tab_score_heuristics = heuristics_config.get("tab_score") or {}
        domain_context = self._load_domain_context(config)

        tab_shortlist = select_tabs_from_inventory(
            index_records,
            inventory_rows,
            tab_score_heuristics=tab_score_heuristics,
            domain_context=domain_context,
            per_workbook_heuristic_overrides=(
                config.get("per_workbook_heuristic_overrides") or {}
            ),
        )
        selection_summary: dict = {
            "by_workbook_by_year": {},
            "candidate_count": len(tab_shortlist),
        }
        if domain_context is not None:
            by_wb_by_year: dict[str, dict[str, int]] = defaultdict(
                lambda: defaultdict(int)
            )
            for row in tab_shortlist:
                for yr in row.get("years", []):
                    by_wb_by_year[row["workbook_code"]][str(yr)] = (
                        by_wb_by_year[row["workbook_code"]].get(str(yr), 0) + 1
                    )
            selection_summary["by_workbook_by_year"] = {
                wb: dict(years) for wb, years in by_wb_by_year.items()
            }
            dup_total = sum(len(r.get("duplicate_years", [])) for r in tab_shortlist)
            if dup_total:
                selection_summary["deduplication_note"] = (
                    f"{dup_total} structural duplicates collapsed via latest_year strategy"
                )

        heuristic_tabs, tab_details = auto_select_tabs(
            tab_shortlist,
            per_workbook=int(config.get("tab_auto_limit", 3)),
            per_code_overrides=config.get("tab_auto_limit_overrides"),
            score_cutoff=config.get("score_cutoff"),
        )
        overrides = config.get("tab_selection_overrides")
        approved_tabs = apply_tab_selection_overrides(heuristic_tabs, overrides)
        return {
            "approved_tabs": approved_tabs,
            "tab_details": tab_details,
            "tab_shortlist": tab_shortlist,
            "selection_summary": selection_summary,
            "overrides": overrides,
        }

    # ------------------------------------------------------------------
    # Phase 5 — Deep profile
    # ------------------------------------------------------------------

    def deep_profile(
        self,
        selection: dict[str, Any],
        index: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Detailed per-tab analysis via grid fetch and summarisation.

        Args:
            selection: Output from :meth:`select`.
            index: Output from :meth:`build_index`.
            config: Parsed corpus configuration dict.

        Returns:
            Deep-profile payload with per-tab results and artifact paths.
        """
        approved_tabs = selection["approved_tabs"]
        index_records = index["records"]
        heuristics_config = config.get("heuristics") or {}
        column_score_heuristics = heuristics_config.get("column_score") or {}
        domain_context = self._load_domain_context(config)
        out_dir = Path(config["_out_dir"])
        date_stamp = config["_date_stamp"]
        skip_existing_deep = self.skip_existing_deep or bool(
            config.get("deep_skip_existing")
        )
        deep_read_delay_seconds = float(config.get("deep_read_delay_seconds") or 0.5)
        deep_dir = out_dir / "deep"
        deep_dir.mkdir(parents=True, exist_ok=True)

        deep_results: list[dict] = []
        candidate_columns: list[dict] = []

        _429_cooldown_seconds = float(config.get("deep_read_429_cooldown") or 60.0)
        _429_max_cooldowns = int(config.get("deep_read_429_max_cooldowns") or 5)
        _429_cooldown_count = 0
        _429_abort = False

        index_records = deduplicate_index_records(
            index_records, approved_tabs, domain_context
        )

        latest_year_by_workbook: dict[str, int] = {}
        for rec in index_records:
            wb = rec["workbook_code"]
            yr = rec.get("year") or 0
            if yr > latest_year_by_workbook.get(wb, 0):
                latest_year_by_workbook[wb] = yr

        dedup_trace: dict[str, dict] = {}
        # Year-aware tab validation from broad coverage
        known_tabs: set[tuple[str, str]] = set()
        broad_path = out_dir / f"broad_profile_coverage_{date_stamp}.json"
        if broad_path.exists():
            try:
                broad_payload = json.loads(broad_path.read_text(encoding="utf-8"))
                for inventory_row in broad_payload.get("inventory_rows", []):
                    known_tabs.add(
                        (inventory_row["spreadsheet_id"], inventory_row["tab_title"])
                    )
            except (json.JSONDecodeError, KeyError):
                pass

        for record in index_records:
            if _429_abort:
                break
            wb = record["workbook_code"]
            yr = record.get("year") or 0
            for tab_title in approved_tabs.get(wb, []):
                if (
                    known_tabs
                    and (record["spreadsheet_id"], tab_title) not in known_tabs
                ):
                    continue
                if domain_context is not None:
                    is_exception = domain_context.is_deduplication_exception(tab_title)
                    if not is_exception and yr != latest_year_by_workbook.get(wb, 0):
                        continue
                    trace_entry = dedup_trace.setdefault(
                        wb,
                        {
                            "latest_year": latest_year_by_workbook.get(wb),
                            "profiled_all_years": [],
                            "profiled_latest_only": [],
                        },
                    )
                    target_list = (
                        "profiled_all_years" if is_exception else "profiled_latest_only"
                    )
                    if tab_title not in trace_entry[target_list]:
                        trace_entry[target_list].append(tab_title)
                tab_hash = hashlib.sha1(tab_title.encode()).hexdigest()[:8]
                out_path = (
                    deep_dir
                    / f"{record['workbook_code']}_{record['year']}_{record['spreadsheet_id'][:8]}_{make_slug(tab_title)}_{tab_hash}.json"
                )
                if skip_existing_deep and out_path.exists():
                    try:
                        cached_deep_payload = json.loads(
                            out_path.read_text(encoding="utf-8")
                        )
                        cached_grid_payload = cached_deep_payload.get("raw")
                        cached_tab_summary = cached_deep_payload.get("summary")
                    except json.JSONDecodeError:
                        cached_grid_payload = None
                        cached_tab_summary = None
                    if (
                        cached_grid_payload is not None
                        and cached_tab_summary is not None
                    ):
                        resolved_out_json = str(out_path.relative_to(out_dir.parent))
                        deep_results.append(
                            {
                                "year": record["year"],
                                "workbook_code": record["workbook_code"],
                                "spreadsheet_id": record["spreadsheet_id"],
                                "tab_title": tab_title,
                                "out_json": resolved_out_json,
                                "exit_code": 0,
                                "error": None,
                                "reused_cached_deep": True,
                            }
                        )
                        candidate_columns.extend(
                            derive_column_candidates(
                                workbook_code=record["workbook_code"],
                                year=record["year"],
                                spreadsheet_id=record["spreadsheet_id"],
                                tab_title=tab_title,
                                payload={
                                    "raw": cached_grid_payload,
                                    "summary": cached_tab_summary,
                                },
                                column_score_heuristics=column_score_heuristics,
                                domain_context=domain_context,
                            )
                        )
                        continue

                try:
                    if deep_read_delay_seconds > 0:
                        time.sleep(deep_read_delay_seconds)
                    payload_for_candidates = fetch_tab_grid(
                        self.sheets_service, record["spreadsheet_id"], tab_title
                    )
                    summary_for_candidates = summarize_tab(payload_for_candidates)
                    write_json(
                        out_path,
                        {
                            "raw": payload_for_candidates,
                            "summary": summary_for_candidates,
                        },
                    )
                    resolved_out_json = str(out_path.relative_to(out_dir.parent))
                    deep_results.append(
                        {
                            "year": record["year"],
                            "workbook_code": record["workbook_code"],
                            "spreadsheet_id": record["spreadsheet_id"],
                            "tab_title": tab_title,
                            "out_json": resolved_out_json,
                            "exit_code": 0,
                            "error": None,
                            "reused_cached_deep": False,
                        }
                    )
                    candidate_columns.extend(
                        derive_column_candidates(
                            workbook_code=record["workbook_code"],
                            year=record["year"],
                            spreadsheet_id=record["spreadsheet_id"],
                            tab_title=tab_title,
                            payload={
                                "raw": payload_for_candidates,
                                "summary": summary_for_candidates,
                            },
                            column_score_heuristics=column_score_heuristics,
                            domain_context=domain_context,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    is_429 = (
                        isinstance(exc, HttpError)
                        and getattr(exc.resp, "status", None) == 429
                    )
                    if is_429:
                        _429_cooldown_count += 1
                        if _429_cooldown_count <= _429_max_cooldowns:
                            sys.stderr.write(
                                f"429 received; cooling {_429_cooldown_seconds}s "
                                f"({_429_cooldown_count}/{_429_max_cooldowns})\n"
                            )
                            sys.stderr.flush()
                            time.sleep(_429_cooldown_seconds)
                            continue
                        deep_results.append(
                            {
                                "year": record["year"],
                                "workbook_code": record["workbook_code"],
                                "spreadsheet_id": record["spreadsheet_id"],
                                "tab_title": tab_title,
                                "out_json": None,
                                "exit_code": 1,
                                "error": (
                                    f"HttpError 429: exceeded {_429_max_cooldowns} "
                                    f"global cooldowns; aborting deep profile"
                                ),
                                "reused_cached_deep": False,
                            }
                        )
                        _429_abort = True
                        break
                    deep_results.append(
                        {
                            "year": record["year"],
                            "workbook_code": record["workbook_code"],
                            "spreadsheet_id": record["spreadsheet_id"],
                            "tab_title": tab_title,
                            "out_json": None,
                            "exit_code": 1,
                            "error": f"{type(exc).__name__}: {exc}",
                            "reused_cached_deep": False,
                        }
                    )

        return {
            "deep_results": deep_results,
            "candidate_columns": candidate_columns,
            "dedup_trace": dedup_trace,
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
        # Columns are already derived during deep_profile for Sheets.
        return deep_results.get("candidate_columns", [])

    # ------------------------------------------------------------------
    # Phase 6b — Column enrichment
    # ------------------------------------------------------------------

    def enrich_columns(self, columns: list[dict[str, Any]]) -> None:
        """Enrich column candidates in-place with computed / FK / key metadata.

        Args:
            columns: Column candidate dicts to mutate in-place.
        """
        enrich_computed_fields(columns)
        enrich_fk_candidates(columns, set())
        enrich_import_key_candidates(columns)
        enrich_entity_groupings(columns)

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def _load_domain_context(self, config: dict[str, Any]) -> DomainContext | None:
        """Load and validate domain context from config."""
        domain_context_path = config.get("domain_context")
        if not domain_context_path:
            return None
        domain_context = load_domain_context(domain_context_path)
        if domain_context is not None:
            logger.info("Domain context loaded: domain=%s", domain_context.domain)
        if not has_meaningful_vocabulary(domain_context):
            raise CommandError(
                "Profiler cannot proceed with empty vocabulary. "
                "FAIL[PROFILER_EMPTY_VOCABULARY]: Domain context vocabulary is empty. "
                "Action: Populate vocabulary.operational / vocabulary.reference "
                "in domain_context.yaml and re-run phase 1."
            )
        return domain_context

    def _load_resume_artifacts(
        self, config: dict[str, Any], out_dir: Path, date_stamp: str
    ) -> tuple[dict[str, Any], dict[str, Any], set[tuple[str, str]]]:
        """Load index and selection artifacts for resume modes.

        Returns:
            Tuple of (index_records, approved_tabs, known_tabs).
        """
        index_path = out_dir / f"in_scope_workbook_index_{date_stamp}.json"
        tab_selection_path = out_dir / f"tab_selection_{date_stamp}.json"
        broad_path = out_dir / f"broad_profile_coverage_{date_stamp}.json"
        known_tabs: set[tuple[str, str]] = set()

        if not tab_selection_path.exists():
            raise CommandError(
                f"--resume-from-tab-selection requires existing {tab_selection_path}; none found"
            )
        if not index_path.exists():
            raise CommandError(
                f"--resume-from-tab-selection requires existing {index_path} from an earlier "
                "full corpus run on the same --date-stamp/--out-dir. Run profile_cohort_corpus "
                "without the flag once, hand-edit tab_selection_<date>.json, then rerun with "
                "--resume-from-tab-selection."
            )
        try:
            existing_selection_payload = json.loads(
                tab_selection_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as exc:
            raise CommandError(f"Could not parse {tab_selection_path}: {exc}") from exc
        approved_tabs = existing_selection_payload.get("approved_tabs")
        if not isinstance(approved_tabs, dict) or not all(
            isinstance(workbook_code, str)
            and isinstance(selected_tab_titles, list)
            and all(
                isinstance(tab_title_entry, str)
                for tab_title_entry in selected_tab_titles
            )
            for workbook_code, selected_tab_titles in approved_tabs.items()
        ):
            raise CommandError(
                f"{tab_selection_path} must contain 'approved_tabs' as dict[str, list[str]]"
            )
        try:
            workbook_index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Could not parse {index_path}: {exc}") from exc
        index_records = workbook_index_payload.get("records")
        if not isinstance(index_records, list) or not index_records:
            raise CommandError(f"{index_path} must contain a non-empty 'records' list")
        required_index_keys = (
            "spreadsheet_id",
            "workbook_code",
            "year",
            "spreadsheet_name",
        )
        for row_index, index_row in enumerate(index_records):
            if not isinstance(index_row, dict) or not all(
                key in index_row for key in required_index_keys
            ):
                raise CommandError(
                    f"{index_path} records[{row_index}] is missing one of {required_index_keys!r}"
                )
        if broad_path.exists():
            try:
                broad_payload = json.loads(broad_path.read_text(encoding="utf-8"))
                for inventory_row in broad_payload.get("inventory_rows", []):
                    known_tabs.add(
                        (inventory_row["spreadsheet_id"], inventory_row["tab_title"])
                    )
            except (json.JSONDecodeError, KeyError):
                pass
        return index_records, approved_tabs, known_tabs

    def _load_broad_resume_artifacts(
        self, config: dict[str, Any], out_dir: Path, date_stamp: str
    ) -> tuple[list[dict], list[dict], set[tuple[str, str]]]:
        """Load broad coverage and index artifacts for resume-from-broad mode.

        Returns:
            Tuple of (index_records, inventory_rows, known_tabs).
        """
        broad_path = out_dir / f"broad_profile_coverage_{date_stamp}.json"
        index_path = out_dir / f"in_scope_workbook_index_{date_stamp}.json"
        known_tabs: set[tuple[str, str]] = set()

        if not broad_path.exists():
            raise CommandError(
                f"--resume-from-broad requires existing {broad_path}; none found"
            )
        if not index_path.exists():
            raise CommandError(
                f"--resume-from-broad requires existing {index_path} from an earlier "
                "discovery run. Run profile_cohort_corpus without resume flags first."
            )
        try:
            broad_payload = json.loads(broad_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Could not parse {broad_path}: {exc}") from exc
        inventory_rows = broad_payload.get("inventory_rows")
        if not isinstance(inventory_rows, list):
            raise CommandError(
                f"{broad_path} is missing 'inventory_rows' list. "
                "Re-run discovery without resume flags to regenerate in the new format."
            )
        for inventory_row in inventory_rows:
            known_tabs.add(
                (inventory_row["spreadsheet_id"], inventory_row["tab_title"])
            )
        try:
            workbook_index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Could not parse {index_path}: {exc}") from exc
        index_records = workbook_index_payload.get("records")
        if not isinstance(index_records, list) or not index_records:
            raise CommandError(f"{index_path} must contain a non-empty 'records' list")
        return index_records, inventory_rows, known_tabs

    def run(
        self,
        config: dict[str, Any],
        out_dir: Path,
        date_stamp: str,
    ) -> dict[str, str]:
        """Execute the full Sheets corpus pipeline and return artifact paths.

        Mirrors the legacy :func:`~profiler.tools.cohort_corpus.run_cohort_corpus`
        signature minus the service arguments (those are stored on the adapter
        instance).

        Args:
            config: Parsed corpus configuration dict.
            out_dir: Directory where JSON artifacts are written.
            date_stamp: Timestamp suffix for artifact filenames.

        Returns:
            dict[str, str]: Mapping from artifact role to file path.
        """
        in_scope_codes = set(config.get("in_scope_workbooks") or [])
        if not in_scope_codes:
            from workbench.exceptions import command_error

            raise command_error(
                "Config must include non-empty 'in_scope_workbooks'.",
                action="Add 'in_scope_workbooks': ['101', '201'] to the corpus config.",
                check_id="PROFILER-CONFIG-001",
            )

        if self.resume_from_tab_selection and self.resume_from_broad:
            raise CommandError(
                "Cannot combine --resume-from-tab-selection and --resume-from-broad; "
                "they are mutually exclusive."
            )
        if (
            not self.resume_from_tab_selection
            and not self.resume_from_broad
            and not self.folder_id
        ):
            from workbench.exceptions import command_error

            raise command_error(
                "folder_id is required when not in a resume mode.",
                action="Pass --folder or set DRIVE_FOLDER_ID in .env.",
                check_id="PROFILER-CONFIG-002",
            )

        heuristics_config = config.get("heuristics") or {}
        column_score_heuristics = heuristics_config.get("column_score") or {}

        discovery_path = out_dir / f"drive_discovery_{date_stamp}.json"
        index_path = out_dir / f"in_scope_workbook_index_{date_stamp}.json"
        broad_path = out_dir / f"broad_profile_coverage_{date_stamp}.json"
        tab_shortlist_path = out_dir / f"tab_shortlist_{date_stamp}.json"
        tab_selection_path = out_dir / f"tab_selection_{date_stamp}.json"

        known_tabs: set[tuple[str, str]] = set()

        if self.resume_from_tab_selection:
            index_records, approved_tabs, known_tabs = self._load_resume_artifacts(
                config, out_dir, date_stamp
            )

        elif self.resume_from_broad:
            index_records, inventory_rows, known_tabs = (
                self._load_broad_resume_artifacts(config, out_dir, date_stamp)
            )
            broad_for_select = {"inventory_rows": inventory_rows}
            index_for_select = {"records": index_records}
            selection = self.select(broad_for_select, index_for_select, config)
            tab_shortlist = selection["tab_shortlist"]
            selection_summary = selection["selection_summary"]
            overrides = selection["overrides"]
            approved_tabs = selection["approved_tabs"]
            tab_details = selection["tab_details"]

            write_json(
                tab_shortlist_path,
                {
                    "generated_from": broad_path.name,
                    "candidate_count": len(
                        {
                            (row["workbook_code"], row["tab_title"])
                            for row in tab_shortlist
                        }
                    ),
                    "selected_count": len(tab_shortlist),
                    "selected": tab_shortlist,
                    "selection_summary": selection_summary,
                },
            )

            tab_selection_payload: dict = {
                "policy": (
                    "heuristic tab selection (tab_selection_overrides applied)"
                    if overrides
                    else "heuristic tab selection"
                ),
                "approved_tabs": approved_tabs,
                "tab_details": tab_details,
            }
            if overrides:
                tab_selection_payload["overrides_applied"] = overrides
            write_json(tab_selection_path, tab_selection_payload)

        else:
            discovery = self.discover(config)
            write_json(discovery_path, discovery)

            index = self.build_index(discovery, config)
            index_records = index["records"]
            write_json(
                index_path,
                {
                    "generated_from": discovery_path.name,
                    "record_count": len(index_records),
                    "records": index_records,
                },
            )

            broad = self.broad_profile(index, config)
            inventory_rows = broad["inventory_rows"]
            broad_results = broad["results"]
            write_json(
                broad_path,
                {
                    "generated_from": index_path.name,
                    "run_count": len(broad_results),
                    "success_count": sum(
                        1 for row in broad_results if row["exit_code"] == 0
                    ),
                    "failure_count": sum(
                        1 for row in broad_results if row["exit_code"] != 0
                    ),
                    "results": broad_results,
                    "inventory_rows": inventory_rows,
                },
            )

            for inventory_row in inventory_rows:
                known_tabs.add(
                    (inventory_row["spreadsheet_id"], inventory_row["tab_title"])
                )

            selection = self.select(broad, index, config)
            tab_shortlist = selection["tab_shortlist"]
            selection_summary = selection["selection_summary"]
            overrides = selection["overrides"]
            approved_tabs = selection["approved_tabs"]
            tab_details = selection["tab_details"]

            write_json(
                tab_shortlist_path,
                {
                    "generated_from": broad_path.name,
                    "candidate_count": len(
                        {
                            (row["workbook_code"], row["tab_title"])
                            for row in tab_shortlist
                        }
                    ),
                    "selected_count": len(tab_shortlist),
                    "selected": tab_shortlist,
                    "selection_summary": selection_summary,
                },
            )

            tab_selection_payload: dict = {
                "policy": (
                    "heuristic tab selection (tab_selection_overrides applied)"
                    if overrides
                    else "heuristic tab selection"
                ),
                "approved_tabs": approved_tabs,
                "tab_details": tab_details,
            }
            if overrides:
                tab_selection_payload["overrides_applied"] = overrides
            write_json(tab_selection_path, tab_selection_payload)

        artifacts: dict[str, str] = {
            "discovery": str(discovery_path),
            "index": str(index_path),
            "broad_coverage": str(broad_path),
            "tab_shortlist": str(tab_shortlist_path),
            "tab_selection": str(tab_selection_path),
        }

        if self.stop_before_deep:
            return artifacts

        # Deep profile + column candidates
        config_with_meta = dict(config)
        config_with_meta["_out_dir"] = str(out_dir)
        config_with_meta["_date_stamp"] = date_stamp

        deep = self.deep_profile(
            {"approved_tabs": approved_tabs},
            {"records": index_records},
            config_with_meta,
        )
        deep_results = deep["deep_results"]
        candidate_columns = deep["candidate_columns"]
        dedup_trace = deep["dedup_trace"]

        deep_coverage_path = out_dir / f"deep_profile_coverage_{date_stamp}.json"
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
                "dedup_trace": dedup_trace,
            },
        )

        self.enrich_columns(candidate_columns)

        deduped: dict[tuple[str, str, str], dict] = {}
        for candidate in candidate_columns:
            key = (
                candidate["workbook_code"],
                candidate["tab_title"],
                candidate["proposed_canonical_field"],
            )
            previous = deduped.get(key)
            if (
                previous is None
                or candidate["priority_score"] > previous["priority_score"]
            ):
                deduped[key] = candidate
        column_heuristics = _normalize_column_heuristics(column_score_heuristics)
        default_min = 0 if not column_heuristics.get("domain_keyword_tokens") else 4
        min_score = int(config.get("column_min_score", default_min))
        selected_columns = sorted(
            [row for row in deduped.values() if row["priority_score"] >= min_score],
            key=lambda row: (
                -row["priority_score"],
                row["workbook_code"],
                row["tab_title"],
                row["proposed_canonical_field"],
            ),
        )

        column_shortlist_path = out_dir / f"column_shortlist_{date_stamp}.json"
        write_json(
            column_shortlist_path,
            {
                "generated_from": deep_coverage_path.name,
                "candidate_count": len(deduped),
                "selected_count": len(selected_columns),
                "selected": selected_columns,
            },
        )
        column_selection_path = out_dir / f"column_selection_{date_stamp}.json"
        write_json(
            column_selection_path,
            {
                "policy": "auto-approved columns above min score",
                "selected_count": len(selected_columns),
            },
        )

        summary_path = out_dir / f"corpus_summary_{date_stamp}.md"
        _render_corpus_summary(
            summary_path,
            deep_results=deep_results,
            candidate_columns=candidate_columns,
            selected_columns=selected_columns,
            approved_tabs=approved_tabs,
        )

        return {
            "discovery": str(discovery_path),
            "index": str(index_path),
            "broad_coverage": str(broad_path),
            "tab_shortlist": str(tab_shortlist_path),
            "tab_selection": str(tab_selection_path),
            "deep_coverage": str(deep_coverage_path),
            "column_shortlist": str(column_shortlist_path),
            "column_selection": str(column_selection_path),
            "corpus_summary": str(summary_path),
        }
