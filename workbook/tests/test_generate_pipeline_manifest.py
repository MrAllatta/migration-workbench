"""Integration tests for the generate_pipeline_manifest management command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from django.core.management import call_command, CommandError


def _contract_yaml() -> str:
    return yaml.safe_dump({
        "source": {"provider": "google_sheets", "doc_id": "sheet123"},
        "tables": [
            {
                "bundle_worksheet_title": "Crop Planner",
                "suggested_model_name": "crop_plan_entry",
                "model_name": "CropPlanEntry",
                "bundle_output_path": "2025/crop_plan_entry.csv",
                "columns": [
                    {"source_column": "Block", "suggested_field_name": "block"},
                    {"source_column": "Crop", "suggested_field_name": "crop"},
                ],
                "import_config": {
                    "bundle_path": "2025/crop_plan_entry.csv",
                    "required_headers": ["Block", "Crop"],
                },
            }
        ],
    })


def _corpus_config_json() -> str:
    return json.dumps({
        "provider": "google_sheets",
        "drive_folder_id": "folder_abc",
        "workbook_codes": {"201": "CropPlanner"},
        "years": {
            "2025": {
                "folder_pattern": "2025_farm",
                "workbook_ids": {"201": "1QWy4GsP3cpvECVMumj5sjblIwZWfVhQAC73kQhmaqEE"},
            }
        },
    })


def test_command_generates_yaml(tmp_path):
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(_contract_yaml(), encoding="utf-8")
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(_corpus_config_json(), encoding="utf-8")
    out_path = tmp_path / "pipeline_manifest.yaml"

    call_command(
        "generate_pipeline_manifest",
        contract=str(contract_path),
        corpus_config=str(corpus_path),
        out=str(out_path),
        force=True,
    )

    assert out_path.exists()
    manifest = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert manifest["version"] == "1.0"
    assert len(manifest["tables"]) == 1
    assert manifest["tables"][0]["model"] == "crop_plan_entry"


def test_command_rejects_missing_contract(tmp_path):
    with pytest.raises(CommandError, match="contract not found"):
        call_command(
            "generate_pipeline_manifest",
            contract=str(tmp_path / "nope.yaml"),
            corpus_config=str(tmp_path / "corpus.json"),
            out=str(tmp_path / "out.yaml"),
            force=True,
        )


def test_command_rejects_missing_corpus_config(tmp_path):
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(_contract_yaml(), encoding="utf-8")
    with pytest.raises(CommandError, match="corpus_config not found"):
        call_command(
            "generate_pipeline_manifest",
            contract=str(contract_path),
            corpus_config=str(tmp_path / "nope.json"),
            out=str(tmp_path / "out.yaml"),
            force=True,
        )


def test_command_warns_on_existing_output_without_force(tmp_path):
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(_contract_yaml(), encoding="utf-8")
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(_corpus_config_json(), encoding="utf-8")
    out_path = tmp_path / "pipeline_manifest.yaml"
    out_path.write_text("# existing", encoding="utf-8")

    with pytest.raises(SystemExit):
        call_command(
            "generate_pipeline_manifest",
            contract=str(contract_path),
            corpus_config=str(corpus_path),
            out=str(out_path),
        )
