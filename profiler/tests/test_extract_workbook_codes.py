import json
from io import StringIO

from django.core.management import call_command


def test_extract_workbook_codes_smoke():
    out = StringIO()
    call_command(
        "extract_workbook_codes",
        drive_tree="/dev/null",
        config="/dev/null",
        smoke=True,
        stdout=out,
    )
    assert "smoke ok" in out.getvalue()


def test_extract_workbook_codes_extracts_codes(tmp_path):
    tree = {
        "folders": [
            {
                "name": "2026",
                "spreadsheets": [
                    {"name": "402 Farm Plan 2026"},
                    {"name": "503 Reference 2026"},
                ],
                "folders": [],
            }
        ],
        "spreadsheets": [],
    }
    tree_path = tmp_path / "drive_tree.json"
    tree_path.write_text(json.dumps(tree), encoding="utf-8")

    config = {"workbook_id_regex": r"\b(\d{3})\b"}
    config_path = tmp_path / "cohort_corpus.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    out = StringIO()
    call_command(
        "extract_workbook_codes",
        drive_tree=str(tree_path),
        config=str(config_path),
        stdout=out,
    )
    output = out.getvalue()
    assert "402" in output
    assert "503" in output


def test_extract_workbook_codes_update_config(tmp_path):
    tree = {
        "folders": [
            {
                "name": "2026",
                "spreadsheets": [{"name": "402 Farm Plan 2026"}],
                "folders": [],
            }
        ],
        "spreadsheets": [],
    }
    tree_path = tmp_path / "drive_tree.json"
    tree_path.write_text(json.dumps(tree), encoding="utf-8")

    config = {"workbook_id_regex": r"\b(\d{3})\b", "in_scope_workbooks": ["OLD"]}
    config_path = tmp_path / "cohort_corpus.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    call_command(
        "extract_workbook_codes",
        drive_tree=str(tree_path),
        config=str(config_path),
        update_config=True,
    )

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["in_scope_workbooks"] == ["402"]
    assert (config_path.with_suffix(".json.bak")).exists()
