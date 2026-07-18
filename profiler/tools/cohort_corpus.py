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
import math
import re
import re as _re
import logging
from dataclasses import dataclass, field
from pathlib import Path

from django.core.management.base import CommandError

from connectors.spreadsheet import (
    column_index_to_letter,
    guess_header_row,
    raw_sheet_to_row_lists,
)

from profiler.tools.domain_context import (
    DomainContext,
    merge_vocabulary,
)
from profiler.tools.enrichment_utils import (
    _ENTITY_KEYWORDS,
    _IDENTIFIER_NAMES,
    _IDENTIFIER_SUFFIXES,
    _to_pascal_case,
    glossary_expand,
)

from profiler.pipeline.selection import (  # noqa: F401 — re-exported for backward compat
    TAB_SELECTION_OVERRIDE_KEYS,
    apply_tab_selection_overrides,
    auto_select_tabs,
)
from profiler.pipeline.utils import (  # noqa: F401 — re-exported for backward compat
    make_slug,
    normalize_column_heuristics as _normalize_column_heuristics,
    normalize_tab_heuristics as _normalize_tab_heuristics,
    token_match as _token_match,
    write_json,
)

logger = logging.getLogger(__name__)

_TRUNCATE_LENGTH = 200


@dataclass
class ColumnProfile:
    """Profiled metadata for a single column in a spreadsheet tab."""

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
    """Lowercase a header and replace non-alphanumeric runs with underscores."""
    return _re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_") if header else ""


def compute_column_profiles(summary: dict, return_patterns_by_slug: bool = False):
    """Build ``ColumnProfile`` instances from a tab summary, classifying each column's formula pattern, type, and section-header status. Returns a list of profiles or a slug-to-pattern dict if ``return_patterns_by_slug`` is True."""
    raw_patterns = summary.get("column_formula_patterns") or {}
    if isinstance(raw_patterns, dict) and raw_patterns:
        first_key = next(iter(raw_patterns))
        patterns_by_letter = (
            raw_patterns if not isinstance(raw_patterns[first_key], dict) else {}
        )
    else:
        patterns_by_letter = {}

    candidates = summary.get("column_candidates") or summary.get("columns") or []
    total_columns = (
        max(
            (c.get("total_columns") or c.get("total_count") or len(candidates))
            for c in candidates
        )
        if candidates
        else 0
    )

    profiles = []
    for cand in candidates:
        letter = cand.get("letter") or cand.get("col_letter") or ""
        header_raw = (
            cand.get("header") or cand.get("header_label") or cand.get("name") or ""
        )
        header_slug = (
            _slugify_header(header_raw) if header_raw else f"col_{letter.lower()}"
        )
        pattern = patterns_by_letter.get(letter, "raw")

        pattern_truncated = len(pattern) > _TRUNCATE_LENGTH
        pattern_hash = (
            hashlib.sha256(pattern.encode()).hexdigest()[:8] if pattern else ""
        )
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
        unique_values = (
            cand.get("unique_values_sample") or cand.get("sample_values") or []
        )

        profiles.append(
            ColumnProfile(
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
            )
        )

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
        """Recursively walk folder structure, collecting workbook matches."""
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


# _token_match is re-exported from profiler.pipeline.utils


# _normalize_tab_heuristics is re-exported from profiler.pipeline.utils


# _normalize_column_heuristics is re-exported from profiler.pipeline.utils


def score_tab(
    title: str,
    rows: int,
    cols: int,
    *,
    tab_score_heuristics: dict | None = None,
    column_formula_patterns: dict[str, str] | None = None,
    domain_context: DomainContext | None = None,
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
    match_texts = {title.lower()}
    if domain_context is not None and domain_context.glossary:
        title_expansions = glossary_expand(title.lower(), domain_context.glossary)
        if title_expansions:
            match_texts.update(title_expansions)
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
            matched = []
            for token in tokens:
                if any(_token_match(token, text, match_mode) for text in match_texts):
                    matched.append(token)
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
                any(_token_match(token, text, match_mode) for text in match_texts)
                for token in combo
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
            exclude_matches.append(
                {
                    "pattern": entry["pattern"].pattern,
                    "penalty": entry["penalty"],
                }
            )
    if exclude_penalties:
        score += exclude_penalties
        reasons.append("tab_exclude_pattern")

    # Apply expansion_formula_ratio penalty
    expansion_penalty = heuristics.get("expansion_formula_penalty", 0)
    if expansion_penalty and column_formula_patterns:
        expansion_threshold = heuristics.get("expansion_formula_threshold", 0.5)
        total_cols = len(column_formula_patterns)
        expansion_count = sum(
            1
            for pattern in column_formula_patterns.values()
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


def _compile_exclude_regexes(
    tab_score_heuristics: dict | None,
) -> list[re.Pattern]:
    """Compile exclude-mode regexes from tab scoring heuristics.

    Extracts patterns where ``"exclude": true`` in ``tab_exclude_patterns``
    entries.  These are used for unconditional removal before scoring,
    unlike penalty patterns that only adjust scores.

    Args:
        tab_score_heuristics: Raw heuristic config dict (may be ``None``).

    Returns:
        list[re.Pattern]: Compiled regex patterns for true exclusion.
    """
    exclude_regexes: list[re.Pattern] = []
    for entry in (tab_score_heuristics or {}).get("tab_exclude_patterns", []):
        if (
            isinstance(entry, dict)
            and entry.get("exclude", False)
            and "pattern" in entry
        ):
            try:
                exclude_regexes.append(re.compile(entry["pattern"]))
            except re.error:
                logger.warning(
                    "Invalid tab_exclude_pattern regex (exclude mode): %r",
                    entry["pattern"],
                )
    return exclude_regexes


def select_tabs_from_inventory(
    index_records: list[dict],
    inventory_rows: list[dict],
    *,
    min_final_score: float = 2.0,
    tab_score_heuristics: dict | None = None,
    domain_context: DomainContext | None = None,
    per_workbook_heuristic_overrides: dict[str, dict] | None = None,
) -> list[dict]:
    """Score, aggregate across years, and filter inventory tabs by final score. Applies coverage bonus for tabs appearing in 3+ years. Returns a sorted shortlist."""
    tab_exclude_regexes = _compile_exclude_regexes(tab_score_heuristics)
    per_wb_exclude_regexes: dict[str, list[re.Pattern]] = {}
    for wb_code, wb_overrides in (per_workbook_heuristic_overrides or {}).items():
        per_wb_exclude_regexes[wb_code] = _compile_exclude_regexes(wb_overrides)

    base_heuristics = merge_vocabulary(tab_score_heuristics or {}, domain_context)
    effective_heuristics_by_wb: dict[str, dict] = {}
    by_sheet_id = {record["spreadsheet_id"]: record for record in index_records}
    scored: list[dict] = []
    for row in inventory_rows:
        meta = by_sheet_id.get(row["spreadsheet_id"])
        if meta is None:
            continue
        wb_code = meta["workbook_code"]

        # True exclusion — tabs matching exclude-mode patterns are removed
        # entirely from the candidate pool before scoring.
        if any(
            exclude_re.search(row["tab_title"])
            for exclude_re in tab_exclude_regexes
            + per_wb_exclude_regexes.get(wb_code, [])
        ):
            continue

        # Resolve per-workbook heuristic overrides
        if wb_code not in effective_heuristics_by_wb:
            wb_overrides = (per_workbook_heuristic_overrides or {}).get(wb_code, {})
            if wb_overrides:
                merged = dict(base_heuristics)
                for override_key, override_value in wb_overrides.items():
                    if override_key == "tab_exclude_patterns":
                        continue  # already handled by _compile_exclude_regexes
                    if isinstance(override_value, list) and isinstance(
                        merged.get(override_key), list
                    ):
                        merged[override_key] = merged[override_key] + override_value
                    else:
                        merged[override_key] = override_value
                effective_heuristics_by_wb[wb_code] = merged
            else:
                effective_heuristics_by_wb[wb_code] = base_heuristics

        score, reasons, breakdown = score_tab(
            row["tab_title"],
            row["rows"],
            row["cols"],
            tab_score_heuristics=effective_heuristics_by_wb[wb_code],
            domain_context=domain_context,
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

    # --- Tab Classification ---
    from profiler.tools.tab_classifier import classify_tabs_batch

    # Build domain hits map from breakdown token_matches
    domain_hits_map: dict[str, dict[str, int]] = {}
    for entry in scored:
        title = entry["tab_title"]
        breakdown = entry.get("breakdown", {})
        token_matches = breakdown.get("token_matches", [])
        hits: dict[str, int] = {}
        for tm in token_matches:
            cat = tm.get("category", "unknown")
            hits[cat] = hits.get(cat, 0) + 1
        if hits:
            domain_hits_map[title] = hits

    classifications = classify_tabs_batch(
        scored,
        domain_category_hits_map=domain_hits_map if domain_hits_map else None,
    )
    class_map = {c.tab_title: c for c in classifications}

    for entry in scored:
        cl = class_map.get(entry["tab_title"])
        if cl:
            entry["classification"] = cl.category
            entry["classification_confidence"] = cl.confidence
            entry["classification_rationale"] = cl.rationale
        else:
            entry["classification"] = "unknown"
            entry["classification_confidence"] = 0.0
            entry["classification_rationale"] = "Missing classification"

    aggregate: dict[tuple[str, str], dict] = {}
    for entry in scored:
        key = (entry["workbook_code"], entry["tab_title"])
        bucket = aggregate.setdefault(
            key,
            {
                "workbook_code": entry["workbook_code"],
                "tab_title": entry["tab_title"],
                "classification": entry.get("classification", "unknown"),
                "classification_confidence": entry.get(
                    "classification_confidence", 0.0
                ),
                "classification_rationale": entry.get("classification_rationale", ""),
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
        if domain_context is not None:
            active_or_forward = set(domain_context.year_scope.active) | set(
                domain_context.year_scope.forward
            )
            bonus_years = len(bucket["years"] & active_or_forward)
            coverage_bonus = 1 if bonus_years >= 2 else 0
        else:
            coverage_bonus = 1 if len(bucket["years"]) >= 2 else 0
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
            total_size_bonus += sum(bd.get("size_bonuses", {}).values())
        breakdown_summary = {
            "total_token_matches": total_token_matches,
            "category_counts": cat_counts,
            "avg_size_bonus": (
                round(total_size_bonus / len(bucket["breakdowns"]), 2)
                if bucket["breakdowns"]
                else 0
            ),
        }

        selected.append(
            {
                "workbook_code": bucket["workbook_code"],
                "tab_title": bucket["tab_title"],
                "classification": bucket.get("classification", "unknown"),
                "classification_confidence": bucket.get(
                    "classification_confidence", 0.0
                ),
                "classification_rationale": bucket.get("classification_rationale", ""),
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
    if domain_context is not None:
        for entry in selected:
            years = entry.get("years", [])
            if len(years) > 1:
                active_or_forward = set(domain_context.year_scope.active) | set(
                    domain_context.year_scope.forward
                )
                non_active = sorted(y for y in years if y not in active_or_forward)
                if non_active:
                    entry["duplicate_years"] = non_active

    selected.sort(
        key=lambda row: (-row["final_score"], row["workbook_code"], row["tab_title"])
    )
    return selected


# auto_select_tabs is re-exported from profiler.pipeline.selection


# TAB_SELECTION_OVERRIDE_KEYS and apply_tab_selection_overrides are re-exported from profiler.pipeline.selection


# make_slug is re-exported from profiler.pipeline.utils


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
    domain_context: DomainContext | None = None,
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
        if domain_context is not None and domain_context.glossary:
            header_expanded = glossary_expand(lowered, domain_context.glossary)
            if header_expanded:
                lowered = lowered + " " + " ".join(header_expanded)
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
    """Tag columns whose formula pattern indicates a computed (derived) field."""
    computed_patterns = {"row_formula", "expansion_formula"}
    for col in columns:
        evidence = col.get("evidence") or {}
        pattern = evidence.get("formula_pattern")
        col["is_computed"] = pattern in computed_patterns


def enrich_fk_candidates(columns: list[dict], entity_names: set[str]) -> None:
    """Suggest FK targets for ``_id``-suffixed columns or cross-sheet references."""
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
    """Tag columns that look like natural-key candidates for import lookup."""
    for col in columns:
        name = col.get("proposed_canonical_field", "")
        is_identifier = False
        for suffix in _IDENTIFIER_SUFFIXES:
            if name.endswith(suffix):
                is_identifier = True
                break
        if name in _IDENTIFIER_NAMES:
            is_identifier = True
        is_computed = col.get("is_computed", False)
        col["is_import_key_candidate"] = is_identifier and not is_computed


def enrich_entity_groupings(
    columns: list[dict],
) -> dict[str, str]:
    """Map each workbook-tab pair to a suggested entity name via header overlap."""
    tab_headers: dict[tuple[str, str], set[str]] = {}
    for col in columns:
        key = (col.get("workbook_code", ""), col.get("tab_title", ""))
        tab_headers.setdefault(key, set()).add(col.get("proposed_canonical_field", ""))
    tabs_by_wb: dict[str, list[tuple[str, set[str]]]] = {}
    for (wb_code, tab_title), headers in tab_headers.items():
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
        entity_name = entity_map.get(col.get("tab_title", ""))
        if entity_name is not None:
            col["suggested_entity"] = entity_name
            col["cross_tab_group"] = entity_name
        else:
            col["suggested_entity"] = None
            col["cross_tab_group"] = None
    return entity_map


# write_json is re-exported from profiler.pipeline.utils


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
            status = (
                "OK"
                if successes > 0 and failures == 0
                else "FAIL"
                if failures > 0
                else "N/A"
            )
            lines.append(
                f"- **{tab_title}** — {status} ({successes} ok, {failures} fail)"
            )
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
    from profiler.pipeline.adapters.sheets import SheetsCorpusAdapter

    adapter = SheetsCorpusAdapter(
        drive_service=drive_service,
        sheets_service=sheets_service,
        resume_from_tab_selection=resume_from_tab_selection,
        resume_from_broad=resume_from_broad,
        stop_before_deep=stop_before_deep,
        skip_existing_deep=skip_existing_deep,
        folder_id=folder_id,
    )
    return adapter.run(config=config, out_dir=out_dir, date_stamp=date_stamp)
