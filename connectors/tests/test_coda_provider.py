"""Tests for Coda provider shape utilities."""

from connectors.coda import shape_coda_table_structure
from connectors.coda_source import extract_relation_columns


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
