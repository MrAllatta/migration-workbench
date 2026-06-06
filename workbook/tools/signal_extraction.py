"""Profiler signal extraction from structure artifacts and bundle config.

Profiler signals are Layer 1 of the interaction contract: automatically-inferred
heuristics that describe how each spreadsheet tab is *actually used* — whether
it is a data-entry form, a reference table, a dashboard of computed values, or
a list view.  These signals are the inputs operators confirm or correct during
the discovery interview (Layer 2).

Signal derivation rules
----------------------
*ui_archetype*
    Determined by the weighted heuristic matrix in ``archetype_matrix.py``
    (Approach A from the v0.4.0 design doc).  The archetype with the highest
    weighted score across 12 signals wins.

*formula_density*
    Ratio of formula-classified columns to total columns in the tab.

*cross_sheet_refs*
    Count of cross-sheet references extracted from profiler metadata (named
    ranges or filter views that reference other sheets).

*null_rates*
    Per-column null ratio derived from deep-profile row counts, or an empty
    dict when deep-profile data is not available.

*confidence_score*
    Margin-based confidence: ``(winner_score - runner_up_score) / max_possible``.
    Always in the range ``[0.0, 1.0]``.

*archetype_scores*
    Normalised score vector ``{form, list, dashboard, reference}`` showing
    how strongly each archetype matches.
"""

from __future__ import annotations

import datetime
from typing import Any

from profiler.tools.enrichment_utils import detect_header_semantic_category
from workbook.tools.archetype_matrix import (
    classify_archetype,
    explain_archetype as _explain_archetype,
)

SIGNALS_VERSION = 2

_MERGED_CELL_RATIO_DEFAULT = 0.0
_EXPANSION_FORMULA_RATIO_DEFAULT = 0.0


def _classify_ui_archetype_v2(
    *,
    column_count: int,
    formula_density: float,
    cross_sheet_ref_count: int,
    avg_null_rate: float,
    has_status_column: bool,
    has_time_scope: bool,
    data_validation_density: float,
    header_formula_count: int,
    header_entity_count: int,
    merged_cell_ratio: float,
    row_count: int,
    expansion_formula_ratio: float,
) -> tuple[str, float, dict[str, float]]:
    """Classify a tab using the weighted heuristic matrix.

    Delegates to ``archetype_matrix.classify_archetype()`` with all 12
    signals.  Returns the winning archetype label, margin-based confidence,
    and the full scores vector.
    """
    return classify_archetype(
        column_count=float(column_count),
        formula_density=formula_density,
        cross_sheet_ref_count=float(cross_sheet_ref_count),
        avg_null_rate=avg_null_rate,
        has_status_column=1.0 if has_status_column else 0.0,
        has_time_scope=1.0 if has_time_scope else 0.0,
        data_validation_density=data_validation_density,
        header_formula_count=float(header_formula_count),
        header_entity_count=float(header_entity_count),
        merged_cell_ratio=merged_cell_ratio,
        row_count=float(row_count),
        expansion_formula_ratio=expansion_formula_ratio,
    )


def _compute_avg_null_rate(null_rates: dict[str, float]) -> float:
    """Compute the average null rate across all columns."""
    if not null_rates:
        return 0.0
    return sum(null_rates.values()) / len(null_rates)


def _extract_cross_sheet_refs(tab: dict[str, Any]) -> int:
    """Count cross-sheet references from a tab's metadata."""
    count = 0
    for named_range in tab.get("named_ranges") or []:
        range_str = str(named_range.get("range", ""))
        if "!" in range_str:
            count += 1
    for fv in tab.get("filter_views") or []:
        fv_range = str(fv.get("range", ""))
        if "!" in fv_range:
            count += 1
    return count


def _detect_has_status_column(columns: list[dict[str, Any]]) -> bool:
    """Check if any column header matches a status keyword."""
    for col in columns:
        header = str(col.get("header_label") or "")
        if detect_header_semantic_category(header) == "status_keyword":
            return True
    return False


def _detect_has_time_scope(columns: list[dict[str, Any]]) -> bool:
    """Check if any column header matches a time-scope keyword."""
    for col in columns:
        header = str(col.get("header_label") or "")
        if detect_header_semantic_category(header) == "time_scope_keyword":
            return True
    return False


def _compute_data_validation_density(columns: list[dict[str, Any]]) -> float:
    """Compute the fraction of columns with a data validation type."""
    if not columns:
        return 0.0
    validated = sum(
        1 for col in columns if col.get("data_validation_type") is not None
    )
    return validated / len(columns)


def _count_header_formula_keywords(columns: list[dict[str, Any]]) -> int:
    """Count columns whose headers match formula keywords."""
    count = 0
    for col in columns:
        header = str(col.get("header_label") or "")
        if detect_header_semantic_category(header) == "formula_keyword":
            count += 1
    return count


def _count_header_entity_keywords(columns: list[dict[str, Any]]) -> int:
    """Count columns whose headers match entity keywords."""
    count = 0
    for col in columns:
        header = str(col.get("header_label") or "")
        if detect_header_semantic_category(header) == "entity_keyword":
            count += 1
    return count


def _compute_merged_cell_ratio(
    columns: list[dict[str, Any]],
    tab_profile: dict[str, Any] | None = None,
) -> float:
    """Compute the fraction of columns with merged header cells.

    Uses deep-profile data when available; otherwise returns 0.0.
    """
    if not columns:
        return 0.0
    if tab_profile:
        merged_count = tab_profile.get("merged_header_cells", 0)
        if merged_count > 0:
            return min(merged_count / len(columns), 1.0)
    return _MERGED_CELL_RATIO_DEFAULT


def _compute_expansion_formula_ratio(columns: list[dict[str, Any]]) -> float:
    """Compute the ratio of expansion-formula columns to total columns.

    Returns 0.0 when the structure artifact does not provide
    ``is_expansion_formula`` metadata.
    """
    if not columns:
        return 0.0
    expansion_count = sum(
        1 for col in columns if col.get("is_expansion_formula")
    )
    if expansion_count > 0:
        return expansion_count / len(columns)
    return _EXPANSION_FORMULA_RATIO_DEFAULT


def extract_signals(
    structure: dict[str, Any],
    bundle_config: dict[str, Any] | None = None,
    deep_profiles: dict[str, Any] | None = None,
    tab_classifications: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract profiler signals from a structure artifact.

    Args:
        structure: Parsed ``structure.json`` from
            ``pull_bundle --include-structure``.
        bundle_config: Optional parsed bundle config JSON.
        deep_profiles: Optional dict of deep-profile data keyed by tab title.
        tab_classifications: Optional dict mapping tab title to classification
            dict (with ``category``, ``confidence``, ``rationale`` keys).

    Returns:
        A signals dict conforming to the version-2 format::

            {
                "version": 2,
                "generated_at": "2026-06-01T...",
                "signals": [
                    {
                        "tab_title": "Crop Planner",
                        "workbook_code": "101",
                        "ui_archetype": "form",
                        "confidence_score": 0.17,
                        "formula_density": 0.25,
                        "cross_sheet_refs": 0,
                        "null_rates": {"Crop": 0.0, ...},
                        "has_status_column": true,
                        "has_time_scope": true,
                        "data_validation_density": 0.38,
                        "header_formula_count": 2,
                        "header_entity_count": 4,
                        "row_count": 200,
                        "expansion_formula_ratio": 0.0,
                        "merged_cell_ratio": 0.0,
                        "archetype_scores": {
                            "form": 0.37,
                            "list": 0.20,
                            "dashboard": 0.10,
                            "reference": 0.03,
                        },
                    },
                ],
            }
    """
    tabs = list(structure.get("tabs") or [])
    source_id = structure.get("source_id", "")

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

        formula_count = sum(1 for col in columns if col.get("is_formula"))
        formula_density = formula_count / len(columns) if columns else 0.0

        cross_sheet_refs = _extract_cross_sheet_refs(tab)

        null_rates: dict[str, float] = {}
        tab_profile: dict[str, Any] = {}
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

        avg_null_rate = _compute_avg_null_rate(null_rates)

        has_status_column = _detect_has_status_column(columns)
        has_time_scope = _detect_has_time_scope(columns)
        data_validation_density = _compute_data_validation_density(columns)
        header_formula_count = _count_header_formula_keywords(columns)
        header_entity_count = _count_header_entity_keywords(columns)
        row_count = total_rows
        expansion_formula_ratio = _compute_expansion_formula_ratio(columns)
        merged_cell_ratio = _compute_merged_cell_ratio(columns, tab_profile)

        ui_archetype, confidence_score, archetype_scores = (
            _classify_ui_archetype_v2(
                column_count=total_cols,
                formula_density=formula_density,
                cross_sheet_ref_count=cross_sheet_refs,
                avg_null_rate=avg_null_rate,
                has_status_column=has_status_column,
                has_time_scope=has_time_scope,
                data_validation_density=data_validation_density,
                header_formula_count=header_formula_count,
                header_entity_count=header_entity_count,
                merged_cell_ratio=merged_cell_ratio,
                row_count=row_count,
                expansion_formula_ratio=expansion_formula_ratio,
            )
        )

        # Attach tab classification if available
        tab_class: dict[str, Any] | None = None
        if tab_classifications and title in tab_classifications:
            tab_class = tab_classifications[title]

        entry: dict[str, Any] = {
            "tab_title": title,
            "workbook_code": workbook_code,
            "ui_archetype": ui_archetype,
            "confidence_score": round(confidence_score, 2),
            "column_count": total_cols,
            "avg_null_rate": round(avg_null_rate, 2),
            "formula_density": round(formula_density, 2),
            "cross_sheet_refs": cross_sheet_refs,
            "null_rates": null_rates,
            "has_status_column": has_status_column,
            "has_time_scope": has_time_scope,
            "data_validation_density": round(data_validation_density, 2),
            "header_formula_count": header_formula_count,
            "header_entity_count": header_entity_count,
            "row_count": row_count,
            "expansion_formula_ratio": round(expansion_formula_ratio, 2),
            "merged_cell_ratio": round(merged_cell_ratio, 2),
            "archetype_scores": archetype_scores,
        }
        if tab_class:
            entry["tab_classification"] = tab_class

        signals.append(entry)

    return {
        "version": SIGNALS_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "signals": signals,
    }


def explain_archetype(
    tab_title: str,
    structure: dict[str, Any] | None = None,
    deep_profiles: dict[str, Any] | None = None,
    signals_dict: dict[str, float] | None = None,
    label: str | None = None,
    confidence: float | None = None,
    archetype_scores: dict[str, float] | None = None,
) -> str:
    """Return a human-readable explanation of a tab's archetype classification.

    When *structure* is provided, signals are extracted on-the-fly.
    Alternatively, pass pre-computed *signals_dict*.
    """
    if structure is not None:
        tabs = list(structure.get("tabs") or [])
        for tab in tabs:
            tab_title_candidate = str(tab.get("worksheet_title") or "")
            if tab_title_candidate == tab_title:
                columns = list(tab.get("columns") or [])
                tab_profile = (
                    (deep_profiles or {}).get(tab_title) if deep_profiles else None
                )
                signals_dict = {
                    "column_count": float(
                        max(len(columns), tab.get("total_cols") or 0)
                    ),
                    "formula_density": sum(
                        1 for c in columns if c.get("is_formula")
                    )
                    / max(len(columns), 1),
                    "cross_sheet_ref_count": float(
                        _extract_cross_sheet_refs(tab)
                    ),
                    "avg_null_rate": _compute_avg_null_rate(
                        dict.fromkeys(
                            [c.get("header_label", "") for c in columns], 0.0
                        )
                    ),
                    "has_status_column": (
                        1.0 if _detect_has_status_column(columns) else 0.0
                    ),
                    "has_time_scope": (
                        1.0 if _detect_has_time_scope(columns) else 0.0
                    ),
                    "data_validation_density": (
                        _compute_data_validation_density(columns)
                    ),
                    "header_formula_count": float(
                        _count_header_formula_keywords(columns)
                    ),
                    "header_entity_count": float(
                        _count_header_entity_keywords(columns)
                    ),
                    "merged_cell_ratio": _compute_merged_cell_ratio(
                        columns, tab_profile
                    ),
                    "row_count": float(tab.get("total_rows") or 0),
                    "expansion_formula_ratio": (
                        _compute_expansion_formula_ratio(columns)
                    ),
                }
                break

    if signals_dict is None:
        return f"{tab_title} -- no signals available"

    if label is None or confidence is None or archetype_scores is None:
        label, confidence, archetype_scores = classify_archetype(**signals_dict)

    return _explain_archetype(
        tab_title,
        signals_dict,
        label=label,
        confidence=confidence,
        archetype_scores=archetype_scores,
    )
