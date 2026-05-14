"""Tests for workbook.codegen.contract.migration_safety_checks."""

from __future__ import annotations

from workbook.codegen.contract import (
    MIGRATION_SEVERITY_DANGER,
    MIGRATION_SEVERITY_WARNING,
    migration_safety_checks,
)


def test_field_removed_is_danger():
    """Removing a field produces a DANGER-level warning."""
    diffs = {
        "model_diffs": {
            "Crop": {
                "fields_removed": [
                    {"name": "legacy_id", "class": "models.IntegerField",
                     "kwargs": {}},
                ],
            },
        },
    }
    results = migration_safety_checks(diffs)
    assert len(results) == 1
    assert results[0]["severity"] == MIGRATION_SEVERITY_DANGER
    assert results[0]["model"] == "Crop"
    assert results[0]["field"] == "legacy_id"
    assert "removed" in results[0]["message"].lower()


def test_nullable_becomes_non_nullable_is_danger():
    """A field losing null=True is a DANGER — migration fails if nulls exist."""
    diffs = {
        "model_diffs": {
            "Crop": {
                "fields_changed": [
                    {
                        "name": "name",
                        "class": {"old": "models.CharField", "new": "models.CharField"},
                        "kwargs": {
                            "null": {"old": True, "new": False},
                            "max_length": {"old": 100, "new": 200},
                        },
                    },
                ],
            },
        },
    }
    results = migration_safety_checks(diffs)
    assert len(results) >= 1
    danger = [r for r in results if r["severity"] == MIGRATION_SEVERITY_DANGER]
    assert any("null" in r["message"].lower() for r in danger)
    assert danger[0]["model"] == "Crop"
    assert danger[0]["field"] == "name"


def test_field_class_changed_is_warning():
    """Changing a field's class type is a WARNING."""
    diffs = {
        "model_diffs": {
            "Crop": {
                "fields_changed": [
                    {
                        "name": "notes",
                        "class": {"old": "models.TextField", "new": "models.CharField"},
                        "kwargs": {"max_length": {"old": None, "new": 500}},
                    },
                ],
            },
        },
    }
    results = migration_safety_checks(diffs)
    assert len(results) >= 1
    warnings = [r for r in results if r["severity"] == MIGRATION_SEVERITY_WARNING]
    assert any("class" in r["message"].lower() or "type" in r["message"].lower()
               for r in warnings)


def test_max_length_decreased_is_warning():
    """Reducing max_length is a WARNING — truncation risk."""
    diffs = {
        "model_diffs": {
            "Crop": {
                "fields_changed": [
                    {
                        "name": "name",
                        "class": {"old": "models.CharField", "new": "models.CharField"},
                        "kwargs": {
                            "max_length": {"old": 200, "new": 100},
                        },
                    },
                ],
            },
        },
    }
    results = migration_safety_checks(diffs)
    assert len(results) >= 1
    warnings = [r for r in results if r["severity"] == MIGRATION_SEVERITY_WARNING]
    assert any("max_length" in r["message"] for r in warnings)


def test_unique_added_is_warning():
    """Adding unique=True is a WARNING — migration fails if duplicates exist."""
    diffs = {
        "model_diffs": {
            "Crop": {
                "fields_changed": [
                    {
                        "name": "name",
                        "class": {"old": "models.CharField", "new": "models.CharField"},
                        "kwargs": {
                            "unique": {"old": None, "new": True},
                        },
                    },
                ],
            },
        },
    }
    results = migration_safety_checks(diffs)
    assert len(results) >= 1
    warnings = [r for r in results if r["severity"] == MIGRATION_SEVERITY_WARNING]
    assert any("unique" in r["message"].lower() for r in warnings)


def test_non_nullable_field_added_without_default_is_warning():
    """Adding a non-nullable field without a default is a WARNING."""
    diffs = {
        "model_diffs": {
            "Crop": {
                "fields_added": [
                    {"name": "required_field", "class": "models.CharField",
                     "kwargs": {"max_length": 100}},
                ],
            },
        },
    }
    results = migration_safety_checks(diffs)
    assert len(results) >= 1
    warnings = [r for r in results if r["severity"] == MIGRATION_SEVERITY_WARNING]
    assert any("null" in r["message"].lower() or "default" in r["message"].lower()
               for r in warnings)


def test_no_diffs_returns_empty():
    """Empty diff produces no safety warnings."""
    assert migration_safety_checks({}) == []
    assert migration_safety_checks({"model_diffs": {}}) == []
