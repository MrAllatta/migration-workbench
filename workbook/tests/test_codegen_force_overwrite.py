"""Tests that ``--force`` overwrites in place without creating ``.bak`` files."""

from __future__ import annotations

from pathlib import Path

import yaml
from django.core.management import call_command


def _contract() -> dict:
    """Return a minimal contract with one table."""
    return {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "bundle_worksheet_title": "Crop Info",
                "suggested_model_name": "crop",
                "bundle_output_path": "reference/crop_info.csv",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200, "unique": True},
                    },
                ],
            },
        ],
    }


def _manifest() -> dict:
    """Return a minimal view manifest for the Crop model."""
    return {
        "version": "view-manifest-draft-1",
        "views": [
            {
                "entity": "Crop",
                "list_display": ["name"],
                "filterable_by": ["name"],
                "editable_fields": ["name"],
            },
        ],
    }


def test_generate_models_force_does_not_create_backup(tmp_path: Path) -> None:
    """Running ``generate_models --force`` must not leave a ``.bak`` file."""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(_contract()), encoding="utf-8")

    out_path = tmp_path / "models.py"
    out_path.write_text("# pre-existing content\n", encoding="utf-8")

    call_command(
        "generate_models",
        contract=str(contract_path),
        out=str(out_path),
        app_label="core",
        force=True,
    )

    bak_path = Path(str(out_path) + ".bak")
    assert not bak_path.exists(), f".bak file should not exist, found {bak_path}"
    assert out_path.exists()
    source = out_path.read_text(encoding="utf-8")
    assert "class Crop(models.Model):" in source


def test_generate_admin_force_does_not_create_backup(tmp_path: Path) -> None:
    """Running ``generate_admin --force`` must not leave a ``.bak`` file."""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(_contract()), encoding="utf-8")

    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.dump(_manifest()), encoding="utf-8")

    out_path = tmp_path / "admin.py"
    out_path.write_text("# pre-existing content\n", encoding="utf-8")

    call_command(
        "generate_admin",
        contract=str(contract_path),
        manifest=str(manifest_path),
        out=str(out_path),
        app_label="core",
        force=True,
    )

    bak_path = Path(str(out_path) + ".bak")
    assert not bak_path.exists(), f".bak file should not exist, found {bak_path}"
    assert out_path.exists()
    source = out_path.read_text(encoding="utf-8")
    assert "@admin.register(Crop)" in source