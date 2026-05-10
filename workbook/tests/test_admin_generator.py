"""Tests for ``workbook/codegen/admin_generator`` and ``generate_admin`` command."""

from __future__ import annotations

from pathlib import Path

import yaml

from workbook.codegen.admin_generator import render_admin_py
from workbook.codegen.manifest import find_view_for_entity, load_manifest


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _contract() -> dict:
    """Return a v1.1 contract with Crop + Planting (Planting FK to Crop)."""
    return {
        "version": "1.1",
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "bundle_worksheet_title": "Crop Info",
                "suggested_model_name": "crop",
                "bundle_output_path": "reference/crop_info.csv",
                "model_meta": {"verbose_name": "Crop", "ordering": ["name"]},
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
            },
            {
                "bundle_worksheet_title": "Crop Planner",
                "suggested_model_name": "planting",
                "bundle_output_path": "year_2025/crop_planner.csv",
                "model_meta": {
                    "verbose_name": "Planting", "ordering": ["-plant_date"]
                },
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
            },
        ],
    }


def _manifest() -> dict:
    """Return a view manifest with Crop + Planting entities."""
    return {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop_info",
                "entity": "crop",
                "source_tab": "Crop Info",
                "type": "list",
                "editable_fields": ["name", "crop_type"],
                "computed_fields": [],
                "filterable_by": ["crop_type"],
                "status_field": None,
                "notes": None,
            },
            {
                "name": "crop_planner",
                "entity": "planting",
                "source_tab": "Crop Planner",
                "type": "list",
                "editable_fields": ["crop", "plant_date", "beds_used"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": None,
                "notes": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Crop Info", "Crop Planner"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }


def _check_compiles(source: str) -> None:
    """Assert that *source* is syntactically valid Python."""
    try:
        compile(source, "<test>", "exec")
    except SyntaxError as exc:
        raise AssertionError(f"generated Python failed to compile:\n{source}") from exc


# ---------------------------------------------------------------------------
# manifest.load_manifest
# ---------------------------------------------------------------------------


def test_load_manifest(tmp_path):
    p = tmp_path / "manifest.yaml"
    p.write_text(yaml.dump(_manifest()), encoding="utf-8")
    m = load_manifest(str(p))
    assert len(m["views"]) == 2


def test_load_manifest_bad_version(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.dump({"version": "v0", "views": []}), encoding="utf-8")
    import pytest

    with pytest.raises(ValueError, match="unsupported.*version"):
        load_manifest(str(p))


# ---------------------------------------------------------------------------
# manifest.find_view_for_entity
# ---------------------------------------------------------------------------


def test_find_view_for_entity_found():
    manifest = _manifest()
    view = find_view_for_entity(manifest, "crop")
    assert view is not None
    assert view["name"] == "crop_info"


def test_find_view_for_entity_not_found():
    assert find_view_for_entity(_manifest(), "nonexistent") is None


# ---------------------------------------------------------------------------
# render_admin_py — inline detection
# ---------------------------------------------------------------------------


def test_inline_detected_for_fk_target():
    """Planting has FK to Crop, so Crop gets PlantingInline."""
    source = render_admin_py(_contract(), _manifest(), app_label="core")
    assert "class PlantingInline(admin.TabularInline):" in source
    assert "model = Planting" in source
    assert "class CropAdmin(admin.ModelAdmin):" in source
    assert "inlines = [PlantingInline]" in source


def test_no_inline_when_no_reverse_fk():
    """A model with no FK targets gets no inlines."""
    c = _contract()
    c["tables"] = [c["tables"][0]]  # Crop only, no Planting
    m = _manifest()
    m["views"] = [m["views"][0]]
    source = render_admin_py(c, m, app_label="core")
    assert "Inline" not in source
    assert "inlines" not in source


# ---------------------------------------------------------------------------
# render_admin_py — list_display
# ---------------------------------------------------------------------------


def test_list_display_from_manifest():
    source = render_admin_py(_contract(), _manifest(), app_label="core")
    assert "list_display = ['name', 'crop_type']" in source


def test_list_display_no_manifest():
    """Without a manifest, list_display is empty."""
    source = render_admin_py(_contract(), manifest=None, app_label="core")
    # Should still render admin classes but with minimal fields.
    assert "class CropAdmin" in source


# ---------------------------------------------------------------------------
# render_admin_py — list_filter
# ---------------------------------------------------------------------------


def test_list_filter_from_manifest():
    source = render_admin_py(_contract(), _manifest(), app_label="core")
    assert "list_filter = ['crop_type']" in source


# ---------------------------------------------------------------------------
# render_admin_py — search_fields
# ---------------------------------------------------------------------------


def test_search_fields_text_fields():
    source = render_admin_py(_contract(), _manifest(), app_label="core")
    assert "search_fields = ['name', 'crop_type']" in source


def test_search_fields_includes_fk():
    """FK fields should get 'field__name' in search_fields."""
    m = _manifest()
    m["views"][0]["editable_fields"] = ["name", "crop_type"]
    source = render_admin_py(_contract(), m, app_label="core")
    # Planting has FK 'crop' → search_fields includes 'crop__name'
    assert "crop__name" in source


# ---------------------------------------------------------------------------
# render_admin_py — readonly_fields
# ---------------------------------------------------------------------------


def test_readonly_fields_from_computed():
    c = _contract()
    # Add a computed field to crop table
    c["tables"][0]["columns"].append(
        {
            "suggested_field_name": "total_revenue",
            "django_field_class": "models.DecimalField",
            "django_field_kwargs": {"max_digits": 10, "decimal_places": 2},
        }
    )
    m = _manifest()
    m["views"][0]["computed_fields"] = ["total_revenue"]
    source = render_admin_py(c, m, app_label="core")
    assert "readonly_fields = ['total_revenue']" in source


# ---------------------------------------------------------------------------
# render_admin_py — full file structure
# ---------------------------------------------------------------------------


def test_render_admin_py_has_imports():
    source = render_admin_py(_contract(), _manifest(), app_label="core")
    assert "from django.contrib import admin" in source
    assert "from .models import Crop, Planting" in source


def test_render_admin_py_has_registrations():
    source = render_admin_py(_contract(), _manifest(), app_label="core")
    assert "@admin.register(Crop)" in source
    assert "@admin.register(Planting)" in source


def test_render_admin_py_no_manifest():
    """Without a manifest, all models still get registrations."""
    source = render_admin_py(_contract(), manifest=None, app_label="core")
    assert "@admin.register(Crop)" in source
    assert "@admin.register(Planting)" in source


# ---------------------------------------------------------------------------
# Compilation checks
# ---------------------------------------------------------------------------


def test_generated_admin_compiles_with_manifest():
    _check_compiles(render_admin_py(_contract(), _manifest(), app_label="core"))


def test_generated_admin_compiles_no_manifest():
    _check_compiles(render_admin_py(_contract(), manifest=None, app_label="core"))


def test_generated_admin_compiles_empty():
    _check_compiles(
        render_admin_py(
            {"version": "1.0", "source": {}, "tables": []},
            manifest=None,
            app_label="core",
        )
    )


# ---------------------------------------------------------------------------
# Management command integration
# ---------------------------------------------------------------------------


def test_command_output(tmp_path):
    """End-to-end: write contract + manifest, run command, verify output."""
    from django.core.management import call_command

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(_contract()), encoding="utf-8")

    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.dump(_manifest()), encoding="utf-8")

    out_path = tmp_path / "admin.py"

    call_command(
        "generate_admin",
        contract=str(contract_path),
        manifest=str(manifest_path),
        out=str(out_path),
        app_label="core",
        force=True,
    )

    assert out_path.exists()
    source = out_path.read_text(encoding="utf-8")
    assert "@admin.register(Crop)" in source
    assert "@admin.register(Planting)" in source
    _check_compiles(source)


def test_command_no_manifest(tmp_path):
    """Command still works without --manifest."""
    from django.core.management import call_command

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(_contract()), encoding="utf-8")
    out_path = tmp_path / "admin.py"

    call_command(
        "generate_admin",
        contract=str(contract_path),
        out=str(out_path),
        app_label="core",
        force=True,
    )
    assert out_path.exists()


def test_command_rejects_missing_contract(tmp_path):
    from django.core.management import call_command, CommandError

    import pytest

    with pytest.raises(CommandError, match="contract not found"):
        call_command(
            "generate_admin",
            contract=str(tmp_path / "nope.yaml"),
            out=str(tmp_path / "admin.py"),
            force=True,
        )


def test_command_warns_on_existing_output(tmp_path):
    from django.core.management import call_command

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(_contract()), encoding="utf-8")
    out_path = tmp_path / "admin.py"
    out_path.write_text("# existing")

    import pytest

    with pytest.raises(SystemExit):
        call_command(
            "generate_admin",
            contract=str(contract_path),
            out=str(out_path),
            app_label="core",
        )
