"""Tests for workbook.codegen.contract.diff_contracts."""

from __future__ import annotations

from workbook.codegen.contract import diff_contracts


def _make_table(name, fields=None, meta=None):
    """Build a minimal contract table dict."""
    table = {
        "suggested_model_name": name,
        "columns": fields or [],
    }
    if meta:
        table["model_meta"] = meta
    return table


def test_diff_identical_contracts():
    """Two identical contracts produce an empty diff."""
    contract = {
        "version": "1.1",
        "source": {"provider": "google_sheets"},
        "tables": [
            _make_table("crop", [
                {"suggested_field_name": "name",
                 "django_field_class": "models.CharField",
                 "django_field_kwargs": {"max_length": 200}},
            ]),
        ],
    }
    result = diff_contracts(contract, contract)
    assert result == {}


def test_diff_model_added_and_removed():
    old_contract = {
        "version": "1.1",
        "source": {},
        "tables": [
            _make_table("crop"),
            _make_table("legacy_crop"),
        ],
    }
    new_contract = {
        "version": "1.1",
        "source": {},
        "tables": [
            _make_table("crop"),
            _make_table("inventory_entry"),
        ],
    }
    result = diff_contracts(old_contract, new_contract)
    assert "models_removed" in result
    assert "LegacyCrop" in result["models_removed"]
    assert "models_added" in result
    assert "InventoryEntry" in result["models_added"]


def test_diff_field_changes():
    old_table = _make_table("crop", [
        {"suggested_field_name": "name",
         "django_field_class": "models.CharField",
         "django_field_kwargs": {"max_length": 100}},
        {"suggested_field_name": "legacy_id",
         "django_field_class": "models.IntegerField",
         "django_field_kwargs": {}},
    ])
    new_table = _make_table("crop", [
        {"suggested_field_name": "name",
         "django_field_class": "models.CharField",
         "django_field_kwargs": {"max_length": 200}},
        {"suggested_field_name": "variety",
         "django_field_class": "models.CharField",
         "django_field_kwargs": {"max_length": 100}},
    ])
    old_contract = {"version": "1.1", "source": {}, "tables": [old_table]}
    new_contract = {"version": "1.1", "source": {}, "tables": [new_table]}
    result = diff_contracts(old_contract, new_contract)
    diffs = result["model_diffs"]["Crop"]
    assert diffs["fields_added"] == [
        {"name": "variety", "class": "models.CharField",
         "kwargs": {"max_length": 100}}
    ]
    assert diffs["fields_removed"] == [
        {"name": "legacy_id", "class": "models.IntegerField", "kwargs": {}}
    ]
    assert diffs["fields_changed"] == [
        {"name": "name",
         "class": {"old": "models.CharField", "new": "models.CharField"},
         "kwargs": {"max_length": {"old": 100, "new": 200}}}
    ]


def test_diff_meta_changes():
    old_table = _make_table("crop", meta={
        "verbose_name": "Crop",
        "unique_together": [["name"]],
        "ordering": ["name"],
    })
    new_table = _make_table("crop", meta={
        "verbose_name": "Crop",
        "unique_together": [["name", "variety"]],
        "ordering": ["name"],
    })
    old_contract = {"version": "1.1", "source": {}, "tables": [old_table]}
    new_contract = {"version": "1.1", "source": {}, "tables": [new_table]}
    result = diff_contracts(old_contract, new_contract)
    diffs = result["model_diffs"]["Crop"]
    assert "meta_changed" in diffs
    assert "unique_together" in diffs["meta_changed"]
    assert diffs["meta_changed"]["unique_together"] == {
        "old": [["name"]],
        "new": [["name", "variety"]],
    }
    # verbose_name and ordering unchanged — not in meta_changed
    assert "verbose_name" not in diffs["meta_changed"]
    assert "ordering" not in diffs["meta_changed"]


def test_diff_field_class_change():
    old_table = _make_table("crop", [
        {"suggested_field_name": "notes",
         "django_field_class": "models.TextField",
         "django_field_kwargs": {}},
    ])
    new_table = _make_table("crop", [
        {"suggested_field_name": "notes",
         "django_field_class": "models.CharField",
         "django_field_kwargs": {"max_length": 500}},
    ])
    old_contract = {"version": "1.1", "source": {}, "tables": [old_table]}
    new_contract = {"version": "1.1", "source": {}, "tables": [new_table]}
    result = diff_contracts(old_contract, new_contract)
    changed = result["model_diffs"]["Crop"]["fields_changed"]
    assert len(changed) == 1
    assert changed[0]["class"] == {
        "old": "models.TextField",
        "new": "models.CharField",
    }
    assert changed[0]["kwargs"]["max_length"] == {"old": None, "new": 500}
