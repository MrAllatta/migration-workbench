"""Tests for the generate_import management command."""

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest
import yaml


CONTRACT_WITH_APP_LABEL = """\
tables:
  - suggested_model_name: "Widget"
    model_name: "Widget"
    bundle_worksheet_title: "Widgets"
    columns:
      - suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 255}
    model_meta:
      app_label: "myapp"
    import_config:
      import_key: name
      unique_on: [name]
      bundle_path: "widgets.csv"
"""


def test_generate_import_reads_app_label_from_contract(tmp_path):
    """When --app-label is not passed, generate_import should read from
    each table's model_meta.app_label in the contract."""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(CONTRACT_WITH_APP_LABEL)
    out_path = tmp_path / "import_data.py"

    call_command(
        "generate_import",
        contract=str(contract_path),
        out=str(out_path),
        force=True,
    )

    source = out_path.read_text()
    assert "from myapp.models import Widget" in source, (
        f"Expected generated import to use app_label 'myapp', got:\n{source}"
    )
    assert 'help = "Import myapp data' in source, (
        "Expected help text to use app_label 'myapp'"
    )


def test_generate_import_cli_app_label_overrides_contract(tmp_path):
    """When --app-label is explicitly passed, it should override the contract."""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(CONTRACT_WITH_APP_LABEL)
    out_path = tmp_path / "import_data.py"

    call_command(
        "generate_import",
        contract=str(contract_path),
        out=str(out_path),
        app_label="override",
        force=True,
    )

    source = out_path.read_text()
    assert "from override.models import Widget" in source
    assert 'help = "Import override data' in source


def test_generate_import_falls_back_to_core(tmp_path):
    """When contract has no app_label, generate_import falls back to 'core'."""
    contract_no_label = CONTRACT_WITH_APP_LABEL.replace(
        '    model_meta:\n      app_label: "myapp"\n', ""
    )
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(contract_no_label)
    out_path = tmp_path / "import_data.py"

    call_command(
        "generate_import",
        contract=str(contract_path),
        out=str(out_path),
        force=True,
    )

    source = out_path.read_text()
    assert "from core.models import Widget" in source


def test_generate_import_auto_derives_output_path(tmp_path, monkeypatch):
    """When --out is omitted, generate_import should derive path from --app-label."""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(CONTRACT_WITH_APP_LABEL)
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "backend" / "apps" / "myapp"
    mgmt_dir = app_dir / "management" / "commands"
    mgmt_dir.mkdir(parents=True, exist_ok=True)

    call_command(
        "generate_import",
        contract=str(contract_path),
        app_label="myapp",
        force=True,
    )

    expected = mgmt_dir / "import_myapp.py"
    assert expected.exists(), f"Expected {expected} to exist"


def test_generate_import_missing_bundle_path(tmp_path):
    """generate_import emits a clean error when bundle_path is missing."""

    contract = tmp_path / "contract.yaml"
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
    import_config:
      tier: 1
      # no bundle_path
""")

    out = tmp_path / "import_test.py"
    with pytest.raises(CommandError, match="bundle_path"):
        call_command("generate_import", contract=str(contract), out=str(out))


def test_generate_import_skips_invalid_tables(tmp_path, monkeypatch):
    from django.core.management import call_command
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        yaml.safe_dump({
            "version": "1.0",
            "tables": [
                {"model_name": "Valid", "import_config": {"bundle_path": "test.csv"}, "columns": [{"suggested_field_name": "name", "django_field_class": "models.CharField", "django_field_kwargs": {"max_length": 100}}]},
                {"model_name": "", "import_config": {"bundle_path": "test.csv"}, "columns": []},
            ],
        })
    )
    out = tmp_path / "import.py"
    call_command("generate_import", contract=str(contract), out=str(out), force=True)
    source = out.read_text()
    assert "Valid" in source


def test_generate_import_year_aware_contract(tmp_path):
    """When contract has {year} in bundle_path, generated command includes year-loop."""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        yaml.safe_dump({
            "version": "1.3",
            "tables": [
                {
                    "model_name": "Crop",
                    "columns": [
                        {
                            "suggested_field_name": "name",
                            "django_field_class": "models.CharField",
                            "django_field_kwargs": {"max_length": 200},
                        },
                    ],
                    "import_config": {
                        "bundle_path": "{year}/crops.csv",
                        "unique_on": ["name"],
                    },
                },
            ],
        })
    )
    out_path = tmp_path / "import_core.py"
    call_command(
        "generate_import",
        contract=str(contract_path),
        out=str(out_path),
        force=True,
    )
    source = out_path.read_text()
    assert "_resolve_years" in source
    assert "_resolve_path" in source
    assert "_run_year" in source
    assert "--year" in source


def test_generate_import_static_bundle_path_unchanged(tmp_path):
    """When contract has static bundle_path, generated command matches existing format."""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        yaml.safe_dump({
            "version": "1.3",
            "tables": [
                {
                    "model_name": "Crop",
                    "columns": [
                        {
                            "suggested_field_name": "name",
                            "django_field_class": "models.CharField",
                            "django_field_kwargs": {"max_length": 200},
                        },
                    ],
                    "import_config": {
                        "bundle_path": "crops.csv",
                        "unique_on": ["name"],
                    },
                },
            ],
        })
    )
    out_path = tmp_path / "import_core.py"
    call_command(
        "generate_import",
        contract=str(contract_path),
        out=str(out_path),
        force=True,
    )
    source = out_path.read_text()
    assert "_resolve_years" not in source
    assert "_run_year" not in source
    assert "read_bundle_tab('crops.csv'" in source
