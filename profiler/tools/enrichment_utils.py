"""Profiler enrichment utilities for FK detection, computed fields, and entity grouping."""

import re
from typing import Literal

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
    "formula_keyword", "entity_keyword", "time_scope_keyword",
    "status_keyword", "generic",
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
