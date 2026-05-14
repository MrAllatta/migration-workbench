"""Tests for column-level formula pattern classification."""

from profiler.tools.formula_classifier import classify_column_formula_pattern


def test_raw_column_no_formulas():
    cells = [
        {"row": 1, "col": 0, "kind": "string", "text": "Name"},
        {"row": 2, "col": 0, "kind": "string", "text": "Apple"},
        {"row": 3, "col": 0, "kind": "string", "text": "Banana"},
        {"row": 4, "col": 0, "kind": "string", "text": "Carrot"},
    ]
    result = classify_column_formula_pattern(cells)
    assert result == "raw"


def test_row_formula_column():
    cells = [
        {"row": 1, "col": 0, "kind": "formula", "text": "=A2+B2"},
        {"row": 2, "col": 0, "kind": "formula", "text": "=A3+B3"},
        {"row": 3, "col": 0, "kind": "formula", "text": "=A4+B4"},
        {"row": 4, "col": 0, "kind": "formula", "text": "=A5+B5"},
    ]
    result = classify_column_formula_pattern(cells)
    assert result == "row_formula"


def test_expansion_formula_column():
    cells = [
        {"row": 1, "col": 0, "kind": "formula", "text": "=ARRAYFORMULA(A2:A)"},
        {"row": 2, "col": 0, "kind": "empty", "text": ""},
        {"row": 3, "col": 0, "kind": "empty", "text": ""},
    ]
    result = classify_column_formula_pattern(cells)
    assert result == "expansion_formula"


def test_hybrid_column_mixed_raw_and_formula():
    cells = [
        {"row": 1, "col": 0, "kind": "string", "text": "Notes"},
        {"row": 2, "col": 0, "kind": "string", "text": "Manual entry"},
        {"row": 3, "col": 0, "kind": "formula", "text": '=IF(A3>0,"yes","no")'},
        {"row": 4, "col": 0, "kind": "string", "text": "Another manual"},
        {"row": 5, "col": 0, "kind": "formula", "text": "=B5*0.1"},
    ]
    result = classify_column_formula_pattern(cells)
    assert result == "hybrid"


def test_empty_column():
    cells = [
        {"row": 1, "col": 0, "kind": "string", "text": "Header"},
        {"row": 2, "col": 0, "kind": "empty", "text": ""},
        {"row": 3, "col": 0, "kind": "empty", "text": ""},
        {"row": 4, "col": 0, "kind": "empty", "text": ""},
    ]
    result = classify_column_formula_pattern(cells)
    assert result == "empty"


def test_empty_cell_list_returns_empty():
    result = classify_column_formula_pattern([])
    assert result == "empty"


def test_expansion_detection_querys():
    cells = [
        {"row": 1, "col": 0, "kind": "formula", "text": '=QUERY(A:B,"select *")'},
    ]
    result = classify_column_formula_pattern(cells)
    assert result == "expansion_formula"
