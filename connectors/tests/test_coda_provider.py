"""Tests for Coda provider shape utilities."""

from connectors.coda import shape_coda_table_structure
from connectors.coda_source import extract_relation_columns, classify_formula_columns


def test_shape_coda_table_structure_sanitizes_tab_name():
    columns = [{"id": "col-1", "name": "Name", "format": {}}]
    result = shape_coda_table_structure(
        None,
        columns,
        table_id="tbl-1",
        table_name="i|Orders",
        table_position=0,
    )
    assert result["worksheet_title"] == "i_Orders"


def test_shape_coda_table_structure_includes_relation_columns():
    columns = [
        {"id": "c-1", "name": "Name", "format": {"type": "text"}},
        {
            "id": "c-2",
            "name": "Project",
            "format": {
                "type": "lookup",
                "table": {"id": "t-proj", "name": "Projects"},
                "displayColumn": {"name": "Project Name"},
            },
        },
        {"id": "c-3", "name": "Owner", "format": {"type": "person"}},
    ]
    result = shape_coda_table_structure(
        None,
        columns,
        table_id="tbl-1",
        table_name="Tasks",
        table_position=0,
    )
    assert "relation_columns" in result
    rels = result["relation_columns"]
    assert len(rels) == 2
    lookup = next(r for r in rels if r["column_name"] == "Project")
    assert lookup["column_type"] == "lookup"
    assert lookup["target_table_name"] == "Projects"
    assert lookup["target_table_id"] == "t-proj"
    assert lookup["is_bidirectional"] is False
    person = next(r for r in rels if r["column_name"] == "Owner")
    assert person["column_type"] == "person"


def test_extract_relation_columns_handles_linked_relation():
    columns = [
        {
            "id": "c-1",
            "name": "Backrefs",
            "format": {
                "type": "linked_relation",
                "table": {"id": "t-tasks", "name": "Tasks"},
                "sourceTable": {"name": "Projects"},
            },
        }
    ]
    rels = extract_relation_columns(columns)
    assert len(rels) == 1
    assert rels[0]["column_type"] == "linked_relation"
    assert rels[0]["is_bidirectional"] is True
    assert rels[0]["target_table_name"] == "Tasks"
    assert any("source_table:Projects" in n for n in rels[0]["notes"])


def test_extract_relation_columns_skips_plain_text():
    columns = [
        {"id": "c-1", "name": "Title", "format": {"type": "text"}},
        {"id": "c-2", "name": "Count", "format": {"type": "number"}},
    ]
    rels = extract_relation_columns(columns)
    assert rels == []


def test_classify_formula_columns_row_formula():
    columns = [
        {
            "id": "c-1",
            "name": "Total",
            "formulaText": "thisRow.Price * thisRow.Quantity",
        }
    ]
    result = classify_formula_columns(columns)
    assert len(result) == 1
    assert result[0]["column_name"] == "Total"
    assert result[0]["classification"] == "row_formula"
    assert result[0]["confidence"] == "high"


def test_classify_formula_columns_expansion_formula():
    columns = [
        {
            "id": "c-1",
            "name": "Grand Total",
            "formulaText": 'Sum([Orders].[Total]).Filter([Status] = "paid")',
        }
    ]
    result = classify_formula_columns(columns)
    assert len(result) == 1
    assert result[0]["classification"] == "expansion_formula"
    assert result[0]["confidence"] == "high"


def test_classify_formula_columns_hybrid():
    columns = [
        {
            "id": "c-1",
            "name": "Weighted",
            "formulaText": "thisRow.Price * Sum([Orders].[Quantity])",
        }
    ]
    result = classify_formula_columns(columns)
    assert len(result) == 1
    assert result[0]["classification"] == "hybrid"
    assert result[0]["confidence"] == "medium"


def test_classify_formula_columns_unknown():
    columns = [
        {
            "id": "c-1",
            "name": "Mystery",
            "formulaText": "CustomFunction(42)",
        }
    ]
    result = classify_formula_columns(columns)
    assert len(result) == 1
    assert result[0]["classification"] == "unknown"
    assert result[0]["confidence"] == "low"


def test_classify_formula_columns_skips_non_formula():
    columns = [
        {"id": "c-1", "name": "Plain", "format": {"type": "text"}},
    ]
    result = classify_formula_columns(columns)
    assert result == []


def test_classify_formula_columns_string_concat():
    """Bare string concatenation (e.g. ``First+" "+Last``) is a row_formula."""
    columns = [
        {
            "id": "c-1",
            "name": "Full Name",
            "formulaText": 'First+" "+Last',
        }
    ]
    result = classify_formula_columns(columns)
    assert len(result) == 1
    assert result[0]["classification"] == "row_formula"
    assert result[0]["confidence"] == "high"


def test_classify_formula_columns_concatenate_function():
    """``Concatenate()`` function signals a row-level string assembly."""
    columns = [
        {
            "id": "c-1",
            "name": "Display",
            "formulaText": 'Concatenate(Description," ... ", [Flat Rate])',
        }
    ]
    result = classify_formula_columns(columns)
    assert len(result) == 1
    assert result[0]["classification"] == "row_formula"


def test_shape_coda_table_structure_includes_formula_classifications():
    columns = [
        {"id": "c-1", "name": "Name", "format": {"type": "text"}},
        {
            "id": "c-2",
            "name": "Total",
            "formulaText": "thisRow.Price * thisRow.Quantity",
        },
    ]
    result = shape_coda_table_structure(
        None,
        columns,
        table_id="tbl-1",
        table_name="Tasks",
        table_position=0,
    )
    assert "formula_classifications" in result
    fcs = result["formula_classifications"]
    assert len(fcs) == 1
    assert fcs[0]["column_name"] == "Total"
    assert fcs[0]["classification"] == "row_formula"


def test_extract_relation_columns_notes_missing_target():
    columns = [
        {
            "id": "c-1",
            "name": "Mystery",
            "format": {"type": "lookup"},
        }
    ]
    rels = extract_relation_columns(columns)
    assert len(rels) == 1
    assert rels[0]["target_table_name"] is None
    assert "lookup_target_table_not_exposed_in_api" in rels[0]["notes"]


def test_extract_relation_columns_flags_person_as_user_reference():
    """Person-type columns are user references, not domain-table lookups.

    The contract scaffold treats ``is_user_reference=True`` rows as a signal
    to render ``ForeignKey(settings.AUTH_USER_MODEL)`` rather than chasing a
    domain target.  ``target_table_name`` is set to the canonical auth model
    so downstream callers can resolve it without special-casing format.type.
    """
    columns = [
        {
            "id": "c-owner",
            "name": "Owner",
            "format": {"type": "person"},
        },
    ]
    rels = extract_relation_columns(columns)
    assert len(rels) == 1
    owner = rels[0]
    assert owner["column_name"] == "Owner"
    assert owner["column_type"] == "person"
    assert owner["is_user_reference"] is True
    assert owner["target_table_name"] == "auth.User"
    assert owner["target_table_id"] is None
