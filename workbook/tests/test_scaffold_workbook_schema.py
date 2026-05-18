"""Tests for the scaffold_workbook_schema management command."""

from pathlib import Path
from django.core.management import call_command

from workbook.management.commands.scaffold_workbook_schema import _to_pascal_case


def test_to_pascal_case_preserves_pascalcase():
    """Input that is already PascalCase passes through unchanged."""
    assert _to_pascal_case("SalesChannel") == "SalesChannel"
    assert _to_pascal_case("FarmUser") == "FarmUser"
    assert _to_pascal_case("FieldBlock") == "FieldBlock"


def test_to_pascal_case_converts_snake_case():
    """Standard snake_case to PascalCase conversion still works."""
    assert _to_pascal_case("sales_channel") == "SalesChannel"
    assert _to_pascal_case("farm_user") == "FarmUser"
    assert _to_pascal_case("field_block") == "FieldBlock"


def test_scaffold_stores_app_label_in_contract(tmp_path, monkeypatch):
    """scaffold_workbook_schema should store --models-app-label in each table's model_meta."""
    bundle = tmp_path / "bundle.json"
    bundle.write_text('{"provider": "coda", "doc_url": "...", "doc_id": "x", "source_id": "x", "tabs": [{"worksheet_title": "Test", "output_path": "t.csv", "required_headers": ["A"]}]}')
    table_profile = tmp_path / "profile.json"
    table_profile.write_text('{"summary": {"doc_name": "D", "table_id": "t", "table_name": "Test", "columns": [{"name": "A", "format_type": "text"}]}, "columns_raw": [], "rows_sample": []}')
    out = tmp_path / "contract.yaml"

    call_command(
        "scaffold_workbook_schema",
        bundle_config=str(bundle),
        table_profile=[str(table_profile)],
        models_app_label="testapp",
        out=str(out),
    )

    import yaml
    contract = yaml.safe_load(out.read_text())
    for table in contract.get("tables", []):
        meta = table.get("model_meta", {})
        assert meta.get("app_label") == "testapp", (
            f"Expected app_label='testapp', got {meta.get('app_label')!r}"
        )
