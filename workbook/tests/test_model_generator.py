"""Tests for ``workbook/codegen`` — contract loading, Python rendering, and model generation."""

from __future__ import annotations

import textwrap
from pathlib import Path

import yaml

from workbook.codegen.contract import (
    get_db_table_name,
    get_fields,
    get_model_meta,
    get_model_name,
    get_str_template,
    load_contract,
)
from workbook.codegen.model_generator import render_model, render_models_py
from workbook.codegen.python_render import (
    render_field,
    render_field_kwargs,
    render_import_block,
    render_meta,
    render_str_method,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _contract_v1_0() -> dict:
    """Return a minimal contract with two tables."""
    return {
        "source": {"provider": "google_sheets", "doc_url": None},
        "tables": [
            {
                "bundle_worksheet_title": "Crop Info",
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "bundle_output_path": "reference/crop_info.csv",
                "columns": [
                    {
                        "source_column": "Crop",
                        "suggested_field_name": "name",
                        "profiler_format_type": "text",
                        "has_formula": False,
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200, "unique": True},
                        "notes": [],
                    },
                    {
                        "source_column": "Type",
                        "suggested_field_name": "crop_type",
                        "profiler_format_type": "text",
                        "has_formula": False,
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 100, "blank": True, "default": ""},
                        "notes": [],
                    },
                ],
            },
            {
                "bundle_worksheet_title": "Crop Planner",
                "suggested_model_name": "planting",
                "model_name": "Planting",
                "bundle_output_path": "year_2025/crop_planner.csv",
                "columns": [
                    {
                        "source_column": "Crop",
                        "suggested_field_name": "crop",
                        "profiler_format_type": "lookup",
                        "has_formula": False,
                        "django_field_class": "models.ForeignKey",
                        "django_field_kwargs": {
                            "to": "TODO_TargetModel",
                            "on_delete": "models.PROTECT",
                            "null": True,
                            "blank": True,
                        },
                        "notes": ["relation_target_todo:Crop"],
                    },
                    {
                        "source_column": "Plant Date",
                        "suggested_field_name": "plant_date",
                        "profiler_format_type": "date",
                        "has_formula": False,
                        "django_field_class": "models.DateField",
                        "django_field_kwargs": {"null": True, "blank": True},
                        "notes": [],
                    },
                ],
            },
        ],
    }


def _contract_v1_1() -> dict:
    """Return a hardened v1.1 contract building on the v1.0 base."""
    c = _contract_v1_0()

    # Harden Crop
    c["tables"][0].update(
        {
            "model_meta": {
                "verbose_name": "Crop",
                "verbose_name_plural": "Crops",
                "ordering": ["name"],
            },
            "str_template": "{self.name}",
            "extra_fields": {
                "slug": {
                    "class": "models.SlugField",
                    "kwargs": {"max_length": 200, "unique": True, "blank": True},
                }
            },
        }
    )

    # Harden Planting
    c["tables"][1].update(
        {
            "model_meta": {
                "verbose_name": "Planting",
                "verbose_name_plural": "Plantings",
                "ordering": ["-plant_date"],
            },
            "str_template": "{self.crop} \u2014 {self.plant_date}",
            "fk_resolutions": {"crop": "Crop"},
            "field_overrides": {
                "crop": {"kwargs": {"null": False, "blank": False}},
            },
        }
    )

    return c


# ---------------------------------------------------------------------------
# render_field_kwargs
# ---------------------------------------------------------------------------


def test_render_field_kwargs_empty():
    assert render_field_kwargs({}) == ""


def test_render_field_kwargs_basic():
    result = render_field_kwargs({"max_length": 200, "unique": True})
    assert "max_length=200" in result
    assert "unique=True" in result


def test_render_field_kwargs_on_delete():
    result = render_field_kwargs({"on_delete": "models.PROTECT"})
    assert result == "on_delete=models.PROTECT"


def test_render_field_kwargs_to_identifier():
    """Without FK special handling, 'to' is rendered as a kwarg via repr()."""
    result = render_field_kwargs({"to": "Crop"})
    assert result == "to='Crop'"


def test_render_field_kwargs_to_non_identifier():
    result = render_field_kwargs({"to": "TODO_TargetModel"})
    assert result == "to='TODO_TargetModel'"


def test_render_field_kwargs_to_skips_on_delete_prefix():
    result = render_field_kwargs({"on_delete": "models.SET_NULL"})
    assert result == "on_delete=models.SET_NULL"


def test_render_field_kwargs_none():
    result = render_field_kwargs({"null": True, "blank": True})
    assert "null=True" in result
    assert "blank=True" in result


def test_render_field_kwargs_choices_accepts_bare_enum_name():
    """Bare enum class name renders as ``choices=EnumName.choices``."""
    result = render_field_kwargs({"choices": "EventType"}, enum_names={"EventType"})
    assert result == "choices=EventType.choices"


def test_render_field_kwargs_choices_accepts_enum_dot_choices():
    """``EventType.choices`` input is normalised to ``choices=EventType.choices``."""
    result = render_field_kwargs({"choices": "EventType.choices"}, enum_names={"EventType"})
    assert result == "choices=EventType.choices"


def test_render_field_kwargs_choices_unknown_enum_falls_back():
    """Unknown enum name is rendered as a quoted string, not a class reference."""
    result = render_field_kwargs({"choices": "UnknownType"}, enum_names={"EventType"})
    assert result == "choices='UnknownType'"


# ---------------------------------------------------------------------------
# render_field
# ---------------------------------------------------------------------------


def test_render_field_charfield():
    result = render_field("name", "models.CharField", {"max_length": 200, "unique": True})
    assert "name = models.CharField(max_length=200, unique=True)" in result


def test_render_field_foreign_key_resolved():
    result = render_field(
        "crop",
        "models.ForeignKey",
        {"to": "Crop", "on_delete": "models.PROTECT", "null": True, "blank": True},
    )
    assert "crop = models.ForeignKey(Crop, on_delete=models.PROTECT" in result
    assert "to=Crop" not in result



def test_render_field_foreign_key_todo():
    result = render_field(
        "crop",
        "models.ForeignKey",
        {"to": "TODO_TargetModel", "on_delete": "models.PROTECT"},
    )
    assert "TODO_TargetModel" in result


def test_render_field_no_kwargs():
    result = render_field("notes", "models.TextField", {})
    assert result.strip() == "notes = models.TextField()"


# ---------------------------------------------------------------------------
# render_import_block
# ---------------------------------------------------------------------------


def test_render_import_block_default():
    result = render_import_block("core")
    assert "from django.db import models" in result
    assert "# Generated by migration-workbench" in result
    assert "core" in result


def test_render_import_block_with_extras():
    result = render_import_block("farm", extra_imports=["from django.conf import settings"])
    assert "from django.conf import settings" in result


# ---------------------------------------------------------------------------
# render_str_method
# ---------------------------------------------------------------------------


def test_render_str_method_with_template():
    result = render_str_method("{self.name}")
    assert "def __str__(self):" in result
    assert 'return f"{self.name}"' in result


def test_render_str_method_none():
    assert render_str_method(None) == ""
    assert render_str_method("") == ""


# ---------------------------------------------------------------------------
# render_meta
# ---------------------------------------------------------------------------


def test_render_meta_empty():
    assert render_meta({}) == ""


def test_render_meta_basic():
    result = render_meta({"verbose_name": "Crop", "ordering": ["name"]})
    assert "class Meta:" in result
    assert 'verbose_name = "Crop"' in result
    assert 'ordering = ["name"]' in result


# ---------------------------------------------------------------------------
# contract.load_contract
# ---------------------------------------------------------------------------


def test_load_contract_v1_0(tmp_path):
    p = tmp_path / "contract.yaml"
    p.write_text(yaml.dump(_contract_v1_0()), encoding="utf-8")
    c = load_contract(str(p))
    assert len(c["tables"]) == 2


def test_load_contract_v1_1(tmp_path):
    p = tmp_path / "contract.yaml"
    p.write_text(yaml.dump(_contract_v1_1()), encoding="utf-8")
    c = load_contract(str(p))
    assert c["tables"][0].get("str_template") == "{self.name}"


# ---------------------------------------------------------------------------
# contract accessors
# ---------------------------------------------------------------------------


def test_get_model_name():
    table = {"suggested_model_name": "crop_block", "model_name": "CropBlock"}
    assert get_model_name(table) == "CropBlock"

    table2 = {"suggested_model_name": "sales_channel", "model_name": "SalesChannel"}
    assert get_model_name(table2) == "SalesChannel"


def test_get_db_table_name_explicit():
    t = {"suggested_model_name": "crop", "model_meta": {"db_table": "my_crop"}}
    assert get_db_table_name(t, "core") == "my_crop"


def test_get_db_table_name_fallback():
    assert get_db_table_name({"suggested_model_name": "crop"}, "farm") == "farm_crop"


def test_get_model_meta():
    t = {"model_meta": {"verbose_name": "Crop", "ordering": ["name"]}}
    assert get_model_meta(t) == {"verbose_name": "Crop", "ordering": ["name"]}


def test_get_model_meta_empty():
    assert get_model_meta({}) == {}


def test_get_str_template():
    assert get_str_template({"str_template": "{self.name}"}) == "{self.name}"
    assert get_str_template({}) is None
    assert get_str_template({"str_template": ""}) is None


# ---------------------------------------------------------------------------
# contract.get_fields
# ---------------------------------------------------------------------------


def test_get_fields_v1_0():
    """v1.0 fields pass through with no overrides."""
    t = _contract_v1_0()["tables"][0]
    fields = get_fields(t)
    assert len(fields) == 2
    assert fields[0]["name"] == "name"
    assert fields[0]["class"] == "models.CharField"


def test_get_fields_fk_resolved():
    """FK with resolution gets the target model name."""
    t = _contract_v1_1()["tables"][1]
    fields = get_fields(t)
    crop_field = next(f for f in fields if f["name"] == "crop")
    assert crop_field["kwargs"]["to"] == "Crop"


def test_get_fields_extra_fields():
    """Extra fields are appended."""
    t = _contract_v1_1()["tables"][0]
    fields = get_fields(t)
    names = [f["name"] for f in fields]
    assert "slug" in names


def test_get_fields_preserves_extra_fields_order():
    table = {
        "suggested_model_name": "crop",
        "model_name": "Crop",
        "columns": [
            {
                "suggested_field_name": "name",
                "django_field_class": "models.CharField",
                "django_field_kwargs": {"max_length": 200},
            }
        ],
        "extra_fields": {
            "season_label": {
                "class": "models.CharField",
                "kwargs": {"max_length": 50, "blank": True, "default": ""},
            },
            "farm_notes": {
                "class": "models.TextField",
                "kwargs": {"blank": True, "default": ""},
            },
            "audit_hash": {
                "class": "models.CharField",
                "kwargs": {"max_length": 64, "blank": True, "default": ""},
            },
        },
    }

    fields = get_fields(table)
    field_names = [field["name"] for field in fields]
    assert field_names == [
        "name",
        "season_label",
        "farm_notes",
        "audit_hash",
    ]


def test_get_fields_override_class():
    """Field overrides replace the auto-inferred class."""
    t = _contract_v1_1()["tables"][1]
    overrides = {"crop": {"kwargs": {"null": False}}}
    t["field_overrides"] = overrides
    fields = get_fields(t)
    crop_field = next(f for f in fields if f["name"] == "crop")
    assert crop_field["kwargs"]["null"] is False


# ---------------------------------------------------------------------------
# render_model
# ---------------------------------------------------------------------------


def test_render_model_v1_0():
    """A v1.0 table produces a valid class with inferred fields."""
    t = _contract_v1_0()["tables"][0]
    source = render_model(t, app_label="core")
    assert "class Crop(models.Model):" in source
    assert "name = models.CharField(max_length=200, unique=True)" in source
    assert "crop_type" in source
    # v1.0 gets db_table in Meta but no extras
    assert "class Meta:" in source
    assert "db_table" in source
    assert "def __str__" not in source


def test_render_model_v1_1():
    """A v1.1 table includes Meta, __str__, extra fields, resolved FK."""
    t = _contract_v1_1()["tables"][0]
    source = render_model(t, app_label="core")
    assert "class Crop(models.Model):" in source
    assert "class Meta:" in source
    assert 'verbose_name = "Crop"' in source
    assert "def __str__(self):" in source
    assert "slug = models.SlugField" in source


def test_render_model_fk_resolved():
    t = _contract_v1_1()["tables"][1]
    source = render_model(t, app_label="core")
    assert "class Planting(models.Model):" in source
    assert "crop = models.ForeignKey(Crop," in source
    assert "on_delete=models.PROTECT" in source


def test_render_model_empty_fields():
    """A table with no columns still produces a valid class."""
    t = {"suggested_model_name": "empty", "model_name": "Empty", "columns": []}
    source = render_model(t, app_label="core")
    assert "class Empty(models.Model):" in source
    assert "pass" in source


# ---------------------------------------------------------------------------
# render_models_py — full file
# ---------------------------------------------------------------------------


def test_render_models_py_v1_0():
    contract = _contract_v1_0()
    source = render_models_py(contract, app_label="core")
    assert "from django.db import models" in source
    assert "class Crop(models.Model):" in source
    assert "class Planting(models.Model):" in source
    assert source.endswith("\n")


def test_render_models_py_v1_1():
    contract = _contract_v1_1()
    source = render_models_py(contract, app_label="farm")
    assert "class Planting(models.Model):" in source
    # FK resolved
    assert "ForeignKey(Crop," in source


# ---------------------------------------------------------------------------
# Compilation check — rendered Python is syntactically valid
# ---------------------------------------------------------------------------


def _check_compiles(source: str) -> None:
    try:
        compile(source, "<test>", "exec")
    except SyntaxError as exc:
        raise AssertionError(f"generated Python failed to compile:\n{source}") from exc


def test_generated_python_compiles_v1_0():
    _check_compiles(render_models_py(_contract_v1_0()))


def test_generated_python_compiles_v1_1():
    _check_compiles(render_models_py(_contract_v1_1()))


def test_generated_python_compiles_empty():
    _check_compiles(render_models_py({"source": {}, "tables": []}))


def test_generated_python_compiles_single_table_no_fields():
    contract = {
        "source": {},
        "tables": [{"suggested_model_name": "widget", "model_name": "Widget", "columns": []}],
    }
    _check_compiles(render_models_py(contract))


# ---------------------------------------------------------------------------
# Management command integration
# ---------------------------------------------------------------------------


def test_command_output(tmp_path, monkeypatch):
    """End-to-end: write contract, run command, verify output compiles."""
    from django.core.management import call_command

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(_contract_v1_1()), encoding="utf-8")

    out_path = tmp_path / "models.py"

    call_command(
        "generate_models",
        contract=str(contract_path),
        out=str(out_path),
        app_label="core",
        force=True,
    )

    assert out_path.exists()
    source = out_path.read_text(encoding="utf-8")
    assert "class Crop(models.Model):" in source
    assert "class Planting(models.Model):" in source
    _check_compiles(source)


def test_command_rejects_missing_contract(tmp_path):
    from django.core.management import call_command, CommandError

    import pytest

    with pytest.raises(CommandError, match="contract not found"):
        call_command(
            "generate_models",
            contract=str(tmp_path / "nope.yaml"),
            out=str(tmp_path / "models.py"),
            force=True,
        )


def test_command_warns_on_existing_output(tmp_path, capsys):
    from django.core.management import call_command

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(_contract_v1_0()), encoding="utf-8")

    out_path = tmp_path / "models.py"
    out_path.write_text("# existing")

    import sys

    with pytest.raises(SystemExit):
        call_command(
            "generate_models",
            contract=str(contract_path),
            out=str(out_path),
            app_label="core",
        )


# Need pytest marker for the SystemExit test
import pytest
