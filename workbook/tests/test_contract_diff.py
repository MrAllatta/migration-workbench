"""Tests for workbook.codegen.contract.diff_contracts."""

from __future__ import annotations

from workbook.codegen.contract import diff_contracts


def _make_table(name, fields=None, meta=None):
    """Build a minimal contract table dict."""
    model_name = "".join(
        p.capitalize() for p in name.replace("-", "_").split("_")
    )
    table = {
        "suggested_model_name": name,
        "model_name": model_name,
        "columns": fields or [],
    }
    if meta:
        table["model_meta"] = meta
    return table


def test_diff_identical_contracts():
    """Two identical contracts produce an empty diff."""
    contract = {

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

        "source": {},
        "tables": [
            _make_table("crop"),
            _make_table("legacy_crop"),
        ],
    }
    new_contract = {

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
    old_contract = {"source": {}, "tables": [old_table]}
    new_contract = {"source": {}, "tables": [new_table]}
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
    old_contract = {"source": {}, "tables": [old_table]}
    new_contract = {"source": {}, "tables": [new_table]}
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
    old_contract = {"source": {}, "tables": [old_table]}
    new_contract = {"source": {}, "tables": [new_table]}
    result = diff_contracts(old_contract, new_contract)
    changed = result["model_diffs"]["Crop"]["fields_changed"]
    assert len(changed) == 1
    assert changed[0]["class"] == {
        "old": "models.TextField",
        "new": "models.CharField",
    }
    assert changed[0]["kwargs"]["max_length"] == {"old": None, "new": 500}


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_contract_diff_cli_text(tmp_path):
    """CLI emits human-readable text with no args by default."""
    from deployment.wb_cli import main
    import sys

    old_path = tmp_path / "old.yaml"
    new_path = tmp_path / "new.yaml"
    old_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")
    new_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")

    sys.argv = ["wb", "contract", "diff",
                "--old", str(old_path),
                "--new", str(new_path)]
    rc = main()
    assert rc == 0


def test_contract_diff_cli_renders_text(tmp_path, capsys):
    """Direct test of _contract_diff handler text output."""
    from deployment.wb_cli import _contract_diff
    import argparse

    old_path = tmp_path / "old.yaml"
    new_path = tmp_path / "new.yaml"
    old_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")
    new_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")

    args = argparse.Namespace(
        old=str(old_path), new=str(new_path), json=False
    )
    rc = _contract_diff(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "identical" in captured.out.lower()


def test_contract_diff_cli_json(tmp_path, capsys):
    """Direct test of _contract_diff handler JSON output."""
    from deployment.wb_cli import _contract_diff
    import argparse
    import json

    old_path = tmp_path / "old.yaml"
    new_path = tmp_path / "new.yaml"
    old_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")
    new_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")

    args = argparse.Namespace(
        old=str(old_path), new=str(new_path), json=True
    )
    rc = _contract_diff(args)
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
