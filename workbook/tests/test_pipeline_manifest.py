"""Tests for workbook.pipeline_manifest builder."""

import json
from pathlib import Path

import pytest


def _minimal_contract() -> dict:
    return {
        "version": "1.0",
        "source": {"provider": "google_sheets", "doc_id": "sheet123"},
        "tables": [
            {
                "bundle_worksheet_title": "Crop Planner",
                "suggested_model_name": "crop_plan_entry",
                "bundle_output_path": "{year}/crop_plan_entry.csv",
                "columns": [
                    {"source_column": "Block", "suggested_field_name": "block"},
                    {"source_column": "Crop", "suggested_field_name": "crop"},
                    {"source_column": "Status", "suggested_field_name": "status"},
                ],
                "import_config": {
                    "bundle_path": "{year}/crop_plan_entry.csv",
                    "required_headers": ["Block", "Crop", "Status"],
                    "unique_on": ["block"],
                    "column_map": {"block": "Block", "crop": "Crop", "status": "Status"},
                },
            }
        ],
    }


def _minimal_corpus_config() -> dict:
    return {
        "provider": "google_sheets",
        "drive_folder_id": "folder_abc",
        "workbook_codes": {"201": "CropPlanner"},
        "tab_selection_overrides": {"201": {"Crop Planner": True}},
        "years": {
            "2025": {
                "folder_pattern": "2025_farm",
                "workbook_ids": {"201": "1QWy4GsP3cpvECVMumj5sjblIwZWfVhQAC73kQhmaqEE"},
            }
        },
    }


def _minimal_corpus_dir(tmp_path) -> Path:
    index_path = tmp_path / "in_scope_workbook_index_2025.json"
    index_data = {
        "schema_version": "1.0",
        "workbooks": [
            {
                "workbook_code": "201",
                "year": 2025,
                "spreadsheet_id": "1QWy4GsP3cpvECVMumj5sjblIwZWfVhQAC73kQhmaqEE",
                "title": "2025 Farm Plan",
                "tabs": [
                    {"worksheet_title": "Crop Planner", "tab_position": 0},
                ],
            }
        ],
    }
    index_path.write_text(json.dumps(index_data), encoding="utf-8")
    return tmp_path


def test_build_pipeline_manifest_returns_version():
    from workbook.pipeline_manifest import build_pipeline_manifest
    contract = _minimal_contract()
    corpus_config = _minimal_corpus_config()
    result = build_pipeline_manifest(contract, corpus_config, corpus_dir=None)
    assert result["version"] == "1.0"


def test_build_pipeline_manifest_maps_tables_to_years():
    from workbook.pipeline_manifest import build_pipeline_manifest
    contract = _minimal_contract()
    corpus_config = _minimal_corpus_config()
    result = build_pipeline_manifest(contract, corpus_config, corpus_dir=None)
    assert len(result["tables"]) == 1
    table = result["tables"][0]
    assert table["model"] == "crop_plan_entry"
    assert table["bundle_worksheet_title"] == "Crop Planner"
    assert table["output_pattern"] == "{year}/crop_plan_entry.csv"


def test_build_pipeline_manifest_includes_required_headers():
    from workbook.pipeline_manifest import build_pipeline_manifest
    contract = _minimal_contract()
    corpus_config = _minimal_corpus_config()
    result = build_pipeline_manifest(contract, corpus_config, corpus_dir=None)
    table = result["tables"][0]
    assert "Block" in table["required_headers"]
    assert "Crop" in table["required_headers"]


def test_build_pipeline_manifest_with_corpus_dir_adds_years():
    from workbook.pipeline_manifest import build_pipeline_manifest
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        corpus_dir = _minimal_corpus_dir(tmp_path)
        contract = _minimal_contract()
        corpus_config = _minimal_corpus_config()
        result = build_pipeline_manifest(
            contract, corpus_config, corpus_dir=str(corpus_dir)
        )
        table = result["tables"][0]
        assert "years" in table
        assert len(table["years"]) >= 1
        year_entry = table["years"][0]
        assert year_entry["year"] == 2025
        assert "spreadsheet_id" in year_entry
