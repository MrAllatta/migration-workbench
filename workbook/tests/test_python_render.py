"""Tests for python_render utilities."""

from __future__ import annotations

import pytest

from workbook.codegen.python_render import (
    render_field,
    render_computed_property,
    to_python_identifier,
)


@pytest.mark.parametrize(
    "input,expected",
    [
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
    ],
)
def test_to_python_identifier(input, expected):
    assert to_python_identifier(input) == expected


@pytest.mark.parametrize(
    "keyword",
    [
        "False",
        "None",
        "True",
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "try",
        "while",
        "with",
        "yield",
    ],
)
def test_python_keywords_get_underscore_suffix(keyword):
    result = to_python_identifier(keyword)
    assert result.endswith("_")
    assert result.isidentifier()


def test_render_field_sanitizes_name_and_looks_up_kwargs_by_sanitized_name():
    result = render_field(
        name="1",
        field_class="models.CharField",
        kwargs={
            "max_length": 100,
            "null": True,
        },
    )
    assert "f_1 = models.CharField" in result
    assert "max_length=100" in result

    result2 = render_field(
        name="yield",
        field_class="models.CharField",
        kwargs={
            "max_length": 50,
        },
    )
    assert "yield_ = models.CharField" in result2
    assert "max_length=50" in result2


def test_render_field_remaps_non_identifier_kwargs():
    result = render_field(
        name="my_field",
        field_class="models.CharField",
        kwargs={
            "max_length": 50,
        },
    )
    assert "my_field = models.CharField" in result


def test_render_field_fk_forward_reference():
    result = render_field(
        name="owner",
        field_class="models.ForeignKey",
        kwargs={
            "to": "Person",
            "on_delete": "models.CASCADE",
        },
        rendered_model_names={"Person", "Organization"},
    )
    assert "owner = models.ForeignKey(Person, on_delete=models.CASCADE)" in result


def test_render_computed_property_sanitizes_name():
    result = render_computed_property(name="201_value", return_type="int")
    assert "def f_201_value(self) -> int:" in result

    result2 = render_computed_property(name="class")
    assert "def class_(self):" in result2
