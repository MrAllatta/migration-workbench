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
import re
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


def _extract_sheet_name_from_range(range_str: str) -> str | None:
    """Extract the sheet name from a range string like ``'Sheet2'!A1:B10``.

    Args:
        range_str: A range string potentially containing a sheet reference.

    Returns:
        The sheet name (without surrounding quotes), or ``None`` if the
        range string does not reference another sheet.
    """
    if "!" not in range_str:
        return None
    sheet_part = range_str.split("!")[0]
    return sheet_part.strip("'\"")


def _extract_formula_edges_from_text(
    formula_text: str,
    source_tab: str,
) -> list[dict[str, Any]]:
    """Extract dependency edges from a single formula text string.

    Detects IMPORTRANGE, VLOOKUP, HLOOKUP, SUM/SUMIF/SUMIFS range refs,
    and direct cell references (``'Sheet'!A1``) to other sheets.

    Args:
        formula_text: The raw formula text.
        source_tab: Name of the tab containing the formula.

    Returns:
        List of edge dicts extracted from this formula.
    """
    found: list[dict[str, Any]] = []
    seen_targets: set[str] = set()

    # IMPORTRANGE("key", "'Sheet'!range") or IMPORTRANGE("url", "'Sheet'!range")
    for match in re.finditer(r"IMPORTRANGE\s*\([^)]+\)", formula_text, re.IGNORECASE):
        inner = match.group()
        # Find the second argument which contains the range
        parts = re.findall(r'"([^"]+)"', inner)
        if len(parts) >= 2:
            range_arg = parts[-1]
            target = _extract_sheet_name_from_range(range_arg)
            if target and target != source_tab and target not in seen_targets:
                seen_targets.add(target)
                found.append(
                    {
                        "from": source_tab,
                        "to": target,
                        "ref_type": "IMPORTRANGE",
                        "confidence": 0.90,
                    }
                )

    # VLOOKUP(lookup, 'Sheet'!range, ...)
    for match in re.finditer(
        r"(?:V|H)LOOKUP\s*\([^,]+,\s*'([^']+)'!",
        formula_text,
        re.IGNORECASE,
    ):
        target = match.group(1)
        if target != source_tab and target not in seen_targets:
            seen_targets.add(target)
            ref_type = (
                "VLOOKUP" if formula_text[match.start()].upper() == "V" else "HLOOKUP"
            )
            found.append(
                {
                    "from": source_tab,
                    "to": target,
                    "ref_type": ref_type,
                    "confidence": 0.85,
                }
            )

    # SUM/SUMIF/SUMIFS('Sheet'!range)
    for match in re.finditer(
        r"SUM(?:IF[S]?)?\s*\(\s*'([^']+)'!",
        formula_text,
        re.IGNORECASE,
    ):
        target = match.group(1)
        if target != source_tab and target not in seen_targets:
            seen_targets.add(target)
            found.append(
                {
                    "from": source_tab,
                    "to": target,
                    "ref_type": "SUM_range",
                    "confidence": 0.80,
                }
            )

    # Direct cell references: 'Sheet'!A1 (but not already caught above)
    for match in re.finditer(
        r"'([^']+)'!\$?[A-Z]+\$?\d+",
        formula_text,
    ):
        target = match.group(1)
        if target != source_tab and target not in seen_targets:
            seen_targets.add(target)
            found.append(
                {
                    "from": source_tab,
                    "to": target,
                    "ref_type": "cell_ref",
                    "confidence": 0.60,
                }
            )

    return found


def _extract_dependency_edges(
    tab: dict[str, Any],
    tab_title: str,
    deep_profiles: dict[str, Any] | None = None,
    formula_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Extract dependency edges from a tab's metadata.

    Extracts edges from:
    - Named ranges referencing other sheets
    - Filter views referencing other sheets
    - Formula patterns (IMPORTRANGE, VLOOKUP, SUM range refs, cell refs)
      when ``deep_profiles`` or ``formula_data`` is available

    Args:
        tab: Tab structure dict from the structure artifact.
        tab_title: Title of the source tab (used as the ``from`` field).
        deep_profiles: Optional deep-profile data keyed by tab title.
            When present, checks each column for ``formula_text``.
        formula_data: Optional pre-scanned formula data keyed by tab
            title.  Each entry is a list of dicts with a ``formula_text``
            key.

    Returns:
        List of edge dicts with keys ``from``, ``to``, ``ref_type``,
        ``confidence``.
    """
    edges: list[dict[str, Any]] = []

    # Named ranges referencing other sheets.
    for named_range in tab.get("named_ranges") or []:
        range_str = str(named_range.get("range", ""))
        target = _extract_sheet_name_from_range(range_str)
        if target and target != tab_title:
            edges.append(
                {
                    "from": tab_title,
                    "to": target,
                    "ref_type": "named_range",
                    "confidence": 0.95,
                }
            )

    # Filter views referencing other sheets.
    for fv in tab.get("filter_views") or []:
        fv_range = str(fv.get("range", ""))
        target = _extract_sheet_name_from_range(fv_range)
        if target and target != tab_title:
            edges.append(
                {
                    "from": tab_title,
                    "to": target,
                    "ref_type": "filter_view",
                    "confidence": 0.80,
                }
            )

    # Formula patterns from deep_profiles (column-level formula_text).
    if deep_profiles and tab_title in deep_profiles:
        tab_profile = deep_profiles[tab_title]
        if isinstance(tab_profile, dict):
            for col_name, col_profile in tab_profile.items():
                if isinstance(col_profile, dict):
                    formula_text = str(col_profile.get("formula_text") or "")
                    if formula_text:
                        edges.extend(
                            _extract_formula_edges_from_text(formula_text, tab_title)
                        )

    # Formula patterns from optional formula_data parameter.
    if formula_data and tab_title in formula_data:
        for formula_entry in formula_data[tab_title]:
            formula_text = str(formula_entry.get("formula_text") or "")
            if formula_text:
                edges.extend(_extract_formula_edges_from_text(formula_text, tab_title))

    return edges


def _build_workflow_graph(
    all_edges: list[dict[str, Any]],
    tabs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a workflow_graph from dependency edges across all tabs.

    Produces a graph with tab metadata, deduplicated edges, topological
    tab ordering, and cycle detection flags.

    Args:
        all_edges: All dependency edges from all tabs.
        tabs: List of tab dicts from the structure artifact.

    Returns:
        Workflow graph dict::

            {
                "tabs": {
                    "CropPlanner": {"title": "Crop Planner", "position": 0},
                },
                "edges": [
                    {"from": "CropPlanner", "to": "HarvestRecord",
                     "ref_type": "VLOOKUP", "confidence": 0.85},
                ],
                "tab_sequence": ["CropPlanner", "HarvestRecord"],
                "has_cycles": false,
            }
    """
    # Build tab lookup from structure.
    tab_lookup: dict[str, dict[str, Any]] = {}
    for tab in tabs:
        title = str(tab.get("worksheet_title") or "")
        if title:
            tab_lookup[title] = {
                "title": title,
                "position": tab.get("tab_position", 0),
            }

    # Deduplicate edges.
    unique_edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for edge in all_edges:
        key = (edge["from"], edge["to"], edge["ref_type"])
        if key not in seen_edges:
            seen_edges.add(key)
            unique_edges.append(edge)

    # Collect all tab names from structure + edges.
    all_tab_names: set[str] = set(tab_lookup.keys())
    for edge in unique_edges:
        all_tab_names.add(edge["from"])
        all_tab_names.add(edge["to"])
    all_tabs_sorted = sorted(all_tab_names)

    # Build adjacency list.
    adjacency: dict[str, list[str]] = {t: [] for t in all_tabs_sorted}
    for edge in unique_edges:
        if edge["from"] in adjacency and edge["to"] in adjacency:
            adjacency[edge["from"]].append(edge["to"])

    # Cycle detection via DFS colouring.
    WHITE, GRAY, BLACK = 0, 1, 2
    colour: dict[str, int] = {t: WHITE for t in all_tabs_sorted}
    cycles_found: list[str] = []

    def _dfs_cycle(node: str, path: list[str]) -> None:
        colour[node] = GRAY
        path.append(node)
        for neighbor in adjacency.get(node, []):
            if colour.get(neighbor) == GRAY:
                cycle_start = path.index(neighbor)
                cycle_path = path[cycle_start:] + [neighbor]
                cycles_found.append(" -> ".join(cycle_path))
            elif colour.get(neighbor) == WHITE:
                _dfs_cycle(neighbor, path)
        path.pop()
        colour[node] = BLACK

    for node_name in all_tabs_sorted:
        if colour.get(node_name) == WHITE:
            _dfs_cycle(node_name, [])

    has_cycles = len(cycles_found) > 0

    # Topological sort via Kahn's algorithm.
    in_degree: dict[str, int] = {t: 0 for t in all_tabs_sorted}
    for edge in unique_edges:
        if edge["to"] in in_degree:
            in_degree[edge["to"]] += 1

    queue: list[str] = [t for t in all_tabs_sorted if in_degree[t] == 0]
    tab_sequence: list[str] = []

    while queue:
        node = queue.pop(0)
        tab_sequence.append(node)
        for neighbor in adjacency.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Add any remaining nodes (in cycles) at the end.
    remaining = [t for t in all_tabs_sorted if t not in tab_sequence]
    tab_sequence.extend(remaining)

    # Build tabs dict for graph output.
    graph_tabs: dict[str, dict[str, Any]] = {}
    for tab_name in all_tabs_sorted:
        tab_info = tab_lookup.get(
            tab_name,
            {
                "title": tab_name,
                "position": -1,
            },
        )
        graph_tabs[tab_name] = dict(tab_info)

    workflow_graph: dict[str, Any] = {
        "tabs": graph_tabs,
        "edges": unique_edges,
        "tab_sequence": tab_sequence,
        "has_cycles": has_cycles,
    }
    if cycles_found:
        workflow_graph["cycles"] = list(cycles_found)

    return workflow_graph


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
    validated = sum(1 for col in columns if col.get("data_validation_type") is not None)
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
    expansion_count = sum(1 for col in columns if col.get("is_expansion_formula"))
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
                "workflow_graph": {
                    "tabs": {
                        "CropPlanner": {"title": "Crop Planner", "position": 0},
                    },
                    "edges": [
                        {"from": "CropPlanner", "to": "HarvestRecord",
                         "ref_type": "VLOOKUP", "confidence": 0.85},
                    ],
                    "tab_sequence": ["CropPlanner", "HarvestRecord"],
                    "has_cycles": false,
                },
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
    all_edges: list[dict[str, Any]] = []

    for tab in tabs:
        title = str(tab.get("worksheet_title") or "")
        columns = list(tab.get("columns") or [])
        total_cols = max(len(columns), tab.get("total_cols") or 0)
        total_rows = tab.get("total_rows") or 0

        workbook_code = source_id
        if bundle_config:
            workbook_code = str(bundle_config.get("source_id", "") or workbook_code)
        bundle_match = bundle_tabs.get(title)
        if bundle_match:
            per_tab = bundle_match.get("source_id") or bundle_match.get("workbook_code")
            if per_tab:
                workbook_code = str(per_tab)

        formula_count = sum(1 for col in columns if col.get("is_formula"))
        formula_density = formula_count / len(columns) if columns else 0.0

        tab_edges = _extract_dependency_edges(tab, title, deep_profiles=deep_profiles)
        all_edges.extend(tab_edges)
        cross_sheet_refs = len(tab_edges)

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

        ui_archetype, confidence_score, archetype_scores = _classify_ui_archetype_v2(
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

    workflow_graph = _build_workflow_graph(all_edges, tabs)

    return {
        "version": SIGNALS_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "signals": signals,
        "workflow_graph": workflow_graph,
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
                    "formula_density": sum(1 for c in columns if c.get("is_formula"))
                    / max(len(columns), 1),
                    "cross_sheet_ref_count": float(
                        len(_extract_dependency_edges(tab, tab_title_candidate))
                    ),
                    "avg_null_rate": _compute_avg_null_rate(
                        dict.fromkeys([c.get("header_label", "") for c in columns], 0.0)
                    ),
                    "has_status_column": (
                        1.0 if _detect_has_status_column(columns) else 0.0
                    ),
                    "has_time_scope": (1.0 if _detect_has_time_scope(columns) else 0.0),
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
