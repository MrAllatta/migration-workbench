"""Multi-workbook Google Sheets profiling pipeline (cohort corpus mode).

Orchestrates a full corpus run over a Drive folder hierarchy containing a
cohort of workbooks whose **ids and years** are extracted via configurable
regexes (defaults match e.g. ``"101_FarmPlan_2023"`` — see ``workbook_id_regex``
and ``year_regex`` in the corpus config):

1. **Discovery** — walk the Drive folder tree, listing all spreadsheets and
   their tabs.
2. **Indexing** — filter to in-scope workbook codes; extract year from folder
   or filename; sort chronologically.
3. **Broad profile** — list tabs for every in-scope spreadsheet.
4. **Scoring / shortlist** — rank tabs by heuristic score (row/col counts,
   name keyword patterns for operational vs. reference vs. support tabs).
5. **Tab selection** — auto-select the top *N* per workbook code, then apply
   manual overrides (or reuse a hand-edited ``tab_selection_*.json`` with
   :func:`run_cohort_corpus` ``resume_from_tab_selection``, which also skips
   Drive discovery through tab shortlisting when ``in_scope_workbook_index_*.json``
   is already present alongside that selection).
6. **Deep profile** — call ``fetch_tab_grid`` + ``summarize_tab`` on each
   selected tab, writing per-tab JSON artifacts under ``out_dir/deep/``.
7. **Column candidates** — score header columns for domain relevance and
   formula density.

The main entry point is :func:`run_cohort_corpus`.  All intermediate artifacts
are written to *out_dir* with date-stamped filenames so successive runs are
non-destructive.
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from pathlib import Path

from django.core.management.base import CommandError

from profiler.management.commands.profile_tab import (
    fetch_tab_grid,
    list_tabs,
    summarize_tab,
)

DEFAULT_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
DEFAULT_WORKBOOK_ID_PATTERN = re.compile(r"\b(\d{3})\b")


def _corpus_regex_from_config(
    config: dict, key: str, default: re.Pattern[str]
) -> re.Pattern[str]:
    """Return a compiled regex from *config*[*key*] or *default*.

    The pattern must include at least one capturing group; group 1 is the
    extracted workbook id or calendar year string.

    Raises:
        CommandError: When the value is present but not a valid regex or has
            no capturing groups.
    """
    raw = config.get(key)
    if raw is None:
        return default
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        compiled = re.compile(raw)
    except re.error as exc:
        raise CommandError(f"Invalid corpus config regex {key!r}: {exc}") from exc
    if compiled.groups < 1:
        raise CommandError(
            f"Corpus config {key!r} must include at least one capturing group (...) for extraction."
        )
    return compiled


def build_cohort_corpus_index(
    discovery_payload: dict,
    in_scope_codes: set[str],
    *,
    workbook_id_re: re.Pattern[str] | None = None,
    year_re: re.Pattern[str] | None = None,
) -> list[dict]:
    """Build index rows from a ``profile_drive_folder``-style tree payload.

    Args:
        discovery_payload: Root folder node with nested ``folders`` and
            ``spreadsheets``.
        in_scope_codes: Workbook ids (group 1 of *workbook_id_re*) to retain.
        workbook_id_re: Pattern for workbook id in each spreadsheet file name.
            Defaults to three consecutive digits.
        year_re: Pattern for a four-digit calendar year in folder or file names.
            Defaults to years 2000--2099.

    Returns:
        Sorted list of index record dicts.
    """
    wb_pat = workbook_id_re or DEFAULT_WORKBOOK_ID_PATTERN
    year_pat = year_re or DEFAULT_YEAR_PATTERN
    records: list[dict] = []

    def walk(node: dict, path_parts: list[str]):
        name = node.get("name") or node.get("id") or ""
        current = path_parts + ([name] if name else [])
        folder_year = None
        for part in reversed(current):
            match = year_pat.search(part)
            if match:
                folder_year = int(match.group(1))
                break

        for sheet in node.get("spreadsheets", []):
            sheet_name = sheet.get("name", "")
            code_match = wb_pat.search(sheet_name)
            if not code_match:
                continue
            code = code_match.group(1)
            if code not in in_scope_codes:
                continue
            year = folder_year
            if year is None:
                year_match = year_pat.search(sheet_name)
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
    records.sort(
        key=lambda row: (
            (row["year"] or 0),
            row["workbook_code"],
            row["spreadsheet_name"],
        )
    )
    return records


def _normalize_tab_heuristics(config: dict | None) -> dict:
    config = config or {}
    combo_tokens: list[tuple[str, ...]] = []
    for entry in config.get("reference_combo_tokens") or []:
        if isinstance(entry, (list, tuple)) and all(
            isinstance(token, str) for token in entry
        ):
            combo_tokens.append(tuple(token.lower() for token in entry))
    return {
        "operational_tokens": [
            token.lower()
            for token in (config.get("operational_tokens") or [])
            if isinstance(token, str)
        ],
        "reference_tokens": [
            token.lower()
            for token in (config.get("reference_tokens") or [])
            if isinstance(token, str)
        ],
        "reference_combo_tokens": combo_tokens,
        "support_tokens": [
            token.lower()
            for token in (config.get("support_tokens") or [])
            if isinstance(token, str)
        ],
    }


def _normalize_column_heuristics(config: dict | None) -> dict:
    config = config or {}
    return {
        "domain_keyword_tokens": [
            token.lower()
            for token in (config.get("domain_keyword_tokens") or [])
            if isinstance(token, str)
        ]
    }


def score_tab(
    title: str, rows: int, cols: int, *, tab_score_heuristics: dict | None = None
) -> tuple[int, list[str]]:
    lowered = title.lower()
    score = 0
    reasons: list[str] = []

    heuristics = _normalize_tab_heuristics(tab_score_heuristics)
    operational_tokens = heuristics["operational_tokens"]
    reference_tokens = heuristics["reference_tokens"]
    reference_combo_tokens = heuristics["reference_combo_tokens"]
    support_tokens = heuristics["support_tokens"]

    if operational_tokens and any(token in lowered for token in operational_tokens):
        score += 3
        reasons.append("operational_tab_name")
    if reference_tokens and any(token in lowered for token in reference_tokens):
        score += 3
        reasons.append("reference_lookup_tab_name")
    if reference_combo_tokens and any(
        all(token in lowered for token in combo) for combo in reference_combo_tokens
    ):
        score += 3
        reasons.append("reference_lookup_tab_name")
    if support_tokens and any(token in lowered for token in support_tokens):
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


def select_tabs_from_inventory(
    index_records: list[dict],
    inventory_rows: list[dict],
    *,
    min_final_score: float = 2.0,
    tab_score_heuristics: dict | None = None,
) -> list[dict]:
    by_sheet_id = {record["spreadsheet_id"]: record for record in index_records}
    scored: list[dict] = []
    for row in inventory_rows:
        meta = by_sheet_id.get(row["spreadsheet_id"])
        if meta is None:
            continue
        score, reasons = score_tab(
            row["tab_title"],
            row["rows"],
            row["cols"],
            tab_score_heuristics=tab_score_heuristics,
        )
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
            bucket["examples"].append(
                {"year": entry["year"], "spreadsheet_id": entry["spreadsheet_id"]}
            )

    selected: list[dict] = []
    for bucket in aggregate.values():
        avg_score = sum(bucket["scores"]) / len(bucket["scores"])
        coverage_bonus = 1 if len(bucket["years"]) >= 3 else 0
        final_score = avg_score + coverage_bonus
        confidence = (
            "high" if final_score >= 3 else "medium" if final_score >= 2 else "low"
        )
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
    selected.sort(
        key=lambda row: (-row["final_score"], row["workbook_code"], row["tab_title"])
    )
    return selected


def auto_select_tabs(
    tab_shortlist: list[dict], *, per_workbook: int = 3
) -> dict[str, list[str]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in tab_shortlist:
        grouped[row["workbook_code"]].append(row)
    approved: dict[str, list[str]] = {}
    for workbook_code, rows in grouped.items():
        rows.sort(
            key=lambda row: (-row["final_score"], -row["occurrences"], row["tab_title"])
        )
        approved[workbook_code] = [row["tab_title"] for row in rows[:per_workbook]]
    return approved


TAB_SELECTION_OVERRIDE_KEYS = frozenset({"add", "remove", "replace", "tabs"})


def apply_tab_selection_overrides(
    approved_tabs: dict[str, list[str]],
    overrides: dict | None,
) -> dict[str, list[str]]:
    """Merge user-supplied tab selection overrides into heuristic *approved_tabs*.

    Each override entry supports three mutually exclusive operations:

    * ``replace: true`` + ``tabs: [...]`` — replace the workbook's entire
      selection with the provided list.
    * ``add: [...]`` — append tab titles not already present.
    * ``remove: [...]`` — remove tab titles from the current selection.

    Args:
        approved_tabs: Heuristic selection mapping
            ``{workbook_code: [tab_title, ...]}``.
        overrides: Optional ``{workbook_code: override_entry}`` dict from the
            corpus config.  ``None`` or empty returns a copy of *approved_tabs*
            unchanged.

    Returns:
        dict[str, list[str]]: Merged tab selection.

    Raises:
        CommandError: On type violations or unknown override keys.
    """
    merged: dict[str, list[str]] = {
        code: list(tabs) for code, tabs in approved_tabs.items()
    }
    if not overrides:
        return merged

    if not isinstance(overrides, dict):
        raise CommandError(
            "tab_selection_overrides must be a mapping of workbook_code to override entry"
        )

    for workbook_code, entry in overrides.items():
        if not isinstance(entry, dict):
            raise CommandError(
                f"tab_selection_overrides[{workbook_code!r}] must be a mapping; got {type(entry).__name__}"
            )
        unknown = set(entry.keys()) - TAB_SELECTION_OVERRIDE_KEYS
        if unknown:
            raise CommandError(
                f"tab_selection_overrides[{workbook_code!r}] has unknown keys: {sorted(unknown)}"
            )

        if entry.get("replace"):
            tabs = entry.get("tabs")
            if not isinstance(tabs, list) or not all(
                isinstance(item, str) for item in tabs
            ):
                raise CommandError(
                    f"tab_selection_overrides[{workbook_code!r}] requires 'tabs' as list[str] when 'replace' is true"
                )
            merged[workbook_code] = list(tabs)
            continue

        if "tabs" in entry:
            raise CommandError(
                f"tab_selection_overrides[{workbook_code!r}] uses 'tabs' without 'replace: true'"
            )

        add = entry.get("add", []) or []
        remove = entry.get("remove", []) or []
        if not isinstance(add, list) or not all(isinstance(item, str) for item in add):
            raise CommandError(
                f"tab_selection_overrides[{workbook_code!r}].add must be a list of strings"
            )
        if not isinstance(remove, list) or not all(
            isinstance(item, str) for item in remove
        ):
            raise CommandError(
                f"tab_selection_overrides[{workbook_code!r}].remove must be a list of strings"
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


def derive_column_candidates(
    *,
    workbook_code: str,
    year: int | None,
    spreadsheet_id: str,
    tab_title: str,
    payload: dict,
    column_score_heuristics: dict | None = None,
) -> list[dict]:
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

    heuristics = _normalize_column_heuristics(column_score_heuristics)
    domain_keyword_tokens = heuristics["domain_keyword_tokens"]
    candidates: list[dict] = []
    for col_letter, header in headers[:40]:
        lowered = header.lower()
        score = 0
        reasons: list[str] = []
        if domain_keyword_tokens and any(
            token in lowered for token in domain_keyword_tokens
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
                "evidence": {
                    "formula_cell_count": formula_count,
                    "functions_used": functions,
                },
            }
        )
    return candidates


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_tab_inventory_output(text: str) -> list[dict]:
    pattern = re.compile(
        r"^\[(\s*\d+)\]\s+sheetId=\s*([0-9]+)\s+rows=\s*([0-9]+)\s+cols=\s*([0-9]+)\s+(.+)$"
    )
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


def run_cohort_corpus(
    *,
    drive_service,
    sheets_service,
    config: dict,
    out_dir: Path,
    date_stamp: str,
    resume_from_tab_selection: bool = False,
    skip_existing_deep: bool = False,
) -> dict:
    """Execute the full cohort corpus profiling pipeline and write all artifacts.

    All intermediate JSON files are written to *out_dir* with *date_stamp*
    suffixes.  Deep-profile per-tab files go into ``out_dir/deep/``.

    When *resume_from_tab_selection* is ``True``, *out_dir* must contain both
    ``tab_selection_<date_stamp>.json`` and
    ``in_scope_workbook_index_<date_stamp>.json`` from an earlier full run.
    The pipeline skips Drive discovery through tab shortlisting,
    preserves the hand-edited tab selection JSON, reloads workbook index rows from
    disk, then runs deep profiling and downstream column artifacts using the
    selected tab titles (one deep job per index row workbook code matched to
    those titles).

    Args:
        drive_service: Authenticated Google Drive API service object.
        sheets_service: Authenticated Google Sheets API service object.
        config: Parsed corpus config dict.  Required keys: ``folder_id``
            (Drive folder), ``in_scope_workbooks`` (list of code strings
            matching capturing group 1 of ``workbook_id_regex``).
            Optional keys include ``workbook_id_regex``, ``year_regex``,
            ``heuristics``, ``tab_auto_limit``, ``column_min_score``,
            ``tab_selection_overrides``, ``discovery_no_tabs``, ``max_depth``,
            ``deep_read_delay_seconds``, ``deep_skip_existing``.
        out_dir: Directory where all artifact JSON files are written.
        date_stamp: Timestamp string appended to artifact filenames.
        resume_from_tab_selection: Load workbook index rows and ``approved_tabs``
            from artifacts on disk, skipping Drive discovery and broad Sheets
            tab listing unless a full rerun is executed. Defaults to ``False``.
        skip_existing_deep: When combined with cached files under ``out_dir/deep/``,
            reuse existing payloads for column scoring instead of refetching.
            Intended for retrying quota-throttled corpus runs without repeating
            successful tab pulls. Combines logically with JSON config
            ``deep_skip_existing``. Defaults to ``False``.

    Returns:
        dict[str, str]: Mapping from artifact role to file path for every file
        written (keys: ``"discovery"``, ``"index"``, ``"broad_coverage"``,
        ``"tab_shortlist"``, ``"tab_selection"``, ``"deep_coverage"``,
        ``"column_shortlist"``, ``"column_selection"``).

    Raises:
        CommandError: If required config keys are missing or resume mode is
            requested but no selection file exists.
    """
    from profiler.management.commands.profile_drive_folder import walk_folder

    folder_id = config.get("folder_id")
    if not folder_id:
        raise CommandError("Config must include 'folder_id'")
    in_scope_codes = set(config.get("in_scope_workbooks") or [])
    if not in_scope_codes:
        raise CommandError("Config must include non-empty 'in_scope_workbooks'")

    workbook_id_re = _corpus_regex_from_config(
        config, "workbook_id_regex", DEFAULT_WORKBOOK_ID_PATTERN
    )
    year_re = _corpus_regex_from_config(config, "year_regex", DEFAULT_YEAR_PATTERN)

    heuristics_config = config.get("heuristics") or {}
    tab_score_heuristics = heuristics_config.get("tab_score") or {}
    column_score_heuristics = heuristics_config.get("column_score") or {}

    discovery_path = out_dir / f"drive_discovery_{date_stamp}.json"
    index_path = out_dir / f"in_scope_workbook_index_{date_stamp}.json"
    broad_path = out_dir / f"broad_profile_coverage_{date_stamp}.json"
    tab_shortlist_path = out_dir / f"tab_shortlist_{date_stamp}.json"
    tab_selection_path = out_dir / f"tab_selection_{date_stamp}.json"

    if resume_from_tab_selection:
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
            and all(isinstance(tab_title_entry, str) for tab_title_entry in selected_tab_titles)
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
    else:
        include_tabs = not bool(config.get("discovery_no_tabs"))
        tree = walk_folder(
            drive_service,
            sheets_service,
            folder_id,
            include_tabs=include_tabs,
            max_depth=config.get("max_depth"),
        )
        discovery_payload = {
            "id": folder_id,
            "name": config.get("folder_name") or folder_id,
            **tree,
        }
        write_json(discovery_path, discovery_payload)

        index_records = build_cohort_corpus_index(
            discovery_payload,
            in_scope_codes,
            workbook_id_re=workbook_id_re,
            year_re=year_re,
        )
        write_json(
            index_path,
            {
                "generated_from": discovery_path.name,
                "record_count": len(index_records),
                "records": index_records,
            },
        )

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

        tab_shortlist = select_tabs_from_inventory(
            index_records,
            inventory_rows,
            tab_score_heuristics=tab_score_heuristics,
        )
        write_json(
            tab_shortlist_path,
            {
                "generated_from": broad_path.name,
                "candidate_count": len(
                    {(row["workbook_code"], row["tab_title"]) for row in tab_shortlist}
                ),
                "selected_count": len(tab_shortlist),
                "selected": tab_shortlist,
            },
        )

        heuristic_tabs = auto_select_tabs(
            tab_shortlist, per_workbook=int(config.get("tab_auto_limit", 3))
        )
        overrides = config.get("tab_selection_overrides")
        approved_tabs = apply_tab_selection_overrides(heuristic_tabs, overrides)
        tab_selection_payload: dict = {
            "policy": (
                "heuristic tab selection (tab_selection_overrides applied)"
                if overrides
                else "heuristic tab selection"
            ),
            "approved_tabs": approved_tabs,
        }
        if overrides:
            tab_selection_payload["overrides_applied"] = overrides
        write_json(tab_selection_path, tab_selection_payload)

    reuse_cached_deep = bool(skip_existing_deep) or bool(config.get("deep_skip_existing"))
    deep_read_delay_seconds = float(config.get("deep_read_delay_seconds") or 0.0)

    deep_results: list[dict] = []
    candidate_columns: list[dict] = []
    deep_dir = out_dir / "deep"
    deep_dir.mkdir(parents=True, exist_ok=True)

    payload_for_candidates: dict
    summary_for_candidates: dict
    resolved_out_json: str | None

    for record in index_records:
        for tab_title in approved_tabs.get(record["workbook_code"], []):
            out_path = (
                deep_dir
                / f"{record['workbook_code']}_{record['year']}_{record['spreadsheet_id'][:8]}_{make_slug(tab_title)}.json"
            )
            if reuse_cached_deep and out_path.exists():
                try:
                    cached_deep_payload = json.loads(out_path.read_text(encoding="utf-8"))
                    cached_grid_payload = cached_deep_payload.get("raw")
                    cached_tab_summary = cached_deep_payload.get("summary")
                except json.JSONDecodeError:
                    cached_grid_payload = None
                    cached_tab_summary = None
                if cached_grid_payload is not None and cached_tab_summary is not None:
                    payload_for_candidates = cached_grid_payload
                    summary_for_candidates = cached_tab_summary
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
                                "raw": payload_for_candidates,
                                "summary": summary_for_candidates,
                            },
                            column_score_heuristics=column_score_heuristics,
                        )
                    )
                    continue

            try:
                if deep_read_delay_seconds > 0:
                    time.sleep(deep_read_delay_seconds)
                payload_for_candidates = fetch_tab_grid(
                    sheets_service, record["spreadsheet_id"], tab_title
                )
                summary_for_candidates = summarize_tab(payload_for_candidates)
                write_json(
                    out_path,
                    {"raw": payload_for_candidates, "summary": summary_for_candidates},
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
                        "reused_cached_deep": False,
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
        key = (
            candidate["workbook_code"],
            candidate["tab_title"],
            candidate["proposed_canonical_field"],
        )
        previous = deduped.get(key)
        if previous is None or candidate["priority_score"] > previous["priority_score"]:
            deduped[key] = candidate
    selected_columns = sorted(
        [
            row
            for row in deduped.values()
            if row["priority_score"] >= int(config.get("column_min_score", 4))
        ],
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

    return {
        "discovery": str(discovery_path),
        "index": str(index_path),
        "broad_coverage": str(broad_path),
        "tab_shortlist": str(tab_shortlist_path),
        "tab_selection": str(tab_selection_path),
        "deep_coverage": str(deep_coverage_path),
        "column_shortlist": str(column_shortlist_path),
        "column_selection": str(column_selection_path),
    }
