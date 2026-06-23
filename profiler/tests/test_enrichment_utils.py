"""Tests for profiler enrichment utilities."""

from profiler.tools.enrichment_utils import (
    enrich_fk_from_sheet_graph,
    enrich_from_dependency_graph,
)


def test_enrich_from_dependency_graph_empty():
    """Empty artifact does not modify column profiles."""
    profiles = {"col1": {"header": "Name"}}
    artifact = {"nodes": [], "edges": [], "summary": {}}
    result = enrich_from_dependency_graph(profiles, artifact)
    assert result is None  # in-place mutation, returns None


def test_enrich_from_dependency_graph_all_formula_column():
    """Column where all cells are formula types gets is_computed=True."""
    artifact = {
        "nodes": [
            {"id": "Sheet1!B2", "sheet": "Sheet1", "cell": "B2",
             "formula": "=A2*2", "node_type": "formula"},
            {"id": "Sheet1!B3", "sheet": "Sheet1", "cell": "B3",
             "formula": "=A3*2", "node_type": "formula"},
        ],
        "edges": [],
        "summary": {},
        "high_value_nodes": [],
    }
    profiles = {
        "B": {
            "header": "Total",
            "column_cells": [
                {"kind": "formula", "text": "=A2*2"},
                {"kind": "formula", "text": "=A3*2"},
            ],
        },
    }
    enrich_from_dependency_graph(profiles, artifact)
    assert profiles["B"].get("is_computed") is True


def test_enrich_from_dependency_graph_fk_candidate():
    """INDEX/MATCH cross-sheet reference suggests FK target."""
    artifact = {
        "nodes": [
            {"id": "Sheet1!D2", "sheet": "Sheet1", "cell": "D2",
             "formula": "=INDEX(Products!A:A, MATCH(C2, Products!B:B, 0))",
             "node_type": "formula"},
        ],
        "edges": [
            {"source": "Products!A:A", "target": "Sheet1!D2",
             "ref_type": "range", "is_cross_sheet": True},
        ],
        "summary": {},
        "high_value_nodes": [],
    }
    profiles = {
        "D": {
            "header": "ProductName",
            "column_cells": [
                {"kind": "formula",
                 "text": "=INDEX(Products!A:A, MATCH(C2, Products!B:B, 0))"},
            ],
        },
    }
    enrich_from_dependency_graph(profiles, artifact)
    assert profiles["D"].get("suggested_fk_target") is not None


def test_enrich_from_dependency_graph_mixed_column_no_computed():
    """Column with mixed raw and formula cells does not get is_computed."""
    artifact = {
        "nodes": [
            {"id": "Sheet1!B2", "sheet": "Sheet1", "cell": "B2",
             "formula": "=A2*2", "node_type": "formula"},
        ],
        "edges": [],
        "summary": {},
        "high_value_nodes": [],
    }
    profiles = {
        "B": {
            "header": "Total",
            "column_cells": [
                {"kind": "formula", "text": "=A2*2"},
                {"kind": "raw", "text": "42"},
            ],
        },
    }
    enrich_from_dependency_graph(profiles, artifact)
    assert profiles["B"].get("is_computed") is not True


def test_enrich_from_dependency_graph_empty_profiles():
    """Empty profiles dict does not raise."""
    artifact = {"nodes": [], "edges": [], "summary": {}}
    enrich_from_dependency_graph({}, artifact)
    # Should not raise


def test_enrich_from_dependency_graph_missing_column_cells():
    """Profile without column_cells key does not raise."""
    artifact = {"nodes": [], "edges": [], "summary": {}}
    profiles = {"A": {"header": "Name"}}
    enrich_from_dependency_graph(profiles, artifact)
    # Should not raise


def test_enrich_fk_from_sheet_graph_empty_artifact():
    """No sheet_graph, no crash, no modification."""
    profiles = {
        "A": {"header": "Name", "tab_name": "Summary"},
    }
    artifact = {"nodes": [], "edges": [], "summary": {}}
    enrich_fk_from_sheet_graph(profiles, artifact)
    assert profiles["A"].get("suggested_fk_target") is None


def test_enrich_fk_from_sheet_graph_suggests_fk():
    """Column with tab 'Summary' gets suggested_fk_target when Summary->Data weight 7 >= threshold 3."""
    profiles = {
        "A": {"header": "Name", "tab_name": "Summary", "column_cells": []},
    }
    artifact = {
        "sheet_graph": {
            "nodes": [
                {"id": "Summary", "formula_count": 5, "node_count": 3},
                {"id": "Data", "formula_count": 2, "node_count": 1},
            ],
            "edges": [
                {"from_sheet": "Summary", "to_sheet": "Data", "weight": 7},
            ],
        },
    }
    enrich_fk_from_sheet_graph(profiles, artifact)
    assert profiles["A"]["suggested_fk_target"] == "Data"
    assert profiles["A"].get("_fk_from_sheet_graph") is True


def test_enrich_fk_from_sheet_graph_skips_existing():
    """Column that already has suggested_fk_target is not overridden."""
    profiles = {
        "A": {
            "header": "Name",
            "tab_name": "Summary",
            "suggested_fk_target": "Products",
            "column_cells": [],
        },
    }
    artifact = {
        "sheet_graph": {
            "nodes": [
                {"id": "Summary", "formula_count": 5, "node_count": 3},
                {"id": "Data", "formula_count": 2, "node_count": 1},
            ],
            "edges": [
                {"from_sheet": "Summary", "to_sheet": "Data", "weight": 7},
            ],
        },
    }
    enrich_fk_from_sheet_graph(profiles, artifact)
    assert profiles["A"]["suggested_fk_target"] == "Products"
    assert profiles["A"].get("_fk_from_sheet_graph") is None


def test_enrich_fk_from_sheet_graph_below_threshold():
    """Low-weight edge doesn't produce suggestion."""
    profiles = {
        "A": {"header": "Name", "tab_name": "Summary", "column_cells": []},
    }
    artifact = {
        "sheet_graph": {
            "nodes": [
                {"id": "Summary", "formula_count": 5, "node_count": 3},
                {"id": "Data", "formula_count": 2, "node_count": 1},
            ],
            "edges": [
                {"from_sheet": "Summary", "to_sheet": "Data", "weight": 2},
            ],
        },
    }
    enrich_fk_from_sheet_graph(profiles, artifact, weight_threshold=3)
    assert profiles["A"].get("suggested_fk_target") is None


def test_enrich_fk_from_sheet_graph_no_tab_name():
    """Column without tab_name/worksheet key is skipped gracefully."""
    profiles = {
        "A": {"header": "Name", "column_cells": []},
    }
    artifact = {
        "sheet_graph": {
            "nodes": [
                {"id": "Summary", "formula_count": 5, "node_count": 3},
                {"id": "Data", "formula_count": 2, "node_count": 1},
            ],
            "edges": [
                {"from_sheet": "Summary", "to_sheet": "Data", "weight": 7},
            ],
        },
    }
    enrich_fk_from_sheet_graph(profiles, artifact)
    assert profiles["A"].get("suggested_fk_target") is None
