"""Tests for ``workbook/codegen/admin_generator`` and ``generate_admin`` command."""

from __future__ import annotations


import yaml

from workbook.codegen.admin_generator import render_admin_py
from workbook.codegen.manifest import find_view_for_entity, load_manifest


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _contract() -> dict:
    """Return a v1.1 contract with Crop + Planting (Planting FK to Crop)."""
    return {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "bundle_worksheet_title": "Crop Info",
                "suggested_model_name": "crop",
                "model_name": "Crop",
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
                            "max_length": 100,
                            "blank": True,
                            "default": "",
                        },
                    },
                ],
            },
            {
                "bundle_worksheet_title": "Crop Planner",
                "suggested_model_name": "planting",
                "model_name": "Planting",
                "bundle_output_path": "year_2025/crop_planner.csv",
                "model_meta": {"verbose_name": "Planting", "ordering": ["-plant_date"]},
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
                            "max_digits": 6,
                            "decimal_places": 1,
                            "null": True,
                            "blank": True,
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
    from workbench.exceptions import UserFacingError

    import pytest

    with pytest.raises(UserFacingError, match="Unsupported view manifest version"):
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
            {"source": {}, "tables": []},
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


# ---------------------------------------------------------------------------
# AbstractUser / BaseUserAdmin support
# ---------------------------------------------------------------------------


def _contract_abstract_user_admin() -> dict:
    """Return a contract with an AbstractUser model and an ``admin:`` block."""
    return {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "farm_user",
                "model_name": "FarmUser",
                "model_base": "django.contrib.auth.models.AbstractUser",
                "model_meta": {"verbose_name": "Farm User"},
                "admin": {
                    "list_display": ["username", "email", "is_active"],
                    "list_filter": ["is_active"],
                    "search_fields": ["username", "email"],
                    "readonly_fields": ["date_joined"],
                },
            }
        ],
    }


def test_user_model_admin_uses_useradmin_and_is_authoritative():
    source = render_admin_py(
        _contract_abstract_user_admin(), manifest=None, app_label="core"
    )
    assert "from django.contrib.auth.admin import UserAdmin as BaseUserAdmin" in source
    assert "class FarmUserAdmin(BaseUserAdmin):" in source
    assert "list_display = ['username', 'email', 'is_active']" in source
    assert "list_filter = ['is_active']" in source
    assert "search_fields = ['username', 'email']" in source
    assert "readonly_fields = ['date_joined']" in source
    _check_compiles(source)


# ---------------------------------------------------------------------------
# status_field promotion and comment
# ---------------------------------------------------------------------------


def test_status_field_promoted_in_list_filter():
    """When manifest has status_field already in filterable_by, it appears first."""
    contract = _contract()
    manifest = _manifest()
    manifest["views"][0]["filterable_by"] = ["crop_type"]
    manifest["views"][0]["status_field"] = "crop_type"
    source = render_admin_py(contract, manifest, app_label="core")
    assert "list_filter = ['crop_type']" in source


def test_status_field_added_to_list_filter_when_not_in_filterable():
    """When manifest has status_field not in filterable_by, it is added and promoted first."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "order",
                "model_name": "Order",
                "columns": [
                    {
                        "suggested_field_name": "status",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                    {
                        "suggested_field_name": "total",
                        "django_field_class": "models.DecimalField",
                        "django_field_kwargs": {"max_digits": 10, "decimal_places": 2},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "order",
                "entity": "order",
                "source_tab": "Orders",
                "type": "list",
                "editable_fields": ["status", "total"],
                "computed_fields": [],
                "filterable_by": ["total"],
                "status_field": "status",
                "notes": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Orders"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "list_filter = ['status', 'total']" in source


def test_admin_class_includes_status_field_comment():
    """When status_field is set, a comment appears above the admin class."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "order",
                "model_name": "Order",
                "columns": [
                    {
                        "suggested_field_name": "status",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                    {
                        "suggested_field_name": "total",
                        "django_field_class": "models.DecimalField",
                        "django_field_kwargs": {"max_digits": 10, "decimal_places": 2},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "order",
                "entity": "order",
                "source_tab": "Orders",
                "type": "list",
                "editable_fields": ["status", "total"],
                "computed_fields": [],
                "filterable_by": ["status"],
                "status_field": "status",
                "notes": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Orders"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "# status_field: status" in source


def test_no_status_field_comment_when_absent():
    """When status_field is not set, no comment appears."""
    source = render_admin_py(_contract(), _manifest(), app_label="core")
    assert "status_field" not in source


def test_manifest_round_trip_in_end_to_end_admin_generation():
    """Verify manifest fields flow through to generated admin output end-to-end."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "order",
                "model_name": "Order",
                "columns": [
                    {
                        "suggested_field_name": "status",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                    {
                        "suggested_field_name": "customer",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "total",
                        "django_field_class": "models.DecimalField",
                        "django_field_kwargs": {"max_digits": 10, "decimal_places": 2},
                    },
                    {
                        "suggested_field_name": "created_at",
                        "django_field_class": "models.DateTimeField",
                        "django_field_kwargs": {"null": True},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "test", "provider": "google_sheets"},
        "views": [
            {
                "name": "order",
                "entity": "order",
                "source_tab": "Orders",
                "type": "list",
                "editable_fields": ["status", "customer"],
                "computed_fields": ["total"],
                "filterable_by": ["status", "created_at"],
                "status_field": "status",
                "notes": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Orders"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "list_display" in source
    assert "'status'" in source
    assert "'customer'" in source
    assert "readonly_fields = ['total']" in source
    assert "list_filter = ['status', 'created_at']" in source
    assert "# status_field: status" in source
    _check_compiles(source)


def test_status_field_not_injected_into_list_filter_when_not_in_valid_fields():
    """Manifest status_field referencing a non-existent field is not added to list_filter."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "order",
                "model_name": "Order",
                "columns": [
                    {
                        "suggested_field_name": "status",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "order",
                "entity": "order",
                "source_tab": "Orders",
                "type": "list",
                "editable_fields": ["status"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": "nonexistent_field_name",
                "notes": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Orders"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "nonexistent_field_name" not in source.splitlines()
    _check_compiles(source)


# ---------------------------------------------------------------------------
# FK link display methods
# ---------------------------------------------------------------------------


def test_fk_field_gets_link_method():
    """FK fields should get a _link display method."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "field_block",
                "model_name": "FieldBlock",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                ],
            },
            {
                "suggested_model_name": "crop_plan_entry",
                "model_name": "CropPlanEntry",
                "columns": [
                    {
                        "suggested_field_name": "block",
                        "django_field_class": "models.ForeignKey",
                        "django_field_kwargs": {
                            "to": "FieldBlock",
                            "on_delete": "models.PROTECT",
                            "null": True,
                        },
                    },
                    {
                        "suggested_field_name": "crop",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop_plan",
                "entity": "crop_plan_entry",
                "source_tab": "Crop Planner",
                "type": "list",
                "editable_fields": ["block", "crop"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": None,
                "notes": None,
            },
        ],
        "workflow_hints": {"tab_sequence": [], "role_hints": [], "weekly_actions": []},
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "block_link" in source
    assert "reverse(" in source
    assert "format_html" in source
    assert "short_description" in source
    _check_compiles(source)


def test_fk_link_appears_in_list_display_instead_of_raw_fk():
    """list_display should use block_link instead of block."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "field_block",
                "model_name": "FieldBlock",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                ],
            },
            {
                "suggested_model_name": "crop_plan_entry",
                "model_name": "CropPlanEntry",
                "columns": [
                    {
                        "suggested_field_name": "block",
                        "django_field_class": "models.ForeignKey",
                        "django_field_kwargs": {
                            "to": "FieldBlock",
                            "on_delete": "models.PROTECT",
                            "null": True,
                        },
                    },
                    {
                        "suggested_field_name": "crop",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop_plan",
                "entity": "crop_plan_entry",
                "source_tab": "Crop Planner",
                "type": "list",
                "editable_fields": ["block", "crop"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": None,
                "notes": None,
            },
        ],
        "workflow_hints": {"tab_sequence": [], "role_hints": [], "weekly_actions": []},
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert (
        "list_display = ['crop', 'block_link']" in source
        or "list_display = ['block_link', 'crop']" in source
    )
    # Confirm list_display uses block_link, not bare block
    list_display_line = [
        l.strip() for l in source.splitlines() if l.strip().startswith("list_display")
    ][0]
    assert "'block'" not in list_display_line.replace("'block_link'", "")
    _check_compiles(source)


def test_non_fk_fields_not_turned_into_links():
    """Non-FK fields should not get _link methods."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop_plan_entry",
                "model_name": "CropPlanEntry",
                "columns": [
                    {
                        "suggested_field_name": "crop",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop_plan",
                "entity": "crop_plan_entry",
                "source_tab": "Crop Planner",
                "type": "list",
                "editable_fields": ["crop"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": None,
                "notes": None,
            },
        ],
        "workflow_hints": {"tab_sequence": [], "role_hints": [], "weekly_actions": []},
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "_link" not in source
    assert "format_html" not in source
    _check_compiles(source)


def test_status_field_comment_emitted_even_when_not_in_contract():
    """The status_field comment is emitted as informational even for non-existent fields."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "order",
                "model_name": "Order",
                "columns": [
                    {
                        "suggested_field_name": "status",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "order",
                "entity": "order",
                "source_tab": "Orders",
                "type": "list",
                "editable_fields": ["status"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": "nonexistent_field_name",
                "notes": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Orders"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "# status_field: nonexistent_field_name" in source
    _check_compiles(source)


# ---------------------------------------------------------------------------
# Time scope: year_field / date_field / current-season filtering
# ---------------------------------------------------------------------------


def test_temporal_year_field_in_list_filter():
    """source_bundle_year should appear in list_filter when present."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop_plan_entry",
                "model_name": "CropPlanEntry",
                "columns": [
                    {
                        "suggested_field_name": "crop",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "source_bundle_year",
                        "django_field_class": "models.IntegerField",
                        "django_field_kwargs": {"null": True},
                    },
                    {
                        "suggested_field_name": "status",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop_plan",
                "entity": "crop_plan_entry",
                "source_tab": "Crop Planner",
                "type": "list",
                "editable_fields": ["crop"],
                "computed_fields": [],
                "filterable_by": ["status"],
                "status_field": "status",
                "time_scope": {
                    "year_field": "source_bundle_year",
                    "default_scope": "current_season",
                },
                "notes": None,
            },
        ],
        "workflow_hints": {"tab_sequence": [], "role_hints": [], "weekly_actions": []},
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "source_bundle_year" in source
    assert "list_filter" in source
    _check_compiles(source)


def test_date_hierarchy_for_date_fields():
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "market_entry",
                "model_name": "MarketEntry",
                "columns": [
                    {
                        "suggested_field_name": "outlet",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "distribution_date",
                        "django_field_class": "models.DateField",
                        "django_field_kwargs": {"null": True},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "market",
                "entity": "market_entry",
                "source_tab": "Market",
                "type": "list",
                "editable_fields": ["outlet"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": None,
                "time_scope": {
                    "date_field": "distribution_date",
                    "default_scope": "current_season",
                },
                "notes": None,
            },
        ],
        "workflow_hints": {"tab_sequence": [], "role_hints": [], "weekly_actions": []},
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "date_hierarchy = 'distribution_date'" in source
    _check_compiles(source)


def test_current_season_queryset_filter():
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop_plan_entry",
                "model_name": "CropPlanEntry",
                "columns": [
                    {
                        "suggested_field_name": "crop",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "source_bundle_year",
                        "django_field_class": "models.IntegerField",
                        "django_field_kwargs": {"null": True},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop_plan",
                "entity": "crop_plan_entry",
                "source_tab": "Crop Planner",
                "type": "list",
                "editable_fields": ["crop"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": None,
                "time_scope": {
                    "year_field": "source_bundle_year",
                    "default_scope": "current_season",
                },
                "notes": None,
            },
        ],
        "workflow_hints": {"tab_sequence": [], "role_hints": [], "weekly_actions": []},
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "get_queryset" in source
    assert "timezone" in source
    assert "source_bundle_year" in source
    _check_compiles(source)


def test_status_field_generates_admin_actions():
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "field_record",
                "model_name": "FieldRecord",
                "columns": [
                    {
                        "suggested_field_name": "status",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                    {
                        "suggested_field_name": "crop_variety",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "field_record",
                "entity": "field_record",
                "source_tab": "Field Records",
                "type": "list",
                "editable_fields": ["status", "crop_variety"],
                "computed_fields": [],
                "filterable_by": ["status"],
                "status_field": "status",
                "status_values": ["Planted", "Harvested", "Finished"],
                "notes": None,
            },
        ],
        "workflow_hints": {"tab_sequence": [], "role_hints": [], "weekly_actions": []},
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "mark_as_planted" in source
    assert "mark_as_harvested" in source
    assert "mark_as_finished" in source
    assert "actions =" in source
    _check_compiles(source)


def test_editable_fields_become_fields():
    """editable_fields from manifest become the fields attribute."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop_plan_entry",
                "model_name": "CropPlanEntry",
                "columns": [
                    {
                        "suggested_field_name": "block",
                        "django_field_class": "models.ForeignKey",
                        "django_field_kwargs": {
                            "to": "FieldBlock",
                            "on_delete": "models.PROTECT",
                            "null": True,
                        },
                    },
                    {
                        "suggested_field_name": "bed",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                    {
                        "suggested_field_name": "crop",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "location",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "weekly_yield",
                        "django_field_class": "models.DecimalField",
                        "django_field_kwargs": {"max_digits": 10, "decimal_places": 2},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop_plan",
                "entity": "crop_plan_entry",
                "source_tab": "Crop Planner",
                "type": "list",
                "editable_fields": ["block", "bed", "crop"],
                "computed_fields": ["location", "weekly_yield"],
                "filterable_by": [],
                "status_field": None,
                "notes": None,
            },
        ],
        "workflow_hints": {"tab_sequence": [], "role_hints": [], "weekly_actions": []},
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "readonly_fields = ['location', 'weekly_yield']" in source
    assert "fields = ['block', 'bed', 'crop']" in source
    _check_compiles(source)


def test_generate_admin_skips_invalid_tables(tmp_path, monkeypatch):
    from django.core.management import call_command

    contract = tmp_path / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "version": "1.0",
                "tables": [
                    {
                        "model_name": "Valid",
                        "columns": [
                            {
                                "suggested_field_name": "name",
                                "django_field_class": "models.CharField",
                                "django_field_kwargs": {"max_length": 100},
                            }
                        ],
                    },
                    {"model_name": "", "columns": []},
                ],
            }
        )
    )
    out = tmp_path / "admin.py"
    call_command("generate_admin", contract=str(contract), out=str(out), force=True)
    source = out.read_text()
    assert "Valid" in source


# ---------------------------------------------------------------------------
# Codegen manifest integration (Layer 3 → admin)
# ---------------------------------------------------------------------------


def _codegen_manifest_form() -> dict:
    """Return a codegen manifest with form archetype for a Crop model."""
    return {
        "version": 1,
        "generated_at": "2026-06-01T00:00:00Z",
        "tables": [
            {
                "model_name": "Crop",
                "ui_archetype": "form",
                "confidence": 0.85,
                "workflow_hints": {
                    "editable": True,
                    "status_field": "status",
                    "status_transitions": {
                        "planted": "growing",
                        "growing": "harvested",
                    },
                    "roles": ["field_manager"],
                    "workflow_notes": "Updated weekly by field managers.",
                },
            },
        ],
    }


def test_admin_with_codegen_manifest_form_archetype():
    """Form archetype from codegen manifest should set list_editable."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "status",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                    {
                        "suggested_field_name": "crop_type",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 100},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "test", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop",
                "entity": "crop",
                "source_tab": "Crops",
                "type": "list",
                "editable_fields": ["name", "status", "crop_type"],
                "computed_fields": [],
                "filterable_by": ["status"],
                "status_field": "status",
                "status_values": ["Planted", "Growing", "Harvested"],
                "notes": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Crops"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    # Without codegen manifest — no list_editable.
    source_no_cg = render_admin_py(contract, manifest, app_label="core")
    # With codegen manifest — list_editable should be set for form archetype.
    source_with_cg = render_admin_py(
        contract, manifest, app_label="core", codegen_manifest=_codegen_manifest_form()
    )
    assert "list_editable" not in source_no_cg or "list_editable = []" in source_no_cg
    assert "list_editable" in source_with_cg
    assert "list_editable = ['name', 'status', 'crop_type']" in source_with_cg
    _check_compiles(source_with_cg)


def test_admin_with_codegen_manifest_dashboard_archetype():
    """Dashboard archetype should make all fields readonly."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "total_yield",
                        "django_field_class": "models.DecimalField",
                        "django_field_kwargs": {"max_digits": 10, "decimal_places": 2},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "test", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop",
                "entity": "crop",
                "source_tab": "Crops",
                "type": "list",
                "editable_fields": ["name", "total_yield"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": None,
                "notes": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Crops"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    codegen = {
        "version": 1,
        "tables": [
            {
                "model_name": "Crop",
                "ui_archetype": "dashboard",
                "confidence": 0.92,
                "workflow_hints": {"editable": False},
            },
        ],
    }
    source = render_admin_py(
        contract, manifest, app_label="core", codegen_manifest=codegen
    )
    # Dashboard archetype should make name readonly.
    assert "readonly_fields" in source
    assert "'name'" in source
    assert "'total_yield'" in source
    _check_compiles(source)


def test_admin_with_codegen_manifest_status_transitions():
    """Status transitions from codegen manifest should generate admin actions."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "status",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "test", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop",
                "entity": "crop",
                "source_tab": "Crops",
                "type": "list",
                "editable_fields": ["name", "status"],
                "computed_fields": [],
                "filterable_by": ["status"],
                "status_field": "status",
                "notes": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Crops"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    codegen = {
        "version": 1,
        "tables": [
            {
                "model_name": "Crop",
                "ui_archetype": "form",
                "confidence": 0.85,
                "workflow_hints": {
                    "status_field": "status",
                    "status_transitions": {
                        "planted": "growing",
                        "growing": "harvested",
                    },
                },
            },
        ],
    }
    source = render_admin_py(
        contract, manifest, app_label="core", codegen_manifest=codegen
    )
    # Should produce admin actions for planted, growing, harvested.
    assert "mark_as_planted" in source
    assert "mark_as_growing" in source
    assert "mark_as_harvested" in source
    assert "actions = [" in source
    _check_compiles(source)


def test_status_transition_validation_in_action():
    """Status transitions generate actions that filter before updating."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "status",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                ],
            }
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "test", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop",
                "entity": "crop",
                "source_tab": "Crops",
                "type": "list",
                "editable_fields": ["name", "status"],
                "computed_fields": [],
                "filterable_by": ["status"],
                "status_field": "status",
                "notes": None,
            }
        ],
        "workflow_hints": {
            "tab_sequence": ["Crops"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    codegen = {
        "version": 1,
        "tables": [
            {
                "model_name": "Crop",
                "ui_archetype": "form",
                "confidence": 0.85,
                "workflow_hints": {
                    "status_field": "status",
                    "status_transitions": {
                        "planted": "growing",
                        "growing": "harvested",
                    },
                },
            }
        ],
    }
    source = render_admin_py(
        contract, manifest, app_label="core", codegen_manifest=codegen
    )
    _check_compiles(source)
    assert "mark_as_harvested" in source
    # Must filter before updating (validating transition)
    assert ".filter(" in source or ".exclude(" in source
    # Must report skipped count
    assert "message_user" in source
    assert "WARNING" in source or "skipped" in source


def test_role_restricted_get_queryset():
    """access_hints.restricted_to should generate get_queryset filtering by group."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                ],
            }
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "test", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop",
                "entity": "crop",
                "source_tab": "Crops",
                "type": "list",
                "editable_fields": ["name"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": None,
                "notes": None,
            }
        ],
        "workflow_hints": {
            "tab_sequence": ["Crops"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    codegen = {
        "version": 1,
        "tables": [
            {
                "model_name": "Crop",
                "ui_archetype": "list",
                "confidence": 0.85,
                "access_hints": {"restricted_to": ["field_manager"]},
            }
        ],
    }
    source = render_admin_py(
        contract, manifest, app_label="core", codegen_manifest=codegen
    )
    _check_compiles(source)
    assert "def get_queryset(self, request):" in source
    assert "filter(name" in source or "filter(name__in" in source


def test_no_get_queryset_when_no_role_restriction():
    """Without access_hints.restricted_to, no get_queryset override."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    }
                ],
            }
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "test", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop",
                "entity": "crop",
                "source_tab": "Crops",
                "type": "list",
                "editable_fields": ["name"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": None,
                "notes": None,
            }
        ],
        "workflow_hints": {
            "tab_sequence": ["Crops"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    codegen = {
        "version": 1,
        "tables": [{"model_name": "Crop", "ui_archetype": "list", "confidence": 0.5}],
    }
    source = render_admin_py(
        contract, manifest, app_label="core", codegen_manifest=codegen
    )
    assert "def get_queryset(self, request):" not in source


def test_year_week_filter_generated():
    """time_scope with week_field should generate a YearWeekFilter class."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "plant_date",
                        "django_field_class": "models.DateField",
                        "django_field_kwargs": {"null": True, "blank": True},
                    },
                ],
            }
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "test", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop",
                "entity": "crop",
                "source_tab": "Crops",
                "type": "list",
                "editable_fields": ["name", "plant_date"],
                "computed_fields": [],
                "filterable_by": ["plant_date"],
                "status_field": None,
                "notes": None,
                "time_scope": {
                    "year_field": "plant_date__year",
                    "week_field": "plant_date__week",
                },
            }
        ],
        "workflow_hints": {
            "tab_sequence": ["Crops"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    source = render_admin_py(contract, manifest, app_label="core")
    _check_compiles(source)
    assert "class CropYearWeekFilter" in source
    assert "admin.SimpleListFilter" in source
    assert "plant_date__year" in source  # year_field in filter field lookups


def test_no_week_filter_when_no_week_field():
    """Without week_field in time_scope, no filter class generated."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    }
                ],
            }
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "test", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop",
                "entity": "crop",
                "source_tab": "Crops",
                "type": "list",
                "editable_fields": ["name"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": None,
                "notes": None,
                "time_scope": {"year_field": "plant_date__year"},
            }
        ],
        "workflow_hints": {
            "tab_sequence": ["Crops"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    source = render_admin_py(contract, manifest, app_label="core")
    assert "class YearWeekFilter" not in source


def test_admin_output_differs_with_codegen_manifest():
    """Admin output must differ materially when codegen manifest is present."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "status",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "test", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop",
                "entity": "crop",
                "source_tab": "Crops",
                "type": "list",
                "editable_fields": ["name", "status"],
                "computed_fields": [],
                "filterable_by": ["status"],
                "status_field": "status",
                "status_values": ["Planted", "Growing", "Harvested"],
                "notes": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Crops"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    codegen = _codegen_manifest_form()
    source_no_cg = render_admin_py(contract, manifest, app_label="core")
    source_with_cg = render_admin_py(
        contract, manifest, app_label="core", codegen_manifest=codegen
    )
    assert source_no_cg != source_with_cg, (
        "Admin output must differ when codegen manifest is provided"
    )
    _check_compiles(source_with_cg)
    _check_compiles(source_no_cg)


def test_command_with_codegen_manifest(tmp_path):
    """End-to-end: generate_admin with --codegen-manifest flag."""
    from django.core.management import call_command

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        yaml.safe_dump(
            {
                "source": {"provider": "google_sheets"},
                "tables": [
                    {
                        "suggested_model_name": "crop",
                        "model_name": "Crop",
                        "columns": [
                            {
                                "suggested_field_name": "name",
                                "django_field_class": "models.CharField",
                                "django_field_kwargs": {"max_length": 200},
                            },
                            {
                                "suggested_field_name": "status",
                                "django_field_class": "models.CharField",
                                "django_field_kwargs": {"max_length": 50},
                            },
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "version": "view-manifest-draft-1",
                "source": {"source_id": "test", "provider": "google_sheets"},
                "views": [
                    {
                        "name": "crop",
                        "entity": "crop",
                        "source_tab": "Crops",
                        "type": "list",
                        "editable_fields": ["name", "status"],
                        "computed_fields": [],
                        "filterable_by": ["status"],
                        "status_field": "status",
                        "status_values": ["Planted", "Growing", "Harvested"],
                        "notes": None,
                    },
                ],
                "workflow_hints": {
                    "tab_sequence": ["Crops"],
                    "role_hints": [],
                    "weekly_actions": [],
                },
            }
        ),
        encoding="utf-8",
    )
    codegen_path = tmp_path / "codegen.yaml"
    codegen_path.write_text(
        yaml.safe_dump(_codegen_manifest_form()),
        encoding="utf-8",
    )
    out_path = tmp_path / "admin.py"

    call_command(
        "generate_admin",
        contract=str(contract_path),
        manifest=str(manifest_path),
        codegen_manifest=str(codegen_path),
        out=str(out_path),
        force=True,
    )

    assert out_path.exists()
    source = out_path.read_text(encoding="utf-8")
    assert "@admin.register(Crop)" in source
    _check_compiles(source)
