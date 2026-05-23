"""Tests for scoping_assessment.py."""
import json
from pathlib import Path
from scripts.scoping_assessment import assess_spreadsheet_complexity

SAMPLE_PROFILE = {
    "tabs": [
        {"title": "Crop Planner", "columns": ["Crop", "Type", "Plant Date", "Block"], "row_count": 500, "formula_columns": 1},
        {"title": "Planting Log", "columns": ["Date", "Field", "Crop", "Seed Qty", "Notes"], "row_count": 1200, "formula_columns": 0},
        {"title": "Harvest Log", "columns": ["Date", "Field", "Crop", "Qty", "Grade", "Notes"], "row_count": 800, "formula_columns": 1},
    ],
    "cross_sheet_refs": [
        {"from": "Harvest Log", "to": "Crop Planner", "ref_count": 1},
    ],
}


def test_assess_spreadsheet_complexity_returns_expected_keys():
    result = assess_spreadsheet_complexity(SAMPLE_PROFILE)
    assert "tab_count" in result
    assert "total_rows" in result
    assert "formula_density" in result
    assert "cross_sheet_ref_count" in result
    assert "complexity_tier" in result
    assert "estimated_build_weeks" in result
    assert "recommendation" in result


def test_simple_spreadsheet_is_appliance():
    simple = {"tabs": [{"title": "Sheet1", "columns": ["A", "B"], "row_count": 50, "formula_columns": 0}], "cross_sheet_refs": []}
    result = assess_spreadsheet_complexity(simple)
    assert result["complexity_tier"] == "appliance"


def test_complex_spreadsheet_is_partnership():
    complex_profile = {
        "tabs": [
            {"title": f"Tab{i}", "columns": [f"Col{j}" for j in range(15)], "row_count": 2000, "formula_columns": 8}
            for i in range(12)
        ],
        "cross_sheet_refs": [
            {"from": f"Tab{i}", "to": f"Tab{j}", "ref_count": 3}
            for i in range(12) for j in range(12) if i != j
        ],
    }
    result = assess_spreadsheet_complexity(complex_profile)
    assert result["complexity_tier"] == "partnership"
