"""Tests for the generate_import management command."""

from pathlib import Path
from django.core.management import call_command


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
        "    model_meta:\n      app_label: \"myapp\"\n", ""
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
