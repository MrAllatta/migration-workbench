"""Tests for the manifest merger (Layer 1 + Layer 2 → Layer 3)."""

from __future__ import annotations

import yaml

from workbook.tools.manifest_merger import merge_manifests


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _profiler_signals() -> dict:
    """Return a profiler-signals dict with two tabs."""
    return {
        "version": 1,
        "generated_at": "2026-06-01T00:00:00Z",
        "signals": [
            {
                "tab_title": "Crop Planner",
                "ui_archetype": "form",
                "confidence_score": 0.85,
                "formula_density": 0.12,
                "cross_sheet_refs": 0,
            },
            {
                "tab_title": "Harvest Log",
                "ui_archetype": "list",
                "confidence_score": 0.72,
                "formula_density": 0.05,
                "cross_sheet_refs": 0,
            },
        ],
    }


def _interaction_contract() -> dict:
    """Return an interaction-contract dict with one role."""
    return {
        "version": "interaction-contract-1",
        "generated_at": "2026-06-01T00:00:00Z",
        "source_id": "farm",
        "interviews": [
            {
                "role": "field_manager",
                "archetype_overrides": {
                    "Crop Planner": "form",
                },
                "status_semantics": {
                    "planted": "active",
                    "harvested": "complete",
                },
                "workflow_notes": "Field managers update crop status weekly.",
                "weekly_actions": [
                    "Mark crops as harvested",
                    "Add weekly bed count",
                ],
            },
            {
                "role": "operations",
                "archetype_overrides": {
                    "Harvest Log": "list",
                },
            },
        ],
    }


def _view_manifest() -> dict:
    """Return a view manifest with Crop Planner and Harvest Log."""
    return {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "farm", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop_planner",
                "entity": "crop_planner",
                "source_tab": "Crop Planner",
                "type": "list",
                "editable_fields": ["crop", "plant_date"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": "status",
                "status_values": ["Planted", "Harvested"],
            },
            {
                "name": "harvest_log",
                "entity": "harvest_log",
                "source_tab": "Harvest Log",
                "type": "list",
                "editable_fields": ["crop", "quantity"],
                "computed_fields": ["total"],
                "filterable_by": [],
                "status_field": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Crop Planner", "Harvest Log"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }


# ---------------------------------------------------------------------------
# Merge: full three-layer
# ---------------------------------------------------------------------------


def test_merge_full_produces_tables():
    """Merging all three layers produces a codegen manifest with tables."""
    result = merge_manifests(
        profiler_signals=_profiler_signals(),
        interaction_contract=_interaction_contract(),
        view_manifest=_view_manifest(),
    )
    assert result["version"] == 1
    assert "generated_at" in result
    assert len(result["tables"]) == 2


def test_merge_archetype_from_contract_overrides_signal():
    """Interaction contract archetype should win over profiler signal."""
    result = merge_manifests(
        profiler_signals=_profiler_signals(),
        interaction_contract=_interaction_contract(),
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    assert planner["ui_archetype"] == "form"


def test_merge_archetype_from_signal_when_no_contract():
    """Without interaction contract, profiler signal archetype is used."""
    signals = _profiler_signals()
    # Override to dashboard to distinguish from default
    signals["signals"][0]["ui_archetype"] = "dashboard"
    result = merge_manifests(
        profiler_signals=signals,
        interaction_contract=None,
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    assert planner["ui_archetype"] == "dashboard"


def test_merge_archetype_from_manifest_fallback():
    """Without signals or contract, view manifest type is used."""
    result = merge_manifests(
        profiler_signals=None,
        interaction_contract=None,
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    assert planner["ui_archetype"] == "list"  # manifest type is 'list'


def test_merge_confidence_from_signal():
    """Confidence score should come from profiler signal."""
    result = merge_manifests(
        profiler_signals=_profiler_signals(),
        interaction_contract=None,
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    assert planner["confidence"] == 0.85


def test_merge_confidence_one_when_overridden():
    """Confidence should be 1.0 when interaction contract overrides."""
    result = merge_manifests(
        profiler_signals=_profiler_signals(),
        interaction_contract=_interaction_contract(),
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    assert planner["confidence"] == 1.0


# ---------------------------------------------------------------------------
# Merge: workflow_hints
# ---------------------------------------------------------------------------


def test_merge_editable_form():
    """Form archetype tables should be editable."""
    result = merge_manifests(
        profiler_signals=_profiler_signals(),
        interaction_contract=_interaction_contract(),
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    assert planner["workflow_hints"]["editable"] is True


def test_merge_non_editable_dashboard():
    """Non-form archetype tables should not be editable."""
    signals = _profiler_signals()
    signals["signals"][0]["ui_archetype"] = "dashboard"
    result = merge_manifests(
        profiler_signals=signals,
        interaction_contract=None,
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    assert planner["workflow_hints"]["editable"] is False


def test_merge_status_transitions_from_contract():
    """Status transitions should come from interaction contract status_semantics."""
    result = merge_manifests(
        profiler_signals=_profiler_signals(),
        interaction_contract=_interaction_contract(),
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    hints = planner["workflow_hints"]
    assert hints["status_field"] != ""
    assert "status_transitions" in hints


def test_merge_roles_from_contract():
    """Role hints should come from interaction contract."""
    result = merge_manifests(
        profiler_signals=_profiler_signals(),
        interaction_contract=_interaction_contract(),
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    assert "roles" in planner["workflow_hints"]
    assert "field_manager" in planner["workflow_hints"]["roles"]


def test_merge_workflow_notes_from_contract():
    """Workflow notes should propagate from interaction contract."""
    result = merge_manifests(
        profiler_signals=_profiler_signals(),
        interaction_contract=_interaction_contract(),
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    assert "workflow_notes" in planner["workflow_hints"]
    assert "Field managers" in planner["workflow_hints"]["workflow_notes"]


# ---------------------------------------------------------------------------
# Role supplement: non-override tabs get per-role data
# ---------------------------------------------------------------------------


def _contract_with_role_data_no_overrides() -> dict:
    """Interaction contract where a role has status_semantics but no overrides."""
    return {
        "version": "interaction-contract-1",
        "generated_at": "2026-06-01T00:00:00Z",
        "source_id": "farm",
        "interviews": [
            {
                "role": "field_manager",
                "status_semantics": {
                    "planned": "in_progress",
                    "in_progress": "completed",
                },
                "workflow_notes": "Field managers review status daily.",
                "weekly_actions": [
                    "Review open tasks",
                    "Update statuses",
                ],
                "access_hints": {"level": "write", "group": "field_ops"},
            },
        ],
    }


def _manifest_with_role_hints() -> dict:
    """View manifest with role_hints for tabs not in archetype_overrides."""
    manifest = _view_manifest()
    # Add a third tab only known to the view manifest.
    manifest["views"].append(
        {
            "name": "field_map",
            "entity": "field_map",
            "source_tab": "Field Map",
            "type": "list",
            "status_field": None,
        }
    )
    manifest["workflow_hints"]["role_hints"] = [
        "Crop Planner: field_manager",
        "Field Map: field_manager",
    ]
    manifest["workflow_hints"]["tab_sequence"] = [
        "Crop Planner",
        "Harvest Log",
        "Field Map",
    ]
    return manifest


def test_role_supplement_flows_to_non_override_tab():
    """A tab with role_hints but NO archetype_overrides gets per-role data."""
    result = merge_manifests(
        profiler_signals=None,
        interaction_contract=_contract_with_role_data_no_overrides(),
        view_manifest=_manifest_with_role_hints(),
    )
    field_map = next(t for t in result["tables"] if t["model_name"] == "FieldMap")
    hints = field_map["workflow_hints"]
    assert "Field managers" in hints["workflow_notes"]
    assert "Review open tasks" in hints["weekly_actions"]
    assert "status_transitions" in hints
    assert field_map.get("access_hints", {}).get("level") == "write"


def test_role_supplement_does_not_override_archetype_tab():
    """Tabs already in archetype_overrides keep their existing data."""
    result = merge_manifests(
        profiler_signals=None,
        interaction_contract=_contract_with_role_data_no_overrides(),
        view_manifest=_manifest_with_role_hints(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    assert planner["ui_archetype"] == "list"
    hints = planner["workflow_hints"]
    assert "Field managers" in hints["workflow_notes"]


def test_role_hints_clean_role_names():
    """Priority 2 role_hints should return clean role names, not 'Tab: role'."""
    result = merge_manifests(
        profiler_signals=None,
        interaction_contract=None,
        view_manifest=_manifest_with_role_hints(),
    )
    field_map = next(t for t in result["tables"] if t["model_name"] == "FieldMap")
    roles = field_map["workflow_hints"].get("roles", [])
    assert "field_manager" in roles
    assert all(":" not in r for r in roles)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_merge_no_inputs():
    """Merging with no inputs returns an empty codegen manifest."""
    result = merge_manifests()
    assert result["version"] == 1
    assert result["tables"] == []


def test_merge_only_signals():
    result = merge_manifests(profiler_signals=_profiler_signals())
    assert len(result["tables"]) == 2
    assert all(t["ui_archetype"] in ("form", "list") for t in result["tables"])


def test_merge_only_manifest():
    result = merge_manifests(view_manifest=_view_manifest())
    assert len(result["tables"]) == 2
    # All archetypes default to 'list' from manifest
    assert all(t["ui_archetype"] == "list" for t in result["tables"])


def test_merge_propagates_source_id():
    result = merge_manifests(view_manifest=_view_manifest())
    assert result["source_id"] == "farm"


def test_yaml_round_trip():
    """The codegen manifest survives a YAML dump/load cycle."""
    result = merge_manifests(
        profiler_signals=_profiler_signals(),
        interaction_contract=_interaction_contract(),
        view_manifest=_view_manifest(),
    )
    serialized = yaml.safe_dump(result, sort_keys=False)
    reloaded = yaml.safe_load(serialized)
    assert reloaded["version"] == 1
    assert len(reloaded["tables"]) == 2


def test_status_transitions_from_view_manifest():
    """When no interaction contract, status_values create transitions."""
    result = merge_manifests(
        profiler_signals=None,
        interaction_contract=None,
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    assert planner["workflow_hints"]["status_field"] == "status"
    assert "status_transitions" in planner["workflow_hints"]


# ---------------------------------------------------------------------------
# Management command integration
# ---------------------------------------------------------------------------


def test_merge_command_with_all_inputs(tmp_path):
    """End-to-end: write all inputs, run command, verify output."""
    from django.core.management import call_command

    signals_path = tmp_path / "signals.yaml"
    signals_path.write_text(
        yaml.safe_dump(_profiler_signals()), encoding="utf-8"
    )
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        yaml.safe_dump(_interaction_contract()), encoding="utf-8"
    )
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(_view_manifest()), encoding="utf-8"
    )
    out_path = tmp_path / "codegen-manifest.yaml"

    call_command(
        "merge_interaction_contract",
        profiler_signals=str(signals_path),
        interaction_contract=str(contract_path),
        view_manifest=str(manifest_path),
        output=str(out_path),
    )

    assert out_path.exists()
    result = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert result["version"] == 1
    assert len(result["tables"]) == 2


def test_merge_command_without_optional_inputs(tmp_path):
    """Command works with --output only (no optional inputs)."""
    from django.core.management import call_command

    out_path = tmp_path / "codegen-manifest.yaml"
    call_command(
        "merge_interaction_contract",
        output=str(out_path),
    )
    assert out_path.exists()
    result = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert result["tables"] == []


def test_merge_command_rejects_missing_file(tmp_path):
    from django.core.management import call_command, CommandError

    import pytest

    with pytest.raises(CommandError, match="not found"):
        call_command(
            "merge_interaction_contract",
            profiler_signals=str(tmp_path / "nonexistent.yaml"),
            output=str(tmp_path / "out.yaml"),
        )


# ---------------------------------------------------------------------------
# Permissions propagation (v0.4.0 Phase 3)
# ---------------------------------------------------------------------------


def _contract_with_permissions() -> dict:
    """Return an interaction contract with role_owner and role_reviewers."""
    return {
        "version": "interaction-contract-1",
        "generated_at": "2026-06-01T00:00:00Z",
        "source_id": "farm",
        "interviews": [
            {
                "role": "field_manager",
                "archetype_overrides": {
                    "Crop Planner": "form",
                },
                "role_reviewers": ["operations", "auditor"],
            },
        ],
    }


def test_permissions_propagated_to_access_hints():
    """role_owner and role_reviewers should propagate to access_hints.permissions."""
    result = merge_manifests(
        profiler_signals=None,
        interaction_contract=_contract_with_permissions(),
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    assert "access_hints" in planner
    assert "permissions" in planner["access_hints"]
    perms = planner["access_hints"]["permissions"]
    assert perms["owner_role"] == "field_manager"
    assert perms["reviewer_roles"] == ["operations", "auditor"]
    assert perms["mechanism"] == "django_groups"


def test_permissions_multiple_reviewers_preserved():
    """Multiple role_reviewers should be preserved as a list."""
    result = merge_manifests(
        profiler_signals=None,
        interaction_contract=_contract_with_permissions(),
        view_manifest=_view_manifest(),
    )
    planner = next(t for t in result["tables"] if t["model_name"] == "CropPlanner")
    perms = planner["access_hints"]["permissions"]
    assert isinstance(perms["reviewer_roles"], list)
    assert len(perms["reviewer_roles"]) == 2
    assert "operations" in perms["reviewer_roles"]
    assert "auditor" in perms["reviewer_roles"]


def test_no_permissions_key_when_role_owner_absent():
    """When a tab has no role_owner, no permissions key should appear."""
    # A tab from view_manifest with no interaction contract entry
    # and no role_hints pointing to it should not get permissions.
    contract = {
        "version": "interaction-contract-1",
        "interviews": [
            {
                "role": "viewer",
                "archetype_overrides": {},
            },
        ],
    }
    result = merge_manifests(
        profiler_signals=None,
        interaction_contract=contract,
        view_manifest=_view_manifest(),
    )
    # HarvestLog has no interaction contract entry (no archetype_overrides for it)
    harvest = next(t for t in result["tables"] if t["model_name"] == "HarvestLog")
    if "access_hints" in harvest:
        assert "permissions" not in harvest["access_hints"]
