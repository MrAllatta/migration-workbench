from workbook.codegen.contract import validate_contract_tables


def test_validate_contract_tables_warns_on_missing_fk_target_in_extra_fields():
    contract = {
        "tables": [
            {
                "suggested_model_name": "planting",
                "columns": [],
                "extra_fields": {
                    "crop": {
                        "class": "models.ForeignKey",
                        "kwargs": {"to": "Crop", "on_delete": "PROTECT"},
                    }
                },
            }
        ]
    }

    warnings = validate_contract_tables(contract)

    expected_warning = 'Planting.crop: FK target "Crop" is not a table in the contract'
    assert expected_warning in warnings
