"""Tests for validate_contract_tables FK target validation in extra_fields."""

import pytest

from workbook.codegen.contract import validate_contract_tables


def test_validate_contract_tables_warns_on_missing_fk_target_in_extra_fields():
    contract = {
        "tables": [
            {
                "suggested_model_name": "planting",
                "model_name": "Planting",
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


def test_validate_contract_command_valid(tmp_path):
    """A valid contract passes validation."""
    from io import StringIO
    from django.core.management import call_command

    contract = tmp_path / "valid.yaml"
    contract.write_text("""\
version: "2.0"
tables:
  - suggested_model_name: Widget
    model_name: Widget
    columns:
      - source_column: Name
        suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 200}
""")

    out = StringIO()
    call_command("validate_contract", contract=str(contract), stdout=out)
    assert "Contract is valid" in out.getvalue()


def test_validate_contract_command_missing_model_name(tmp_path):
    """A contract missing model_name fails validation."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    contract = tmp_path / "missing.yaml"
    contract.write_text("""\
version: "2.0"
tables:
  - suggested_model_name: Widget
    # no model_name
    columns: []
""")

    with pytest.raises(CommandError, match="validation error"):
        call_command("validate_contract", contract=str(contract))


def test_validate_contract_command_fk_target_not_found(tmp_path):
    """FK target that doesn't match any model_name produces a warning."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    contract = tmp_path / "bad_fk.yaml"
    contract.write_text("""\
version: "2.0"
tables:
  - suggested_model_name: Crop
    model_name: Crop
    columns:
      - source_column: Name
        suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 200}
  - suggested_model_name: Planting
    model_name: Planting
    columns:
      - source_column: Crop
        suggested_field_name: crop
        django_field_class: models.ForeignKey
        django_field_kwargs:
          to: NonExistent    # doesn't match any model_name
          on_delete: models.CASCADE
""")

    with pytest.raises(CommandError, match="validation warning"):
        call_command("validate_contract", contract=str(contract))
