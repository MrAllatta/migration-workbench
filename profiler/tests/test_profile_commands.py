import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command


def test_profile_tab_lists_tabs():
    class FakeSheetsGet:
        def execute(self):
            return {
                "sheets": [
                    {
                        "properties": {
                            "title": "Tab A",
                            "sheetId": 11,
                            "index": 0,
                            "gridProperties": {"rowCount": 10, "columnCount": 5},
                        }
                    }
                ]
            }

    class FakeSpreadsheets:
        def get(self, **kwargs):
            return FakeSheetsGet()

    class FakeService:
        def spreadsheets(self):
            return FakeSpreadsheets()

    with patch("profiler.management.commands.profile_tab.build_google_service", return_value=FakeService()):
        out = StringIO()
        call_command("profile_tab", spreadsheet_id="abc123", stdout=out)

    rendered = out.getvalue()
    assert "Tab A" in rendered
    assert "sheetId=11" in rendered


def test_profile_tab_writes_out_files(tmp_path):
    class FakeSheetsGet:
        def execute(self):
            return {
                "properties": {"title": "Book 1"},
                "sheets": [
                    {
                        "properties": {
                            "title": "Tab A",
                            "gridProperties": {"rowCount": 3, "columnCount": 3},
                        },
                        "data": [
                            {
                                "startRow": 0,
                                "startColumn": 0,
                                "rowData": [
                                    {
                                        "values": [
                                            {"userEnteredValue": {"stringValue": "Header"}},
                                            {"userEnteredValue": {"stringValue": "Val"}},
                                        ]
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }

    class FakeSpreadsheets:
        def get(self, **kwargs):
            return FakeSheetsGet()

    class FakeService:
        def spreadsheets(self):
            return FakeSpreadsheets()

    out_path = tmp_path / "tab_profile.json"
    with patch("profiler.management.commands.profile_tab.build_google_service", return_value=FakeService()):
        call_command("profile_tab", spreadsheet_id="abc123", tab="Tab A", out=str(out_path))

    assert out_path.exists()
    assert out_path.with_suffix(".md").exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["summary"]["tab_title"] == "Tab A"


def test_scan_formula_patterns_smoke_writes_output(tmp_path):
    config = {
        "workbooks": [{"name": "Workbook 1", "spreadsheet_id": "sheet-id-1"}],
        "patterns": [{"name": "sum", "regex": r"SUM\("}],
    }
    config_path = tmp_path / "scan.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    out_path = tmp_path / "scan_results.json"

    call_command("scan_formula_patterns", config=str(config_path), out=str(out_path), smoke=True)

    result = json.loads(out_path.read_text(encoding="utf-8"))
    assert result["mode"] == "smoke"
    assert result["pattern_count"] == 1


def test_profile_drive_folder_smoke():
    out = StringIO()
    call_command("profile_drive_folder", smoke=True, stdout=out)
    assert "smoke ok" in out.getvalue()
