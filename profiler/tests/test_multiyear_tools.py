import json
from io import StringIO

from django.core.management import call_command

from profiler.tools.farm.multiyear import build_multiyear_index, select_tabs_from_inventory


def test_build_multiyear_index_filters_in_scope_codes():
    payload = {
        "name": "Crop Plans",
        "folders": [
            {
                "name": "2026 Crop Plan",
                "folders": [],
                "spreadsheets": [
                    {"id": "sheet-201", "name": "201 Farm Grown Crop List LSF 2026", "tabs": [{"title": "Crop Info"}]},
                    {"id": "sheet-999", "name": "999 Ignore Me 2026", "tabs": []},
                ],
                "other_files": [],
            }
        ],
        "spreadsheets": [],
        "other_files": [],
    }
    rows = build_multiyear_index(payload, {"201", "202"})
    assert len(rows) == 1
    assert rows[0]["workbook_code"] == "201"
    assert rows[0]["year"] == 2026


def test_select_tabs_from_inventory_scores_operational_tabs():
    index_records = [
        {"year": 2026, "workbook_code": "402", "spreadsheet_id": "sheet-402", "spreadsheet_name": "402 Crop Plan LSF 2026"}
    ]
    inventory_rows = [
        {"spreadsheet_id": "sheet-402", "sheet_id": 1, "rows": 1200, "cols": 40, "tab_title": "Crop Planner"},
        {"spreadsheet_id": "sheet-402", "sheet_id": 2, "rows": 40, "cols": 6, "tab_title": "INDEX"},
    ]
    selected = select_tabs_from_inventory(index_records, inventory_rows)
    assert any(row["tab_title"] == "Crop Planner" for row in selected)
    assert not any(row["tab_title"] == "INDEX" for row in selected)


def test_profile_multiyear_smoke_writes_output(tmp_path):
    config = {
        "folder_id": "folder-1",
        "in_scope_workbooks": ["201", "202"],
    }
    config_path = tmp_path / "multiyear.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    out = StringIO()
    call_command("profile_multiyear", config=str(config_path), out_dir=str(tmp_path), date_stamp="2026-04-28", smoke=True, stdout=out)

    smoke_path = tmp_path / "profile_multiyear_smoke_2026-04-28.json"
    assert smoke_path.exists()
    payload = json.loads(smoke_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "smoke"


def test_profile_preflight_smoke_ok():
    out = StringIO()
    call_command("profile_preflight", smoke=True, stdout=out)
    assert "smoke ok" in out.getvalue()

