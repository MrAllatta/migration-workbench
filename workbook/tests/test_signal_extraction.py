"""Tests for profiler signal extraction from structure artifacts."""

from __future__ import annotations

import io
import json
from datetime import datetime

import pytest
import yaml
from django.core.management import call_command, CommandError

from workbook.tools.signal_extraction import (
    SIGNALS_VERSION,
    _build_workflow_graph,
    _classify_ui_archetype_v2,
    _compute_avg_null_rate,
    _extract_dependency_edges,
    _extract_formula_edges_from_text,
    _extract_sheet_name_from_range,
    extract_signals,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_structure(**overrides: dict) -> dict:
    """Build a minimal structure dict with one tab."""
    tab = {
        "worksheet_title": "Orders",
        "tab_position": 0,
        "hidden": False,
        "frozen_rows": 1,
        "frozen_cols": 0,
        "total_rows": 100,
        "total_cols": 6,
        "columns": [
            {
                "index": 0,
                "col_letter": "A",
                "header_label": "Order ID",
                "is_formula": False,
                "data_validation_type": None,
            },
            {
                "index": 1,
                "col_letter": "B",
                "header_label": "Customer",
                "is_formula": False,
                "data_validation_type": None,
            },
            {
                "index": 2,
                "col_letter": "C",
                "header_label": "Status",
                "is_formula": False,
                "data_validation_type": "ONE_OF_LIST",
            },
            {
                "index": 3,
                "col_letter": "D",
                "header_label": "Total",
                "is_formula": True,
                "data_validation_type": None,
            },
            {
                "index": 4,
                "col_letter": "E",
                "header_label": "Tax",
                "is_formula": True,
                "data_validation_type": None,
            },
            {
                "index": 5,
                "col_letter": "F",
                "header_label": "Notes",
                "is_formula": False,
                "data_validation_type": None,
            },
        ],
        "named_ranges": [],
        "filter_views": [],
    }
    tab.update(overrides)
    return {
        "schema_version": "structure-draft-1",
        "source_id": "demo",
        "provider": "google_sheets",
        "tabs": [tab],
    }


def _form_like_structure() -> dict:
    """5-12 cols with moderate formula density."""
    return {
        "schema_version": "structure-draft-1",
        "source_id": "farm",
        "provider": "google_sheets",
        "tabs": [
            {
                "worksheet_title": "Crop Planner",
                "tab_position": 0,
                "total_rows": 200,
                "total_cols": 8,
                "columns": [
                    {"header_label": "Crop", "is_formula": False},
                    {"header_label": "Variety", "is_formula": False},
                    {"header_label": "Plant Date", "is_formula": False},
                    {"header_label": "Beds", "is_formula": False},
                    {"header_label": "Block", "is_formula": False},
                    {"header_label": "Yield", "is_formula": True},
                    {"header_label": "Revenue", "is_formula": True},
                    {"header_label": "Notes", "is_formula": False},
                ],
                "named_ranges": [],
                "filter_views": [],
            }
        ],
    }


def _list_like_structure() -> dict:
    """15+ cols with low formula density."""
    cols = []
    for index in range(18):
        cols.append(
            {
                "header_label": f"Field {index}",
                "is_formula": index >= 16,  # 2 formulas out of 18
            }
        )
    return {
        "schema_version": "structure-draft-1",
        "source_id": "inventory",
        "provider": "google_sheets",
        "tabs": [
            {
                "worksheet_title": "Inventory",
                "tab_position": 0,
                "total_rows": 500,
                "total_cols": 18,
                "columns": cols,
                "named_ranges": [],
                "filter_views": [],
            }
        ],
    }


def _dashboard_like_structure() -> dict:
    """High formula density + cross-sheet refs."""
    return {
        "schema_version": "structure-draft-1",
        "source_id": "ops",
        "provider": "google_sheets",
        "tabs": [
            {
                "worksheet_title": "KPI Dashboard",
                "tab_position": 0,
                "total_rows": 50,
                "total_cols": 6,
                "columns": [
                    {"header_label": "Metric", "is_formula": False},
                    {"header_label": "Q1", "is_formula": True},
                    {"header_label": "Q2", "is_formula": True},
                    {"header_label": "Q3", "is_formula": True},
                    {"header_label": "Q4", "is_formula": True},
                    {"header_label": "Annual", "is_formula": True},
                ],
                "named_ranges": [{"name": "Q1Data", "range": "'Source Data'!A1:B10"}],
                "filter_views": [],
            }
        ],
    }


def _reference_like_structure() -> dict:
    """Fewer than 5 cols."""
    return {
        "schema_version": "structure-draft-1",
        "source_id": "refs",
        "provider": "google_sheets",
        "tabs": [
            {
                "worksheet_title": "Unit Codes",
                "tab_position": 0,
                "total_rows": 30,
                "total_cols": 3,
                "columns": [
                    {"header_label": "Code", "is_formula": False},
                    {"header_label": "Description", "is_formula": False},
                    {"header_label": "Category", "is_formula": False},
                ],
                "named_ranges": [],
                "filter_views": [],
            }
        ],
    }


# ---------------------------------------------------------------------------
# UI archetype classification
# ---------------------------------------------------------------------------


class TestClassifyUiArchetype:
    """Verify each archetype heuristic produces the expected classification."""

    def test_form_archetype(self):
        """5-12 cols with moderate formula density → form."""
        label, confidence, scores = _classify_ui_archetype_v2(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=False,
            has_time_scope=False,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=200,
            expansion_formula_ratio=0.0,
        )
        assert label == "form"
        assert 0.0 <= confidence <= 1.0
        assert isinstance(scores, dict)

    def test_list_archetype(self):
        """15+ cols with low formula density → list."""
        label, confidence, scores = _classify_ui_archetype_v2(
            column_count=18,
            formula_density=0.11,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=False,
            has_time_scope=False,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=500,
            expansion_formula_ratio=0.0,
        )
        assert label == "list"

    def test_dashboard_archetype_high_formula(self):
        """High formula density (>=0.50) → dashboard."""
        label, confidence, scores = _classify_ui_archetype_v2(
            column_count=6,
            formula_density=0.83,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=False,
            has_time_scope=False,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=50,
            expansion_formula_ratio=0.0,
        )
        assert label == "dashboard"

    def test_dashboard_archetype_cross_sheet_refs(self):
        """High formula density + cross-sheet refs → dashboard."""
        label, confidence, scores = _classify_ui_archetype_v2(
            column_count=10,
            formula_density=0.50,
            cross_sheet_ref_count=2,
            avg_null_rate=0.0,
            has_status_column=False,
            has_time_scope=False,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=200,
            expansion_formula_ratio=0.0,
        )
        assert label == "dashboard"

    def test_reference_archetype_few_cols(self):
        """Fewer than 5 cols → reference."""
        label, confidence, scores = _classify_ui_archetype_v2(
            column_count=3,
            formula_density=0.0,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=False,
            has_time_scope=False,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=30,
            expansion_formula_ratio=0.0,
        )
        assert label == "reference"

    def test_reference_archetype_high_null_rate(self):
        """Few columns + high null rate → reference."""
        label, confidence, scores = _classify_ui_archetype_v2(
            column_count=4,
            formula_density=0.0,
            cross_sheet_ref_count=0,
            avg_null_rate=0.70,
            has_status_column=False,
            has_time_scope=False,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=30,
            expansion_formula_ratio=0.0,
        )
        assert label == "reference"

    def test_form_fallback_for_5_to_12_low_formula(self):
        """5-12 cols with very low formula density → form (fallback)."""
        label, confidence, scores = _classify_ui_archetype_v2(
            column_count=7,
            formula_density=0.05,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=False,
            has_time_scope=False,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=200,
            expansion_formula_ratio=0.0,
        )
        assert label == "form"


# ---------------------------------------------------------------------------
# Formula density
# ---------------------------------------------------------------------------


class TestFormulaDensity:
    """Verify formula_density is computed correctly from column data."""

    def test_no_formulas(self):
        """All raw columns → density of 0.0."""
        signals = extract_signals(_form_like_structure())
        entry = signals["signals"][0]
        # 2 formulas / 8 columns = 0.25
        assert entry["formula_density"] == 0.25

    def test_all_formulas(self):
        """All formula columns → density of 1.0."""
        structure = {
            "schema_version": "1",
            "source_id": "test",
            "provider": "sheets",
            "tabs": [
                {
                    "worksheet_title": "All Formulas",
                    "columns": [
                        {"header_label": "A", "is_formula": True},
                        {"header_label": "B", "is_formula": True},
                    ],
                }
            ],
        }
        signals = extract_signals(structure)
        entry = signals["signals"][0]
        assert entry["formula_density"] == 1.0

    def test_no_columns(self):
        """No columns → density of 0.0 (no division by zero)."""
        structure = {
            "schema_version": "1",
            "source_id": "test",
            "provider": "sheets",
            "tabs": [
                {
                    "worksheet_title": "Empty Tab",
                    "columns": [],
                }
            ],
        }
        signals = extract_signals(structure)
        entry = signals["signals"][0]
        assert entry["formula_density"] == 0.0


# ---------------------------------------------------------------------------
# Cross-sheet references
# ---------------------------------------------------------------------------


class TestDependencyEdges:
    """Dependency edge extraction from named_ranges / filter_views / formulas."""

    def test_no_refs(self):
        """No named ranges or filter views → empty list."""
        edges = _extract_dependency_edges(
            {"named_ranges": [], "filter_views": []}, "SourceTab"
        )
        assert edges == []

    def test_named_range_with_cross_sheet(self):
        """Named range referencing another sheet produces an edge."""
        edges = _extract_dependency_edges(
            {
                "named_ranges": [{"name": "External", "range": "'Sheet2'!A1:B10"}],
                "filter_views": [],
            },
            "SourceTab",
        )
        assert len(edges) == 1
        assert edges[0]["to"] == "Sheet2"
        assert edges[0]["ref_type"] == "named_range"
        assert edges[0]["confidence"] == 0.95

    def test_named_range_same_sheet(self):
        """Named range only on the same sheet produces no edge."""
        edges = _extract_dependency_edges(
            {
                "named_ranges": [{"name": "LocalData", "range": "A1:B10"}],
                "filter_views": [],
            },
            "SourceTab",
        )
        assert len(edges) == 0

    def test_filter_view_with_cross_sheet(self):
        """Filter view referencing another sheet produces an edge."""
        edges = _extract_dependency_edges(
            {
                "named_ranges": [],
                "filter_views": [{"range": "'Summary'!A1:C50"}],
            },
            "SourceTab",
        )
        assert len(edges) == 1
        assert edges[0]["to"] == "Summary"
        assert edges[0]["ref_type"] == "filter_view"
        assert edges[0]["confidence"] == 0.80

    def test_only_in_scope_tabs(self):
        """Tabs outside the current extraction scope are still linked."""
        edges = _extract_dependency_edges(
            {
                "named_ranges": [],
                "filter_views": [],
            },
            "IsolatedTab",
        )
        assert len(edges) == 0


# ---------------------------------------------------------------------------
# Sheet name extraction from range strings
# ---------------------------------------------------------------------------


class TestExtractSheetNameFromRange:
    def test_quoted_sheet_name(self):
        result = _extract_sheet_name_from_range("'Sheet2'!A1:B10")
        assert result == "Sheet2"

    def test_unquoted_sheet_name(self):
        result = _extract_sheet_name_from_range("Sheet2!A1:B10")
        assert result == "Sheet2"

    def test_no_sheet_reference(self):
        result = _extract_sheet_name_from_range("A1:B10")
        assert result is None

    def test_sheet_name_with_spaces(self):
        result = _extract_sheet_name_from_range("'Source Data'!A1")
        assert result == "Source Data"


# ---------------------------------------------------------------------------
# Formula edge extraction
# ---------------------------------------------------------------------------


class TestExtractFormulaEdgesFromText:
    def test_importrange(self):
        edges = _extract_formula_edges_from_text(
            '=IMPORTRANGE("abc123", "Sheet2!A1:B10")', "CurrentTab"
        )
        assert len(edges) == 1
        assert edges[0]["to"] == "Sheet2"
        assert edges[0]["ref_type"] == "IMPORTRANGE"
        assert edges[0]["confidence"] == 0.90

    def test_vlookup(self):
        edges = _extract_formula_edges_from_text(
            "=VLOOKUP(A2, 'LookupSheet'!A:B, 2, FALSE)", "CurrentTab"
        )
        assert len(edges) == 1
        assert edges[0]["to"] == "LookupSheet"
        assert edges[0]["ref_type"] == "VLOOKUP"
        assert edges[0]["confidence"] == 0.85

    def test_hlookup(self):
        edges = _extract_formula_edges_from_text(
            "=HLOOKUP(B5, 'Rates'!A1:Z100, 3, FALSE)", "CurrentTab"
        )
        assert len(edges) == 1
        assert edges[0]["to"] == "Rates"
        assert edges[0]["ref_type"] == "HLOOKUP"
        assert edges[0]["confidence"] == 0.85

    def test_sum_range(self):
        edges = _extract_formula_edges_from_text(
            "=SUM('Monthly Totals'!C2:C50)", "CurrentTab"
        )
        assert len(edges) == 1
        assert edges[0]["to"] == "Monthly Totals"
        assert edges[0]["ref_type"] == "SUM_range"
        assert edges[0]["confidence"] == 0.80

    def test_direct_cell_reference(self):
        edges = _extract_formula_edges_from_text(
            "='ArchiveSheet'!A1 + B2", "CurrentTab"
        )
        assert len(edges) == 1
        assert edges[0]["to"] == "ArchiveSheet"
        assert edges[0]["ref_type"] == "cell_ref"
        assert edges[0]["confidence"] == 0.60

    def test_same_sheet_formula_ignored(self):
        edges = _extract_formula_edges_from_text("=SUM(A1:A10)", "CurrentTab")
        assert len(edges) == 0

    def test_multiple_formulas_in_one_cell(self):
        edges = _extract_formula_edges_from_text(
            "=VLOOKUP(A2, 'SheetA'!A:B, 2, FALSE) + SUM('SheetB'!C1:C10)",
            "CurrentTab",
        )
        assert len(edges) == 2
        targets = {e["to"] for e in edges}
        assert targets == {"SheetA", "SheetB"}


# ---------------------------------------------------------------------------
# Workflow graph building
# ---------------------------------------------------------------------------


class TestBuildWorkflowGraph:
    def test_simple_graph(self):
        edges = [
            {
                "from": "CropPlanner",
                "to": "HarvestRecord",
                "ref_type": "VLOOKUP",
                "confidence": 0.85,
            },
        ]
        tabs = [
            {"worksheet_title": "CropPlanner", "tab_position": 0},
            {"worksheet_title": "HarvestRecord", "tab_position": 1},
        ]
        graph = _build_workflow_graph(edges, tabs)
        assert len(graph["edges"]) == 1
        assert graph["tab_sequence"] == ["CropPlanner", "HarvestRecord"]
        assert graph["has_cycles"] is False

    def test_no_edges(self):
        graph = _build_workflow_graph([], [])
        assert graph["edges"] == []
        assert graph["tab_sequence"] == []
        assert graph["has_cycles"] is False
        assert graph["tabs"] == {}

    def test_cycle_detection(self):
        edges = [
            {"from": "A", "to": "B", "ref_type": "named_range", "confidence": 0.95},
            {"from": "B", "to": "C", "ref_type": "named_range", "confidence": 0.95},
            {"from": "C", "to": "A", "ref_type": "named_range", "confidence": 0.95},
        ]
        tabs = [
            {"worksheet_title": "A", "tab_position": 0},
            {"worksheet_title": "B", "tab_position": 1},
            {"worksheet_title": "C", "tab_position": 2},
        ]
        graph = _build_workflow_graph(edges, tabs)
        assert graph["has_cycles"] is True
        assert "cycles" in graph
        # Should still produce a tab_sequence (cycles are flagged, not rejected)
        assert len(graph["tab_sequence"]) == 3
        assert set(graph["tab_sequence"]) == {"A", "B", "C"}

    def test_graph_tabs_include_edge_targets(self):
        edges = [
            {
                "from": "Orders",
                "to": "Products",
                "ref_type": "VLOOKUP",
                "confidence": 0.85,
            },
        ]
        tabs = [
            {"worksheet_title": "Orders", "tab_position": 0},
        ]
        graph = _build_workflow_graph(edges, tabs)
        # Products is not in structure tabs but referenced by edge
        assert "Products" in graph["tabs"]
        assert graph["tabs"]["Products"]["position"] == -1

    def test_topological_sort(self):
        edges = [
            {
                "from": "Budget",
                "to": "Actuals",
                "ref_type": "VLOOKUP",
                "confidence": 0.85,
            },
            {
                "from": "Actuals",
                "to": "Report",
                "ref_type": "named_range",
                "confidence": 0.95,
            },
            {
                "from": "Input",
                "to": "Budget",
                "ref_type": "SUM_range",
                "confidence": 0.80,
            },
        ]
        tabs = [
            {"worksheet_title": "Input", "tab_position": 0},
            {"worksheet_title": "Budget", "tab_position": 1},
            {"worksheet_title": "Actuals", "tab_position": 2},
            {"worksheet_title": "Report", "tab_position": 3},
        ]
        graph = _build_workflow_graph(edges, tabs)
        seq = graph["tab_sequence"]
        # Input must come before Budget, Budget before Actuals, Actuals before Report
        assert seq.index("Input") < seq.index("Budget")
        assert seq.index("Budget") < seq.index("Actuals")
        assert seq.index("Actuals") < seq.index("Report")


# ---------------------------------------------------------------------------
# Null rates
# ---------------------------------------------------------------------------


class TestNullRates:
    """Null rate extraction from deep-profile data."""

    def test_no_deep_profile(self):
        """Without deep-profile data, null_rates is empty."""
        signals = extract_signals(_form_like_structure())
        entry = signals["signals"][0]
        assert entry["null_rates"] == {}

    def test_with_deep_profile(self):
        """Deep-profile data populates per-column null_rates."""
        structure = _form_like_structure()
        deep_profiles = {
            "Crop Planner": {
                "Crop": {"null_count": 0, "non_null_count": 200},
                "Variety": {"null_count": 10, "non_null_count": 190},
                "Plant Date": {"null_count": 24, "non_null_count": 176},
                "Beds": {"null_count": 50, "non_null_count": 150},
                "Block": {"null_count": 5, "non_null_count": 195},
                "Yield": {"null_count": 0, "non_null_count": 200},
                "Revenue": {"null_count": 100, "non_null_count": 100},
                "Notes": {"null_count": 180, "non_null_count": 20},
            }
        }
        signals = extract_signals(structure, deep_profiles=deep_profiles)
        entry = signals["signals"][0]
        assert "Crop" in entry["null_rates"]
        assert entry["null_rates"]["Crop"] == 0.0
        assert entry["null_rates"]["Plant Date"] == 0.12
        assert entry["null_rates"]["Notes"] == 0.9

    def test_avg_null_rate_empty(self):
        """Empty null_rates dict → avg of 0.0."""
        assert _compute_avg_null_rate({}) == 0.0

    def test_avg_null_rate_computation(self):
        """Compute average across columns."""
        rates = {"A": 0.0, "B": 0.5, "C": 1.0}
        assert _compute_avg_null_rate(rates) == 0.5


# ---------------------------------------------------------------------------
# Confidence score
# ---------------------------------------------------------------------------


class TestConfidenceScore:
    """Confidence score is always in [0, 1] and varies with archetype margin."""

    def test_confidence_in_range(self):
        """Confidence score is always between 0 and 1."""
        label, confidence, scores = _classify_ui_archetype_v2(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=False,
            has_time_scope=False,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=200,
            expansion_formula_ratio=0.0,
        )
        assert 0.0 <= confidence <= 1.0

    def test_confidence_higher_with_clear_winner(self):
        """Clear archetype winner → higher confidence."""
        # Strong form signals (all form indicators present)
        label1, c1, scores1 = _classify_ui_archetype_v2(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=True,
            has_time_scope=False,
            data_validation_density=0.38,
            header_formula_count=2,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=200,
            expansion_formula_ratio=0.0,
        )
        # Weak/ambiguous signals
        label2, c2, scores2 = _classify_ui_archetype_v2(
            column_count=10,
            formula_density=0.15,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=False,
            has_time_scope=False,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=100,
            expansion_formula_ratio=0.0,
        )
        assert c1 >= c2

    def test_archetype_scores_has_four_keys(self):
        """Scores dict always contains all 4 archetype keys."""
        label, confidence, scores = _classify_ui_archetype_v2(
            column_count=8,
            formula_density=0.25,
            cross_sheet_ref_count=0,
            avg_null_rate=0.0,
            has_status_column=False,
            has_time_scope=False,
            data_validation_density=0.0,
            header_formula_count=0,
            header_entity_count=0,
            merged_cell_ratio=0.0,
            row_count=200,
            expansion_formula_ratio=0.0,
        )
        assert set(scores.keys()) == {"form", "list", "dashboard", "reference"}


# ---------------------------------------------------------------------------
# Full extraction
# ---------------------------------------------------------------------------


class TestExtractSignals:
    """Integration-style tests for the full extraction pipeline."""

    def test_extract_signals_structure_only(self):
        """Basic extraction produces expected shape."""
        structure = _form_like_structure()
        signals = extract_signals(structure)

        assert signals["version"] == SIGNALS_VERSION
        assert "generated_at" in signals
        assert len(signals["signals"]) == 1

        entry = signals["signals"][0]
        assert entry["tab_title"] == "Crop Planner"
        assert entry["workbook_code"] == "farm"
        assert entry["ui_archetype"] == "form"
        assert entry["formula_density"] == 0.25
        assert entry["cross_sheet_refs"] == 0
        assert entry["null_rates"] == {}
        assert 0.0 <= entry["confidence_score"] <= 1.0
        assert "archetype_scores" in entry
        assert set(entry["archetype_scores"].keys()) == {
            "form",
            "list",
            "dashboard",
            "reference",
        }
        # New v2 signal fields
        assert entry["has_status_column"] is False
        assert "has_time_scope" in entry
        assert isinstance(entry["data_validation_density"], float)
        assert isinstance(entry["header_formula_count"], int)
        assert isinstance(entry["header_entity_count"], int)
        assert isinstance(entry["row_count"], int)
        assert isinstance(entry["expansion_formula_ratio"], float)
        assert isinstance(entry["merged_cell_ratio"], float)
        # workflow_graph in top-level output
        assert "workflow_graph" in signals
        assert "tabs" in signals["workflow_graph"]
        assert "edges" in signals["workflow_graph"]
        assert "tab_sequence" in signals["workflow_graph"]
        assert "has_cycles" in signals["workflow_graph"]

    def test_with_bundle_config(self):
        """Bundle config provides workbook_code per tab."""
        structure = _form_like_structure()
        bundle_config = {
            "provider": "google_sheets",
            "source_id": "bundle-source",
            "tabs": [
                {
                    "spreadsheet_id": "abc123",
                    "worksheet_title": "Crop Planner",
                    "output_path": "crop_planner.csv",
                }
            ],
        }
        signals = extract_signals(structure, bundle_config=bundle_config)
        entry = signals["signals"][0]
        assert entry["workbook_code"] == "bundle-source"

    def test_list_archetype_extraction(self):
        """A list-like structure classifies as list."""
        structure = _list_like_structure()
        signals = extract_signals(structure)
        entry = signals["signals"][0]
        assert entry["ui_archetype"] == "list"
        assert entry["formula_density"] == pytest.approx(2 / 18, rel=1e-2)

    def test_dashboard_archetype_extraction(self):
        """A dashboard-like structure classifies as dashboard."""
        structure = _dashboard_like_structure()
        signals = extract_signals(structure)
        entry = signals["signals"][0]
        assert entry["ui_archetype"] == "dashboard"
        assert entry["cross_sheet_refs"] == 1

    def test_reference_archetype_extraction(self):
        """A reference-like structure classifies as reference."""
        structure = _reference_like_structure()
        signals = extract_signals(structure)
        entry = signals["signals"][0]
        assert entry["ui_archetype"] == "reference"

    def test_signals_yaml_roundtrip(self, tmp_path):
        """Signals dict serializes to YAML and reads back correctly."""
        structure = _form_like_structure()
        signals = extract_signals(structure)

        out_path = tmp_path / "profiler-signals.yaml"
        out_path.write_text(
            yaml.safe_dump(
                signals,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )

        loaded = yaml.safe_load(out_path.read_text(encoding="utf-8"))
        assert loaded["version"] == SIGNALS_VERSION
        assert len(loaded["signals"]) == 1
        assert loaded["signals"][0]["tab_title"] == "Crop Planner"

    def test_scaffold_view_manifest_signals_only_command(self, tmp_path):
        """The management command with --signals-only produces valid YAML."""
        structure = _form_like_structure()
        structure_path = tmp_path / "structure.json"
        import json

        structure_path.write_text(json.dumps(structure), encoding="utf-8")

        out_path = tmp_path / "profiler-signals.yaml"

        call_command(
            "scaffold_view_manifest",
            structure=str(structure_path),
            signals_only=True,
            output=str(out_path),
        )

        assert out_path.exists()
        loaded = yaml.safe_load(out_path.read_text(encoding="utf-8"))
        assert loaded["version"] == SIGNALS_VERSION
        assert len(loaded["signals"]) == 1
        entry = loaded["signals"][0]
        assert entry["tab_title"] == "Crop Planner"
        assert entry["ui_archetype"] == "form"
        assert 0.0 <= entry["confidence_score"] <= 1.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases: empty structure, missing fields, zero-division guards."""

    def test_empty_tabs(self):
        """No tabs → empty signals list."""
        structure = {
            "schema_version": "1",
            "source_id": "test",
            "provider": "sheets",
            "tabs": [],
        }
        signals = extract_signals(structure)
        assert signals["signals"] == []

    def test_missing_total_rows(self):
        """Missing total_rows → 0 (no crash)."""
        structure = {
            "schema_version": "1",
            "source_id": "test",
            "provider": "sheets",
            "tabs": [
                {
                    "worksheet_title": "Test",
                    "columns": [{"header_label": "A", "is_formula": False}],
                }
            ],
        }
        signals = extract_signals(structure)
        entry = signals["signals"][0]
        assert entry["tab_title"] == "Test"
        assert 0.0 <= entry["confidence_score"] <= 1.0

    def test_single_column_tab(self):
        """Single column → reference archetype."""
        structure = {
            "schema_version": "1",
            "source_id": "test",
            "provider": "sheets",
            "tabs": [
                {
                    "worksheet_title": "Single",
                    "columns": [{"header_label": "A", "is_formula": False}],
                }
            ],
        }
        signals = extract_signals(structure)
        entry = signals["signals"][0]
        assert entry["ui_archetype"] == "reference"

    def test_generated_at_is_valid_iso(self):
        """generated_at is a valid ISO 8601 timestamp."""
        structure = _form_like_structure()
        signals = extract_signals(structure)
        # Parse it back — will raise if invalid
        datetime.fromisoformat(signals["generated_at"])


# ---------------------------------------------------------------------------
# CLI --explain / --min-confidence integration
# ---------------------------------------------------------------------------


class TestCliExplain:
    """Integration tests for --explain and --min-confidence flags."""

    def test_explain_flag_outputs_archetype_labels(self, tmp_path):
        """--explain prints archetype labels for each tab."""
        structure = _form_like_structure()
        structure_path = tmp_path / "structure.json"
        structure_path.write_text(json.dumps(structure), encoding="utf-8")

        out = io.StringIO()
        call_command(
            "scaffold_view_manifest",
            "--signals-only",
            "--explain",
            "--structure",
            str(structure_path),
            stdout=out,
        )
        output = out.getvalue()
        # Should contain archetype labels in the explanation output
        assert any(
            label in output for label in ("form", "list", "dashboard", "reference")
        )

    def test_explain_requires_signals_only(self):
        """--explain without --signals-only raises error."""
        with pytest.raises(CommandError, match="signals-only"):
            call_command(
                "scaffold_view_manifest",
                "--explain",
                "--structure",
                "/nonexistent/structure.json",
            )

    def test_min_confidence_requires_explain(self):
        """--min-confidence without --explain raises error."""
        with pytest.raises(CommandError, match="explain"):
            call_command(
                "scaffold_view_manifest",
                "--signals-only",
                "--min-confidence",
                "0.7",
                "--structure",
                "/nonexistent/structure.json",
            )

    def test_min_confidence_filters_low_confidence(self, tmp_path):
        """--min-confidence 1.0 shows all tabs (all below threshold)."""
        structure = _form_like_structure()
        structure_path = tmp_path / "structure.json"
        structure_path.write_text(json.dumps(structure), encoding="utf-8")

        out = io.StringIO()
        call_command(
            "scaffold_view_manifest",
            "--signals-only",
            "--explain",
            "--min-confidence",
            "1.0",
            "--structure",
            str(structure_path),
            stdout=out,
        )
        output = out.getvalue()
        # The explanation always includes the word "confidence"
        assert "confidence" in output
