"""Weighted heuristic archetype matrix for UI archetype classification.

This module defines the scoring matrix (Approach A from the v0.4.0 design doc)
that replaces the sequential ``if/elif`` classifier with a multi-factor weighted
scoring system.  Each archetype (form, list, dashboard, reference) defines
weights for 12 signals.  The archetype with the highest weighted score wins,
and confidence is the margin between the winner and runner-up.

Typical usage::

    from workbook.tools.archetype_matrix import classify_archetype

    label, confidence, scores = classify_archetype(
        column_count=8,
        formula_density=0.25,
        cross_sheet_ref_count=0,
        avg_null_rate=0.05,
        has_status_column=True,
        has_time_scope=True,
        data_validation_density=0.38,
        header_formula_count=2,
        header_entity_count=4,
        merged_cell_ratio=0.0,
        row_count=200,
        expansion_formula_ratio=0.0,
    )
    # label == "form", confidence == 0.56, scores == {...}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Weight functions — each maps a signal value to a numeric contribution
# for a specific archetype.
# ---------------------------------------------------------------------------

# Sentinel for "weight is a single callable used by all archetypes"
_WEIGHT_FN = Callable[[float], float]


def _threshold(value: float, threshold: float, weight: float) -> float:
    """Return *weight* when *value* >= *threshold*, else 0."""
    return weight if value >= threshold else 0.0


def _range_weight(value: float, lo: float, hi: float, weight: float) -> float:
    """Return *weight* when *lo* <= *value* <= *hi*, else 0."""
    return weight if lo <= value <= hi else 0.0


def _range_below(value: float, hi: float, weight: float) -> float:
    """Return *weight* when *value* < *hi*, else 0."""
    return weight if value < hi else 0.0


def _range_above(value: float, lo: float, weight: float) -> float:
    """Return *weight* when *value* > *lo*, else 0."""
    return weight if value > lo else 0.0


def _penalty(value: float, threshold: float, penalty: float) -> float:
    """Return *penalty* (negative) when *value* > *threshold*, else 0."""
    return penalty if value > threshold else 0.0


def _boolean_weight(value: float, weight: float) -> float:
    """Return *weight* when *value* is truthy (>= 0.5), else 0."""
    return weight if value >= 0.5 else 0.0


def _always_one(_value: float) -> float:
    """Always contributes +1 regardless of signal value."""
    return 1.0


# ---------------------------------------------------------------------------
# SCORING_MATRIX
#
# Nested dict: archetype_label -> signal_name -> weight_fn_or_value.
# Each weight_fn receives the signal value (float) and returns a float score.
# A plain int/float value is treated as a constant (unconditional) weight.
# ---------------------------------------------------------------------------

SCORING_MATRIX: dict[str, dict[str, _WEIGHT_FN | int | float]] = {
    "form": {
        "column_count": lambda v: _range_weight(v, 5, 12, 2.0),
        "formula_density": lambda v: _range_weight(v, 0.05, 0.40, 2.0),
        "cross_sheet_ref_count": lambda v: 0.0,
        "avg_null_rate": lambda v: _penalty(v, 0.30, -1.0),
        "has_status_column": lambda v: _boolean_weight(v, 3.0),
        "has_time_scope": lambda v: _boolean_weight(v, 2.0),
        "data_validation_density": lambda v: _threshold(v, 0.40, 3.0),
        "header_formula_count": lambda v: 0.0,
        "header_entity_count": lambda v: _threshold(v, 3, 2.0),
        "merged_cell_ratio": lambda v: 0.0,
        "row_count": lambda v: _penalty(v, 200, -1.0),
        "expansion_formula_ratio": lambda v: 0.0,
    },
    "list": {
        "column_count": lambda v: _threshold(v, 15, 3.0),
        "formula_density": lambda v: _range_below(v, 0.20, 1.0),
        "cross_sheet_ref_count": lambda v: _threshold(v, 1, 1.0),
        "avg_null_rate": lambda v: _penalty(v, 0.50, -2.0),
        "has_status_column": lambda v: _boolean_weight(v, 2.0),
        "has_time_scope": lambda v: _boolean_weight(v, 1.0),
        "data_validation_density": lambda v: _threshold(v, 0.20, 1.0),
        "header_formula_count": lambda v: 0.0,
        "header_entity_count": lambda v: _threshold(v, 3, 2.0),
        "merged_cell_ratio": lambda v: 0.0,
        "row_count": lambda v: _range_above(v, 200, 2.0),
        "expansion_formula_ratio": lambda v: 0.0,
    },
    "dashboard": {
        "column_count": lambda v: _always_one(v),
        "formula_density": lambda v: _threshold(v, 0.40, 4.0),
        "cross_sheet_ref_count": lambda v: _threshold(v, 1, 3.0),
        "avg_null_rate": lambda v: 0.0,
        "has_status_column": lambda v: 0.0,
        "has_time_scope": lambda v: _boolean_weight(v, 2.0),
        "data_validation_density": lambda v: 0.0,
        "header_formula_count": lambda v: _threshold(v, 3, 3.0),
        "header_entity_count": lambda v: 0.0,
        "merged_cell_ratio": lambda v: _threshold(v, 0.30, 3.0),
        "row_count": lambda v: 0.0,
        "expansion_formula_ratio": lambda v: _threshold(v, 0.20, 2.0),
    },
    "reference": {
        "column_count": lambda v: _range_below(v, 5, 3.0),
        "formula_density": lambda v: 0.0,
        "cross_sheet_ref_count": lambda v: 0.0,
        "avg_null_rate": lambda v: _threshold(v, 0.60, 3.0),
        "has_status_column": lambda v: 0.0,
        "has_time_scope": lambda v: 0.0,
        "data_validation_density": lambda v: 0.0,
        "header_formula_count": lambda v: 0.0,
        "header_entity_count": lambda v: _threshold(v, 2, 1.0),
        "merged_cell_ratio": lambda v: 0.0,
        "row_count": lambda v: _range_below(v, 50, 1.0),
        "expansion_formula_ratio": lambda v: 0.0,
    },
}

# Precomputed max possible score (highest achievable by any archetype)
# Used for margin-based confidence normalisation.
# Computed as the sum of all positive-capable signal max values.
_MAX_POSSIBLE_SCORE = 0.0
for archetype_name, archetype_weights in SCORING_MATRIX.items():
    total = 0.0
    for signal_name, weight_fn in archetype_weights.items():
        # Estimate max contribution by using the highest possible weight for each signal
        if signal_name == "column_count":
            total += 3.0  # highest positive weight
        elif signal_name == "formula_density":
            total += 4.0  # dashboard's +4
        elif signal_name == "cross_sheet_ref_count":
            total += 3.0
        elif signal_name == "avg_null_rate":
            total += 0.0  # only penalties or +3 for reference
        elif signal_name == "has_status_column":
            total += 3.0
        elif signal_name == "has_time_scope":
            total += 2.0
        elif signal_name == "data_validation_density":
            total += 3.0
        elif signal_name == "header_formula_count":
            total += 3.0
        elif signal_name == "header_entity_count":
            total += 2.0
        elif signal_name == "merged_cell_ratio":
            total += 3.0
        elif signal_name == "row_count":
            total += 2.0
        elif signal_name == "expansion_formula_ratio":
            total += 2.0
    if total > _MAX_POSSIBLE_SCORE:
        _MAX_POSSIBLE_SCORE = total


# ---------------------------------------------------------------------------
# ArchetypeProfile dataclass
# ---------------------------------------------------------------------------


@dataclass
class ArchetypeProfile:
    """Describes a single archetype's behaviour in the scoring matrix.

    Attributes:
        label: The archetype name (``"form"``, ``"list"``, ``"dashboard"``,
            ``"reference"``).
        description: Human-readable description.
        typical_signals: Dict mapping signal names to typical values for
            this archetype (for explainability).
        weight_overrides: Optional dict of signal → weight_fn for vertical
            or custom adjustments (P2 feature).
    """

    label: str
    description: str
    typical_signals: dict[str, str] = field(default_factory=dict)
    weight_overrides: dict[str, _WEIGHT_FN | int | float] = field(
        default_factory=dict
    )


_ARCHETYPE_DESCRIPTIONS: dict[str, ArchetypeProfile] = {
    "form": ArchetypeProfile(
        label="form",
        description="Data-entry form: moderate columns, moderate formulas, "
        "status column, data validation on key fields.",
        typical_signals={
            "column_count": "5–12",
            "formula_density": "0.05–0.40",
            "has_status_column": "yes",
            "data_validation_density": "≥ 0.40",
        },
    ),
    "list": ArchetypeProfile(
        label="list",
        description="List view: many columns, few formulas, many rows, "
        "optional status tracking.",
        typical_signals={
            "column_count": "≥ 15",
            "formula_density": "< 0.20",
            "row_count": "> 200",
        },
    ),
    "dashboard": ArchetypeProfile(
        label="dashboard",
        description="Dashboard: high formula density, cross-sheet references, "
        "formula header patterns, merged cells.",
        typical_signals={
            "formula_density": "≥ 0.40",
            "cross_sheet_ref_count": "≥ 1",
            "header_formula_count": "≥ 3",
            "expansion_formula_ratio": "≥ 0.20",
        },
    ),
    "reference": ArchetypeProfile(
        label="reference",
        description="Reference table: few columns, high null rate (sparse), "
        "few formulas.",
        typical_signals={
            "column_count": "< 5",
            "avg_null_rate": "≥ 0.60",
            "row_count": "< 50",
        },
    ),
}


def _compute_weighted_score(
    archetype_weights: dict[str, _WEIGHT_FN | int | float],
    signals: dict[str, float],
) -> float:
    """Compute a single archetype's weighted score from signal values.

    Args:
        archetype_weights: Weight functions for one archetype from
            ``SCORING_MATRIX``.
        signals: Dict of signal name → float value.

    Returns:
        Weighted score for this archetype.
    """
    total = 0.0
    for signal_name, weight_fn in archetype_weights.items():
        value = signals.get(signal_name, 0.0)
        if isinstance(weight_fn, (int, float)):
            total += weight_fn
        else:
            total += weight_fn(float(value))
    return total


def classify_archetype(
    **signals: float,
) -> tuple[str, float, dict[str, float]]:
    """Classify a tab using the weighted scoring matrix.

    Args:
        **signals: Keyword arguments mapping signal names to float values.
            Expected signals: ``column_count``, ``formula_density``,
            ``cross_sheet_ref_count``, ``avg_null_rate``,
            ``has_status_column``, ``has_time_scope``,
            ``data_validation_density``, ``header_formula_count``,
            ``header_entity_count``, ``merged_cell_ratio``,
            ``row_count``, ``expansion_formula_ratio``.
            Missing signals default to 0.0.

    Returns:
        Tuple of ``(label, confidence, archetype_scores)``:

        - ``label``: The winning archetype name (``"form"``, ``"list"``,
          ``"dashboard"``, or ``"reference"``).
        - ``confidence``: Margin-based confidence in ``[0.0, 1.0]``,
          computed as ``(winner_score - runner_up_score) / max_possible_score``.
        - ``archetype_scores``: Dict of ``{archetype: normalized_score}``
          where each score is in ``[0.0, 1.0]`` (normalised by
          ``max_possible_score``).
    """
    raw_scores: dict[str, float] = {}
    for archetype_name, archetype_weights in SCORING_MATRIX.items():
        raw_scores[archetype_name] = _compute_weighted_score(
            archetype_weights, signals
        )

    # Find winner and runner-up
    sorted_scores = sorted(raw_scores.items(), key=lambda x: x[1], reverse=True)
    winner_label = sorted_scores[0][0]
    winner_score = sorted_scores[0][1]
    runner_up_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

    # Normalise scores to [0.0, 1.0] for the scores vector
    max_possible = _MAX_POSSIBLE_SCORE
    archetype_scores: dict[str, float] = {
        name: round(score / max_possible, 2) if max_possible > 0 else 0.0
        for name, score in raw_scores.items()
    }

    # Margin-based confidence
    if max_possible > 0:
        confidence = round((winner_score - runner_up_score) / max_possible, 2)
    else:
        confidence = 0.0

    confidence = max(0.0, min(confidence, 1.0))

    return winner_label, confidence, archetype_scores


def explain_archetype(
    tab_title: str,
    signals: dict[str, float],
    label: str | None = None,
    confidence: float | None = None,
    archetype_scores: dict[str, float] | None = None,
) -> str:
    """Return a human-readable explanation of an archetype classification.

    Args:
        tab_title: Display name of the tab.
        signals: Dict of signal name → float value.
        label: Optional pre-computed archetype label.  When ``None``,
            classification is run first.
        confidence: Optional pre-computed confidence.  Auto-computed when
            ``None``.
        archetype_scores: Optional pre-computed scores vector.  Auto-computed
            when ``None``.

    Returns:
        Multi-line string with classification result and top contributing
        signals.
    """
    if label is None or confidence is None or archetype_scores is None:
        label, confidence, archetype_scores = classify_archetype(**signals)

    profile = _ARCHETYPE_DESCRIPTIONS.get(label)
    description = profile.description if profile else ""

    # Find top positive signals for the winning archetype
    winner_weights = SCORING_MATRIX.get(label, {})
    contributing: list[tuple[str, float]] = []
    for signal_name, weight_fn in winner_weights.items():
        raw_value = signals.get(signal_name, 0.0)
        if isinstance(weight_fn, (int, float)):
            contribution = weight_fn
        else:
            contribution = weight_fn(float(raw_value))
        if contribution > 0:
            contributing.append((signal_name, contribution))

    # Sort by contribution descending
    contributing.sort(key=lambda x: x[1], reverse=True)
    top_signals = contributing[:5]

    # Find second-place archetype
    sorted_scores = sorted(
        archetype_scores.items(), key=lambda x: x[1], reverse=True
    )
    runner_up_label = sorted_scores[1][0] if len(sorted_scores) > 1 else "none"
    runner_up_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

    lines: list[str] = [
        f"{tab_title} — {label} (confidence {confidence}, "
        f"margin {confidence} over {runner_up_label} at {runner_up_score})",
        f"  Description: {description}",
    ]

    if top_signals:
        lines.append("  Top contributing signals:")
        for signal_name, contribution in top_signals:
            raw_value = signals.get(signal_name, 0.0)
            lines.append(
                f"    - {signal_name}: {raw_value} → +{contribution}"
            )

    # Check for signals that hurt the winner (negative contributions)
    negative_signals: list[tuple[str, float]] = []
    for signal_name, weight_fn in winner_weights.items():
        raw_value = signals.get(signal_name, 0.0)
        if isinstance(weight_fn, (int, float)):
            contribution = weight_fn
        else:
            contribution = weight_fn(float(raw_value))
        if contribution < 0:
            negative_signals.append((signal_name, contribution))

    if negative_signals:
        lines.append("  Signals against:")
        for signal_name, contribution in negative_signals:
            raw_value = signals.get(signal_name, 0.0)
            lines.append(
                f"    - {signal_name}: {raw_value} → {contribution}"
            )

    if confidence < 0.3:
        lines.append(
            "  → RECOMMENDATION: Low confidence. "
            "Check if this tab has a status workflow or data validation."
        )

    return "\n".join(lines)


def _max_possible_score() -> float:
    """Return the maximum possible raw score across all archetypes.

    This is the denominator for margin-based confidence and score
    normalisation.  Computed from the ideal signal values for each archetype.
    """
    return _MAX_POSSIBLE_SCORE
