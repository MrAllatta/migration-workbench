"""Tests for the scaffold_workbook_schema management command."""

from pathlib import Path
from django.core.management import call_command

from workbook.management.commands.scaffold_workbook_schema import (
    _to_pascal_case,
    _flag_fk_columns,
    _flag_computed_fields,
    _suggest_tab_merges,
)


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


def test_flag_fk_columns_detects_id_suffix():
    """Columns ending in _id get flagged with suggested_fk_target."""
    columns = [
        {"suggested_field_name": "season_id", "source_column": "Season ID"},
        {"suggested_field_name": "name", "source_column": "Name"},
    ]
    _flag_fk_columns(columns)
    assert columns[0].get("suggested_fk_target") == "Season"
    assert columns[0].get("review_note") is not None
    assert "suggested_fk_target" not in columns[1]


def test_flag_fk_columns_detects_entity_names():
    """Columns named after known entities (channel, season, etc.) get flagged."""
    columns = [
        {"suggested_field_name": "channel", "source_column": "Channel"},
        {"suggested_field_name": "season", "source_column": "Season"},
    ]
    _flag_fk_columns(columns)
    assert columns[0].get("suggested_fk_target") == "Channel"
    assert columns[1].get("suggested_fk_target") == "Season"


def test_flag_computed_fields_moves_formula_columns():
    """Columns with formula_pattern row_formula or expansion_formula move to computed_fields."""
    table = {
        "suggested_model_name": "CropPlan",
        "columns": [
            {"suggested_field_name": "name", "formula_pattern": "raw"},
            {"suggested_field_name": "yield_est", "formula_pattern": "row_formula"},
            {"suggested_field_name": "total", "formula_pattern": "expansion_formula"},
        ],
    }
    _flag_computed_fields(table)
    remaining = {c["suggested_field_name"] for c in table["columns"]}
    assert "name" in remaining
    assert "yield_est" not in remaining
    assert "total" not in remaining
    computed = table.get("computed_fields", {})
    assert "yield_est" in computed
    assert "total" in computed
    assert "return_type" in computed["yield_est"]
    assert "expression" in computed["yield_est"]


def test_flag_computed_fields_skips_missing_pattern():
    """Columns without a formula_pattern field are left as-is."""
    table = {
        "columns": [
            {"suggested_field_name": "name"},
        ],
    }
    _flag_computed_fields(table)
    assert len(table["columns"]) == 1


def test_suggest_tab_merges_groups_by_shared_headers():
    """Tabs sharing 2+ column headers get merge_candidates."""
    tabs = {
        "Crop Planner": {"columns": ["Crop", "Week", "Block", "Variety"]},
        "Crop Plan 501": {"columns": ["Crop", "Week", "Block", "Yield"]},
        "Harvest": {"columns": ["Date", "Weight", "Block"]},
    }
    result = _suggest_tab_merges(tabs)
    assert any(
        r["tabs"] == {"Crop Planner", "Crop Plan 501"}
        for r in result
    )
    assert not any("Harvest" in r["tabs"] for r in result)
