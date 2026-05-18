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

import hashlib
import json
import math
import re
import re as _re
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from django.core.management.base import CommandError

from googleapiclient.errors import HttpError

from connectors.spreadsheet import column_index_to_letter, guess_header_row, raw_sheet_to_row_lists
from profiler.management.commands.profile_tab import (
    fetch_tab_grid,
    list_tabs,
    summarize_tab,
)

logger = logging.getLogger(__name__)

_TRUNCATE_LENGTH = 200

_ENTITY_KEYWORDS = {"channel", "season", "crop", "block", "farm", "field", "variety"}
_IDENTIFIER_SUFFIXES = {"_id", "_code", "_key"}
_IDENTIFIER_NAMES = {"id", "name", "code", "slug", "uid", "uuid", "external_id"}


def _to_pascal_case(raw: str) -> str:
    if "_" not in raw and "-" not in raw and any(c.isupper() for c in raw[1:]):
        return raw
    return "".join(p.capitalize() for p in raw.replace("-", "_").split("_"))


@dataclass
class ColumnProfile:
    letter: str
    header_slug: str
    header_raw: str
    inferred_type: str
    formula_pattern: str
    non_empty_cells: int
    unique_value_sample: list = field(default_factory=list)
    is_section_header: bool = False
    cross_sheet_refs: list = field(default_factory=list)
    pattern_truncated: bool = False
    pattern_hash: str = ""


def _slugify_header(header: str) -> str:
    return _re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_") if header else ""


def compute_column_profiles(summary: dict, return_patterns_by_slug: bool = False):
    """Build ``ColumnProfile`` instances from a tab summary, classifying each column's formula pattern, type, and section-header status. Returns a list of profiles or a slug-to-pattern dict if ``return_patterns_by_slug`` is True."""
    raw_patterns = summary.get("column_formula_patterns") or {}
    if isinstance(raw_patterns, dict) and raw_patterns:
        first_key = next(iter(raw_patterns))
        patterns_by_letter = raw_patterns if not isinstance(raw_patterns[first_key], dict) else {}
    else:
        patterns_by_letter = {}

    candidates = summary.get("column_candidates") or summary.get("columns") or []
    total_columns = max(
        (c.get("total_columns") or c.get("total_count") or len(candidates)) for c in candidates
    ) if candidates else 0

    profiles = []
    for cand in candidates:
        letter = cand.get("letter") or cand.get("col_letter") or ""
        header_raw = cand.get("header") or cand.get("header_label") or cand.get("name") or ""
        header_slug = _slugify_header(header_raw) if header_raw else f"col_{letter.lower()}"
        pattern = patterns_by_letter.get(letter, "raw")

        pattern_truncated = len(pattern) > _TRUNCATE_LENGTH
        pattern_hash = hashlib.sha256(pattern.encode()).hexdigest()[:8] if pattern else ""
        if pattern_truncated:
            pattern = pattern[:_TRUNCATE_LENGTH]

        unique_count = cand.get("unique_count") or 0
        total_count = cand.get("total_count") or cand.get("non_empty_cells") or 0
        merged_span = cand.get("merged_span") or 0

        is_section_header = (
            bool(header_raw)
            and header_raw == header_raw.upper()
            and unique_count <= 2
            and total_count > 0
            and (total_columns > 0 and merged_span > total_columns * 0.5)
        )

        inferred_type = cand.get("format_type") or cand.get("type") or "text"
        if pattern in ("expansion_formula", "row_formula"):
            inferred_type = "formula"

        cross_refs = cand.get("cross_sheet_refs") or []
        unique_values = cand.get("unique_values_sample") or cand.get("sample_values") or []

        profiles.append(ColumnProfile(
            letter=letter,
            header_slug=header_slug,
            header_raw=header_raw,
            inferred_type=inferred_type,
            formula_pattern=pattern,
            non_empty_cells=total_count,
            unique_value_sample=unique_values[:5],
            is_section_header=is_section_header,
            cross_sheet_refs=cross_refs,
            pattern_truncated=pattern_truncated,
            pattern_hash=pattern_hash,
        ))

    if return_patterns_by_slug:
        return {
            p.header_slug: {"letter": p.letter, "pattern": p.formula_pattern}
            for p in profiles
        }
    return profiles


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


def _token_match(token: str, text: str, mode: str) -> bool:
    """Check if *token* appears in *text* according to *mode*.

    Args:
        token: The keyword to look for (already lowered).
        text: The target string (already lowered).
        mode: ``"substring"`` (default) or ``"word"``.

    Returns:
        bool: Whether a match was found.
    """
    if mode == "word":
        return bool(re.search(rf"\b{re.escape(token)}\b", text))
    return token in text


def _normalize_tab_heuristics(config: dict | None) -> dict:
    config = config or {}

    operational_weight = config.get("operational_weight", 3)
    reference_weight = config.get("reference_weight", 3)
    derived_weight = config.get("derived_weight", -4)
    support_weight = config.get("support_weight", -2)
    reference_combo_weight = config.get(
        "reference_combo_weight", reference_weight
    )
    match_mode = config.get("match_mode", "substring")
    if match_mode not in ("substring", "word"):
        match_mode = "substring"

    combo_tokens: list[tuple[str, ...]] = []
    for entry in config.get("reference_combo_tokens") or []:
        if isinstance(entry, (list, tuple)) and all(
            isinstance(token, str) for token in entry
        ):
            combo_tokens.append(tuple(token.lower() for token in entry))
    exclude_patterns: list[dict] = []
    for entry in config.get("tab_exclude_patterns") or []:
        if isinstance(entry, dict) and "pattern" in entry:
            try:
                compiled = re.compile(entry["pattern"])
                penalty = int(entry.get("penalty", -5))
                exclude_patterns.append({"pattern": compiled, "penalty": penalty})
            except re.error:
                logger.warning("Invalid tab_exclude_pattern regex: %r", entry["pattern"])
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
        "derived_tokens": [
            token.lower()
            for token in (config.get("derived_tokens") or [])
            if isinstance(token, str)
        ],
        "operational_weight": operational_weight,
        "reference_weight": reference_weight,
        "derived_weight": derived_weight,
        "support_weight": support_weight,
        "reference_combo_weight": reference_combo_weight,
        "match_mode": match_mode,
        "exclude_patterns": exclude_patterns,
        "expansion_formula_penalty": int(config.get("expansion_formula_penalty", 0)),
        "expansion_formula_threshold": float(config.get("expansion_formula_threshold", 0.5)),
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
    title: str, rows: int, cols: int, *,
    tab_score_heuristics: dict | None = None,
    column_formula_patterns: dict[str, str] | None = None,
) -> tuple[int, list[str], dict]:
    """Score a single tab by its title and dimensions.

    Args:
        title: Tab worksheet title.
        rows: Number of data rows.
        cols: Number of data columns.
        tab_score_heuristics: Optional config dict (see
            ``_normalize_tab_heuristics``).
        column_formula_patterns: Optional mapping from column letter to
            formula pattern (``"raw"``, ``"row_formula"``,
            ``"expansion_formula"``, ``"hybrid"``, or ``"empty"``).
            When provided together with a configured
            ``expansion_formula_penalty``, tabs whose expansion-formula
            ratio exceeds ``expansion_formula_threshold`` receive the
            configured penalty.

    Returns:
        Tuple of (score, reason_labels, breakdown_dict).  Reason labels
        include ``"expansion_formula_ratio"`` when the expansion-formula
        penalty is applied.
    """
    lowered = title.lower()
    score = 0
    reasons: list[str] = []
    token_matches: list[dict] = []
    size_bonuses: dict[str, int] = {}

    heuristics = _normalize_tab_heuristics(tab_score_heuristics)
    match_mode = heuristics["match_mode"]

    categories: list[tuple[str, list[str], str, int, str]] = [
        (
            "operational_tokens",
            heuristics["operational_tokens"],
            "operational",
            heuristics["operational_weight"],
            "operational_tab_name",
        ),
        (
            "reference_tokens",
            heuristics["reference_tokens"],
            "reference",
            heuristics["reference_weight"],
            "reference_lookup_tab_name",
        ),
        (
            "support_tokens",
            heuristics["support_tokens"],
            "support",
            heuristics["support_weight"],
            "likely_support_tab",
        ),
        (
            "derived_tokens",
            heuristics["derived_tokens"],
            "derived",
            heuristics["derived_weight"],
            "derived_tab",
        ),
    ]
    for _key, tokens, category, weight, reason in categories:
        if tokens:
            matched = [
                token
                for token in tokens
                if _token_match(token, lowered, match_mode)
            ]
            if matched:
                score += weight
                reasons.append(reason)
                for token in matched:
                    token_matches.append(
                        {
                            "token": token,
                            "category": category,
                            "weight": weight,
                        }
                    )

    combo_tokens = heuristics["reference_combo_tokens"]
    if combo_tokens:
        combo_weight = heuristics["reference_combo_weight"]
        for combo in combo_tokens:
            if all(
                _token_match(token, lowered, match_mode) for token in combo
            ):
                score += combo_weight
                reasons.append("reference_lookup_tab_name")
                token_matches.append(
                    {
                        "token": " + ".join(combo),
                        "category": "reference_combo",
                        "weight": combo_weight,
                    }
                )
                break

    cells = rows * cols
    total_size_bonus = 0
    if cells >= 50_000:
        bonus = min(2, 1 + int(math.log10(cells / 100_000)))
        score += bonus
        reasons.append(f"large_grid(+{bonus})")
        size_bonuses["large_grid"] = bonus
        total_size_bonus += bonus
    elif cells >= 10_000:
        score += 1
        reasons.append("medium_grid")
        size_bonuses["medium_grid"] = 1
        total_size_bonus += 1
    remaining_cap = max(0, 3 - total_size_bonus)
    if rows >= 1000 and remaining_cap > 0:
        add = min(1, remaining_cap)
        score += add
        reasons.append("many_rows")
        size_bonuses["many_rows"] = add
        remaining_cap -= add
    if cols >= 20 and remaining_cap > 0:
        add = min(1, remaining_cap)
        score += add
        reasons.append("wide_sheet")
        size_bonuses["wide_sheet"] = add

    exclude_penalties = 0
    exclude_matches: list[dict] = []
    for entry in heuristics.get("exclude_patterns", []):
        if entry["pattern"].search(title):
            exclude_penalties += entry["penalty"]
            exclude_matches.append({
                "pattern": entry["pattern"].pattern,
                "penalty": entry["penalty"],
            })
    if exclude_penalties:
        score += exclude_penalties
        reasons.append("tab_exclude_pattern")

    # Apply expansion_formula_ratio penalty
    expansion_penalty = heuristics.get("expansion_formula_penalty", 0)
    if expansion_penalty and column_formula_patterns:
        expansion_threshold = heuristics.get("expansion_formula_threshold", 0.5)
        total_cols = len(column_formula_patterns)
        expansion_count = sum(
            1 for pattern in column_formula_patterns.values()
            if pattern == "expansion_formula"
        )
        if total_cols > 0 and (expansion_count / total_cols) >= expansion_threshold:
            score += expansion_penalty
            reasons.append("expansion_formula_ratio")

    breakdown = {
        "token_matches": token_matches,
        "size_bonuses": size_bonuses,
        "exclude_penalties": exclude_penalties,
        "exclude_matches": exclude_matches,
        "subtotal": score,
    }

    return score, reasons, breakdown


def select_tabs_from_inventory(
    index_records: list[dict],
    inventory_rows: list[dict],
    *,
    min_final_score: float = 2.0,
    tab_score_heuristics: dict | None = None,
) -> list[dict]:
    """Score, aggregate across years, and filter inventory tabs by final score. Applies coverage bonus for tabs appearing in 3+ years. Returns a sorted shortlist."""
    by_sheet_id = {record["spreadsheet_id"]: record for record in index_records}
    scored: list[dict] = []
    for row in inventory_rows:
        meta = by_sheet_id.get(row["spreadsheet_id"])
        if meta is None:
            continue
        score, reasons, breakdown = score_tab(
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
                "breakdown": breakdown,
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
                "breakdowns": [],
            },
        )
        bucket["occurrences"] += 1
        bucket["years"].add(entry["year"])
        bucket["scores"].append(entry["score"])
        bucket["rows_max"] = max(bucket["rows_max"], entry["rows"])
        bucket["cols_max"] = max(bucket["cols_max"], entry["cols"])
        bucket["breakdowns"].append(entry.get("breakdown", {}))
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

        cat_counts: dict[str, int] = {}
        total_size_bonus = 0
        total_token_matches = 0
        for bd in bucket["breakdowns"]:
            for tm in bd.get("token_matches", []):
                cat = tm.get("category", "unknown")
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
                total_token_matches += 1
            total_size_bonus += sum(
                bd.get("size_bonuses", {}).values()
            )
        breakdown_summary = {
            "total_token_matches": total_token_matches,
            "category_counts": cat_counts,
            "avg_size_bonus": round(
                total_size_bonus / len(bucket["breakdowns"]), 2
            )
            if bucket["breakdowns"]
            else 0,
        }

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
                "breakdown_summary": breakdown_summary,
            }
        )
    selected.sort(
        key=lambda row: (-row["final_score"], row["workbook_code"], row["tab_title"])
    )
    return selected


def auto_select_tabs(
    tab_shortlist: list[dict], *, per_workbook: int = 3, per_code_overrides: dict[str, int] | None = None
) -> dict[str, list[str]]:
    """Group shortlisted tabs by workbook code, sort by score/occurrences, and pick the top N per workbook. Returns ``{workbook_code: [tab_titles]}``."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in tab_shortlist:
        grouped[row["workbook_code"]].append(row)
    approved: dict[str, list[str]] = {}
    for workbook_code, rows in grouped.items():
        limit = (per_code_overrides or {}).get(workbook_code, per_workbook)
        rows.sort(
            key=lambda row: (-row["final_score"], -row["occurrences"], row["tab_title"])
        )
        approved[workbook_code] = [row["tab_title"] for row in rows[:limit]]
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
    """Convert arbitrary text into a filesystem-safe slug (lowercase alphanumeric + underscores, max 50 chars). Falls back to ``"tab"`` if empty."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return slug[:50] or "tab"


def _raw_sheet_to_row_lists(raw: dict) -> list[list[str]]:
    """Convert raw Sheets API grid data into list-of-lists for ``guess_header_row``."""
    return raw_sheet_to_row_lists(raw)


def derive_column_candidates(
    *,
    workbook_code: str,
    year: int | None,
    spreadsheet_id: str,
    tab_title: str,
    payload: dict,
    column_score_heuristics: dict | None = None,
) -> list[dict]:
    """Extract column headers from a raw sheet payload and score each by domain keywords and formula density. Returns a list of candidate dicts with canonical field name proposals."""
    summary = payload.get("summary", {})
    raw = payload.get("raw", {})
    formula_count = int(summary.get("formula_cell_count") or 0)
    functions = [name for name, _count in summary.get("functions_used", [])][:8]

    headers: list[tuple[str, str]] = []
    try:
        row_lists = _raw_sheet_to_row_lists(raw)
        header_index = guess_header_row(row_lists)
        if header_index is None:
            return []
        headers_raw = row_lists[header_index]
        for col_index, header in enumerate(headers_raw):
            if not header.strip():
                continue
            col_letter = column_index_to_letter(col_index)
            headers.append((col_letter, header.strip()))
    except (KeyError, IndexError, TypeError):
        return []

    heuristics = _normalize_column_heuristics(column_score_heuristics)
    domain_keyword_tokens = heuristics["domain_keyword_tokens"]
    raw_patterns = summary.get("column_formula_patterns")
    formula_patterns = raw_patterns if isinstance(raw_patterns, dict) else {}
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
                    "formula_pattern": formula_patterns.get(col_letter, "raw"),
                },
            }
        )
    return candidates


def enrich_computed_fields(columns: list[dict]) -> None:
    computed_patterns = {"row_formula", "expansion_formula"}
    for col in columns:
        evidence = col.get("evidence") or {}
        pattern = evidence.get("formula_pattern")
        col["is_computed"] = pattern in computed_patterns


def enrich_fk_candidates(columns: list[dict], entity_names: set[str]) -> None:
    for col in columns:
        name = col.get("proposed_canonical_field", "")
        evidence = col.get("evidence") or {}
        target = None
        if name.endswith("_id"):
            prefix = name[:-3]
            target = _to_pascal_case(prefix)
        elif name.lower() in _ENTITY_KEYWORDS:
            target = _to_pascal_case(name)
        elif evidence.get("cross_sheet_refs"):
            target = _to_pascal_case(name)
        if target is not None:
            if entity_names and target not in entity_names:
                target = None
        col["suggested_fk_target"] = target


def enrich_import_key_candidates(columns: list[dict]) -> None:
    for col in columns:
        name = col.get("proposed_canonical_field", "")
        evidence = col.get("evidence") or {}
        pattern = evidence.get("formula_pattern", "raw")
        is_identifier = False
        for suffix in _IDENTIFIER_SUFFIXES:
            if name.endswith(suffix):
                is_identifier = True
                break
        if name in _IDENTIFIER_NAMES:
            is_identifier = True
        col["is_import_key_candidate"] = is_identifier and pattern == "raw"


def enrich_entity_groupings(
    columns: list[dict], workbook_index: dict[str, dict]
) -> dict[str, str]:
    tab_headers: dict[tuple[str, str], set[str]] = {}
    for col in columns:
        key = (col.get("workbook_code", ""), col.get("tab_title", ""))
        tab_headers.setdefault(key, set()).add(col.get("proposed_canonical_field", ""))
    wb_cols: dict[str, set[str]] = {}
    for (wb_code, _tab), headers in tab_headers.items():
        wb_cols.setdefault(wb_code, set()).update(headers)
    tabs_by_wb: dict[str, list[tuple[str, set[str]]]] = {}
    for (wb_code, tab_title), headers in tab_headers.items():
        if wb_code not in wb_cols:
            continue
        tabs_by_wb.setdefault(wb_code, []).append((tab_title, headers))
    entity_map: dict[str, str] = {}
    group_counter = 0
    for wb_code, tab_list in tabs_by_wb.items():
        if len(tab_list) < 2:
            continue
        assigned: dict[str, str] = {}
        for i, (title_a, headers_a) in enumerate(tab_list):
            if title_a in assigned:
                continue
            for j, (title_b, headers_b) in enumerate(tab_list):
                if j <= i:
                    continue
                if title_b in assigned:
                    continue
                if len(headers_a & headers_b) >= 2:
                    if title_a not in assigned:
                        group_name = f"{wb_code}_entity_{group_counter}"
                        group_counter += 1
                        assigned[title_a] = group_name
                    assigned[title_b] = assigned[title_a]
        for tab_title, entity_name in assigned.items():
            entity_map[tab_title] = entity_name
    for col in columns:
        key = (col.get("workbook_code", ""), col.get("tab_title", ""))
        entity_name = entity_map.get(col.get("tab_title", ""))
        if entity_name is not None:
            col["suggested_entity"] = entity_name
            col["cross_tab_group"] = entity_name
        else:
            col["suggested_entity"] = None
            col["cross_tab_group"] = None
    return entity_map


def write_json(path: Path, payload: dict):
    """Create parent directories if needed and write *payload* as pretty-printed JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_tab_inventory_output(text: str) -> list[dict]:
    """Parse a text inventory format like ``[ 1] sheetId=123 rows=45 cols=6 TabName`` into structured dicts."""
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


def _render_corpus_summary(
    path: Path,
    *,
    deep_results: list[dict],
    candidate_columns: list[dict],
    selected_columns: list[dict],
    approved_tabs: dict[str, list[str]],
) -> None:
    """Write a human-readable Markdown summary of the corpus run."""
    lines: list[str] = [
        "# Corpus Summary",
        "",
        f"- **Generated:** `{path.name}`",
        f"- **Deep profile jobs:** {len(deep_results)}",
        f"  - Success: {sum(1 for row in deep_results if row['exit_code'] == 0)}",
        f"  - Failure: {sum(1 for row in deep_results if row['exit_code'] != 0)}",
        "",
        "## Column Candidates",
        "",
        f"- Total candidates: {len(candidate_columns)}",
        f"- Selected: {len(selected_columns)}",
        "",
        "## Per-Workbook Tab Selection",
        "",
    ]
    for workbook_code in sorted(approved_tabs):
        tabs = approved_tabs[workbook_code]
        lines.append(f"### Workbook {workbook_code}")
        lines.append("")
        for tab_title in tabs:
            failures = sum(
                1
                for row in deep_results
                if row["workbook_code"] == workbook_code
                and row["tab_title"] == tab_title
                and row["exit_code"] != 0
            )
            successes = sum(
                1
                for row in deep_results
                if row["workbook_code"] == workbook_code
                and row["tab_title"] == tab_title
                and row["exit_code"] == 0
            )
            status = "OK" if successes > 0 and failures == 0 else "FAIL" if failures > 0 else "N/A"
            lines.append(f"- **{tab_title}** — {status} ({successes} ok, {failures} fail)")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_cohort_corpus(
    *,
    drive_service,
    sheets_service,
    config: dict,
    out_dir: Path,
    date_stamp: str,
    resume_from_tab_selection: bool = False,
    resume_from_broad: bool = False,
    stop_before_deep: bool = False,
    skip_existing_deep: bool = False,
    folder_id: str | None = None,
) -> dict:
    """Execute the cohort corpus profiling pipeline and write all artifacts.

    All intermediate JSON files are written to *out_dir* with *date_stamp*
    suffixes.  Deep-profile per-tab files go into ``out_dir/deep/``.

    The pipeline can be run in phases to avoid expensive deep profiling until
    tab selection is confirmed:

    **Phase 1 — Discovery + tab selection** (``stop_before_deep=True``):
    Runs Drive discovery, workbook indexing, tab listing, scoring, and tab
    selection.  Returns after writing ``tab_selection_<date_stamp>.json``,
    skipping deep grid fetches and column scoring.  Use to inspect the
    auto-selected tabs before committing to deep profile API calls.

    **Phase 2 — Heuristic refinement** (``resume_from_broad=True``):
    Reads ``broad_profile_coverage_<date_stamp>.json`` and
    ``in_scope_workbook_index_<date_stamp>.json`` from a prior Phase 1 run,
    then re-runs tab scoring, shortlisting, and selection using the
    **current** config heuristics.  No Drive or Sheets API calls are made,
    so this is fast and can be iterated.  Combine with ``stop_before_deep``
    to stop after selection, or omit it to continue into deep profiling.

    **Phase 3 — Deep profiling** (``resume_from_tab_selection=True``):
    Reads ``tab_selection_<date_stamp>.json`` and workbook index from an
    earlier run, preserving hand-edited selections.  Skips Drive discovery
    through tab shortlisting and goes straight to deep grid fetches and
    column scoring.

    Args:
        drive_service: Authenticated Google Drive API service object.
        sheets_service: Authenticated Google Sheets API service object.
        config: Parsed corpus config dict.  Required keys:
            ``in_scope_workbooks`` (list of code strings matching capturing
            group 1 of ``workbook_id_regex``).  Optional keys include
            ``workbook_id_regex``, ``year_regex``, ``heuristics``,
            ``tab_auto_limit``, ``column_min_score``,
            ``tab_selection_overrides``, ``discovery_no_tabs``, ``max_depth``,
            ``deep_read_delay_seconds``, ``deep_skip_existing``,
            ``deep_read_429_cooldown``, ``deep_read_429_max_cooldowns``.
        out_dir: Directory where all artifact JSON files are written.
        date_stamp: Timestamp string appended to artifact filenames.
        resume_from_tab_selection: Phase 3 mode — load hand-edited tab selection
            and workbook index from disk; skip Drive discovery through tab
            shortlisting.  Defaults to ``False``.
        resume_from_broad: Phase 2 mode — reload broad coverage and index from
            disk; re-run scoring and selection with current config without
            API calls.  Defaults to ``False``.
        stop_before_deep: Stop after writing tab selection; skip deep grid
            fetches and column scoring.  Defaults to ``False``.
        skip_existing_deep: When combined with cached files under ``out_dir/deep/``,
            reuse existing payloads for column scoring instead of refetching.
            Intended for retrying quota-throttled corpus runs without repeating
            successful tab pulls. Combines logically with JSON config
            ``deep_skip_existing``. Defaults to ``False``.
        folder_id: Google Drive folder id that contains the workbook corpus.
            Required when not in resume mode. Defaults to ``None``.

    Returns:
        dict[str, str]: Mapping from artifact role to file path for every file
        written (keys: ``"discovery"``, ``"index"``, ``"broad_coverage"``,
        ``"tab_shortlist"``, ``"tab_selection"``).  When ``stop_before_deep`` is
        ``False``, also includes ``"deep_coverage"``, ``"column_shortlist"``,
        ``"column_selection"``.

    Raises:
        CommandError: If required config keys are missing or a resume mode is
            requested but no corresponding artifact file exists.
    """
    from profiler.management.commands.profile_drive_folder import walk_folder

    in_scope_codes = set(config.get("in_scope_workbooks") or [])
    if not in_scope_codes:
        raise CommandError("Config must include non-empty 'in_scope_workbooks'")

    if resume_from_tab_selection and resume_from_broad:
        raise CommandError(
            "Cannot combine --resume-from-tab-selection and --resume-from-broad; "
            "they are mutually exclusive."
        )
    if not resume_from_tab_selection and not resume_from_broad and not folder_id:
        raise CommandError("folder_id is required when not in a resume mode")

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

    # Year-aware tab validation: known_tabs is populated from broad coverage
    # inventory when available, so deep fetches can skip tabs that don't exist
    # in a given year's workbook.
    known_tabs: set[tuple[str, str]] = set()

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

        # Load broad coverage inventory for year-aware tab validation
        if broad_path.exists():
            try:
                broad_payload = json.loads(broad_path.read_text(encoding="utf-8"))
                for inventory_row in broad_payload.get("inventory_rows", []):
                    known_tabs.add((inventory_row["spreadsheet_id"], inventory_row["tab_title"]))
            except (json.JSONDecodeError, KeyError):
                pass

    elif resume_from_broad:
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
        try:
            workbook_index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Could not parse {index_path}: {exc}") from exc
        index_records = workbook_index_payload.get("records")
        if not isinstance(index_records, list) or not index_records:
            raise CommandError(f"{index_path} must contain a non-empty 'records' list")

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
            tab_shortlist,
            per_workbook=int(config.get("tab_auto_limit", 3)),
            per_code_overrides=config.get("tab_auto_limit_overrides"),
        )
        overrides = config.get("tab_selection_overrides")
        approved_tabs = apply_tab_selection_overrides(heuristic_tabs, overrides)
        tab_selection_payload = {
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

    else:
        include_tabs = not bool(config.get("discovery_no_tabs"))
        assert folder_id is not None
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
                "inventory_rows": inventory_rows,
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
            tab_shortlist,
            per_workbook=int(config.get("tab_auto_limit", 3)),
            per_code_overrides=config.get("tab_auto_limit_overrides"),
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

    artifacts: dict[str, str] = {
        "discovery": str(discovery_path),
        "index": str(index_path),
        "broad_coverage": str(broad_path),
        "tab_shortlist": str(tab_shortlist_path),
        "tab_selection": str(tab_selection_path),
    }

    if stop_before_deep:
        return artifacts

    reuse_cached_deep = bool(skip_existing_deep) or bool(config.get("deep_skip_existing"))
    deep_read_delay_seconds = float(config.get("deep_read_delay_seconds") or 0.5)

    deep_results: list[dict] = []
    candidate_columns: list[dict] = []
    deep_dir = out_dir / "deep"
    deep_dir.mkdir(parents=True, exist_ok=True)

    payload_for_candidates: dict
    summary_for_candidates: dict
    resolved_out_json: str | None

    _429_cooldown_seconds = float(config.get("deep_read_429_cooldown") or 60.0)
    _429_max_cooldowns = int(config.get("deep_read_429_max_cooldowns") or 5)
    _429_cooldown_count = 0
    _429_abort = False

    for record in index_records:
        if _429_abort:
            break
        for tab_title in approved_tabs.get(record["workbook_code"], []):
            if known_tabs and (record["spreadsheet_id"], tab_title) not in known_tabs:
                continue
            tab_hash = hashlib.sha1(tab_title.encode()).hexdigest()[:8]
            out_path = (
                deep_dir
                / f"{record['workbook_code']}_{record['year']}_{record['spreadsheet_id'][:8]}_{make_slug(tab_title)}_{tab_hash}.json"
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
                is_429 = isinstance(exc, HttpError) and getattr(exc.resp, "status", None) == 429
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

    enrich_computed_fields(candidate_columns)

    workbook_index: dict[str, dict] = {
        rec["workbook_code"]: rec for rec in index_records if "workbook_code" in rec
    }
    entity_names: set[str] = {
        _to_pascal_case(code) for code in approved_tabs
    }
    enrich_fk_candidates(candidate_columns, entity_names)
    enrich_import_key_candidates(candidate_columns)
    entity_map = enrich_entity_groupings(candidate_columns, workbook_index)

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
    column_heuristics = _normalize_column_heuristics(column_score_heuristics)
    default_min = 0 if not column_heuristics.get("domain_keyword_tokens") else 4
    min_score = int(config.get("column_min_score", default_min))
    selected_columns = sorted(
        [
            row
            for row in deduped.values()
            if row["priority_score"] >= min_score
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
