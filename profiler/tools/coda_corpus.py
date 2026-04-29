from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests
from django.core.management.base import CommandError

from connectors.coda_source import (
    analyze_column_values,
    build_coda_session,
    collect_page_content_items,
    column_has_formula,
    export_page_markdown,
    formula_text,
    get_doc,
    get_table,
    list_columns,
    list_pages,
    list_rows,
    list_tables,
    page_content_items_to_plain_text,
    resolve_doc_id,
    rows_to_grid,
)
from profiler.management.commands.profile_coda_table import summarize_coda_table


def make_slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return slug[:50] or "table"


def score_table(
    table_name: str,
    row_count: int | None,
    col_count: int | None,
    *,
    table_score_heuristics: dict[str, Any] | None = None,
) -> tuple[int, list[str]]:
    heuristics = table_score_heuristics or {}
    prefer = [
        str(x).lower()
        for x in (heuristics.get("prefer_keywords") or [])
        if isinstance(x, str)
    ]
    deprioritize = [
        str(x).lower()
        for x in (heuristics.get("deprioritize_keywords") or [])
        if isinstance(x, str)
    ]

    lowered = (table_name or "").lower()
    score = 0
    reasons: list[str] = []

    if prefer and any(k in lowered for k in prefer):
        score += 3
        reasons.append("prefer_keyword")
    if deprioritize and any(k in lowered for k in deprioritize):
        score -= 2
        reasons.append("deprioritize_keyword")

    rows = int(row_count or 0)
    cols = int(col_count or 0)
    cells = rows * cols
    if cells >= 50_000:
        score += 2
        reasons.append("large_grid")
    elif cells >= 10_000:
        score += 1
        reasons.append("medium_grid")
    if rows >= 1000:
        score += 1
        reasons.append("many_rows")
    if cols >= 20:
        score += 1
        reasons.append("wide_table")
    return score, reasons


def build_coda_table_index(discovery_docs: list[dict[str, Any]]) -> dict[str, Any]:
    base_tables: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []
    for doc in discovery_docs:
        doc_name = doc.get("name") or doc.get("doc_id")
        doc_id = doc.get("doc_id")
        for t in doc.get("tables") or []:
            tid = t.get("id")
            if not tid:
                continue
            entry = {
                "doc_name": doc_name,
                "doc_id": doc_id,
                "table_id": tid,
                "table_name": t.get("name"),
                "type": t.get("type"),
                "rowCount": t.get("rowCount"),
                "columnCount": t.get("columnCount"),
                "parentTable": t.get("parentTable"),
                "parent_page": t.get("parent"),
            }
            if str(t.get("type") or "").lower() == "view":
                entry["is_importable"] = False
                views.append(entry)
            else:
                entry["is_importable"] = True
                base_tables.append(entry)
    return {"base_tables": base_tables, "views": views}


TABLE_SELECTION_OVERRIDE_KEYS = frozenset({"add", "remove", "replace", "tables"})


def apply_table_selection_overrides(
    approved_tables: dict[str, list[str]],
    overrides: dict[str, Any] | None,
) -> dict[str, list[str]]:
    """Merge user overrides into *approved_tables* (keys are doc names from config)."""
    merged: dict[str, list[str]] = {
        name: list(tabs) for name, tabs in approved_tables.items()
    }
    if not overrides:
        return merged
    if not isinstance(overrides, dict):
        raise CommandError(
            "table_selection_overrides must be a mapping of doc_name to override entry"
        )

    for doc_name, entry in overrides.items():
        if not isinstance(entry, dict):
            raise CommandError(
                f"table_selection_overrides[{doc_name!r}] must be a mapping; got {type(entry).__name__}"
            )
        unknown = set(entry.keys()) - TABLE_SELECTION_OVERRIDE_KEYS
        if unknown:
            raise CommandError(
                f"table_selection_overrides[{doc_name!r}] has unknown keys: {sorted(unknown)}"
            )

        if entry.get("replace"):
            tabs = entry.get("tables")
            if not isinstance(tabs, list) or not all(
                isinstance(item, str) for item in tabs
            ):
                raise CommandError(
                    f"table_selection_overrides[{doc_name!r}] requires 'tables' as list[str] when 'replace' is true"
                )
            merged[doc_name] = list(tabs)
            continue

        if "tables" in entry:
            raise CommandError(
                f"table_selection_overrides[{doc_name!r}] uses 'tables' without 'replace: true'"
            )

        add = entry.get("add", []) or []
        remove = entry.get("remove", []) or []
        if not isinstance(add, list) or not all(isinstance(item, str) for item in add):
            raise CommandError(
                f"table_selection_overrides[{doc_name!r}].add must be a list of strings"
            )
        if not isinstance(remove, list) or not all(
            isinstance(item, str) for item in remove
        ):
            raise CommandError(
                f"table_selection_overrides[{doc_name!r}].remove must be a list of strings"
            )

        current = merged.get(doc_name, [])
        remove_set = set(remove)
        kept = [tab for tab in current if tab not in remove_set]
        for tab in add:
            if tab not in kept:
                kept.append(tab)
        merged[doc_name] = kept

    return merged


def select_tables_from_inventory(
    base_tables: list[dict[str, Any]],
    *,
    min_final_score: float = 0.0,
    table_score_heuristics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for row in base_tables:
        name = str(row.get("table_name") or row.get("table_id") or "")
        rc = row.get("rowCount")
        cc = row.get("columnCount")
        score, reasons = score_table(
            name, rc, cc, table_score_heuristics=table_score_heuristics
        )
        final_score = float(score)
        confidence = (
            "high" if final_score >= 4 else "medium" if final_score >= 2 else "low"
        )
        if final_score < min_final_score:
            continue
        scored.append(
            {
                **row,
                "score": score,
                "reasons": reasons,
                "final_score": round(final_score, 2),
                "confidence": confidence,
            }
        )
    scored.sort(
        key=lambda r: (
            -r["final_score"],
            str(r.get("doc_name") or ""),
            str(r.get("table_name") or ""),
        )
    )
    return scored


def auto_select_tables(
    shortlist: list[dict[str, Any]],
    *,
    per_doc: int = 5,
) -> dict[str, list[str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in shortlist:
        dn = str(row.get("doc_name") or "doc")
        grouped[dn].append(row)
    approved: dict[str, list[str]] = {}
    for doc_name, rows in grouped.items():
        rows.sort(
            key=lambda r: (
                -float(r.get("final_score", 0)),
                str(r.get("table_name") or ""),
            )
        )
        approved[doc_name] = [
            str(r.get("table_name") or r.get("table_id")) for r in rows[:per_doc]
        ]
    return approved


def _normalize_column_heuristics(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config or {}
    return {
        "domain_keyword_tokens": [
            token.lower()
            for token in (config.get("domain_keyword_tokens") or [])
            if isinstance(token, str)
        ]
    }


def derive_column_candidates(
    *,
    doc_name: str,
    table_name: str,
    summary: dict[str, Any],
    column_score_heuristics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    heuristics = _normalize_column_heuristics(column_score_heuristics)
    domain_keyword_tokens = heuristics["domain_keyword_tokens"]
    candidates: list[dict[str, Any]] = []
    for col in summary.get("columns") or []:
        header = str(col.get("name") or "")
        if not header:
            continue
        lowered = header.lower()
        score = 0
        reasons: list[str] = []
        if domain_keyword_tokens and any(
            token in lowered for token in domain_keyword_tokens
        ):
            score += 3
            reasons.append("domain_keyword")
        if col.get("is_relation_type") or (col.get("ref_tables_seen") or []):
            score += 2
            reasons.append("relation_or_ref")
        if col.get("has_formula"):
            score += 1
            reasons.append("formula_column")
        canonical = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
        candidates.append(
            {
                "doc_name": doc_name,
                "table_name": table_name,
                "column_name": header,
                "proposed_canonical_field": canonical,
                "priority_score": score,
                "priority_reasons": reasons,
                "evidence": {
                    "null_rate": col.get("null_rate"),
                    "unique_count_sample": col.get("unique_count_sample"),
                    "format_type": col.get("format_type"),
                    "ref_tables_seen": col.get("ref_tables_seen"),
                },
            }
        )
    return candidates


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def load_coda_docs_from_config(
    session: requests.Session, config: dict[str, Any]
) -> list[tuple[str, str]]:
    docs = config.get("docs") or []
    if not docs:
        raise CommandError("Config must include a non-empty 'docs' list")
    resolved: list[tuple[str, str]] = []
    for item in docs:
        name = str(item.get("name") or "doc")
        raw = item.get("doc_url") or item.get("doc_id")
        doc_id = resolve_doc_id(session, raw) if raw else None
        if not doc_id:
            raise CommandError(f"doc {name!r} needs doc_url or doc_id")
        resolved.append((name, doc_id))
    return resolved


def list_tables_for_config(
    session: requests.Session, doc_id: str, config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Respect *exclude_views* (wins over *table_types*) and optional *table_types*."""
    if config.get("exclude_views"):
        return list_tables(session, doc_id, exclude_views=True)
    tt = config.get("table_types")
    if isinstance(tt, list) and tt:
        return list_tables(session, doc_id, table_types=[str(x) for x in tt])
    return list_tables(session, doc_id)


def enrich_table_row_counts(
    session: requests.Session, doc_id: str, tables: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fill missing ``rowCount`` via ``GET …/tables/{id}``."""
    out: list[dict[str, Any]] = []
    for t in tables:
        tid = t.get("id")
        if not tid or t.get("rowCount") is not None:
            out.append(t)
            continue
        try:
            detail = get_table(session, doc_id, str(tid))
        except Exception:  # noqa: BLE001
            out.append(t)
            continue
        merged = dict(t)
        if detail.get("rowCount") is not None:
            merged["rowCount"] = detail["rowCount"]
        out.append(merged)
    return out


def collect_relationship_edges_from_summary(
    doc_name: str,
    doc_id: str,
    from_table_id: str,
    from_table_name: str,
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for col in summary.get("columns") or []:
        cname = col.get("name")
        for ref in col.get("ref_tables_seen") or []:
            tid = ref.get("tableId")
            if not tid:
                continue
            edges.append(
                {
                    "doc_name": doc_name,
                    "doc_id": doc_id,
                    "from_table_id": from_table_id,
                    "from_table_name": from_table_name,
                    "from_column": cname,
                    "to_table_id": tid,
                    "to_table_name": ref.get("tableName"),
                }
            )
    return edges


def finalize_relationship_summary(
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    uniq_links: dict[tuple[str, str, str], dict[str, Any]] = {}
    for e in edges:
        key = (e["doc_id"], e["from_table_id"], e["to_table_id"])
        if key not in uniq_links:
            uniq_links[key] = {
                "doc_id": e["doc_id"],
                "from_table_name": e["from_table_name"],
                "from_table_id": e["from_table_id"],
                "to_table_id": e["to_table_id"],
                "to_table_name": e["to_table_name"],
            }
    return {
        "edge_count": len(edges),
        "unique_table_link_count": len(uniq_links),
        "edges": edges,
        "unique_table_links": sorted(
            uniq_links.values(),
            key=lambda x: (x["doc_id"], x["from_table_id"], x["to_table_id"]),
        ),
    }


def build_canvas_artifact_for_doc(
    session: requests.Session,
    doc_display_name: str,
    doc_id: str,
    canvas_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Pull plain text per page (or markdown export) for summarization pipelines."""
    max_pages = int(canvas_cfg.get("max_pages") or 50)
    max_chars = int(canvas_cfg.get("max_chars_per_page") or 50_000)
    max_items = int(canvas_cfg.get("max_content_items") or 5000)
    use_export = bool(canvas_cfg.get("use_export"))
    all_pages = list_pages(session, doc_id)
    pages_out: list[dict[str, Any]] = []
    for p in all_pages[:max_pages]:
        pid = p.get("id")
        pname = p.get("name")
        text = ""
        err: str | None = None
        try:
            if use_export:
                text = export_page_markdown(session, doc_id, str(pid))
            else:
                items = collect_page_content_items(
                    session,
                    doc_id,
                    str(pid),
                    max_items=max_items,
                )
                text = page_content_items_to_plain_text(items)
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…[truncated]"
            truncated = True
        pages_out.append(
            {
                "id": pid,
                "name": pname,
                "plain_text": text,
                "truncated": truncated,
                "error": err,
                "browserLink": p.get("browserLink"),
            }
        )
    return {
        "doc_name": doc_display_name,
        "doc_id": doc_id,
        "pages": pages_out,
    }


def run_coda_corpus(
    *,
    session: requests.Session,
    config: dict[str, Any],
    out_dir: Path,
    date_stamp: str,
    resume_from_table_selection: bool = False,
) -> dict[str, str]:
    heuristics_config = config.get("heuristics") or {}
    table_score_heuristics = heuristics_config.get("table_score") or {}
    column_score_heuristics = heuristics_config.get("column_score") or {}
    table_auto_limit = int(config.get("table_auto_limit", 5))
    max_rows_deep = int(config.get("max_rows_deep", 500))
    column_min_score = int(config.get("column_min_score", 3))

    discovery_path = out_dir / f"coda_discovery_{date_stamp}.json"
    index_path = out_dir / f"coda_table_index_{date_stamp}.json"

    doc_entries = load_coda_docs_from_config(session, config)
    discovery_docs: list[dict[str, Any]] = []
    for display_name, doc_id in doc_entries:
        doc_meta_full = get_doc(session, doc_id)
        tables = list_tables_for_config(session, doc_id, config)
        tables = enrich_table_row_counts(session, doc_id, tables)
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
    write_json(
        discovery_path,
        {"generated_at": date_stamp, "docs": discovery_docs},
    )

    index_payload = build_coda_table_index(discovery_docs)
    write_json(index_path, {"generated_from": discovery_path.name, **index_payload})

    broad_tables: list[dict[str, Any]] = []
    for bt in index_payload["base_tables"]:
        try:
            cols = list_columns(session, bt["doc_id"], bt["table_id"])
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
                            (formula_text(c)[:200] + "…")
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

    broad_path = out_dir / f"coda_broad_profile_{date_stamp}.json"
    write_json(
        broad_path,
        {"generated_from": index_path.name, "tables": broad_tables},
    )

    for bt in index_payload["base_tables"]:
        match = next(
            (b for b in broad_tables if b.get("table_id") == bt.get("table_id")), None
        )
        if match and match.get("column_count") is not None:
            bt["columnCount"] = match.get("column_count")

    shortlist = select_tables_from_inventory(
        index_payload["base_tables"],
        table_score_heuristics=table_score_heuristics,
    )
    shortlist_path = out_dir / f"table_shortlist_{date_stamp}.json"
    write_json(
        shortlist_path,
        {
            "generated_from": broad_path.name,
            "candidate_count": len(shortlist),
            "selected": shortlist,
        },
    )

    table_selection_path = out_dir / f"table_selection_{date_stamp}.json"
    if resume_from_table_selection:
        if not table_selection_path.exists():
            raise CommandError(
                f"--resume-from-table-selection requires existing {table_selection_path}; none found"
            )
        try:
            existing = json.loads(table_selection_path.read_text(encoding="utf-8"))
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
                f"{table_selection_path} must contain 'approved_tables' as dict[str, list[str]]"
            )
    else:
        heuristic_tables = auto_select_tables(shortlist, per_doc=table_auto_limit)
        overrides = config.get("table_selection_overrides")
        approved_tables = apply_table_selection_overrides(heuristic_tables, overrides)
        payload: dict[str, Any] = {
            "policy": (
                "heuristic table selection (table_selection_overrides applied)"
                if overrides
                else "heuristic table selection"
            ),
            "approved_tables": approved_tables,
        }
        if overrides:
            payload["overrides_applied"] = overrides
        write_json(table_selection_path, payload)

    deep_dir = out_dir / "deep"
    deep_results: list[dict[str, Any]] = []
    candidate_columns: list[dict[str, Any]] = []
    relationship_edges: list[dict[str, Any]] = []

    name_to_doc_id = {d["name"]: d["doc_id"] for d in discovery_docs}

    for doc_display_name, table_names in approved_tables.items():
        doc_id = name_to_doc_id.get(doc_display_name)
        if not doc_id:
            continue
        tables_in_doc = (
            next(
                (d["tables"] for d in discovery_docs if d["name"] == doc_display_name),
                [],
            )
            or []
        )
        doc_title = doc_id
        try:
            doc_title = get_doc(session, doc_id).get("name") or doc_id
        except Exception:  # noqa: BLE001
            pass

        for table_name in table_names:
            match_tb = next(
                (
                    t
                    for t in tables_in_doc
                    if t.get("name") == table_name or t.get("id") == table_name
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
                columns = list_columns(session, doc_id, tid)
                rows = list_rows(session, doc_id, tid, max_rows=max_rows_deep)
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
                        "table_name": str(match_tb.get("name") or table_name),
                        "out_json": None,
                        "exit_code": 1,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    deep_coverage_path = out_dir / f"coda_deep_coverage_{date_stamp}.json"
    write_json(
        deep_coverage_path,
        {
            "job_count": len(deep_results),
            "success_count": sum(1 for row in deep_results if row["exit_code"] == 0),
            "failure_count": sum(1 for row in deep_results if row["exit_code"] != 0),
            "results": deep_results,
        },
    )

    relationship_path = out_dir / f"coda_relationship_summary_{date_stamp}.json"
    write_json(
        relationship_path,
        finalize_relationship_summary(relationship_edges),
    )

    canvas_path: Path | None = None
    canvas_cfg = config.get("canvas")
    if isinstance(canvas_cfg, dict) and canvas_cfg.get("enabled"):
        canvas_docs_payload: list[dict[str, Any]] = []
        for display_name, doc_id in doc_entries:
            canvas_docs_payload.append(
                build_canvas_artifact_for_doc(session, display_name, doc_id, canvas_cfg)
            )
        canvas_path = out_dir / f"coda_canvas_{date_stamp}.json"
        write_json(
            canvas_path,
            {"generated_at": date_stamp, "docs": canvas_docs_payload},
        )

    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for candidate in candidate_columns:
        key = (
            candidate["doc_name"],
            candidate["table_name"],
            candidate["proposed_canonical_field"],
        )
        previous = deduped.get(key)
        if previous is None or candidate["priority_score"] > previous["priority_score"]:
            deduped[key] = candidate

    selected_columns = sorted(
        [row for row in deduped.values() if row["priority_score"] >= column_min_score],
        key=lambda row: (
            -row["priority_score"],
            row["doc_name"],
            row["table_name"],
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
