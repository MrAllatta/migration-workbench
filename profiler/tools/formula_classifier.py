"""Column-level formula pattern classification for profiler output.

Classifies each column's formula structure to distinguish raw data entry
columns from computed columns (row-level formulas, expansion formulas, hybrid).
"""

from __future__ import annotations

from typing import Any

_EXPANSION_FUNCTIONS: frozenset[str] = frozenset({
    "ARRAYFORMULA",
    "QUERY",
    "FILTER",
    "SORT",
    "UNIQUE",
    "FLATTEN",
    "SPLIT",
    "SEQUENCE",
})

_EMPTY_RATIO_THRESHOLD = 0.75


def _is_expansion_formula(formula_text: str) -> bool:
    """Return True when *formula_text* is governed by an expansion function."""
    upper = formula_text.upper()
    for func in _EXPANSION_FUNCTIONS:
        if func in upper:
            return True
    return False


def classify_column_formula_pattern(cells: list[dict[str, Any]]) -> str:
    """Classify a column's formula structure.

    Analyzes cell-level formula patterns within a column to determine whether
    the column is raw data entry, row-level formula, expansion formula, hybrid,
    or empty.

    Args:
        cells: List of cell dicts with at least ``kind`` (``"formula"``,
            ``"string"``, ``"number"``, ``"bool"``, ``"empty"``) and
            ``text`` (the formula text or cell value).

    Returns:
        str: One of ``"raw"``, ``"row_formula"``, ``"expansion_formula"``,
        ``"hybrid"``, or ``"empty"``.
    """
    if not cells:
        return "empty"

    total = len(cells)
    formula_count = 0
    raw_count = 0
    empty_count = 0
    expansion_detected = False
    row_formula_detected = False

    for cell in cells:
        kind = cell.get("kind", "empty")
        text = cell.get("text", "")

        if kind == "formula":
            formula_count += 1
            if _is_expansion_formula(text):
                expansion_detected = True
            else:
                row_formula_detected = True
        elif kind == "empty":
            empty_count += 1
        else:
            raw_count += 1

    empty_ratio = empty_count / total if total > 0 else 1.0

    if empty_ratio >= _EMPTY_RATIO_THRESHOLD:
        return "empty"

    if expansion_detected and not row_formula_detected and raw_count == 0:
        return "expansion_formula"

    if formula_count > 0 and raw_count > 0:
        return "hybrid"

    if formula_count == total:
        return "expansion_formula" if expansion_detected else "row_formula"

    if raw_count == total:
        return "raw"

    if formula_count > 0 and raw_count == 0:
        return "row_formula"

    return "raw"
