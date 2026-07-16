"""Tests for the weighted archetype matrix module.

Covers: scoring matrix constants, weight function behaviour, classification
boundaries, margin confidence, explain output, and vertical overrides.
"""

from __future__ import annotations

from workbook.tools.archetype_matrix import (
    SCORING_MATRIX,
    ArchetypeProfile,
    classify_archetype,
    explain_archetype,
)

# ---------------------------------------------------------------------------
# Scoring matrix structure
# ---------------------------------------------------------------------------


class TestScoringMatrix:
    """Verify the scoring matrix has the expected structure."""

    def test_matrix_has_four_archetypes(self):
        """SCORING_MATRIX contains form, list, dashboard, reference."""
        assert set(SCORING_MATRIX.keys()) == {
            "form",
            "list",
            "dashboard",
            "reference",
        }

    def test_each_archetype_has_12_signals(self):
        """Every archetype defines weights for all 12 signals."""
        expected_signals = {
            "column_count",
            "formula_density",
            "cross_sheet_ref_count",
            "avg_null_rate",
            "has_status_column",
            "has_time_scope",
            "data_validation_density",
            "header_formula_count",
            "header_entity_count",
            "merged_cell_ratio",
            "row_count",
            "expansion_formula_ratio",
        }
        for archetype_name, weights in SCORING_MATRIX.items():
            assert set(weights.keys()) == expected_signals, (
                f"{archetype_name} missing signals: "
                f"{expected_signals - set(weights.keys())}"
            )

    def test_all_weight_fns_are_callable_or_number(self):
        """Each weight entry is a callable or numeric value."""
        for archetype_name, weights in SCORING_MATRIX.items():
            for signal_name, weight_fn in weights.items():
                assert callable(weight_fn) or isinstance(weight_fn, (int, float)), (
                    f"{archetype_name}.{signal_name} is neither callable "
                    f"nor numeric: {type(weight_fn)}"
                )


# ---------------------------------------------------------------------------
# ArchetypeProfile
# ---------------------------------------------------------------------------


class TestArchetypeProfile:
    """Verify ArchetypeProfile dataclass behaviour."""

    def test_profile_creation(self):
        """ArchetypeProfile can be created with label and description."""
        profile = ArchetypeProfile(label="form", description="Data entry form")
        assert profile.label == "form"
        assert profile.description == "Data entry form"
        assert profile.typical_signals == {}
        assert profile.weight_overrides == {}

    def test_profile_with_signals(self):
        """ArchetypeProfile stores typical signal hints."""
        profile = ArchetypeProfile(
            label="dashboard",
            description="KPI dashboard",
            typical_signals={"formula_density": ">= 0.40"},
        )
        assert profile.typical_signals["formula_density"] == ">= 0.40"


# ---------------------------------------------------------------------------
# classify_archetype — each archetype wins for its signal profile
# ---------------------------------------------------------------------------


class TestClassifyForm:
    """Tabs with form-like signals classify as 'form'."""

    def test_typical_form(self):
        """8 cols, moderate formula, status column, validation → form."""
        label, confidence, scores = classify_archetype(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.05,
            has_status_column=1,
            has_time_scope=1,
            data_validation_density=0.50,
            header_formula_count=1,
            header_entity_count=4,
            merged_cell_ratio=0.0,
            row_count=100,
            expansion_formula_ratio=0.0,
        )
        assert label == "form"

    def test_form_without_status_still_form(self):
        """5 cols, moderate formula, no status → still form if cols in range."""
        label, confidence, scores = classify_archetype(
            column_count=6,
            formula_density=0.20,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=50,
            expansion_formula_ratio=0.0,
        )
        assert label == "form"

    def test_form_score_positive_for_status_and_dv(self):
        """Status column and data validation contribute positively to form."""
        label, confidence, scores = classify_archetype(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=1,
            has_time_scope=0,
            data_validation_density=0.50,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=50,
            expansion_formula_ratio=0.0,
        )
        assert label == "form"


class TestClassifyList:
    """Tabs with list-like signals classify as 'list'."""

    def test_typical_list(self):
        """18 cols, low formula, many rows → list."""
        label, confidence, scores = classify_archetype(
            column_count=18,
            formula_density=0.10,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=500,
            expansion_formula_ratio=0.0,
        )
        assert label == "list"

    def test_list_with_status(self):
        """Status column helps list too."""
        label, confidence, scores = classify_archetype(
            column_count=18,
            formula_density=0.10,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=1,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=500,
            expansion_formula_ratio=0.0,
        )
        assert label == "list"

    def test_list_with_few_entities(self):
        """Entity keywords contribute to list score."""
        label, confidence, scores = classify_archetype(
            column_count=18,
            formula_density=0.10,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=5,
            merged_cell_ratio=0.0,
            row_count=500,
            expansion_formula_ratio=0.0,
        )
        assert label == "list"


class TestClassifyDashboard:
    """Tabs with dashboard-like signals classify as 'dashboard'."""

    def test_typical_dashboard(self):
        """High formula density + cross-sheet refs → dashboard."""
        label, confidence, scores = classify_archetype(
            column_count=6,
            formula_density=0.83,
            cross_sheet_ref_count=3,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=50,
            expansion_formula_ratio=0.0,
        )
        assert label == "dashboard"

    def test_dashboard_with_formula_headers(self):
        """Formula headers strengthen dashboard classification."""
        label, confidence, scores = classify_archetype(
            column_count=6,
            formula_density=0.67,
            cross_sheet_ref_count=1,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=4,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=30,
            expansion_formula_ratio=0.0,
        )
        assert label == "dashboard"

    def test_dashboard_with_merged_cells(self):
        """Merged cells contribute to dashboard classification."""
        label, confidence, scores = classify_archetype(
            column_count=8,
            formula_density=0.50,
            cross_sheet_ref_count=1,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=3,
            header_entity_count=0,
            merged_cell_ratio=0.50,
            row_count=20,
            expansion_formula_ratio=0.0,
        )
        assert label == "dashboard"

    def test_dashboard_with_expansion_formulas(self):
        """Expansion formulas contribute to dashboard."""
        label, confidence, scores = classify_archetype(
            column_count=8,
            formula_density=0.50,
            cross_sheet_ref_count=1,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=30,
            expansion_formula_ratio=0.30,
        )
        assert label == "dashboard"


class TestClassifyReference:
    """Tabs with reference-like signals classify as 'reference'."""

    def test_typical_reference(self):
        """Few cols, no formulas → reference."""
        label, confidence, scores = classify_archetype(
            column_count=3,
            formula_density=0.0,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=30,
            expansion_formula_ratio=0.0,
        )
        assert label == "reference"

    def test_reference_high_null_rate(self):
        """High avg null rate classifies as reference."""
        label, confidence, scores = classify_archetype(
            column_count=8,
            formula_density=0.0,
            cross_sheet_ref_count=0,
            avg_null_rate=0.70,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=30,
            expansion_formula_ratio=0.0,
        )
        assert label == "reference"

    def test_reference_with_few_rows(self):
        """Low row count strengthens reference classification."""
        label, confidence, scores = classify_archetype(
            column_count=4,
            formula_density=0.0,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=10,
            expansion_formula_ratio=0.0,
        )
        assert label == "reference"


# ---------------------------------------------------------------------------
# Confidence score
# ---------------------------------------------------------------------------


class TestConfidenceScore:
    """Margin-based confidence behaves as expected."""

    def test_confidence_in_range(self):
        """Confidence is always between 0 and 1."""
        label, confidence, scores = classify_archetype(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=1,
            has_time_scope=1,
            data_validation_density=0.50,
            header_formula_count=1,
            header_entity_count=4,
            merged_cell_ratio=0.0,
            row_count=100,
            expansion_formula_ratio=0.0,
        )
        assert 0.0 <= confidence <= 1.0

    def test_confidence_higher_with_clear_winner(self):
        """Clear dashboard signals give higher confidence."""
        label1, conf1, scores1 = classify_archetype(
            column_count=6,
            formula_density=0.17,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=50,
            expansion_formula_ratio=0.0,
        )
        label2, conf2, scores2 = classify_archetype(
            column_count=6,
            formula_density=0.83,
            cross_sheet_ref_count=3,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=50,
            expansion_formula_ratio=0.0,
        )
        assert conf2 >= conf1, (
            f"Dashboard should have higher confidence than ambiguous case: "
            f"{conf2} < {conf1}"
        )

    def test_low_confidence_for_ambiguous(self):
        """An ambiguous tab with few distinguishing signals has low confidence."""
        label, confidence, scores = classify_archetype(
            column_count=10,
            formula_density=0.12,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=100,
            expansion_formula_ratio=0.0,
        )
        assert confidence < 0.30, (
            f"Ambiguous tab should have low confidence, got {confidence}"
        )


# ---------------------------------------------------------------------------
# archetype_scores vector
# ---------------------------------------------------------------------------


class TestArchetypeScores:
    """The scores vector contains normalised scores for all archetypes."""

    def test_scores_has_four_keys(self):
        """Scores dict contains form, list, dashboard, reference."""
        label, confidence, scores = classify_archetype(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=1,
            has_time_scope=1,
            data_validation_density=0.50,
            header_formula_count=1,
            header_entity_count=4,
            merged_cell_ratio=0.0,
            row_count=100,
            expansion_formula_ratio=0.0,
        )
        assert set(scores.keys()) == {
            "form",
            "list",
            "dashboard",
            "reference",
        }

    def test_winner_has_highest_score(self):
        """The winning archetype has the highest score in the vector."""
        label, confidence, scores = classify_archetype(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=1,
            has_time_scope=1,
            data_validation_density=0.50,
            header_formula_count=1,
            header_entity_count=4,
            merged_cell_ratio=0.0,
            row_count=100,
            expansion_formula_ratio=0.0,
        )
        winner_score = scores[label]
        for other_label, other_score in scores.items():
            if other_label != label:
                assert winner_score >= other_score, (
                    f"Winner {label} ({winner_score}) should be >= "
                    f"{other_label} ({other_score})"
                )


# ---------------------------------------------------------------------------
# Boundary / edge cases
# ---------------------------------------------------------------------------


class TestBoundaries:
    """Boundary values for signal thresholds."""

    def test_column_count_boundary_4_vs_5(self):
        """4 columns is reference territory, 5 can be form."""
        label4, conf4, scores4 = classify_archetype(
            column_count=4,
            formula_density=0.0,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=30,
            expansion_formula_ratio=0.0,
        )
        label5, conf5, scores5 = classify_archetype(
            column_count=5,
            formula_density=0.0,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=30,
            expansion_formula_ratio=0.0,
        )
        assert label4 == "reference"
        assert label5 == "reference" or label5 == "form"

    def test_row_count_boundary_200(self):
        """200 rows is the penalty threshold for form."""
        label_below, conf_below, scores_below = classify_archetype(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=1,
            has_time_scope=1,
            data_validation_density=0.50,
            header_formula_count=1,
            header_entity_count=4,
            merged_cell_ratio=0.0,
            row_count=200,
            expansion_formula_ratio=0.0,
        )
        label_above, conf_above, scores_above = classify_archetype(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=1,
            has_time_scope=1,
            data_validation_density=0.50,
            header_formula_count=1,
            header_entity_count=4,
            merged_cell_ratio=0.0,
            row_count=201,
            expansion_formula_ratio=0.0,
        )
        assert label_below == label_above  # Both still form

    def test_all_defaults(self):
        """All signals at default (0.0) — still produces a valid result."""
        label, confidence, scores = classify_archetype()
        assert label in ("form", "list", "dashboard", "reference")
        assert 0.0 <= confidence <= 1.0
        assert set(scores.keys()) == {
            "form",
            "list",
            "dashboard",
            "reference",
        }

    def test_formula_density_boundary_0_40(self):
        """Formula density at exactly 0.40 is dashboard threshold."""
        label_at, conf_at, scores_at = classify_archetype(
            column_count=6,
            formula_density=0.40,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=50,
            expansion_formula_ratio=0.0,
        )
        label_below, conf_below, scores_below = classify_archetype(
            column_count=6,
            formula_density=0.39,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=0,
            has_time_scope=0,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=50,
            expansion_formula_ratio=0.0,
        )
        assert label_at == "dashboard"


# ---------------------------------------------------------------------------
# explain_archetype
# ---------------------------------------------------------------------------


class TestExplainArchetype:
    """explain_archetype returns a human-readable explanation."""

    def test_explain_contains_label(self):
        """Output contains the archetype label."""
        explanation = explain_archetype(
            "Test Tab",
            signals={
                "column_count": 8,
                "formula_density": 0.25,
                "cross_sheet_ref_count": 0,
                "avg_null_rate": 0.0,
                "has_status_column": 1,
                "has_time_scope": 1,
                "data_validation_density": 0.50,
                "header_formula_count": 1,
                "header_entity_count": 4,
                "merged_cell_ratio": 0.0,
                "row_count": 100,
                "expansion_formula_ratio": 0.0,
            },
        )
        assert "form" in explanation or "list" in explanation

    def test_explain_contains_confidence(self):
        """Output contains the confidence value."""
        explanation = explain_archetype(
            "Test Tab",
            signals={
                "column_count": 8,
                "formula_density": 0.25,
                "cross_sheet_ref_count": 0,
                "avg_null_rate": 0.0,
                "has_status_column": 1,
                "has_time_scope": 1,
                "data_validation_density": 0.50,
                "header_formula_count": 1,
                "header_entity_count": 4,
                "merged_cell_ratio": 0.0,
                "row_count": 100,
                "expansion_formula_ratio": 0.0,
            },
        )
        assert "confidence" in explanation

    def test_explain_shows_top_signals(self):
        """Output includes top contributing signals."""
        explanation = explain_archetype(
            "Test Tab",
            signals={
                "column_count": 8,
                "formula_density": 0.25,
                "cross_sheet_ref_count": 0,
                "avg_null_rate": 0.0,
                "has_status_column": 1,
                "has_time_scope": 1,
                "data_validation_density": 0.50,
                "header_formula_count": 1,
                "header_entity_count": 4,
                "merged_cell_ratio": 0.0,
                "row_count": 100,
                "expansion_formula_ratio": 0.0,
            },
        )
        assert "has_status_column" in explanation
        assert "data_validation_density" in explanation

    def test_low_confidence_recommendation(self):
        """Low confidence output includes a recommendation."""
        explanation = explain_archetype(
            "Ambiguous",
            signals={
                "column_count": 10,
                "formula_density": 0.12,
                "cross_sheet_ref_count": 0,
                "avg_null_rate": 0.0,
                "has_status_column": 0,
                "has_time_scope": 0,
                "data_validation_density": 0.0,
                "header_formula_count": 0,
                "header_entity_count": 0,
                "merged_cell_ratio": 0.0,
                "row_count": 100,
                "expansion_formula_ratio": 0.0,
            },
        )
        assert "RECOMMENDATION" in explanation

    def test_explain_with_precomputed(self):
        """Can pass pre-computed label, confidence, scores."""
        explanation = explain_archetype(
            "Precomputed",
            signals={"column_count": 8, "formula_density": 0.25},
            label="form",
            confidence=0.50,
            archetype_scores={
                "form": 0.5,
                "list": 0.3,
                "dashboard": 0.1,
                "reference": 0.1,
            },
        )
        assert "form" in explanation
        assert "0.5" in explanation

    def test_explain_empty_signals(self):
        """Empty signals dict still produces valid output."""
        explanation = explain_archetype("Unknown", signals={})
        assert "Unknown" in explanation


# ---------------------------------------------------------------------------
# Vertical override mechanism (P2, stub test)
# ---------------------------------------------------------------------------


class TestVerticalOverride:
    """Vertical weight overrides can adjust scores (P2 feature)."""

    def test_base_matrix_default(self):
        """Without overrides, the base matrix is used unchanged."""
        label, confidence, scores = classify_archetype(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=1,
            has_time_scope=1,
            data_validation_density=0.50,
            header_formula_count=1,
            header_entity_count=4,
            merged_cell_ratio=0.0,
            row_count=100,
            expansion_formula_ratio=0.0,
        )
        assert isinstance(scores, dict)
        assert label == "form"


# ---------------------------------------------------------------------------
# Scores vector properties
# ---------------------------------------------------------------------------


class TestScoresVectorProperties:
    """Verification of scores vector invariants."""

    def test_all_scores_are_floats(self):
        """Every score in the vector is a float."""
        label, confidence, scores = classify_archetype(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=1,
            has_time_scope=1,
            data_validation_density=0.50,
            header_formula_count=1,
            header_entity_count=4,
            merged_cell_ratio=0.0,
            row_count=100,
            expansion_formula_ratio=0.0,
        )
        for score in scores.values():
            assert isinstance(score, float)

    def test_scores_are_normalised(self):
        """Raw scores are normalised to [0, 1] range."""
        label, confidence, scores = classify_archetype(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=1,
            has_time_scope=1,
            data_validation_density=0.50,
            header_formula_count=1,
            header_entity_count=4,
            merged_cell_ratio=0.0,
            row_count=100,
            expansion_formula_ratio=0.0,
        )
        for score in scores.values():
            assert 0.0 <= score <= 1.0, f"Score {score} out of range"
