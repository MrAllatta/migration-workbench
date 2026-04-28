from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from django.core.management.base import CommandError

from profiler.management.commands.profile_tab import fetch_tab_grid, list_tabs, summarize_tab

YEAR_RE = re.compile(r"\b(20\d{2})\b")
CODE_RE = re.compile(r"\b(\d{3})\b")


def build_multiyear_index(discovery_payload: dict, in_scope_codes: set[str]) -> list[dict]:
    records: list[dict] = []

    def walk(node: dict, path_parts: list[str]):
        name = node.get("name") or node.get("id") or ""
        current = path_parts + ([name] if name else [])
        folder_year = None
        for part in reversed(current):
            match = YEAR_RE.search(part)
            if match:
                folder_year = int(match.group(1))
                break

        for sheet in node.get("spreadsheets", []):
            sheet_name = sheet.get("name", "")
            code_match = CODE_RE.search(sheet_name)
            if not code_match:
                continue
            code = code_match.group(1)
            if code not in in_scope_codes:
                continue
            year = folder_year
            if year is None:
                year_match = YEAR_RE.search(sheet_name)
                year = int(year_match.group(1)) if year_match else None
            records.append(
                {
                    "year": year,
                    "workbook_code": code,
                    "spreadsheet_id": sheet.get("id"),
                    "spreadsheet_name": sheet_name,
                    "folder_path": "/".join(current),
                    "modified_time": sheet.get("modifiedTime"),
                    "tab_count": len(sheet.get("tabs") or []),
                }
            )

        for sub in node.get("folders", []):
            walk(sub, current)

    walk(discovery_payload, [])
    records.sort(key=lambda row: ((row["year"] or 0), row["workbook_code"], row["spreadsheet_name"]))
    return records


def score_tab(title: str, rows: int, cols: int) -> tuple[int, list[str]]:
    lowered = title.lower()
    score = 0
    reasons: list[str] = []

    if any(
        token in lowered
        for token in (
            "planner",
            "plan",
            "harvest",
            "field walk",
            "orders",
            "market",
            "records",
            "crop info",
            "formats",
            "block map",
            "step 3",
            "seed order",
        )
    ):
        score += 3
        reasons.append("operational_tab_name")
    # Reference tabs are often small but feed validations/lookups.
    if ("define" in lowered and "term" in lowered) or "reference" in lowered:
        score += 3
        reasons.append("reference_lookup_tab_name")
    if any(
        token in lowered for token in ("staging", "pivot", "summary", "print", "workflow", "welcome", "index", "reports>>>", "data>>>")
    ):
        score -= 2
        reasons.append("likely_support_tab")

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
        reasons.append("wide_sheet")
    return score, reasons


def select_tabs_from_inventory(index_records: list[dict], inventory_rows: list[dict], *, min_final_score: float = 2.0) -> list[dict]:
    by_sheet_id = {record["spreadsheet_id"]: record for record in index_records}
    scored: list[dict] = []
    for row in inventory_rows:
        meta = by_sheet_id.get(row["spreadsheet_id"])
        if meta is None:
            continue
        score, reasons = score_tab(row["tab_title"], row["rows"], row["cols"])
        scored.append(
            {
                "year": meta["year"],
                "workbook_code": meta["workbook_code"],
                "spreadsheet_id": row["spreadsheet_id"],
                "spreadsheet_name": meta["spreadsheet_name"],
                "tab_title": row["tab_title"],
                "sheet_id": row["sheet_id"],
                "rows": row["rows"],
                "cols": row["cols"],
                "score": score,
                "reasons": reasons,
            }
        )

    aggregate: dict[tuple[str, str], dict] = {}
    for entry in scored:
        key = (entry["workbook_code"], entry["tab_title"])
        bucket = aggregate.setdefault(
            key,
            {
                "workbook_code": entry["workbook_code"],
                "tab_title": entry["tab_title"],
                "occurrences": 0,
                "years": set(),
                "scores": [],
                "rows_max": 0,
                "cols_max": 0,
                "examples": [],
            },
        )
        bucket["occurrences"] += 1
        bucket["years"].add(entry["year"])
        bucket["scores"].append(entry["score"])
        bucket["rows_max"] = max(bucket["rows_max"], entry["rows"])
        bucket["cols_max"] = max(bucket["cols_max"], entry["cols"])
        if len(bucket["examples"]) < 3:
            bucket["examples"].append({"year": entry["year"], "spreadsheet_id": entry["spreadsheet_id"]})

    selected: list[dict] = []
    for bucket in aggregate.values():
        avg_score = sum(bucket["scores"]) / len(bucket["scores"])
        coverage_bonus = 1 if len(bucket["years"]) >= 3 else 0
        final_score = avg_score + coverage_bonus
        confidence = "high" if final_score >= 3 else "medium" if final_score >= 2 else "low"
        if final_score < min_final_score:
            continue
        selected.append(
            {
                "workbook_code": bucket["workbook_code"],
                "tab_title": bucket["tab_title"],
                "years": sorted(year for year in bucket["years"] if year is not None),
                "occurrences": bucket["occurrences"],
                "avg_score": round(avg_score, 2),
                "coverage_bonus": coverage_bonus,
                "final_score": round(final_score, 2),
                "confidence": confidence,
                "rows_max": bucket["rows_max"],
                "cols_max": bucket["cols_max"],
                "examples": bucket["examples"],
            }
        )
    selected.sort(key=lambda row: (-row["final_score"], row["workbook_code"], row["tab_title"]))
    return selected


def auto_gate_tabs(tab_shortlist: list[dict], *, per_workbook: int = 3) -> dict[str, list[str]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in tab_shortlist:
        grouped[row["workbook_code"]].append(row)
    approved: dict[str, list[str]] = {}
    for workbook_code, rows in grouped.items():
        rows.sort(key=lambda row: (-row["final_score"], -row["occurrences"], row["tab_title"]))
        approved[workbook_code] = [row["tab_title"] for row in rows[:per_workbook]]
    return approved


GATE1_OVERRIDE_KEYS = frozenset({"add", "remove", "replace", "tabs"})


def apply_gate1_overrides(
    approved_tabs: dict[str, list[str]],
    overrides: dict | None,
) -> dict[str, list[str]]:
    """Merge user-supplied gate1 overrides into heuristic approved_tabs.

    Each override entry supports either a delta form (``add``/``remove``) or a
    full replace form (``replace: true`` with ``tabs``). Heuristic order is
    preserved; ``add`` entries already present are not duplicated.
    """
    merged: dict[str, list[str]] = {code: list(tabs) for code, tabs in approved_tabs.items()}
    if not overrides:
        return merged

    if not isinstance(overrides, dict):
        raise CommandError("gate1_overrides must be a mapping of workbook_code to override entry")

    for workbook_code, entry in overrides.items():
        if not isinstance(entry, dict):
            raise CommandError(
                f"gate1_overrides[{workbook_code!r}] must be a mapping; got {type(entry).__name__}"
            )
        unknown = set(entry.keys()) - GATE1_OVERRIDE_KEYS
        if unknown:
            raise CommandError(
                f"gate1_overrides[{workbook_code!r}] has unknown keys: {sorted(unknown)}"
            )

        if entry.get("replace"):
            tabs = entry.get("tabs")
            if not isinstance(tabs, list) or not all(isinstance(item, str) for item in tabs):
                raise CommandError(
                    f"gate1_overrides[{workbook_code!r}] requires 'tabs' as list[str] when 'replace' is true"
                )
            merged[workbook_code] = list(tabs)
            continue

        if "tabs" in entry:
            raise CommandError(
                f"gate1_overrides[{workbook_code!r}] uses 'tabs' without 'replace: true'"
            )

        add = entry.get("add", []) or []
        remove = entry.get("remove", []) or []
        if not isinstance(add, list) or not all(isinstance(item, str) for item in add):
            raise CommandError(
                f"gate1_overrides[{workbook_code!r}].add must be a list of strings"
            )
        if not isinstance(remove, list) or not all(isinstance(item, str) for item in remove):
            raise CommandError(
                f"gate1_overrides[{workbook_code!r}].remove must be a list of strings"
            )

        current = merged.get(workbook_code, [])
        remove_set = set(remove)
        kept = [tab for tab in current if tab not in remove_set]
        for tab in add:
            if tab not in kept:
                kept.append(tab)
        merged[workbook_code] = kept

    return merged


def make_slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return slug[:50] or "tab"


def derive_column_candidates(*, workbook_code: str, year: int | None, spreadsheet_id: str, tab_title: str, payload: dict) -> list[dict]:
    summary = payload.get("summary", {})
    raw = payload.get("raw", {})
    formula_count = int(summary.get("formula_cell_count") or 0)
    functions = [name for name, _count in summary.get("functions_used", [])][:8]

    headers: list[tuple[str, str]] = []
    try:
        sheet = raw["sheets"][0]
        for block in sheet.get("data", []):
            if block.get("startRow", 0) != 0:
                continue
            values = (block.get("rowData") or [{}])[0].get("values") or []
            start_col = block.get("startColumn", 0)
            for idx, value in enumerate(values):
                header = (value.get("formattedValue") or "").strip()
                if not header:
                    continue
                col_index = start_col + idx
                n = col_index + 1
                col_letter = ""
                while n > 0:
                    n, remainder = divmod(n - 1, 26)
                    col_letter = chr(65 + remainder) + col_letter
                headers.append((col_letter, header))
            if headers:
                break
    except (KeyError, IndexError, TypeError):
        return []

    candidates: list[dict] = []
    for col_letter, header in headers[:40]:
        lowered = header.lower()
        score = 0
        reasons: list[str] = []
        if any(
            token in lowered
            for token in (
                "date",
                "week",
                "year",
                "crop",
                "product",
                "mix",
                "format",
                "qty",
                "quantity",
                "yield",
                "harvest",
                "seed",
                "block",
                "bed",
                "order",
                "market",
                "channel",
                "price",
                "customer",
            )
        ):
            score += 3
            reasons.append("domain_keyword")
        if formula_count > 100:
            score += 1
            reasons.append("formula_rich_tab")
        if functions:
            score += 1
            reasons.append("function_usage_present")
        canonical = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
        candidates.append(
            {
                "workbook_code": workbook_code,
                "year": year,
                "spreadsheet_id": spreadsheet_id,
                "tab_title": tab_title,
                "column_letter": col_letter,
                "column_header": header,
                "proposed_canonical_field": canonical,
                "priority_score": score,
                "priority_reasons": reasons,
                "evidence": {"formula_cell_count": formula_count, "functions_used": functions},
            }
        )
    return candidates


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_tab_inventory_output(text: str) -> list[dict]:
    pattern = re.compile(r"^\[(\s*\d+)\]\s+sheetId=\s*([0-9]+)\s+rows=\s*([0-9]+)\s+cols=\s*([0-9]+)\s+(.+)$")
    rows: list[dict] = []
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        _index, sheet_id, row_count, col_count, tab_title = match.groups()
        rows.append(
            {
                "sheet_id": int(sheet_id),
                "rows": int(row_count),
                "cols": int(col_count),
                "tab_title": tab_title,
            }
        )
    return rows


def run_multiyear(
    *,
    drive_service,
    sheets_service,
    config: dict,
    out_dir: Path,
    date_stamp: str,
    resume_from_gate1: bool = False,
) -> dict:
    from profiler.management.commands.profile_drive_folder import walk_folder

    folder_id = config.get("folder_id")
    if not folder_id:
        raise CommandError("Config must include 'folder_id'")
    in_scope_codes = set(config.get("in_scope_workbooks") or [])
    if not in_scope_codes:
        raise CommandError("Config must include non-empty 'in_scope_workbooks'")

    include_tabs = not bool(config.get("discovery_no_tabs"))
    tree = walk_folder(drive_service, sheets_service, folder_id, include_tabs=include_tabs, max_depth=config.get("max_depth"))
    discovery_payload = {"id": folder_id, "name": config.get("folder_name") or folder_id, **tree}
    discovery_path = out_dir / f"drive_discovery_{date_stamp}.json"
    write_json(discovery_path, discovery_payload)

    index_records = build_multiyear_index(discovery_payload, in_scope_codes)
    index_path = out_dir / f"in_scope_workbook_index_{date_stamp}.json"
    write_json(index_path, {"generated_from": discovery_path.name, "record_count": len(index_records), "records": index_records})

    inventory_rows: list[dict] = []
    broad_results: list[dict] = []
    for record in index_records:
        spreadsheet_id = record["spreadsheet_id"]
        try:
            tabs = list_tabs(sheets_service, spreadsheet_id)
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

    broad_path = out_dir / f"multi_year_broad_profile_coverage_{date_stamp}.json"
    write_json(
        broad_path,
        {
            "generated_from": index_path.name,
            "run_count": len(broad_results),
            "success_count": sum(1 for row in broad_results if row["exit_code"] == 0),
            "failure_count": sum(1 for row in broad_results if row["exit_code"] != 0),
            "results": broad_results,
        },
    )

    tab_shortlist = select_tabs_from_inventory(index_records, inventory_rows)
    tab_shortlist_path = out_dir / f"tab_shortlist_{date_stamp}.json"
    write_json(
        tab_shortlist_path,
        {
            "generated_from": broad_path.name,
            "candidate_count": len({(row["workbook_code"], row["tab_title"]) for row in tab_shortlist}),
            "selected_count": len(tab_shortlist),
            "selected": tab_shortlist,
        },
    )

    gate_1_path = out_dir / f"tab_approval_gate1_{date_stamp}.json"
    if resume_from_gate1:
        if not gate_1_path.exists():
            raise CommandError(
                f"--resume-from-gate1 requires existing {gate_1_path}; none found"
            )
        try:
            existing = json.loads(gate_1_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Could not parse {gate_1_path}: {exc}") from exc
        approved_tabs = existing.get("approved_tabs")
        if not isinstance(approved_tabs, dict) or not all(
            isinstance(code, str)
            and isinstance(tabs, list)
            and all(isinstance(tab, str) for tab in tabs)
            for code, tabs in approved_tabs.items()
        ):
            raise CommandError(
                f"{gate_1_path} must contain 'approved_tabs' as dict[str, list[str]]"
            )
    else:
        heuristic_tabs = auto_gate_tabs(tab_shortlist, per_workbook=int(config.get("tab_auto_limit", 3)))
        overrides = config.get("gate1_overrides")
        approved_tabs = apply_gate1_overrides(heuristic_tabs, overrides)
        gate_1_payload: dict = {
            "policy": (
                "auto-approved top tabs per workbook (gate1_overrides applied)"
                if overrides
                else "auto-approved top tabs per workbook"
            ),
            "approved_tabs": approved_tabs,
        }
        if overrides:
            gate_1_payload["overrides_applied"] = overrides
        write_json(gate_1_path, gate_1_payload)

    deep_results: list[dict] = []
    candidate_columns: list[dict] = []
    deep_dir = out_dir / "deep"
    for record in index_records:
        for tab_title in approved_tabs.get(record["workbook_code"], []):
            try:
                payload = fetch_tab_grid(sheets_service, record["spreadsheet_id"], tab_title)
                summary = summarize_tab(payload)
                out_path = deep_dir / f"{record['workbook_code']}_{record['year']}_{record['spreadsheet_id'][:8]}_{make_slug(tab_title)}.json"
                write_json(out_path, {"raw": payload, "summary": summary})
                deep_results.append(
                    {
                        "year": record["year"],
                        "workbook_code": record["workbook_code"],
                        "spreadsheet_id": record["spreadsheet_id"],
                        "tab_title": tab_title,
                        "out_json": str(out_path.relative_to(out_dir.parent)),
                        "exit_code": 0,
                        "error": None,
                    }
                )
                candidate_columns.extend(
                    derive_column_candidates(
                        workbook_code=record["workbook_code"],
                        year=record["year"],
                        spreadsheet_id=record["spreadsheet_id"],
                        tab_title=tab_title,
                        payload={"raw": payload, "summary": summary},
                    )
                )
            except Exception as exc:  # noqa: BLE001
                deep_results.append(
                    {
                        "year": record["year"],
                        "workbook_code": record["workbook_code"],
                        "spreadsheet_id": record["spreadsheet_id"],
                        "tab_title": tab_title,
                        "out_json": None,
                        "exit_code": 1,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    deep_coverage_path = out_dir / f"deep_profile_coverage_{date_stamp}.json"
    write_json(
        deep_coverage_path,
        {
            "job_count": len(deep_results),
            "success_count": sum(1 for row in deep_results if row["exit_code"] == 0),
            "failure_count": sum(1 for row in deep_results if row["exit_code"] != 0),
            "results": deep_results,
        },
    )

    deduped: dict[tuple[str, str, str], dict] = {}
    for candidate in candidate_columns:
        key = (candidate["workbook_code"], candidate["tab_title"], candidate["proposed_canonical_field"])
        previous = deduped.get(key)
        if previous is None or candidate["priority_score"] > previous["priority_score"]:
            deduped[key] = candidate
    selected_columns = sorted(
        [row for row in deduped.values() if row["priority_score"] >= int(config.get("column_min_score", 4))],
        key=lambda row: (-row["priority_score"], row["workbook_code"], row["tab_title"], row["proposed_canonical_field"]),
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
    gate_2_path = out_dir / f"column_approval_gate2_{date_stamp}.json"
    write_json(gate_2_path, {"policy": "auto-approved columns above min score", "selected_count": len(selected_columns)})

    return {
        "discovery": str(discovery_path),
        "index": str(index_path),
        "broad_coverage": str(broad_path),
        "tab_shortlist": str(tab_shortlist_path),
        "gate1": str(gate_1_path),
        "deep_coverage": str(deep_coverage_path),
        "column_shortlist": str(column_shortlist_path),
        "gate2": str(gate_2_path),
    }

