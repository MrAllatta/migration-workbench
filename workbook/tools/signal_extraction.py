"""Profiler signal extraction from structure artifacts and bundle config.

Profiler signals are Layer 1 of the interaction contract: automatically-inferred
heuristics that describe how each spreadsheet tab is *actually used* — whether
it is a data-entry form, a reference table, a dashboard of computed values, or
a list view.  These signals are the inputs operators confirm or correct during
the discovery interview (Layer 2).

Signal derivation rules
-----------------------
*ui_archetype*
    - ``form``: 5–12 columns with moderate formula density (0.15–0.40)
    - ``list``: 15+ columns with low formula density (< 0.20)
    - ``dashboard``: high formula density (>= 0.50) or moderate formula with
      cross-sheet references
    - ``reference``: fewer than 5 columns, or high null rate across all columns

*formula_density*
    Ratio of formula-classified columns to total columns in the tab.

*cross_sheet_refs*
    Count of cross-sheet references extracted from profiler metadata (named
    ranges or filter views that reference other sheets).

*null_rates*
    Per-column null ratio derived from deep-profile row counts, or an empty
    dict when deep-profile data is not available.

*confidence_score*
    Weighted composite (equal weights in v1) of data completeness, coverage
    depth, and heuristic-match quality.  Always in the range ``[0.0, 1.0]``.
"""

from __future__ import annotations

import datetime
from typing import Any

SIGNALS_VERSION = 1

# Archetype thresholds
_FORM_MIN_COLS = 5
_FORM_MAX_COLS = 12
_FORM_MAX_FORMULA = 0.40
_FORM_MIN_FORMULA = 0.15
_LIST_MIN_COLS = 15
_LIST_MAX_FORMULA = 0.20
_DASHBOARD_MIN_FORMULA = 0.50
_REFERENCE_MAX_COLS = 5
_REFERENCE_NULL_RATE_THRESHOLD = 0.60


def _classify_ui_archetype(
    *,
    total_cols: int,
    formula_density: float,
    cross_sheet_refs: int,
    avg_null_rate: float,
) -> str:
    """Classify a tab into a UI archetype based on structural heuristics.

    Args:
        total_cols: Number of columns in the tab.
        formula_density: Ratio of formula columns to total columns (0.0–1.0).
        cross_sheet_refs: Number of cross-sheet references detected.
        avg_null_rate: Average null rate across all columns (0.0–1.0).

    Returns:
        One of ``"form"``, ``"list"``, ``"dashboard"``, or ``"reference"``.
    """
    # Dashboard: high formula density, or moderate + cross-sheet refs
    if formula_density >= _DASHBOARD_MIN_FORMULA or (
        formula_density >= _FORM_MIN_FORMULA and cross_sheet_refs > 0
    ):
        return "dashboard"

    # Reference: few columns or very sparse data
    if total_cols < _REFERENCE_MAX_COLS or avg_null_rate >= _REFERENCE_NULL_RATE_THRESHOLD:
        return "reference"

    # List: many columns with low formula density
    if total_cols >= _LIST_MIN_COLS and formula_density <= _LIST_MAX_FORMULA:
        return "list"

    # Form: moderate number of columns with moderate formula density
    if _FORM_MIN_COLS <= total_cols <= _FORM_MAX_COLS:
        if _FORM_MIN_FORMULA <= formula_density <= _FORM_MAX_FORMULA:
            return "form"
        # Form is also the fallback for 5–12 columns with low formula
        if formula_density < _FORM_MIN_FORMULA:
            return "form"

    # Fallback: form for moderate columns, list for wide, reference for narrow
    if total_cols < _FORM_MIN_COLS:
        return "reference"
    if total_cols > _LIST_MIN_COLS:
        return "list"
    return "form"


def _compute_confidence_score(
    *,
    total_rows: int,
    column_count: int,
    formula_density: float,
    cross_sheet_refs: int,
    has_null_rates: bool,
) -> float:
    """Compute a confidence score for the quality of extracted signals.

    In v1, all components are equally weighted.  Each component is normalised
    to ``[0.0, 1.0]``:

    1. **Data completeness**: rows-per-column ratio capped at 1.0.
    2. **Coverage depth**: how detailed the profile metadata is (formula info,
       cross-sheet refs, null rates).
    3. **Heuristic match quality**: how cleanly the tab fits one archetype
       (tabs near archetype boundaries score lower).

    Args:
        total_rows: Total rows in the tab (from structure artifact).
        column_count: Number of columns in the tab.
        formula_density: Ratio of formula columns (0.0–1.0).
        cross_sheet_refs: Number of cross-sheet references detected.
        has_null_rates: Whether deep-profile null rates are available.

    Returns:
        Float in ``[0.0, 1.0]``.
    """
    # 1. Data completeness
    rows_per_col = total_rows / max(column_count, 1)
    data_completeness = min(rows_per_col / 50.0, 1.0)  # 50 rows/col → 1.0

    # 2. Coverage depth: formula info + cross-sheet + null rates
    depth_score = 0.0
    # Having formula info at all is worth 0.3
    depth_score += 0.3
    # Cross-sheet references give +0.3 if present
    if cross_sheet_refs > 0:
        depth_score += 0.3
    # Null rates boost confidence
    if has_null_rates:
        depth_score += 0.4
    depth_score = min(depth_score, 1.0)

    # 3. Heuristic match quality: penalty for boundary cases
    # Low formula in a "list" is clean. High formula as "form" is less clean.
    if formula_density > 0.45 and column_count < _FORM_MAX_COLS:
        heuristic_quality = 0.6  # Form-ish but high formula
    elif formula_density < 0.1 and column_count > _LIST_MIN_COLS:
        heuristic_quality = 0.9  # Clear list
    elif formula_density > _DASHBOARD_MIN_FORMULA:
        heuristic_quality = 0.8  # Clear dashboard
    elif column_count < _REFERENCE_MAX_COLS:
        heuristic_quality = 0.7  # Reference-ish
    else:
        heuristic_quality = 0.75  # Generic fallback

    # Equal-weighted composite
    score = (data_completeness + depth_score + heuristic_quality) / 3.0
    return max(0.0, min(score, 1.0))


def _compute_avg_null_rate(null_rates: dict[str, float]) -> float:
    """Compute the average null rate across all columns.

    Args:
        null_rates: Mapping of column name to null rate (0.0–1.0).

    Returns:
        Average null rate, or 0.0 if the dict is empty.
    """
    if not null_rates:
        return 0.0
    return sum(null_rates.values()) / len(null_rates)


def _extract_cross_sheet_refs(tab: dict[str, Any]) -> int:
    """Count cross-sheet references from a tab's metadata.

    Checks ``named_ranges`` and ``filter_views`` for references to other
    sheets.  This is an approximation; the true count comes from the
    deep-profile pass.

    Args:
        tab: A tab entry from the structure artifact.

    Returns:
        Estimated count of cross-sheet references.
    """
    count = 0
    for named_range in tab.get("named_ranges") or []:
        range_str = str(named_range.get("range", ""))
        # A named range referencing another sheet contains an exclamation mark
        if "!" in range_str:
            count += 1
    # Filter views referencing other sheets
    for fv in tab.get("filter_views") or []:
        fv_range = str(fv.get("range", ""))
        if "!" in fv_range:
            count += 1
    return count


def extract_signals(
    structure: dict[str, Any],
    bundle_config: dict[str, Any] | None = None,
    deep_profiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract profiler signals from a structure artifact.

    Args:
        structure: Parsed ``structure.json`` from
            ``pull_bundle --include-structure``.
        bundle_config: Optional parsed bundle config JSON.  Used to resolve
            workbook codes for each tab.
        deep_profiles: Optional dict of deep-profile data keyed by tab title.
            When provided, per-column ``null_rates`` are populated from
            profile row counts.

    Returns:
        A signals dict conforming to the version-1 format::

            {
                "version": 1,
                "generated_at": "2026-06-01T...",
                "signals": [
                    {
                        "tab_title": "Crop Planner",
                        "workbook_code": "101",
                        "ui_archetype": "form",
                        "formula_density": 0.23,
                        "cross_sheet_refs": 3,
                        "null_rates": {"Crop Name": 0.0, ...},
                        "confidence_score": 0.85,
                    },
                ],
            }
    """
    tabs = list(structure.get("tabs") or [])
    source_id = structure.get("source_id", "")

    # Index bundle config by worksheet_title for workbook_code lookup
    bundle_tabs: dict[str, dict[str, Any]] = {}
    if bundle_config:
        for tab_entry in bundle_config.get("tabs") or []:
            title = str(tab_entry.get("worksheet_title") or "")
            if title:
                bundle_tabs[title] = tab_entry

    signals: list[dict[str, Any]] = []

    for tab in tabs:
        title = str(tab.get("worksheet_title") or "")
        columns = list(tab.get("columns") or [])
        total_cols = max(len(columns), tab.get("total_cols") or 0)
        total_rows = tab.get("total_rows") or 0

        # Resolve workbook_code: per-tab override → bundle source → structure source
        workbook_code = source_id
        if bundle_config:
            workbook_code = str(
                bundle_config.get("source_id", "") or workbook_code
            )
        bundle_match = bundle_tabs.get(title)
        if bundle_match:
            per_tab = bundle_match.get("source_id") or bundle_match.get(
                "workbook_code"
            )
            if per_tab:
                workbook_code = str(per_tab)

        # Formula density
        formula_count = sum(1 for col in columns if col.get("is_formula"))
        formula_density = formula_count / len(columns) if columns else 0.0

        # Cross-sheet references from struture metadata
        cross_sheet_refs = _extract_cross_sheet_refs(tab)

        # Null rates from deep profile data (if available)
        null_rates: dict[str, float] = {}
        has_null_rates = False
        if deep_profiles:
            tab_profile = deep_profiles.get(title) or {}
            for col_entry in columns:
                col_name = str(col_entry.get("header_label") or "")
                if col_name:
                    col_profile = tab_profile.get(col_name) or {}
                    null_count = col_profile.get("null_count", 0)
                    non_null_count = col_profile.get("non_null_count", 0)
                    total = null_count + non_null_count
                    if total > 0:
                        null_rates[col_name] = round(null_count / total, 2)
                    else:
                        null_rates[col_name] = 0.0
            has_null_rates = bool(null_rates)

        # Average null rate for archetype classification
        avg_null_rate = _compute_avg_null_rate(null_rates)

        # UI archetype
        ui_archetype = _classify_ui_archetype(
            total_cols=total_cols,
            formula_density=formula_density,
            cross_sheet_refs=cross_sheet_refs,
            avg_null_rate=avg_null_rate,
        )

        # Confidence score
        confidence_score = _compute_confidence_score(
            total_rows=total_rows,
            column_count=len(columns),
            formula_density=formula_density,
            cross_sheet_refs=cross_sheet_refs,
            has_null_rates=has_null_rates,
        )

        signals.append(
            {
                "tab_title": title,
                "workbook_code": workbook_code,
                "ui_archetype": ui_archetype,
                "formula_density": round(formula_density, 2),
                "cross_sheet_refs": cross_sheet_refs,
                "null_rates": null_rates,
                "confidence_score": round(confidence_score, 2),
            }
        )

    return {
        "version": SIGNALS_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "signals": signals,
    }
