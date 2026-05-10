import json
import re
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from profiler.tools.cohort_corpus import (
    apply_tab_selection_overrides,
    build_cohort_corpus_index,
    run_cohort_corpus,
    score_tab,
    select_tabs_from_inventory,
)


def test_build_cohort_corpus_index_custom_workbook_id_regex():
    """Non-default filenames are indexed when workbook_id_regex matches."""
    payload = {
        "name": "Corpus",
        "folders": [
            {
                "name": "Season 2026",
                "folders": [],
                "spreadsheets": [
                    {"id": "sh1", "name": "Export WB-K master", "tabs": []}
                ],
                "other_files": [],
            }
        ],
        "spreadsheets": [],
        "other_files": [],
    }
    rows = build_cohort_corpus_index(
        payload,
        {"K"},
        workbook_id_re=re.compile(r"\bWB-([A-Z])\b"),
    )
    assert len(rows) == 1
    assert rows[0]["workbook_code"] == "K"
    assert rows[0]["year"] == 2026


def test_build_cohort_corpus_index_filters_in_scope_codes():
    payload = {
        "name": "Workbook Corpus",
        "folders": [
            {
                "name": "2026 Planning",
                "folders": [],
                "spreadsheets": [
                    {
                        "id": "sheet-201",
                        "name": "201 Reference List LSF 2026",
                        "tabs": [{"title": "Reference Info"}],
                    },
                    {"id": "sheet-999", "name": "999 Ignore Me 2026", "tabs": []},
                ],
                "other_files": [],
            }
        ],
        "spreadsheets": [],
        "other_files": [],
    }
    rows = build_cohort_corpus_index(payload, {"201", "202"})
    assert len(rows) == 1
    assert rows[0]["workbook_code"] == "201"
    assert rows[0]["year"] == 2026


def test_select_tabs_from_inventory_scores_operational_tabs():
    index_records = [
        {
            "year": 2026,
            "workbook_code": "402",
            "spreadsheet_id": "sheet-402",
            "spreadsheet_name": "402 Planning LSF 2026",
        }
    ]
    inventory_rows = [
        {
            "spreadsheet_id": "sheet-402",
            "sheet_id": 1,
            "rows": 1200,
            "cols": 40,
            "tab_title": "Plan Board",
        },
        {
            "spreadsheet_id": "sheet-402",
            "sheet_id": 2,
            "rows": 40,
            "cols": 6,
            "tab_title": "INDEX",
        },
    ]
    selected = select_tabs_from_inventory(
        index_records,
        inventory_rows,
        tab_score_heuristics={
            "operational_tokens": ["planner", "plan"],
            "support_tokens": ["index"],
        },
    )
    assert any(row["tab_title"] == "Plan Board" for row in selected)
    assert not any(row["tab_title"] == "INDEX" for row in selected)


def test_score_tab_boosts_reference_combo_tokens():
    score, reasons = score_tab(
        "Define Shared Terms",
        52,
        17,
        tab_score_heuristics={"reference_combo_tokens": [["define", "term"]]},
    )
    assert score >= 3
    assert "reference_lookup_tab_name" in reasons


def test_score_tab_without_heuristics_uses_grid_shape_only():
    score, reasons = score_tab("Any Name", 1200, 30)
    assert score == 3
    assert set(reasons) == {"medium_grid", "many_rows", "wide_sheet"}


def test_profile_cohort_corpus_smoke_writes_output(tmp_path):
    config = {
        "folder_id": "folder-1",
        "in_scope_workbooks": ["201", "202"],
    }
    config_path = tmp_path / "cohort_corpus.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    out = StringIO()
    call_command(
        "profile_cohort_corpus",
        config=str(config_path),
        out_dir=str(tmp_path),
        date_stamp="2026-04-28",
        smoke=True,
        stdout=out,
    )

    smoke_path = tmp_path / "profile_cohort_corpus_smoke_2026-04-28.json"
    assert smoke_path.exists()
    payload = json.loads(smoke_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "smoke"


def test_profile_preflight_smoke_ok():
    out = StringIO()
    call_command("profile_preflight", smoke=True, stdout=out)
    assert "smoke ok" in out.getvalue()


def test_apply_tab_selection_overrides_no_overrides_returns_copy():
    approved = {"301": ["A", "B"], "401": ["C"]}
    merged = apply_tab_selection_overrides(approved, None)
    assert merged == approved
    merged["301"].append("X")
    assert approved["301"] == ["A", "B"]


def test_apply_tab_selection_overrides_delta_add_and_remove():
    approved = {"503": ["Plan Sheet", "Plan Sheet 402"], "601": ["Sales", "Orders"]}
    overrides = {
        "503": {"add": ["Reference Map"], "remove": ["Plan Sheet"]},
        "601": {"add": ["Weekly Walk"]},
    }
    merged = apply_tab_selection_overrides(approved, overrides)
    assert merged["503"] == ["Plan Sheet 402", "Reference Map"]
    assert merged["601"] == ["Sales", "Orders", "Weekly Walk"]


def test_apply_tab_selection_overrides_add_dedupes_existing_entries():
    approved = {"602": ["Primary List", "Secondary List"]}
    merged = apply_tab_selection_overrides(
        approved, {"602": {"add": ["Primary List", "Secondary List"]}}
    )
    assert merged["602"] == ["Primary List", "Secondary List"]


def test_apply_tab_selection_overrides_replace_supersedes_heuristics():
    approved = {"402": ["Plan Board", "Plan Sheet 501+503+801"]}
    overrides = {"402": {"replace": True, "tabs": ["Custom Only"]}}
    merged = apply_tab_selection_overrides(approved, overrides)
    assert merged["402"] == ["Custom Only"]


def test_apply_tab_selection_overrides_applies_to_missing_workbook_code():
    approved: dict[str, list[str]] = {}
    overrides = {"103": {"add": ["Blocks 201 + 401"]}}
    merged = apply_tab_selection_overrides(approved, overrides)
    assert merged == {"103": ["Blocks 201 + 401"]}


def test_apply_tab_selection_overrides_rejects_unknown_keys():
    with pytest.raises(CommandError, match="unknown keys"):
        apply_tab_selection_overrides({"301": ["A"]}, {"301": {"swap": ["B"]}})


def test_apply_tab_selection_overrides_rejects_tabs_without_replace_flag():
    with pytest.raises(CommandError, match="without 'replace: true'"):
        apply_tab_selection_overrides({"301": ["A"]}, {"301": {"tabs": ["B"]}})


def test_apply_tab_selection_overrides_rejects_replace_without_tabs():
    with pytest.raises(CommandError, match="requires 'tabs'"):
        apply_tab_selection_overrides({"301": ["A"]}, {"301": {"replace": True}})


def test_apply_tab_selection_overrides_rejects_non_string_entries():
    with pytest.raises(CommandError, match=r"add must be a list of strings"):
        apply_tab_selection_overrides({"301": ["A"]}, {"301": {"add": [1]}})


def test_apply_tab_selection_overrides_rejects_non_mapping_entry():
    with pytest.raises(CommandError, match="must be a mapping"):
        apply_tab_selection_overrides({"301": ["A"]}, {"301": ["B"]})


def test_profile_cohort_corpus_smoke_accepts_resume_from_tab_selection_flag(tmp_path):
    config = {"folder_id": "folder-1", "in_scope_workbooks": ["201"]}
    config_path = tmp_path / "cohort_corpus.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    out = StringIO()
    call_command(
        "profile_cohort_corpus",
        config=str(config_path),
        out_dir=str(tmp_path),
        date_stamp="2026-04-28",
        smoke=True,
        resume_from_tab_selection=True,
        stdout=out,
    )
    assert (tmp_path / "profile_cohort_corpus_smoke_2026-04-28.json").exists()


def test_run_cohort_corpus_resume_requires_workbook_index_snapshot(tmp_path: Path):
    """Hand-editing tab selection without a workbook index artifact should raise."""
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-07"
    selection_path = corpus_out_dir / f"tab_selection_{date_stamp}.json"
    selection_path.write_text(
        json.dumps({"approved_tabs": {"301": ["Sheet A"]}}, indent=2),
        encoding="utf-8",
    )
    corpus_config = {"folder_id": "drive-folder-1", "in_scope_workbooks": ["301"]}
    mock_drive = MagicMock()
    mock_sheets = MagicMock()
    with pytest.raises(CommandError, match=r"in_scope_workbook_index_"):
        run_cohort_corpus(
            drive_service=mock_drive,
            sheets_service=mock_sheets,
            config=corpus_config,
            out_dir=corpus_out_dir,
            date_stamp=date_stamp,
            resume_from_tab_selection=True,
        )


def test_run_cohort_corpus_resume_skips_drive_walk(tmp_path: Path):
    """Resume loads index rows from disk and must not crawl Drive anew."""
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-07"
    workbook_index_payload = {
        "generated_from": f"drive_discovery_{date_stamp}.json",
        "record_count": 1,
        "records": [
            {
                "year": 2025,
                "workbook_code": "301",
                "spreadsheet_id": "spreadsheet-id-abcdef",
                "spreadsheet_name": "301 Stub",
                "folder_path": "Corpus",
                "modified_time": None,
                "tab_count": 0,
            },
        ],
    }
    index_path = corpus_out_dir / f"in_scope_workbook_index_{date_stamp}.json"
    index_path.write_text(json.dumps(workbook_index_payload), encoding="utf-8")
    selection_path = corpus_out_dir / f"tab_selection_{date_stamp}.json"
    selection_path.write_text(
        json.dumps({"approved_tabs": {"301": []}}, indent=2),
        encoding="utf-8",
    )
    corpus_config = {"folder_id": "drive-folder-1", "in_scope_workbooks": ["301"]}
    mock_drive = MagicMock()
    mock_sheets = MagicMock()
    with patch(
        "profiler.management.commands.profile_drive_folder.walk_folder"
    ) as mock_walk_drive_tree:
        run_cohort_corpus(
            drive_service=mock_drive,
            sheets_service=mock_sheets,
            config=corpus_config,
            out_dir=corpus_out_dir,
            date_stamp=date_stamp,
            resume_from_tab_selection=True,
        )
    mock_walk_drive_tree.assert_not_called()
