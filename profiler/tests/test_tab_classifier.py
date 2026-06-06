"""Tests for profiler.tools.tab_classifier."""
import pytest
from profiler.tools.tab_classifier import (
    TAB_CLASSIFICATION_CATEGORIES,
    TabClassification,
    classify_tab,
    classify_tabs_batch,
    classification_summary,
)


# ── TabClassification dataclass validation ──────────────────────────────────


class TestTabClassificationDataclass:
    def test_default_fields(self):
        tc = TabClassification(tab_title="My Tab")
        assert tc.tab_title == "My Tab"
        assert tc.category == "unknown"
        assert tc.confidence == 0.0
        assert tc.signals == {}
        assert tc.rationale == ""

    def test_valid_category(self):
        tc = TabClassification(tab_title="Test", category="data", confidence=0.5)
        assert tc.category == "data"

    def test_invalid_category_raises(self):
        with pytest.raises(ValueError, match="Invalid category"):
            TabClassification(tab_title="Test", category="invalid_cat")

    def test_invalid_confidence_negative(self):
        with pytest.raises(ValueError, match="Confidence must be in"):
            TabClassification(tab_title="Test", category="data", confidence=-0.1)

    def test_invalid_confidence_over_one(self):
        with pytest.raises(ValueError, match="Confidence must be in"):
            TabClassification(tab_title="Test", category="data", confidence=1.5)

    def test_boundary_confidence(self):
        tc = TabClassification(tab_title="Test", category="data", confidence=0.0)
        assert tc.confidence == 0.0
        tc2 = TabClassification(tab_title="Test", category="reference", confidence=1.0)
        assert tc2.confidence == 1.0

    def test_signals_and_rationale(self):
        tc = TabClassification(
            tab_title="Test",
            category="derived",
            confidence=0.8,
            signals={"formula_ratio": 0.75},
            rationale="High formula ratio",
        )
        assert tc.signals == {"formula_ratio": 0.75}
        assert tc.rationale == "High formula ratio"


# ── Classification: data tabs ───────────────────────────────────────────────


class TestClassifyData:
    def test_large_operational_tab_is_data(self):
        result = classify_tab(
            tab_title="Crop Plan Board",
            row_count=500,
            col_count=30,
            domain_category_hits={"operational": 2},
        )
        assert result.category == "data"
        assert result.confidence >= 0.7

    def test_large_tab_defaults_to_data(self):
        result = classify_tab(
            tab_title="Some Large Sheet",
            row_count=500,
            col_count=20,
        )
        assert result.category == "data"
        assert result.confidence == 0.60

    def test_small_tab_not_data(self):
        result = classify_tab(
            tab_title="Small Sheet",
            row_count=10,
            col_count=5,
        )
        assert result.category != "data"

    def test_data_confidence_scales_with_hits(self):
        result = classify_tab(
            tab_title="Crop Plan",
            row_count=500,
            col_count=30,
            domain_category_hits={"operational": 3},
        )
        # confidence = min(0.7 + 3 * 0.1, 0.95) = 1.0 → capped at 0.95
        assert result.confidence == 0.95

    def test_data_confidence_one_hit(self):
        result = classify_tab(
            tab_title="Crop Plan",
            row_count=500,
            col_count=30,
            domain_category_hits={"operational": 1},
        )
        # confidence = min(0.7 + 1 * 0.1, 0.95) = 0.80
        assert result.confidence == pytest.approx(0.80)

    def test_data_with_exclusion_is_unknown(self):
        result = classify_tab(
            tab_title="Crop Plan",
            row_count=500,
            col_count=30,
            is_excluded=True,
        )
        assert result.category == "unknown"
        assert result.confidence == 0.0

    def test_data_requires_min_100_rows(self):
        result = classify_tab(
            tab_title="Crop Plan",
            row_count=50,
            col_count=30,
            domain_category_hits={"operational": 1},
        )
        # row_count=50 < 100, but operational hit matches rule 8 (reference)
        # Actually: rule 7 requires row_count >= 100, domain_category_hits > 0
        # Rule 8: reference hit with row_count <= 500 → reference, confidence 0.70
        # But there are no reference hits... so fallback to unknown
        # Wait — let's trace: rule 7 fails (row_count 50 < 100), rule 8 fails (no reference hits)
        # row_count 50 < 100, so rule 9 fails. Fallback → unknown.
        assert result.category == "unknown"
        assert result.confidence == 0.0


# ── Classification: reference tabs ──────────────────────────────────────────


class TestClassifyReference:
    def test_reference_name_pattern_match(self):
        result = classify_tab(
            tab_title="Crop Types Reference",
            row_count=100,
            col_count=10,
        )
        assert result.category == "reference"
        # Rule 5: reference name pattern match + row_count <= 500
        assert result.confidence == 0.85

    def test_reference_domain_hit(self):
        result = classify_tab(
            tab_title="Actual Data Table",
            row_count=200,
            col_count=15,
            domain_category_hits={"reference": 1},
        )
        assert result.category == "reference"
        assert result.confidence == 0.70

    def test_reference_name_with_many_rows_unknown(self):
        result = classify_tab(
            tab_title="Codes Reference",
            row_count=1000,
            col_count=20,
        )
        # Rule 5 requires row_count <= 500 → fails. Rule 7/8/9 also can't apply...
        # Rule 7: row_count >= 100 but no domain_category_hits
        # Rule 9: row_count >= 100 → data with confidence 0.60
        assert result.category == "data"
        assert result.confidence == 0.60

    def test_list_keyword_matches_reference(self):
        result = classify_tab(
            tab_title="Crop List",
            row_count=50,
            col_count=8,
        )
        # "list" matches reference name pattern. row_count=50 <= 500.
        assert result.category == "reference"
        assert result.confidence == 0.85

    def test_glossary_keyword_matches_reference(self):
        result = classify_tab(
            tab_title="Business Glossary",
            row_count=300,
            col_count=12,
        )
        assert result.category == "reference"

    def test_lookup_keyword_matches_reference(self):
        result = classify_tab(
            tab_title="Sales Channel Lookup",
            row_count=30,
            col_count=5,
        )
        assert result.category == "reference"

    def test_codes_pattern_matches_reference(self):
        result = classify_tab(
            tab_title="Error Codes",
            row_count=50,
            col_count=4,
        )
        assert result.category == "reference"

    def test_channel_tab_is_reference(self):
        result = classify_tab(
            tab_title="Channel",
            row_count=100,
            col_count=10,
        )
        assert result.category == "reference"

    def test_channel_code_tab_is_reference(self):
        result = classify_tab(
            tab_title="Channel_Code",
            row_count=100,
            col_count=10,
        )
        assert result.category == "reference"


# ── Classification: ui_config tabs ──────────────────────────────────────────


class TestClassifyUiConfig:
    def test_filter_pattern_matches_ui_config(self):
        result = classify_tab(
            tab_title="Filter Options",
            row_count=10,
            col_count=5,
        )
        assert result.category == "ui_config"
        assert result.confidence == 0.85

    def test_dropdown_matches_ui_config(self):
        result = classify_tab(
            tab_title="Dropdown Config",
            row_count=5,
            col_count=3,
        )
        assert result.category == "ui_config"

    def test_settings_pattern_matches_ui_config(self):
        result = classify_tab(
            tab_title="Settings",
            row_count=15,
            col_count=6,
        )
        assert result.category == "ui_config"

    def test_underscore_prefix_matches_ui_config(self):
        result = classify_tab(
            tab_title="__hidden_sheet",
            row_count=5,
            col_count=2,
        )
        assert result.category == "ui_config"

    def test_helper_matches_ui_config(self):
        result = classify_tab(
            tab_title="Helper Data",
            row_count=8,
            col_count=4,
        )
        assert result.category == "ui_config"

    def test_small_dimensions_fallback_ui_config(self):
        result = classify_tab(
            tab_title="Some Random Thing",
            row_count=5,
            col_count=3,
        )
        # Falls through to rule 4 (small dimensions, no name match)
        assert result.category == "ui_config"
        assert result.confidence == 0.75

    def test_ui_config_name_too_many_rows(self):
        result = classify_tab(
            tab_title="Filter Options",
            row_count=100,
            col_count=30,
        )
        # Rule 3: formula_ratio is 0.0, so rule 1,2,3 fail.
        # Rule 3: UI config name pattern match success, but row_count=100 > 20 and col_count=30 > 8
        # So rule 3 doesn't apply.
        # Rule 4: row_count=100 > 20 — fails. Continue down.
        # Rule 5+: none match → falls through to unknown
        # Actually: row_count=100 >= 100, no domain_hits → rule 9 → data with confidence 0.60
        assert result.category == "data"

    def test_instructions_matches_ui_config(self):
        result = classify_tab(
            tab_title="Instructions",
            row_count=10,
            col_count=5,
        )
        assert result.category == "ui_config"

    def test_notes_matches_ui_config(self):
        result = classify_tab(
            tab_title="Release Notes",
            row_count=8,
            col_count=4,
        )
        assert result.category == "ui_config"

    def test_template_matches_ui_config(self):
        result = classify_tab(
            tab_title="Import Template",
            row_count=15,
            col_count=10,
        )
        assert result.category == "ui_config"

    def test_preset_layout_matches_ui_config(self):
        result = classify_tab(
            tab_title="Default Layout",
            row_count=5,
            col_count=3,
        )
        assert result.category == "ui_config"

    def test_display_config_matches_ui_config(self):
        result = classify_tab(
            tab_title="Display Settings",
            row_count=3,
            col_count=2,
        )
        assert result.category == "ui_config"


# ── Classification: derived tabs ────────────────────────────────────────────


class TestClassifyDerived:
    def test_high_formula_ratio_derived(self):
        result = classify_tab(
            tab_title="Some Sheet",
            row_count=50,
            col_count=10,
            formula_ratio=0.8,
        )
        assert result.category == "derived"
        assert result.confidence == min(0.8, 0.9)

    def test_high_formula_ratio_capped_at_09(self):
        result = classify_tab(
            tab_title="Some Sheet",
            row_count=50,
            col_count=10,
            formula_ratio=1.0,
        )
        assert result.category == "derived"
        assert result.confidence == 0.9

    def test_summary_name_matches_derived(self):
        result = classify_tab(
            tab_title="Sales Summary",
            row_count=200,
            col_count=20,
        )
        assert result.category == "derived"
        assert result.confidence == 0.80

    def test_total_name_matches_derived(self):
        result = classify_tab(
            tab_title="Crop Total",
            row_count=100,
            col_count=15,
        )
        assert result.category == "derived"

    def test_rollup_name_matches_derived(self):
        result = classify_tab(
            tab_title="Monthly Rollup",
            row_count=150,
            col_count=12,
        )
        assert result.category == "derived"

    def test_report_name_matches_derived(self):
        result = classify_tab(
            tab_title="Annual Report",
            row_count=300,
            col_count=25,
        )
        assert result.category == "derived"

    def test_dashboard_name_matches_derived(self):
        result = classify_tab(
            tab_title="Executive Dashboard",
            row_count=50,
            col_count=15,
        )
        assert result.category == "derived"

    def test_pivot_name_matches_derived(self):
        result = classify_tab(
            tab_title="Pivot Table",
            row_count=80,
            col_count=10,
        )
        assert result.category == "derived"

    def test_aggregate_name_matches_derived(self):
        result = classify_tab(
            tab_title="Aggregate Data",
            row_count=200,
            col_count=20,
        )
        assert result.category == "derived"

    def test_consolidated_name_matches_derived(self):
        result = classify_tab(
            tab_title="Consolidated View",
            row_count=100,
            col_count=15,
        )
        assert result.category == "derived"


# ── Classification: unknown tabs ────────────────────────────────────────────


class TestClassifyUnknown:
    def test_excluded_tab_is_unknown(self):
        result = classify_tab(
            tab_title="Anything",
            row_count=500,
            col_count=30,
            is_excluded=True,
        )
        assert result.category == "unknown"
        assert result.confidence == 0.0

    def test_no_heuristic_match_falls_to_unknown(self):
        result = classify_tab(
            tab_title="My Custom Tab",
            row_count=50,
            col_count=15,
        )
        # None of the rules match: small tab, no patterns hit, no domain hits
        assert result.category == "unknown"
        assert result.confidence == 0.0

    def test_scoring_reasons_passed_through(self):
        result = classify_tab(
            tab_title="My Tab",
            row_count=50,
            col_count=15,
            scoring_reasons=["operational_tab_name"],
        )
        # Signals should include scoring_reasons
        assert "scoring_reasons" in result.signals

    def test_rationale_includes_rule_name(self):
        result = classify_tab(
            tab_title="Crop Plan",
            row_count=500,
            col_count=30,
            domain_category_hits={"operational": 2},
        )
        assert "data" in result.rationale.lower()


# ── Batch classification ────────────────────────────────────────────────────


class TestBatchClassification:
    def test_classify_tabs_batch_empty(self):
        result = classify_tabs_batch([])
        assert result == []

    def test_classify_tabs_batch_single(self):
        entries = [
            {
                "tab_title": "Crop Plan",
                "rows": 500,
                "cols": 30,
            }
        ]
        results = classify_tabs_batch(entries)
        assert len(results) == 1
        assert results[0].category == "data"
        assert results[0].confidence == 0.60

    def test_classify_tabs_batch_multiple(self):
        entries = [
            {"tab_title": "Crop Plan", "rows": 500, "cols": 30},
            {"tab_title": "Filter Options", "rows": 10, "cols": 5},
            {"tab_title": "Codes List", "rows": 100, "cols": 10},
        ]
        results = classify_tabs_batch(entries)
        assert len(results) == 3
        categories = {r.tab_title: r.category for r in results}
        assert categories["Crop Plan"] == "data"
        assert categories["Filter Options"] == "ui_config"
        assert categories["Codes List"] == "reference"

    def test_classify_tabs_batch_with_domain_hits(self):
        entries = [
            {"tab_title": "Crop Plan", "rows": 500, "cols": 30},
        ]
        domain_hits = {
            "Crop Plan": {"operational": 2},
        }
        results = classify_tabs_batch(entries, domain_category_hits_map=domain_hits)
        assert len(results) == 1
        assert results[0].category == "data"
        assert results[0].confidence >= 0.7

    def test_classify_tabs_batch_missing_keys(self):
        entries = [{"tab_title": "Test"}]
        results = classify_tabs_batch(entries)
        assert len(results) == 1
        assert results[0].tab_title == "Test"
        assert results[0].category == "ui_config"
        assert results[0].confidence == 0.75


# ── Classification summary ──────────────────────────────────────────────────


class TestClassificationSummary:
    def test_summary_empty(self):
        summary = classification_summary([])
        assert summary["total"] == 0
        assert summary["classified"] == 0
        assert summary["coverage_pct"] == 0.0
        assert summary["unknown_tabs"] == []
        assert summary["data_tabs"] == []
        assert summary["ui_config_tabs"] == []
        assert summary["reference_tabs"] == []
        assert summary["derived_tabs"] == []

    def test_summary_all_unknown(self):
        classifications = [
            TabClassification(tab_title="A", category="unknown"),
            TabClassification(tab_title="B", category="unknown"),
        ]
        summary = classification_summary(classifications)
        assert summary["total"] == 2
        assert summary["classified"] == 0
        assert summary["coverage_pct"] == 0.0

    def test_summary_mixed(self):
        classifications = [
            TabClassification(tab_title="Data1", category="data", confidence=0.8),
            TabClassification(tab_title="Ref1", category="reference", confidence=0.9),
            TabClassification(tab_title="UI1", category="ui_config", confidence=0.85),
            TabClassification(tab_title="Der1", category="derived", confidence=0.7),
            TabClassification(tab_title="Unk1", category="unknown"),
        ]
        summary = classification_summary(classifications)
        assert summary["total"] == 5
        assert summary["classified"] == 4
        assert summary["coverage_pct"] == 80.0
        assert summary["counts"]["data"] == 1
        assert summary["counts"]["reference"] == 1
        assert summary["counts"]["ui_config"] == 1
        assert summary["counts"]["derived"] == 1
        assert summary["counts"]["unknown"] == 1
        assert summary["unknown_tabs"] == ["Unk1"]
        assert summary["data_tabs"] == ["Data1"]
        assert summary["ui_config_tabs"] == ["UI1"]
        assert summary["reference_tabs"] == ["Ref1"]
        assert summary["derived_tabs"] == ["Der1"]

    def test_summary_counts_accurate(self):
        classifications = [
            TabClassification(tab_title="A", category="data"),
            TabClassification(tab_title="B", category="data"),
            TabClassification(tab_title="C", category="reference"),
        ]
        summary = classification_summary(classifications)
        assert summary["counts"]["data"] == 2
        assert summary["counts"]["reference"] == 1
        assert summary["total"] == 3
        assert summary["classified"] == 3


# ── Edge cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_zero_rows_and_cols(self):
        result = classify_tab(
            tab_title="Empty Tab",
            row_count=0,
            col_count=0,
        )
        # "Tab" matches UI config pattern (tab_?\d*$) → rule 3: ui_config 0.85
        assert result.category == "ui_config"
        assert result.confidence == 0.85

    def test_single_row_single_column(self):
        result = classify_tab(
            tab_title="Single Cell Tab",
            row_count=1,
            col_count=1,
        )
        assert result.category == "ui_config"
        # "Tab" matches UI config pattern → rule 3: confidence 0.85
        assert result.confidence == 0.85

    def test_formula_ratio_zero(self):
        result = classify_tab(
            tab_title="No Formulas",
            row_count=500,
            col_count=30,
            formula_ratio=0.0,
        )
        # Should fall through to data (row_count >= 100)
        assert result.category == "data"

    def test_all_heuristics_miss(self):
        result = classify_tab(
            tab_title="RandomSheet123",
            row_count=50,
            col_count=10,
            formula_ratio=0.3,
        )
        assert result.category == "unknown"

    def test_case_insensitive_pattern_matching(self):
        result = classify_tab(
            tab_title="SUMMARY REPORT",
            row_count=100,
            col_count=15,
        )
        assert result.category == "derived"

    def test_domain_hits_empty_dict(self):
        result = classify_tab(
            tab_title="Big Tab",
            row_count=500,
            col_count=30,
            domain_category_hits={},
        )
        assert result.category == "data"
        assert result.confidence == 0.60

    def test_domain_hits_none(self):
        result = classify_tab(
            tab_title="Big Tab",
            row_count=500,
            col_count=30,
            domain_category_hits=None,
        )
        assert result.category == "data"
        assert result.confidence == 0.60

    def test_score_surfaces_in_signals(self):
        result = classify_tab(
            tab_title="Crop Plan",
            row_count=500,
            col_count=30,
            score=12.5,
        )
        assert result.signals.get("score") == 12.5

    def test_combined_name_and_formula_derived(self):
        """If a tab has both derived name pattern and high formula ratio,
        formula ratio rule (rule 2) takes priority since it's checked first."""
        result = classify_tab(
            tab_title="Summary",
            row_count=50,
            col_count=10,
            formula_ratio=0.7,
        )
        assert result.category == "derived"
        # Rule 2: formula_ratio >= 0.6 AND row_count < 100 → derived
        # confidence = min(formula_ratio, 0.9) = min(0.7, 0.9) = 0.7
        assert result.confidence == 0.7

    def test_tab_classification_categories_frozenset(self):
        assert isinstance(TAB_CLASSIFICATION_CATEGORIES, frozenset)
        assert "data" in TAB_CLASSIFICATION_CATEGORIES
        assert "reference" in TAB_CLASSIFICATION_CATEGORIES
        assert "ui_config" in TAB_CLASSIFICATION_CATEGORIES
        assert "derived" in TAB_CLASSIFICATION_CATEGORIES
        assert "unknown" in TAB_CLASSIFICATION_CATEGORIES


# ── test count check ────────────────────────────────────────────────────────


class TestTestCount:
    """Meta-test: verify we have at least 25 test methods across the suite."""

    def test_minimum_test_count(self):
        """Count test methods in this file to ensure at least 25."""
        import inspect
        import sys

        # Get all test functions and methods in this module
        module = sys.modules[__name__]
        test_count = 0
        for name, obj in inspect.getmembers(module):
            if name.startswith("test_") and callable(obj):
                test_count += 1
            elif inspect.isclass(obj) and name.startswith("Test"):
                for method_name, method in inspect.getmembers(obj, predicate=inspect.isfunction):
                    if method_name.startswith("test_"):
                        test_count += 1
        assert test_count >= 25, f"Only {test_count} tests, need >= 25"
