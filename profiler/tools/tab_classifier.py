"""Tab classification module for the profiler.

Classifies spreadsheet tabs into five categories:

- **data**: Operational data that drives the business (large, active-use tabs)
- **reference**: Lookup lists, codes, types, and glossary-style data
- **ui_config**: Small config tabs (filters, dropdowns, settings, helpers)
- **derived**: Computed/summary tabs (pivots, rollups, dashboards, reports)
- **unknown**: No confident classification possible

Usage:
    >>> from profiler.tools.tab_classifier import classify_tab
    >>> result = classify_tab("Crop Plan", row_count=500, col_count=30)
    >>> result.category
    'data'
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

TAB_CLASSIFICATION_CATEGORIES: frozenset[str] = frozenset(
    {"data", "reference", "ui_config", "derived", "unknown"}
)

# ---------------------------------------------------------------------------
# Compiled name patterns (module-level, compiled once)
# ---------------------------------------------------------------------------

_UI_CONFIG_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(filter|view|dropdown|lookup|settings)\b", re.IGNORECASE),
    re.compile(r"\b(filter|preset|layout|display)\b", re.IGNORECASE),
    re.compile(r"\b(menu|nav|tab|sheet)_?\d*$", re.IGNORECASE),
    re.compile(r"^_+", re.IGNORECASE),
    re.compile(r"^helper\b", re.IGNORECASE),
    re.compile(r"\b(instructions|notes|readme|about)\b", re.IGNORECASE),
    re.compile(r"\b(template|example|sample)\b", re.IGNORECASE),
]

_REFERENCE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(list|lookup|codes|types|categories)\b", re.IGNORECASE),
    re.compile(r"\b(reference|ref_)\b", re.IGNORECASE),
    re.compile(r"\b(terms|glossary)\b", re.IGNORECASE),
    re.compile(r"\b(channel|channel_code)\b$", re.IGNORECASE),
]

_DERIVED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(summary|total|rollup|aggregate)\b", re.IGNORECASE),
    re.compile(r"\b(report|dashboard|overview)\b", re.IGNORECASE),
    re.compile(r"\b(combined|consolidated)\b", re.IGNORECASE),
    re.compile(r"\b(pivot|crosstab|cross_tab)\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class TabClassification:
    """Classification result for a single spreadsheet tab.

    Attributes:
        tab_title: The original worksheet tab title.
        category: One of ``TAB_CLASSIFICATION_CATEGORIES``.
        confidence: Float in [0.0, 1.0] indicating classification confidence.
        signals: Dict of signals that influenced the decision.
        rationale: Human-readable explanation of why this classification
            was chosen.
    """

    tab_title: str
    category: str = "unknown"
    confidence: float = 0.0
    signals: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

    def __post_init__(self) -> None:
        """Validate category and confidence range."""
        if self.category not in TAB_CLASSIFICATION_CATEGORIES:
            raise ValueError(
                f"Invalid category {self.category!r}. "
                f"Must be one of {sorted(TAB_CLASSIFICATION_CATEGORIES)}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Confidence must be in [0.0, 1.0], got {self.confidence}"
            )


# ---------------------------------------------------------------------------
# Name pattern matching helpers
# ---------------------------------------------------------------------------


def _matches_any_pattern(title: str, patterns: list[re.Pattern[str]]) -> bool:
    """Return True if *title* matches any regex in *patterns*."""
    for pattern in patterns:
        if pattern.search(title):
            return True
    return False


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------


def classify_tab(
    tab_title: str,
    row_count: int = 0,
    col_count: int = 0,
    formula_ratio: float = 0.0,
    score: float = 0.0,
    scoring_reasons: list[str] | None = None,
    domain_category_hits: dict[str, int] | None = None,
    is_excluded: bool = False,
) -> TabClassification:
    """Classify a single tab by its name, dimensions, formula ratio, and
    domain-category hints.

    Classification priority (first match wins):

    1. ``is_excluded=True`` → ``unknown`` (confidence 0.0)
    2. ``formula_ratio >= 0.6`` AND ``row_count < 100`` → ``derived``
       (confidence = min(formula_ratio, 0.9))
    3. UI config name pattern match AND (``row_count <= 20`` or
       ``col_count <= 8``) → ``ui_config`` (confidence 0.85)
    4. ``row_count <= 20`` AND ``col_count <= 8`` → ``ui_config``
       (confidence 0.75)
    5. Reference name pattern match AND ``row_count <= 500`` → ``reference``
       (confidence 0.85)
    6. Derived name pattern match → ``derived`` (confidence 0.80)
    7. ``row_count >= 100`` AND ``domain_category_hits.get("operational", 0) > 0``
       → ``data`` (confidence = min(0.7 + hits * 0.1, 0.95))
    8. ``domain_category_hits.get("reference", 0) > 0`` AND
       ``row_count <= 500`` → ``reference`` (confidence 0.70)
    9. ``row_count >= 100`` → ``data`` (confidence 0.60, conservative)
    10. Fallback → ``unknown`` (confidence 0.0)

    Args:
        tab_title: The worksheet tab title.
        row_count: Number of data rows in the tab.
        col_count: Number of data columns in the tab.
        formula_ratio: Fraction of columns that are expansion_formula
            (0.0–1.0).
        score: Heuristic or pipeline score for this tab.
        scoring_reasons: List of reason labels from upstream scoring.
        domain_category_hits: Mapping of domain category → hit count
            from token matching (e.g. ``{"operational": 2}``).
        is_excluded: When True, the tab is classified as unknown.

    Returns:
        A ``TabClassification`` instance.
    """
    signals: dict[str, Any] = {
        "row_count": row_count,
        "col_count": col_count,
        "formula_ratio": formula_ratio,
        "score": score,
    }
    if scoring_reasons:
        signals["scoring_reasons"] = scoring_reasons

    hits = domain_category_hits or {}
    title_lower = tab_title  # patterns use re.IGNORECASE

    # -- Rule 1: Excluded tab --
    if is_excluded:
        return TabClassification(
            tab_title=tab_title,
            category="unknown",
            confidence=0.0,
            signals=signals,
            rationale="Tab is excluded from profiling",
        )

    # -- Rule 2: High formula ratio, small rows → derived --
    if formula_ratio >= 0.6 and row_count < 100:
        confidence = min(formula_ratio, 0.9)
        return TabClassification(
            tab_title=tab_title,
            category="derived",
            confidence=confidence,
            signals=signals,
            rationale=(
                f"High formula ratio ({formula_ratio:.2f}) with "
                f"few rows ({row_count}) suggests derived/computed tab"
            ),
        )

    # -- Rule 3: UI config name pattern + small dimensions --
    if _matches_any_pattern(title_lower, _UI_CONFIG_PATTERNS):
        if row_count <= 20 or col_count <= 8:
            return TabClassification(
                tab_title=tab_title,
                category="ui_config",
                confidence=0.85,
                signals=signals,
                rationale=(
                    f"Tab title matches UI config pattern and is small "
                    f"({row_count}r x {col_count}c)"
                ),
            )

    # -- Rule 4: Tiny dimensions → ui_config --
    if row_count <= 20 and col_count <= 8:
        return TabClassification(
            tab_title=tab_title,
            category="ui_config",
            confidence=0.75,
            signals=signals,
            rationale=(
                f"Tab is very small ({row_count}r x {col_count}c), "
                f"likely UI configuration"
            ),
        )

    # -- Rule 5: Reference name pattern + modest rows --
    if _matches_any_pattern(title_lower, _REFERENCE_PATTERNS) and row_count <= 500:
        return TabClassification(
            tab_title=tab_title,
            category="reference",
            confidence=0.85,
            signals=signals,
            rationale=(
                f"Tab title matches reference pattern with "
                f"{row_count} rows"
            ),
        )

    # -- Rule 6: Derived name pattern --
    if _matches_any_pattern(title_lower, _DERIVED_PATTERNS):
        return TabClassification(
            tab_title=tab_title,
            category="derived",
            confidence=0.80,
            signals=signals,
            rationale=(
                f"Tab title matches derived/summary pattern"
            ),
        )

    # -- Rule 7: Large + operational domain hits → data --
    if row_count >= 100 and hits.get("operational", 0) > 0:
        op_hits = hits["operational"]
        confidence = min(0.7 + op_hits * 0.1, 0.95)
        return TabClassification(
            tab_title=tab_title,
            category="data",
            confidence=confidence,
            signals=signals,
            rationale=(
                f"Tab has {row_count} rows and {op_hits} operational "
                f"domain hits → operational data"
            ),
        )

    # -- Rule 8: Reference domain hits + modest rows --
    if hits.get("reference", 0) > 0 and row_count <= 500:
        return TabClassification(
            tab_title=tab_title,
            category="reference",
            confidence=0.70,
            signals=signals,
            rationale=(
                f"Tab has {hits['reference']} reference domain hits "
                f"with {row_count} rows"
            ),
        )

    # -- Rule 9: Large tab → data (conservative) --
    if row_count >= 100:
        return TabClassification(
            tab_title=tab_title,
            category="data",
            confidence=0.60,
            signals=signals,
            rationale=(
                f"Tab has {row_count} rows (>= 100), classified as "
                f"data with conservative confidence"
            ),
        )

    # -- Rule 10: Fallback --
    return TabClassification(
        tab_title=tab_title,
        category="unknown",
        confidence=0.0,
        signals=signals,
        rationale=(
            f"No classification heuristic matched for "
            f"'{tab_title}' ({row_count}r x {col_count}c)"
        ),
    )


# ---------------------------------------------------------------------------
# Batch classification
# ---------------------------------------------------------------------------


def classify_tabs_batch(
    entries: list[dict[str, Any]],
    domain_category_hits_map: dict[str, dict[str, int]] | None = None,
) -> list[TabClassification]:
    """Classify a list of tab entry dicts in batch.

    Each *entry* in *entries* must have at minimum a ``tab_title`` key.
    Optional keys: ``rows`` (or ``row_count``), ``cols`` (or ``col_count``),
    ``score``, ``reasons``, ``breakdown``.

    When an entry has a ``breakdown`` dict with ``token_matches``, the
    token-matches are used as domain-category hits unless an explicit
    *domain_category_hits_map* is provided.

    Args:
        entries: List of tab entry dicts.
        domain_category_hits_map: Optional mapping of tab_title → dict of
            domain category → hit count. When provided, this takes precedence
            over inline ``breakdown`` data.

    Returns:
        List of ``TabClassification`` instances in the same order as
        *entries*.
    """
    if domain_category_hits_map is None:
        domain_category_hits_map = {}

    results: list[TabClassification] = []
    for entry in entries:
        title = entry.get("tab_title", "")
        if not title:
            continue

        rows = entry.get("rows") or entry.get("row_count") or 0
        cols = entry.get("cols") or entry.get("col_count") or 0
        score = entry.get("score") or 0.0
        reasons = entry.get("reasons") or entry.get("scoring_reasons")

        # Formula ratio: from breakdown or direct
        breakdown = entry.get("breakdown", {})
        formula_ratio = breakdown.get("formula_ratio", 0.0)

        # Domain category hits: explicit map > inline token_matches
        if title in domain_category_hits_map:
            domain_hits = domain_category_hits_map[title]
        else:
            token_matches = breakdown.get("token_matches", [])
            domain_hits = _extract_domain_hits(token_matches)

        is_excluded = entry.get("is_excluded", False)

        result = classify_tab(
            tab_title=title,
            row_count=int(rows) if rows else 0,
            col_count=int(cols) if cols else 0,
            formula_ratio=float(formula_ratio),
            score=float(score),
            scoring_reasons=reasons,
            domain_category_hits=domain_hits,
            is_excluded=bool(is_excluded),
        )
        results.append(result)

    return results


def _extract_domain_hits(
    token_matches: list[dict[str, Any]],
) -> dict[str, int]:
    """Extract domain category hit counts from token_match entries.

    Args:
        token_matches: List of token_match dicts, each with a ``category`` key.

    Returns:
        Dict mapping category → count.
    """
    hits: dict[str, int] = {}
    for tm in token_matches:
        cat = tm.get("category", "unknown")
        hits[cat] = hits.get(cat, 0) + 1
    return hits


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def classification_summary(
    classifications: list[TabClassification],
) -> dict[str, Any]:
    """Produce a summary dict from a list of tab classifications.

    Args:
        classifications: List of ``TabClassification`` instances.

    Returns:
        Dict with keys:
        - ``total``: Total number of classifications.
        - ``classified``: Number with category != "unknown".
        - ``coverage_pct``: Percentage of tabs classified (0.0–100.0).
        - ``counts``: Per-category counts dict.
        - ``unknown_tabs``: List of tab titles classified as unknown.
        - ``data_tabs``: List of tab titles classified as data.
        - ``ui_config_tabs``: List of tab titles classified as ui_config.
        - ``reference_tabs``: List of tab titles classified as reference.
        - ``derived_tabs``: List of tab titles classified as derived.
    """
    total = len(classifications)
    counts: dict[str, int] = {c: 0 for c in TAB_CLASSIFICATION_CATEGORIES}
    unknown_tabs: list[str] = []
    data_tabs: list[str] = []
    ui_config_tabs: list[str] = []
    reference_tabs: list[str] = []
    derived_tabs: list[str] = []

    for tc in classifications:
        counts[tc.category] = counts.get(tc.category, 0) + 1
        if tc.category == "unknown":
            unknown_tabs.append(tc.tab_title)
        elif tc.category == "data":
            data_tabs.append(tc.tab_title)
        elif tc.category == "ui_config":
            ui_config_tabs.append(tc.tab_title)
        elif tc.category == "reference":
            reference_tabs.append(tc.tab_title)
        elif tc.category == "derived":
            derived_tabs.append(tc.tab_title)

    classified = total - counts.get("unknown", 0)
    coverage_pct = round(classified / total * 100, 1) if total > 0 else 0.0

    return {
        "total": total,
        "classified": classified,
        "coverage_pct": coverage_pct,
        "counts": counts,
        "unknown_tabs": unknown_tabs,
        "data_tabs": data_tabs,
        "ui_config_tabs": ui_config_tabs,
        "reference_tabs": reference_tabs,
        "derived_tabs": derived_tabs,
    }
