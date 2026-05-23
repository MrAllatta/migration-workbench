from workbook.codegen.contract import strict_validate_contract
from workbook.codegen.validation_pipeline import ValidationResult


def test_strict_validate_duplicate_model():
    contract = {
        "tables": [
            {"model_name": "Crop", "columns": []},
            {"model_name": "Crop", "columns": []},
        ]
    }
    results = strict_validate_contract(contract)
    assert isinstance(results, list)
    assert all(isinstance(r, ValidationResult) for r in results)
    assert any(r.model_name == "Crop" and r.check_id == "WORKBOOK-CONTRACT-DUPLICATE-MODEL" for r in results)


def test_strict_validate_invalid_field():
    contract = {
        "tables": [
            {
                "model_name": "Unit",
                "columns": [{"suggested_field_name": "201_unit"}],
            }
        ]
    }
    results = strict_validate_contract(contract)
    assert isinstance(results, list)
    assert any(r.model_name == "Unit" and r.check_id == "WORKBOOK-CONTRACT-INVALID-FIELD-NAME" for r in results)


def test_strict_validate_null_model():
    contract = {
        "tables": [
            {"model_name": "", "columns": []},
        ]
    }
    results = strict_validate_contract(contract)
    assert isinstance(results, list)
    assert any(r.model_name == "_UNNAMED" and r.check_id == "WORKBOOK-CONTRACT-NULL-MODEL" for r in results)


def test_strict_validate_returns_empty_for_valid():
    contract = {
        "tables": [
            {"model_name": "Crop", "columns": [{"suggested_field_name": "name"}]},
        ]
    }
    results = strict_validate_contract(contract)
    assert results == []
