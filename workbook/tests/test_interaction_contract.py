"""Tests for the interaction-contract YAML schema model (Layer 2)."""

from __future__ import annotations

import yaml

from workbook.interaction_contract import (
    INTERACTION_CONTRACT_VERSION,
    build_interaction_contract,
    validate_interaction_contract,
)

# ---------------------------------------------------------------------------
# Validation: top-level structure
# ---------------------------------------------------------------------------


def test_valid_minimal_contract():
    """A contract with just version and interviews is valid."""
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [{"role": "field_manager"}],
    }
    errors = validate_interaction_contract(raw)
    assert errors == [], f"expected no errors, got: {errors}"


def test_missing_version():
    raw = {"interviews": [{"role": "field_manager"}]}
    errors = validate_interaction_contract(raw)
    assert any("version" in e for e in errors)


def test_invalid_version():
    raw = {
        "version": "v0",
        "interviews": [{"role": "field_manager"}],
    }
    errors = validate_interaction_contract(raw)
    assert any("v0" in e for e in errors)


def test_missing_interviews():
    raw = {"version": INTERACTION_CONTRACT_VERSION}
    errors = validate_interaction_contract(raw)
    assert any("interviews" in e for e in errors)


def test_interviews_not_a_list():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": "not_a_list",
    }
    errors = validate_interaction_contract(raw)
    assert any("list" in e for e in errors)


def test_not_a_dict():
    errors = validate_interaction_contract("string")
    assert errors


# ---------------------------------------------------------------------------
# Validation: interview entry structure
# ---------------------------------------------------------------------------


def test_interview_missing_role():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [{"workflow_notes": "some note"}],
    }
    errors = validate_interaction_contract(raw)
    assert any("missing required" in e and "role" in e for e in errors)


def test_interview_role_must_be_string():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [{"role": 42}],
    }
    errors = validate_interaction_contract(raw)
    assert any("role" in e and "string" in e for e in errors)


# ---------------------------------------------------------------------------
# Validation: archetype_overrides
# ---------------------------------------------------------------------------


def test_archetype_overrides_valid():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [
            {
                "role": "field_manager",
                "archetype_overrides": {"Crop Planner": "form"},
            }
        ],
    }
    errors = validate_interaction_contract(raw)
    assert errors == [], f"expected no errors, got: {errors}"


def test_archetype_overrides_invalid_value():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [
            {
                "role": "field_manager",
                "archetype_overrides": {"Crop Planner": "spreadsheet"},
            }
        ],
    }
    errors = validate_interaction_contract(raw)
    assert any("spreadsheet" in e for e in errors)


def test_archetype_overrides_non_string_value():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [
            {
                "role": "field_manager",
                "archetype_overrides": {"Crop Planner": 123},
            }
        ],
    }
    errors = validate_interaction_contract(raw)
    assert any("must be a string" in e for e in errors)


def test_archetype_overrides_not_a_dict():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [
            {
                "role": "field_manager",
                "archetype_overrides": "not_a_dict",
            }
        ],
    }
    errors = validate_interaction_contract(raw)
    assert any("must be a mapping" in e for e in errors)


# ---------------------------------------------------------------------------
# Validation: status_semantics
# ---------------------------------------------------------------------------


def test_status_semantics_valid():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [
            {
                "role": "field_manager",
                "status_semantics": {
                    "planted": "active",
                    "harvested": "complete",
                },
            }
        ],
    }
    errors = validate_interaction_contract(raw)
    assert errors == [], f"expected no errors, got: {errors}"


def test_status_semantics_non_string_value():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [
            {
                "role": "field_manager",
                "status_semantics": {"planted": 42},
            }
        ],
    }
    errors = validate_interaction_contract(raw)
    assert any("must be a string" in e for e in errors)


def test_status_semantics_not_a_dict():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [
            {
                "role": "field_manager",
                "status_semantics": "not_a_dict",
            }
        ],
    }
    errors = validate_interaction_contract(raw)
    assert any("must be a mapping" in e for e in errors)


# ---------------------------------------------------------------------------
# Validation: workflow_notes, weekly_actions, access_hints
# ---------------------------------------------------------------------------


def test_workflow_notes_non_string():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [
            {
                "role": "field_manager",
                "workflow_notes": 123,
            }
        ],
    }
    errors = validate_interaction_contract(raw)
    assert any("workflow_notes" in e and "string" in e for e in errors)


def test_weekly_actions_valid():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [
            {
                "role": "field_manager",
                "weekly_actions": [
                    "Mark crops as harvested",
                    "Add weekly bed count",
                ],
            }
        ],
    }
    errors = validate_interaction_contract(raw)
    assert errors == [], f"expected no errors, got: {errors}"


def test_weekly_actions_not_a_list():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [
            {
                "role": "field_manager",
                "weekly_actions": "not_a_list",
            }
        ],
    }
    errors = validate_interaction_contract(raw)
    assert any("must be a list" in e for e in errors)


def test_weekly_actions_non_string_item():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [
            {
                "role": "field_manager",
                "weekly_actions": ["valid action", 42],
            }
        ],
    }
    errors = validate_interaction_contract(raw)
    assert any("must be a string" in e for e in errors)


def test_access_hints_must_be_dict():
    raw = {
        "version": INTERACTION_CONTRACT_VERSION,
        "interviews": [
            {
                "role": "field_manager",
                "access_hints": "not_a_dict",
            }
        ],
    }
    errors = validate_interaction_contract(raw)
    assert any("must be a mapping" in e for e in errors)


# ---------------------------------------------------------------------------
# build_interaction_contract
# ---------------------------------------------------------------------------


def test_build_minimal():
    contract = build_interaction_contract(interviews=[{"role": "field_manager"}])
    assert contract["version"] == INTERACTION_CONTRACT_VERSION
    assert "generated_at" in contract
    assert contract["source_id"] == ""
    assert len(contract["interviews"]) == 1
    assert contract["interviews"][0]["role"] == "field_manager"


def test_build_with_source_id():
    contract = build_interaction_contract(
        source_id="farm_corpus",
        interviews=[{"role": "field_manager"}],
    )
    assert contract["source_id"] == "farm_corpus"


def test_build_no_interviews():
    contract = build_interaction_contract()
    assert contract["interviews"] == []


def test_build_with_full_entry():
    contract = build_interaction_contract(
        source_id="farm_corpus",
        interviews=[
            {
                "role": "field_manager",
                "archetype_overrides": {"Crop Planner": "form"},
                "status_semantics": {"planted": "active"},
                "workflow_notes": "Weekly update by field managers.",
                "weekly_actions": ["Mark crops", "Add beds"],
                "access_hints": {"internal_only": False},
            }
        ],
    )
    assert contract["interviews"][0]["archetype_overrides"]["Crop Planner"] == "form"
    assert contract["interviews"][0]["weekly_actions"] == ["Mark crops", "Add beds"]


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


def test_yaml_round_trip():
    """A valid interaction contract survives a YAML dump/load cycle."""
    contract = build_interaction_contract(
        source_id="farm",
        interviews=[
            {
                "role": "field_manager",
                "archetype_overrides": {"Crop Planner": "form"},
                "status_semantics": {"planted": "active"},
                "workflow_notes": "Test note.",
            }
        ],
    )
    serialized = yaml.safe_dump(contract, sort_keys=False)
    reloaded = yaml.safe_load(serialized)
    errors = validate_interaction_contract(reloaded)
    assert errors == [], f"round-trip validation failed: {errors}"


# ---------------------------------------------------------------------------
# merge_strategy
# ---------------------------------------------------------------------------


def test_merge_strategy():
    from workbook.interaction_contract import merge_strategy

    strategy = merge_strategy()
    assert "Profiler signal" in strategy
    assert "Interaction contract" in strategy
    assert "codegen manifest" in strategy
