"""Tests for Coda provider shape utilities."""

from connectors.coda import shape_coda_table_structure


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
