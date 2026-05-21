"""Tests for the generate_models management command."""

from django.core.management import call_command
import yaml


CONTRACT_WITH_APP_LABEL = """\
tables:
  - suggested_model_name: "Widget"
    model_name: "Widget"
    columns:
      - suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 255}
    model_meta:
      app_label: "myapp"
"""


def test_generate_models_reads_app_label_from_contract(tmp_path):
    """When --app-label is not passed, generate_models should read from
    each table's model_meta.app_label in the contract."""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(CONTRACT_WITH_APP_LABEL)
    out_path = tmp_path / "models.py"

    call_command(
        "generate_models",
        contract=str(contract_path),
        out=str(out_path),
        force=True,
    )

    source = out_path.read_text()
    assert "# App label: myapp" in source, (
        f"Expected header comment to use 'myapp', got:\n{source}"
    )
    assert 'db_table = "myapp_Widget"' in source


def test_generate_models_cli_app_label_overrides_contract(tmp_path):
    """When --app-label is explicitly passed, it should override the contract."""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(CONTRACT_WITH_APP_LABEL)
    out_path = tmp_path / "models.py"

    call_command(
        "generate_models",
        contract=str(contract_path),
        out=str(out_path),
        app_label="override",
        force=True,
    )

    source = out_path.read_text()
    assert "# App label: override" in source
    assert 'db_table = "override_Widget"' in source


def test_generate_models_continue_on_error_skips_invalid(tmp_path, monkeypatch):
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        yaml.safe_dump({
            "version": "1.0",
            "tables": [
                {"model_name": "Valid", "columns": [{"suggested_field_name": "name", "django_field_class": "models.CharField", "django_field_kwargs": {"max_length": 100}}]},
                {"model_name": "", "columns": []},
            ],
        })
    )
    out = tmp_path / "models.py"
    call_command("generate_models", contract=str(contract), out=str(out), force=True, continue_on_error=True)
    source = out.read_text()
    assert "class Valid" in source
    import re
    other_classes = re.findall(r"^class \w+", source, re.MULTILINE)
    assert other_classes == ["class Valid"]
