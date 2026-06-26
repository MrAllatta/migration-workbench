"""Profiler enrichment utilities for FK detection, computed fields, and entity grouping."""

import re
from typing import Any, Literal

_ENTITY_KEYWORDS = {"channel", "season", "crop", "block", "farm", "field", "variety"}
_IDENTIFIER_SUFFIXES = {"_id", "_code", "_key"}
_IDENTIFIER_NAMES = {"id", "name", "code", "slug", "uid", "uuid", "external_id"}

# Header semantic classification
_FORMULA_KEYWORDS = {"total", "sum", "avg", "net", "gross", "qty", "count", "subtotal"}
_STATUS_KEYWORDS = {"status", "stage", "state"}
_TIME_SCOPE_KEYWORDS = {"year", "week", "date", "month", "season", "period", "fy"}

# Compiled patterns for Q1/Q2/Q3/Q4 detection
_Q_PATTERN = re.compile(r"^q[1-4]$", re.IGNORECASE)

# Type alias for return values
HeaderCategory = Literal[
    "formula_keyword",
    "entity_keyword",
    "time_scope_keyword",
    "status_keyword",
    "generic",
]


def _to_pascal_case(raw: str) -> str:
    """Convert a label to PascalCase.

    If the input is already PascalCase (no underscores/hyphens, has uppercase
    after position 0), pass it through unchanged.
    """
    if not raw:
        return raw
    if "_" not in raw and "-" not in raw and any(c.isupper() for c in raw[1:]):
        return raw
    return "".join(p.capitalize() for p in raw.replace("-", "_").split("_"))


def detect_header_semantic_category(header_name: str) -> HeaderCategory:
    """Classify a column header into a semantic category.

    Uses keyword sets to classify headers into formula (computed field),
    entity (operational entity), time_scope (temporal), status, or generic.

    Args:
        header_name: The column header string to classify.

    Returns:
        One of ``"formula_keyword"``, ``"entity_keyword"``,
        ``"time_scope_keyword"``, ``"status_keyword"``, or ``"generic"``.
    """
    lowered = header_name.strip().lower()

    # Check status keywords first (most specific)
    if lowered in _STATUS_KEYWORDS:
        return "status_keyword"

    # Check time scope keywords including Q1-Q4 patterns
    if lowered in _TIME_SCOPE_KEYWORDS or _Q_PATTERN.match(lowered):
        return "time_scope_keyword"

    # Check formula keywords
    if lowered in _FORMULA_KEYWORDS:
        return "formula_keyword"

    # Check entity keywords
    if lowered in _ENTITY_KEYWORDS:
        return "entity_keyword"

    return "generic"


def glossary_expand(text: str, glossary: dict[str, str]) -> set[str]:
    """Return expanded forms of glossary keys found in *text*."""
    lowered = text.lower()
    expansions: set[str] = set()
    for abbr, full_form in glossary.items():
        if abbr.lower() in lowered:
            expansions.add(full_form.lower())
    return expansions


def enrich_fk_from_sheet_graph(
    column_profiles: dict[str, dict[str, Any]],
    dependency_artifact: dict[str, Any],
    weight_threshold: int = 3,
) -> None:
    """Suggest FK targets from sheet-level dependency graph edges.

    For each column profile whose tab has a high-weight outgoing edge
    to another tab in the sheet graph, sets ``suggested_fk_target``
    if the column doesn't already have one.

    Args:
        column_profiles: Dict mapping column letter/name to profile dict.
            Each profile should have a ``tab_name`` or ``worksheet`` key
            identifying which tab it belongs to.
        dependency_artifact: Output from ``build_dependency_artifact()``,
            must contain a ``sheet_graph`` key.
        weight_threshold: Minimum edge weight to consider as FK signal.
    """
    sheet_graph = dependency_artifact.get("sheet_graph")
    if not sheet_graph:
        return

    edges = sheet_graph.get("edges", [])
    if not edges:
        return

    # Build map: sheet -> outgoing edges with weight >= threshold, sorted desc
    sheet_out_edges: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        from_sheet = edge.get("from_sheet")
        to_sheet = edge.get("to_sheet")
        weight = edge.get("weight", 0)
        if not from_sheet or not to_sheet or weight < weight_threshold:
            continue
        sheet_out_edges.setdefault(from_sheet, []).append(edge)

    # Sort each sheet's edges by weight descending
    for sheet in sheet_out_edges:
        sheet_out_edges[sheet].sort(key=lambda e: e.get("weight", 0), reverse=True)

    for _col_key, profile in column_profiles.items():
        if profile.get("suggested_fk_target"):
            continue
        tab_name = profile.get("tab_name") or profile.get("worksheet")
        if not tab_name:
            continue
        outgoing = sheet_out_edges.get(tab_name)
        if not outgoing:
            continue
        target_sheet = outgoing[0].get("to_sheet")
        if target_sheet:
            profile["suggested_fk_target"] = target_sheet
            profile["_fk_from_sheet_graph"] = True


def enrich_from_dependency_graph(
    column_profiles: dict[str, dict[str, Any]],
    dependency_artifact: dict[str, Any],
    high_value_threshold: int = 3,
) -> None:
    """Augment column profiles with dependency-derived signals.

    Mutates *column_profiles* in place, adding:
        ``is_computed`` (bool): True when every cell in the column is a formula.
        ``suggested_fk_target`` (str): Tab name when the column's formulas
            contain cross-sheet INDEX/MATCH or other FK-like references.

    Args:
        column_profiles: Dict mapping column letter/name to profile dict.
            Each profile dict should have a ``column_cells`` key with
            a list of cell dicts containing ``kind`` and ``text``.
        dependency_artifact: Output from ``build_dependency_artifact()``.
        high_value_threshold: Minimum references to flag as high-value.
    """
    if not column_profiles or not dependency_artifact.get("nodes"):
        return

    cross_sheet_sources: set[str] = set()
    for edge in dependency_artifact.get("edges", []):
        if edge.get("is_cross_sheet"):
            cross_sheet_sources.add(edge["source"].split("!")[0])

    for _col_key, profile in column_profiles.items():
        cells = profile.get("column_cells", [])
        if not cells:
            continue

        formula_count = sum(1 for c in cells if c.get("kind") == "formula")
        total = len(cells)

        if formula_count == total and total > 0:
            profile["is_computed"] = True

        if formula_count > 0:
            for cell in cells:
                formula_text = cell.get("text", "")
                if not formula_text.startswith("="):
                    continue
                for sheet_name in cross_sheet_sources:
                    if sheet_name in formula_text and (
                        "INDEX" in formula_text.upper()
                        or "MATCH" in formula_text.upper()
                    ):
                        profile["suggested_fk_target"] = sheet_name
                        break
                if profile.get("suggested_fk_target"):
                    break
