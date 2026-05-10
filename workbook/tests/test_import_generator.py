"""Tests for ``workbook/codegen/import_generator`` and ``generate_import`` command."""

from __future__ import annotations

from pathlib import Path

import yaml

from workbook.codegen.contract import get_import_config, load_contract
from workbook.codegen.import_generator import render_import_py


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _contract_with_imports() -> dict:
    """Return a v1.1 contract with two models that have import_config."""
    return {
        "version": "1.1",
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "bundle_worksheet_title": "Crop Info",
                "suggested_model_name": "crop",
                "bundle_output_path": "reference/crop_info.csv",
                "model_meta": {"verbose_name": "Crop"},
                "str_template": "{self.name}",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200, "unique": True},
                    },
                    {
                        "suggested_field_name": "crop_type",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {
                            "max_length": 100, "blank": True, "default": ""
                        },
                    },
                ],
                "import_config": {
                    "tier": 1,
                    "bundle_path": "reference/crop_info.csv",
                    "required_headers": ["Crop", "Type"],
                    "aliases": {"Type": ["Crop Type", "Variety"]},
                    "column_map": {"name": "Crop", "crop_type": "Type"},
                    "default_values": {"crop_type": ""},
                    "unique_on": ["name"],
                    "required_source_columns": ["name"],
                },
            },
            {
                "bundle_worksheet_title": "Crop Planner",
                "suggested_model_name": "planting",
                "bundle_output_path": "year_2025/crop_planner.csv",
                "model_meta": {"verbose_name": "Planting"},
                "fk_resolutions": {"crop": "Crop"},
                "columns": [
                    {
                        "suggested_field_name": "crop",
                        "django_field_class": "models.ForeignKey",
                        "django_field_kwargs": {
                            "to": "TODO_TargetModel",
                            "on_delete": "models.PROTECT",
                            "null": True,
                            "blank": True,
                        },
                    },
                    {
                        "suggested_field_name": "plant_date",
                        "django_field_class": "models.DateField",
                        "django_field_kwargs": {"null": True, "blank": True},
                    },
                    {
                        "suggested_field_name": "beds_used",
                        "django_field_class": "models.DecimalField",
                        "django_field_kwargs": {
                            "max_digits": 6, "decimal_places": 1,
                            "null": True, "blank": True,
                        },
                    },
                ],
                "import_config": {
                    "tier": 2,
                    "bundle_path": "year_2025/crop_planner.csv",
                    "required_headers": ["Crop", "Plant Date", "Beds Used"],
                    "column_map": {
                        "crop": "Crop",
                        "plant_date": "Plant Date",
                        "beds_used": "Beds Used",
                    },
                    "unique_on": ["crop", "plant_date"],
                    "required_source_columns": ["crop"],
                    "fk_lookup": {
                        "crop": {"model": "Crop", "on": "name"},
                    },
                },
            },
        ],
    }


def _contract_no_imports() -> dict:
    """Return a v1.1 contract with no import_config blocks."""
    return {
        "version": "1.1",
        "source": {},
        "tables": [
            {
                "bundle_worksheet_title": "Crop Info",
                "suggested_model_name": "crop",
                "columns": [
                    {"suggested_field_name": "name", "django_field_class": "models.CharField", "django_field_kwargs": {}}
                ],
            }
        ],
    }


def _check_compiles(source: str) -> None:
    """Assert that *source* is syntactically valid Python."""
    try:
        compile(source, "<test>", "exec")
    except SyntaxError as exc:
        raise AssertionError(f"generated Python failed to compile:\n{source}") from exc


# ---------------------------------------------------------------------------
# contract.get_import_config
# ---------------------------------------------------------------------------


def test_get_import_config_present():
    tables = _contract_with_imports()["tables"]
    cfg = get_import_config(tables[0])
    assert cfg is not None
    assert cfg["tier"] == 1
    assert cfg["bundle_path"] == "reference/crop_info.csv"


def test_get_import_config_absent():
    tables = _contract_no_imports()["tables"]
    assert get_import_config(tables[0]) is None


def test_get_import_config_from_empty_table():
    assert get_import_config({}) is None


# ---------------------------------------------------------------------------
# render_import_py — structure and imports
# ---------------------------------------------------------------------------


def test_render_has_imports():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert "from importer.base import BaseImportCommand" in source
    assert "from core.models import Crop, Planting" in source


def test_render_has_command_class():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert "class Command(BaseImportCommand):" in source


def test_render_has_run_import_pipeline():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert "def _run_import_pipeline(self):" in source


def test_render_has_tier_calls():
    """Tiers are emitted in order (1 before 2)."""
    source = render_import_py(_contract_with_imports(), app_label="core")
    crop_idx = source.index("TIER 1: Crops")
    planting_idx = source.index("TIER 2: Plantings")
    assert crop_idx < planting_idx


def test_render_has_import_methods():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert "def _import_crop(self):" in source
    assert "def _import_planting(self):" in source


# ---------------------------------------------------------------------------
# render_import_py — tab_config rendering
# ---------------------------------------------------------------------------


def test_tab_config_has_required_headers():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert '"required_headers"' in source
    assert "'Crop'" in source
    assert "'Type'" in source


def test_tab_config_has_aliases():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert '"aliases"' in source


def test_tab_config_has_column_map():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert '"column_map"' in source
    assert "'name': 'Crop'" in source


def test_tab_config_has_default_values():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert '"default_values"' in source
    assert 'crop_type' in source


# ---------------------------------------------------------------------------
# render_import_py — required field checks
# ---------------------------------------------------------------------------


def test_required_field_check_generated():
    """Fields in required_source_columns get missing_required guard."""
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert "record_missing_required" in source
    assert "name_val" in source


def test_fk_required_check_generated():
    """FK fields with fk_lookup get missing_required + stale_fk guards."""
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert "record_missing_required('Planting'" in source
    assert "_resolve_fk_by_text(Crop, 'name'" in source
    assert "record_stale_fk('Planting'" in source


# ---------------------------------------------------------------------------
# render_import_py — field assignments
# ---------------------------------------------------------------------------


def test_date_field_uses_parse_date():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert "self._parse_date" in source


def test_decimal_field_uses_dec():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert "self._dec(row.get(" in source


def test_char_field_uses_strip():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert '.strip()' in source


# ---------------------------------------------------------------------------
# render_import_py — write_disabled guard and update_or_create
# ---------------------------------------------------------------------------


def test_write_disabled_guard():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert "if self.write_disabled:" in source
    assert "self.stats['Crop'][\"processed\"]" in source


def test_update_or_create_with_unique():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert ".objects.update_or_create(" in source


# ---------------------------------------------------------------------------
# render_import_py — no import config
# ---------------------------------------------------------------------------


def test_no_import_config_still_renders():
    """A contract with no import_config blocks still produces a valid command."""
    source = render_import_py(_contract_no_imports(), app_label="core")
    assert "class Command(BaseImportCommand):" in source
    _check_compiles(source)


# ---------------------------------------------------------------------------
# Compilation checks
# ---------------------------------------------------------------------------


def test_generated_import_compiles():
    _check_compiles(render_import_py(_contract_with_imports(), app_label="core"))


def test_generated_import_compiles_empty():
    _check_compiles(
        render_import_py(
            {"version": "1.0", "source": {}, "tables": []},
            app_label="core",
        )
    )


# ---------------------------------------------------------------------------
# Management command integration
# ---------------------------------------------------------------------------


def test_command_output(tmp_path):
    """End-to-end: write contract, run command, verify output compiles."""
    from django.core.management import call_command

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(_contract_with_imports()), encoding="utf-8")

    out_path = tmp_path / "import_data.py"

    call_command(
        "generate_import",
        contract=str(contract_path),
        out=str(out_path),
        app_label="core",
        force=True,
    )

    assert out_path.exists()
    source = out_path.read_text(encoding="utf-8")
    assert "class Command(BaseImportCommand):" in source
    assert "_import_crop" in source
    assert "_import_planting" in source
    _check_compiles(source)


def test_command_rejects_missing_contract(tmp_path):
    from django.core.management import call_command, CommandError

    import pytest

    with pytest.raises(CommandError, match="contract not found"):
        call_command(
            "generate_import",
            contract=str(tmp_path / "nope.yaml"),
            out=str(tmp_path / "import_data.py"),
            force=True,
        )


def test_command_warns_on_existing_output(tmp_path):
    from django.core.management import call_command

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(_contract_with_imports()), encoding="utf-8")
    out_path = tmp_path / "import_data.py"
    out_path.write_text("# existing")

    import pytest

    with pytest.raises(SystemExit):
        call_command(
            "generate_import",
            contract=str(contract_path),
            out=str(out_path),
            app_label="core",
            force=False,
        )
