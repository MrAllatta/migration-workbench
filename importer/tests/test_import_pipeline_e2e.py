"""End-to-end tests exercising generate_import -> BaseImportCommand runtime."""

import json
from pathlib import Path

import pytest
from django.core.management import call_command

from examples.models import ExampleBlock, ExampleCrop, ExampleFarm
from workbook.codegen.contract import load_contract
from workbook.codegen.import_generator import render_import_py


CONTRACT_PATH = "example_data/import_pipeline_contract.example.yaml"


@pytest.fixture
def fresh_db(db):
    """Clear all example models for clean import."""
    ExampleFarm.objects.all().delete()
    ExampleBlock.objects.all().delete()
    ExampleCrop.objects.all().delete()
    return db


class TestImportPipelineE2E:
    def test_contract_loads_with_import_configs(self):
        contract = load_contract(CONTRACT_PATH)
        tables_with_import = [
            t for t in contract["tables"]
            if t.get("import_config")
        ]
        assert len(tables_with_import) == 3

    def test_generated_import_contains_model_methods(self):
        contract = load_contract(CONTRACT_PATH)
        source = render_import_py(contract, app_label="examples")
        assert "class GeneratedImportExamples" in source
        assert "_import_examplefarm" in source
        assert "_import_examplefield" in source
        assert "_import_examplevariety" in source

    def test_generated_import_contains_fk_resolution(self):
        contract = load_contract(CONTRACT_PATH)
        source = render_import_py(contract, app_label="examples")
        assert "_resolve_fk_by_text" in source
        assert "ExampleFarm" in source
        assert "ExampleCrop" in source

    def test_generated_import_contains_field_transforms(self):
        contract = load_contract(CONTRACT_PATH)
        variety_table = next(
            t for t in contract["tables"]
            if t["suggested_model_name"] == "ExampleVariety"
        )
        assert "field_transforms" in variety_table["import_config"]
        assert "full_description" in variety_table["import_config"]["field_transforms"]
        source = render_import_py(contract, app_label="examples")
        assert "'full_description'" in source

    def test_generated_import_contains_tier_structure(self):
        contract = load_contract(CONTRACT_PATH)
        source = render_import_py(contract, app_label="examples")
        assert "TIER 1" in source
        assert "TIER 2" in source
        assert "TIER 3" in source

    def test_generated_import_contains_integrity_error_catch(self):
        contract = load_contract(CONTRACT_PATH)
        source = render_import_py(contract, app_label="examples")
        assert "IntegrityError" in source
        assert "unique_violation" in source
        assert "row_exception" in source


class TestImportPipelineReference:
    """Test the existing reference import for regression."""

    def test_import_reference_example_creates_records(self, fresh_db, tmp_path):
        summary_path = tmp_path / "summary.json"
        call_command(
            "import_reference_example",
            "example_data",
            "--summary-json",
            str(summary_path),
        )
        assert ExampleBlock.objects.count() >= 1
        assert ExampleCrop.objects.count() >= 2
        payload = json.loads(summary_path.read_text())
        assert payload["status"] == "ok"
        assert payload["schema_version"] == "1.0"