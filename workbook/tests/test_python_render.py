"""Tests for python_render utilities."""

from __future__ import annotations

import pytest

from workbook.codegen.python_render import to_python_identifier


@pytest.mark.parametrize("input,expected", [
    ("1", "f_1"),
    ("201_unit", "f_201_unit"),
    ("yield", "yield_"),
    ("Column #1", "column_1"),
    ("Field.name", "field_name"),
    ("unit-price", "unit_price"),
    ("_hidden", "hidden"),
    ("if", "if_"),
    ("", "f_"),
    ("_1_2_3_", "f_1_2_3_"),
    ("normal_field", "normal_field"),
    ("status", "status"),
    ("Yield", "yield_"),
    ("class", "class_"),
    ("1field", "f_1field"),
    ("Field  1", "field_1"),
    ("a..b", "a_b"),
    ("__dunder__", "dunder"),
])
def test_to_python_identifier(input, expected):
    assert to_python_identifier(input) == expected


@pytest.mark.parametrize("keyword", [
    "False", "None", "True", "and", "as", "assert", "async", "await",
    "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is",
    "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
    "while", "with", "yield",
])
def test_python_keywords_get_underscore_suffix(keyword):
    result = to_python_identifier(keyword)
    assert result.endswith("_")
    assert result.isidentifier()