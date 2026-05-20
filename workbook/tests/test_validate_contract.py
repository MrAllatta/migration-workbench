def test_strict_validate_duplicate_model():
    from workbook.codegen.contract import strict_validate_contract
    contract = {
        "tables": [
            {"model_name": "Crop", "columns": []},
            {"model_name": "Crop", "columns": []},
        ]
    }
    errors = strict_validate_contract(contract)
    assert any("VALIDATE_DUPLICATE_MODEL" in e for e in errors)


def test_strict_validate_invalid_field():
    from workbook.codegen.contract import strict_validate_contract
    contract = {
        "tables": [
            {
                "model_name": "Unit",
                "columns": [{"suggested_field_name": "201_unit"}],
            }
        ]
    }
    errors = strict_validate_contract(contract)
    assert any("VALIDATE_INVALID_FIELD_NAME" in e for e in errors)


def test_strict_validate_null_model():
    from workbook.codegen.contract import strict_validate_contract
    contract = {
        "tables": [
            {"model_name": "", "columns": []},
        ]
    }
    errors = strict_validate_contract(contract)
    assert any("VALIDATE_NULL_MODEL" in e for e in errors)