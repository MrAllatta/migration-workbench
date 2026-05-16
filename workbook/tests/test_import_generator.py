"""Tests for ``workbook/codegen/import_generator`` and ``generate_import`` command."""

from __future__ import annotations

import importlib.util
import sys
from io import StringIO
from pathlib import Path

import yaml

from importer.base import BaseImportCommand
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


def _contract_no_column_map() -> dict:
    """Contract with import_config but no column_map (to test auto-derivation)."""
    return {
        "version": "1.1",
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "bundle_worksheet_title": "Crop Info",
                "suggested_model_name": "crop",
                "bundle_output_path": "reference/crop_info.csv",
                "columns": [
                    {
                        "source_column": "Crop",
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200, "unique": True},
                    },
                    {
                        "source_column": "Type",
                        "suggested_field_name": "crop_type",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 100, "blank": True, "default": ""},
                    },
                ],
                "import_config": {
                    "tier": 1,
                    "bundle_path": "reference/crop_info.csv",
                    "unique_on": ["name"],
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
    assert "class GeneratedImportCore(BaseImportCommand):" in source
    assert "class Command(GeneratedImportCore):" in source


def test_render_has_run_import_pipeline():
    source = render_import_py(_contract_with_imports(), app_label="core")
    assert "def _run_import_pipeline(self):" in source


def test_render_has_tier_calls():
    """Tiers are emitted in order (1 before 2)."""
    source = render_import_py(_contract_with_imports(), app_label="core")
    crop_idx = source.index("TIER 1: Crops")
    planting_idx = source.index("TIER 2: Plantings")
    assert crop_idx < planting_idx


def test_render_all_tables_get_tier_call():
    """Every table with import_config gets its own tier() call, even same tier."""
    contract = {
        "version": "1.1",
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "bundle_worksheet_title": "Crop Info",
                "suggested_model_name": "crop",
                "bundle_output_path": "crop_info.csv",
                "columns": [
                    {"suggested_field_name": "name", "django_field_class": "models.CharField", "django_field_kwargs": {"max_length": 200, "unique": True}},
                ],
                "import_config": {"tier": 1, "bundle_path": "crop_info.csv", "column_map": {"name": "Crop"}, "unique_on": ["name"]},
            },
            {
                "bundle_worksheet_title": "Crop Planner",
                "suggested_model_name": "planting",
                "bundle_output_path": "crop_planner.csv",
                "columns": [
                    {"suggested_field_name": "name", "django_field_class": "models.CharField", "django_field_kwargs": {"max_length": 200, "unique": True}},
                ],
                "import_config": {"tier": 1, "bundle_path": "crop_planner.csv", "column_map": {"name": "Name"}, "unique_on": ["name"]},
            },
        ],
    }
    source = render_import_py(contract, app_label="core")
    # Both tables are tier 1 — without fix, only 1 tier() call because seen_tiers dedup
    assert source.count("self.tier(") == 2


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


def test_column_map_auto_derived_when_absent():
    """When no column_map in import_config, auto-derive from columns array."""
    source = render_import_py(_contract_no_column_map(), app_label="core")
    assert "'name': 'Crop'" in source
    assert "'crop_type': 'Type'" in source
    assert '"column_map"' in source


def test_required_headers_auto_derived_from_unique_on():
    """When required_headers absent, derive from unique_on via column_map."""
    contract = _contract_no_column_map()
    source = render_import_py(contract, app_label="core")
    # unique_on: ['name'] -> column_map: {'name': 'Crop'} -> required_headers: ['Crop']
    # Should not be empty:  "required_headers": [],
    assert '"required_headers": []' not in source
    assert '"required_headers": [\'Crop\']' in source


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
    assert "class GeneratedImportCore(BaseImportCommand):" in source
    assert "class Command(GeneratedImportCore):" in source
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
    assert "class GeneratedImportCore(BaseImportCommand):" in source
    assert "class Command(GeneratedImportCore):" in source
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


# ---------------------------------------------------------------------------
# Execution tests  (dynamically import and run the generated Command)
# ---------------------------------------------------------------------------


def _contract_examplecrop() -> dict:
    """Contract matching the real ``ExampleCrop`` model from the examples app."""
    return {
        "version": "1.1",
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "example_crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200, "unique": True},
                    },
                    {
                        "suggested_field_name": "crop_type",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 100},
                    },
                ],
                "import_config": {
                    "tier": 1,
                    "bundle_path": "crop_info.csv",
                    "column_map": {"name": "Crop", "crop_type": "Type"},
                    "unique_on": ["name"],
                },
            },
        ],
    }


def _contract_exampleblock_with_fk() -> dict:
    """Contract for ExampleBlock with FK lookup to ExampleCrop."""
    return {
        "version": "1.1",
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "example_crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200, "unique": True},
                    },
                    {
                        "suggested_field_name": "crop_type",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 100},
                    },
                ],
                "import_config": {
                    "tier": 1,
                    "bundle_path": "crop_info.csv",
                    "column_map": {"name": "Crop", "crop_type": "Type"},
                    "unique_on": ["name"],
                },
            },
            {
                "suggested_model_name": "example_block",
                "columns": [
                    {
                        "suggested_field_name": "crop",
                        "django_field_class": "models.ForeignKey",
                        "django_field_kwargs": {
                            "to": "ExampleCrop",
                            "on_delete": "models.PROTECT",
                        },
                    },
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200, "unique": True},
                    },
                    {
                        "suggested_field_name": "block_type",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                ],
                "import_config": {
                    "tier": 2,
                    "bundle_path": "blocks.csv",
                    "column_map": {
                        "crop": "Crop",
                        "name": "Block",
                        "block_type": "Block Type",
                    },
                    "unique_on": ["name"],
                    "fk_lookup": {
                        "crop": {"model": "ExampleCrop", "on": "name"},
                    },
                },
            },
        ],
    }


def _contract_examplecrop_required() -> dict:
    """Contract for ExampleCrop with a required column check."""
    return {
        "version": "1.1",
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "example_crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200, "unique": True},
                    },
                    {
                        "suggested_field_name": "crop_type",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 100},
                    },
                ],
                "import_config": {
                    "tier": 1,
                    "bundle_path": "crop_info.csv",
                    "column_map": {"name": "Crop", "crop_type": "Type"},
                    "unique_on": ["name"],
                    "required_source_columns": ["name"],
                },
            },
        ],
    }


def _generate_and_import_command(
    contract: dict,
    csv_files: dict[str, str],
    tmp_path: Path,
    app_label: str = "examples",
) -> tuple[type[BaseImportCommand], str]:
    """Write contract + CSVs, generate import, dynamically import Command class.

    Returns:
        ``(Command_class, data_dir_string)``.
    """
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(contract), encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for rel_path, content in csv_files.items():
        path = data_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    out_path = tmp_path / "import_data.py"
    from django.core.management import call_command

    call_command(
        "generate_import",
        contract=str(contract_path),
        out=str(out_path),
        app_label=app_label,
        force=True,
    )

    assert out_path.exists()
    source = out_path.read_text(encoding="utf-8")

    # Check source compiles
    _check_compiles(source)

    # Dynamic import
    mod_name = f"_test_import_{tmp_path.name}"
    spec = importlib.util.spec_from_file_location(mod_name, str(out_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)

    assert hasattr(mod, "Command")
    assert issubclass(mod.Command, BaseImportCommand)

    return mod.Command, str(data_dir)


def test_generated_import_executes_validate_only(tmp_path, db):
    """Generated command runs with --validate-only and reports processed counts."""
    csv_files = {
        "crop_info.csv": "Crop,Type\nKale,Greens\nTomato,Fruit\nCarrot,Root\n",
    }
    CommandCls, data_dir = _generate_and_import_command(
        _contract_examplecrop(), csv_files, tmp_path
    )

    cmd = CommandCls()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()
    cmd.handle(
        data_dir=data_dir,
        dry_run=False,
        validate_only=True,
        preflight=False,
        non_atomic_apply=False,
        summary_json=None,
        verbose=False,
    )

    # validate-only: write_disabled=False, rows are actually created then rolled back.
    # The stats track "created" (not "processed") in this mode.
    assert cmd.stats["ExampleCrop"]["created"] > 0


def test_generated_import_handles_fk_resolution(tmp_path, db):
    """Generated command with FK resolution runs without error in dry-run mode."""
    csv_files = {
        "crop_info.csv": "Crop,Type\nKale,Greens\nTomato,Fruit\n",
        "blocks.csv": "Block,Block Type,Crop\nField A,field,Kale\nField B,field,Tomato\n",
    }
    CommandCls, data_dir = _generate_and_import_command(
        _contract_exampleblock_with_fk(), csv_files, tmp_path
    )

    cmd = CommandCls()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()
    cmd.handle(
        data_dir=data_dir,
        dry_run=True,
        validate_only=False,
        preflight=False,
        non_atomic_apply=False,
        summary_json=None,
        verbose=False,
    )

    # dry-run: write_disabled=True, rows are parsed but not written.
    # The stats track "processed" in this mode.
    assert cmd.stats["ExampleCrop"]["processed"] > 0
    assert cmd.stats["ExampleBlock"]["processed"] > 0


def test_generated_import_reports_missing_required(tmp_path, db):
    """Generated command records errors when required columns are blank."""
    csv_files = {
        "crop_info.csv": "Crop,Type\nKale,Greens\n,Tomato\nCarrot,Root\n",
    }
    CommandCls, data_dir = _generate_and_import_command(
        _contract_examplecrop_required(), csv_files, tmp_path
    )

    cmd = CommandCls()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()
    cmd.handle(
        data_dir=data_dir,
        dry_run=True,
        validate_only=False,
        preflight=False,
        non_atomic_apply=False,
        summary_json=None,
        verbose=False,
    )

    errors = [e for e in cmd.row_errors if e["code"] == "missing_required"]
    assert len(errors) == 1
    assert errors[0]["model"] == "ExampleCrop"


# ---------------------------------------------------------------------------
# Multi-source column_map and field_transforms
# ---------------------------------------------------------------------------


def _contract_multi_source() -> dict:
    """Return a v1.1 contract with a multi-source column_map entry."""
    return {
        "version": "1.1",
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "person",
                "columns": [
                    {
                        "suggested_field_name": "full_name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "age",
                        "django_field_class": "models.IntegerField",
                        "django_field_kwargs": {"null": True, "blank": True},
                    },
                ],
                "import_config": {
                    "tier": 1,
                    "bundle_path": "people.csv",
                    "column_map": {
                        "full_name": ["First Name", "Last Name"],
                        "age": "Age",
                    },
                    "field_transforms": {
                        "full_name": "' '.join(p for p in parts if p)",
                    },
                    "unique_on": ["full_name"],
                },
            },
        ],
    }


def test_multi_source_defaults_dict():
    """Multi-source fields get parts collection + transform in defaults."""
    from workbook.codegen.import_generator import render_import_py

    source = render_import_py(_contract_multi_source(), app_label="core")
    assert "full_name_parts" in source
    assert "row.get('First Name'" in source
    assert "row.get('Last Name'" in source
    assert "lambda parts" in source
    _check_compiles(source)


def test_multi_source_default_join():
    """Multi-source without explicit transform uses space join."""
    contract = _contract_multi_source()
    del contract["tables"][0]["import_config"]["field_transforms"]
    from workbook.codegen.import_generator import render_import_py

    source = render_import_py(contract, app_label="core")
    assert "full_name_parts" in source
    assert '" ".join' in source
    _check_compiles(source)


def test_multi_source_tab_config_excludes_list_entries():
    """Multi-source entries are omitted from tab_config column_map."""
    from workbook.codegen.import_generator import _render_tab_config

    cfg = _contract_multi_source()["tables"][0]["import_config"]
    rendered = _render_tab_config(cfg, indent=0)
    assert "'full_name'" not in rendered
    assert "'age'" in rendered


def test_multi_source_unique_assignments():
    """Unique multi-source fields get parts + transform in unique assignments."""
    contract = _contract_multi_source()
    from workbook.codegen.contract import get_fields, get_import_config
    from workbook.codegen.import_generator import _render_unique_assignments

    fields = get_fields(contract["tables"][0])
    cfg = get_import_config(contract["tables"][0])
    rendered = _render_unique_assignments(fields, cfg, indent=8)
    assert "full_name_parts" in rendered
    assert "full_name = (lambda parts" in rendered or 'full_name = " ".join' in rendered


# ---------------------------------------------------------------------------
# --diff flag tests
# ---------------------------------------------------------------------------


def test_import_generator_diff_shows_changes(tmp_path):
    """--diff shows unified diff when output differs from current file."""
    from workbook.management.commands.generate_import import Command
    from io import StringIO

    contract = _contract_with_imports()
    contract_path = tmp_path / "contract.yaml"
    with open(contract_path, "w") as f:
        yaml.dump(contract, f, sort_keys=False)

    out_path = tmp_path / "imports.py"
    out_path.write_text("# old content\n", encoding="utf-8")

    cmd = Command(stdout=StringIO())
    cmd.handle(
        contract=str(contract_path),
        out=str(out_path),
        app_label="core",
        force=False,
        diff=True,
    )
    output = cmd.stdout.getvalue()
    assert "---" in output or "+++" in output, "Expected diff output with change markers"


def test_import_generator_diff_no_changes(tmp_path):
    """--diff returns 'no changes' when output matches current file."""
    from workbook.management.commands.generate_import import Command
    from workbook.codegen.import_generator import render_import_py
    from io import StringIO

    contract = _contract_with_imports()
    contract_path = tmp_path / "contract.yaml"
    with open(contract_path, "w") as f:
        yaml.dump(contract, f, sort_keys=False)

    out_path = tmp_path / "imports.py"
    source = render_import_py(contract, app_label="core")
    out_path.write_text(source, encoding="utf-8")

    cmd = Command(stdout=StringIO())
    cmd.handle(
        contract=str(contract_path),
        out=str(out_path),
        app_label="core",
        force=False,
        diff=True,
    )
    assert "no changes" in cmd.stdout.getvalue()


def test_import_generator_diff_no_existing(tmp_path):
    """--diff prints warning when output file doesn't exist yet."""
    from workbook.management.commands.generate_import import Command
    from io import StringIO

    contract = _contract_with_imports()
    contract_path = tmp_path / "contract.yaml"
    with open(contract_path, "w") as f:
        yaml.dump(contract, f, sort_keys=False)

    out_path = tmp_path / "nonexistent.py"

    cmd = Command(stdout=StringIO())
    cmd.handle(
        contract=str(contract_path),
        out=str(out_path),
        app_label="core",
        force=False,
        diff=True,
    )
    assert "no existing file" in cmd.stdout.getvalue()
