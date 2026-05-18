import json
from pathlib import Path

from django.core.management import call_command


def test_generate_source_config_from_contract(tmp_path):
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text("""
tables:
  - suggested_model_name: Crop
    model_name: Crop
    bundle_worksheet_title: Crop Info
    import_config:
      bundle_path: crop_info.csv
      required_headers: [Crop, Block]
      unique_on: [crop]
""")
    index_path = tmp_path / "in_scope_workbook_index_2024-01-01.json"
    index_path.write_text(json.dumps({
        "workbooks": [{"spreadsheet_id": "1abc", "name": "Farm Data 2024", "year": 2024}]
    }))
    out_path = tmp_path / "source_config.json"

    call_command(
        "generate_source_config",
        contract=str(contract_path),
        index=str(index_path),
        out=str(out_path),
    )

    config = json.loads(out_path.read_text())
    assert config["provider"] == "google_sheets"
    assert len(config["tabs"]) == 1
    assert config["tabs"][0]["worksheet_title"] == "Crop Info"
    assert config["tabs"][0]["required_headers"] == ["Crop", "Block"]
    assert "years" in config
    assert "2024" in config["years"]