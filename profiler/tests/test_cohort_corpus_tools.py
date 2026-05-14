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
    score, reasons, breakdown = score_tab(
        "Define Shared Terms",
        52,
        17,
        tab_score_heuristics={"reference_combo_tokens": [["define", "term"]]},
    )
    assert score >= 3
    assert "reference_lookup_tab_name" in reasons
    assert len(breakdown["token_matches"]) == 1
    assert breakdown["token_matches"][0]["category"] == "reference_combo"


def test_score_tab_without_heuristics_uses_grid_shape_only():
    score, reasons, breakdown = score_tab("Any Name", 1200, 30)
    assert score == 3
    assert set(reasons) == {"medium_grid", "many_rows", "wide_sheet"}
    assert breakdown["size_bonuses"] == {"medium_grid": 1, "many_rows": 1, "wide_sheet": 1}


def test_score_tab_with_weights():
    """Override default weights and verify score changes proportionally."""
    score, reasons, _breakdown = score_tab(
        "Plan Board",
        100,
        10,
        tab_score_heuristics={
            "operational_tokens": ["plan"],
            "operational_weight": 5,
        },
    )
    assert score == 5
    assert "operational_tab_name" in reasons


def test_score_tab_derived_tokens():
    """derived_tokens match applies derived_weight (default -4)."""
    score, reasons, breakdown = score_tab(
        "Final Report",
        100,
        10,
        tab_score_heuristics={"derived_tokens": ["final report"]},
    )
    assert score == -4
    assert "derived_tab" in reasons
    assert breakdown["token_matches"][0]["category"] == "derived"
    assert breakdown["token_matches"][0]["weight"] == -4


def test_score_tab_word_boundary():
    """match_mode word prevents substring false matches."""
    score, _reasons, _breakdown = score_tab(
        "Crop Planner",
        100,
        10,
        tab_score_heuristics={
            "operational_tokens": ["crop plan"],
            "match_mode": "word",
        },
    )
    assert score == 0


def test_score_tab_substring_fallback():
    """Default match_mode substring preserves old overlap behavior."""
    score, _reasons, _breakdown = score_tab(
        "Crop Planner",
        100,
        10,
        tab_score_heuristics={"operational_tokens": ["crop plan"]},
    )
    assert score == 3


def test_score_tab_derived_vs_size_bonus():
    """derived_weight -4 partially cancels size bonuses (capped at +3)."""
    score, reasons, breakdown = score_tab(
        "Final Report",
        1507,
        301,
        tab_score_heuristics={"derived_tokens": ["final report"]},
    )
    assert score == -1
    assert "derived_tab" in reasons
    assert any(r.startswith("large_grid") for r in reasons)
    assert breakdown["subtotal"] == -1


def test_select_tabs_from_inventory_breakdown():
    """Breakdown dict present in scored entries."""
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
            "rows": 100,
            "cols": 10,
            "tab_title": "Plan Board",
        }
    ]
    selected = select_tabs_from_inventory(
        index_records,
        inventory_rows,
        tab_score_heuristics={
            "operational_tokens": ["plan"],
            "support_tokens": ["index"],
        },
    )
    assert len(selected) == 1
    summary = selected[0]["breakdown_summary"]
    assert summary["total_token_matches"] >= 1
    assert isinstance(summary["avg_size_bonus"], (int, float))


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


def test_profile_cohort_corpus_accepts_stop_before_deep_flag(tmp_path):
    """--stop-before-deep is accepted as a CLI flag and passes through."""
    config = {"folder_id": "folder-1", "in_scope_workbooks": ["201"]}
    config_path = tmp_path / "cohort_corpus.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    out = StringIO()
    call_command(
        "profile_cohort_corpus",
        config=str(config_path),
        out_dir=str(tmp_path),
        date_stamp="2026-05-13",
        smoke=True,
        stop_before_deep=True,
        stdout=out,
    )
    smoke_path = tmp_path / "profile_cohort_corpus_smoke_2026-05-13.json"
    assert smoke_path.exists()


def test_profile_cohort_corpus_accepts_resume_from_broad_flag(tmp_path):
    """--resume-from-broad is accepted as a CLI flag and passes through."""
    config = {"folder_id": "folder-1", "in_scope_workbooks": ["201"]}
    config_path = tmp_path / "cohort_corpus.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    out = StringIO()
    call_command(
        "profile_cohort_corpus",
        config=str(config_path),
        out_dir=str(tmp_path),
        date_stamp="2026-05-13",
        smoke=True,
        resume_from_broad=True,
        stdout=out,
    )
    smoke_path = tmp_path / "profile_cohort_corpus_smoke_2026-05-13.json"
    assert smoke_path.exists()


def test_run_cohort_corpus_stop_before_deep_returns_early(tmp_path: Path):
    """stop_before_deep=True must skip deep profiling and column scoring."""
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-13"
    corpus_config = {
        "folder_id": "drive-folder-1",
        "in_scope_workbooks": ["301"],
    }
    mock_drive = MagicMock()
    mock_sheets = MagicMock()

    with (
        patch(
            "profiler.management.commands.profile_drive_folder.walk_folder",
            return_value={
                "folders": [],
                "spreadsheets": [
                    {
                        "id": "spreadsheet-301",
                        "name": "301 Stub 2026",
                        "tabs": [{"title": "Plan Board"}],
                    }
                ],
                "other_files": [],
            },
        ) as mock_walk,
        patch(
            "profiler.tools.cohort_corpus.list_tabs",
            return_value=[
                {"sheet_id": 1, "rows": 100, "cols": 20, "title": "Plan Board"}
            ],
        ) as mock_list_tabs,
        patch(
            "profiler.tools.cohort_corpus.fetch_tab_grid",
        ) as mock_fetch_grid,
        patch(
            "profiler.tools.cohort_corpus.summarize_tab",
        ) as mock_summarize,
    ):
        outputs = run_cohort_corpus(
            drive_service=mock_drive,
            sheets_service=mock_sheets,
            config=corpus_config,
            out_dir=corpus_out_dir,
            date_stamp=date_stamp,
            stop_before_deep=True,
            folder_id="drive-folder-1",
        )

    mock_walk.assert_called_once()
    mock_list_tabs.assert_called_once()
    mock_fetch_grid.assert_not_called()
    mock_summarize.assert_not_called()

    assert (
        corpus_out_dir / f"tab_selection_{date_stamp}.json"
    ).exists()
    assert "deep_coverage" not in outputs
    assert "column_shortlist" not in outputs
    assert "column_selection" not in outputs


def test_run_cohort_corpus_resume_from_broad_requires_broad_coverage(tmp_path: Path):
    """resume_from_broad must raise when broad_profile_coverage is missing."""
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-13"
    corpus_config = {"folder_id": "drive-folder-1", "in_scope_workbooks": ["301"]}
    mock_drive = MagicMock()
    mock_sheets = MagicMock()

    with pytest.raises(CommandError, match=r"broad_profile_coverage_"):
        run_cohort_corpus(
            drive_service=mock_drive,
            sheets_service=mock_sheets,
            config=corpus_config,
            out_dir=corpus_out_dir,
            date_stamp=date_stamp,
            resume_from_broad=True,
        )


def test_run_cohort_corpus_resume_from_broad_requires_index(tmp_path: Path):
    """resume_from_broad must raise when workbook index is missing."""
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-13"
    broad_path = corpus_out_dir / f"broad_profile_coverage_{date_stamp}.json"
    broad_path.write_text(
        json.dumps(
            {
                "run_count": 1,
                "success_count": 1,
                "failure_count": 0,
                "results": [],
                "inventory_rows": [],
            }
        ),
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
            resume_from_broad=True,
        )


def test_run_cohort_corpus_resume_from_broad_and_tab_selection_mutual_exclusion(tmp_path: Path):
    """Both resume modes together must raise."""
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-13"
    corpus_config = {"folder_id": "drive-folder-1", "in_scope_workbooks": ["301"]}
    mock_drive = MagicMock()
    mock_sheets = MagicMock()

    with pytest.raises(CommandError, match="mutually exclusive"):
        run_cohort_corpus(
            drive_service=mock_drive,
            sheets_service=mock_sheets,
            config=corpus_config,
            out_dir=corpus_out_dir,
            date_stamp=date_stamp,
            resume_from_tab_selection=True,
            resume_from_broad=True,
        )


def test_run_cohort_corpus_resume_from_broad_skips_api_calls(tmp_path: Path):
    """resume_from_broad must re-score from disk without Drive or Sheets calls."""
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-13"

    workbook_index_payload = {
        "generated_from": f"drive_discovery_{date_stamp}.json",
        "record_count": 1,
        "records": [
            {
                "year": 2026,
                "workbook_code": "402",
                "spreadsheet_id": "sheet-402",
                "spreadsheet_name": "402 Planning LSF 2026",
                "folder_path": "Corpus",
                "modified_time": None,
                "tab_count": 0,
            },
        ],
    }
    index_path = corpus_out_dir / f"in_scope_workbook_index_{date_stamp}.json"
    index_path.write_text(json.dumps(workbook_index_payload), encoding="utf-8")

    broad_payload = {
        "run_count": 1,
        "success_count": 1,
        "failure_count": 0,
        "results": [],
        "inventory_rows": [
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
        ],
    }
    broad_path = corpus_out_dir / f"broad_profile_coverage_{date_stamp}.json"
    broad_path.write_text(json.dumps(broad_payload), encoding="utf-8")

    corpus_config = {
        "folder_id": "drive-folder-1",
        "in_scope_workbooks": ["402"],
        "heuristics": {
            "tab_score": {
                "operational_tokens": ["planner", "plan"],
                "support_tokens": ["index"],
            }
        },
    }
    mock_drive = MagicMock()
    mock_sheets = MagicMock()

    with (
        patch(
            "profiler.management.commands.profile_drive_folder.walk_folder"
        ) as mock_walk,
        patch(
            "profiler.tools.cohort_corpus.list_tabs"
        ) as mock_list_tabs,
        patch(
            "profiler.tools.cohort_corpus.fetch_tab_grid"
        ) as mock_fetch_grid,
        patch(
            "profiler.tools.cohort_corpus.summarize_tab"
        ) as mock_summarize,
    ):
        outputs = run_cohort_corpus(
            drive_service=mock_drive,
            sheets_service=mock_sheets,
            config=corpus_config,
            out_dir=corpus_out_dir,
            date_stamp=date_stamp,
            resume_from_broad=True,
            stop_before_deep=True,
        )

    mock_walk.assert_not_called()
    mock_list_tabs.assert_not_called()
    mock_fetch_grid.assert_not_called()
    mock_summarize.assert_not_called()

    assert (
        corpus_out_dir / f"tab_selection_{date_stamp}.json"
    ).exists()
    assert "deep_coverage" not in outputs

    tab_selection = json.loads(
        (corpus_out_dir / f"tab_selection_{date_stamp}.json").read_text(encoding="utf-8")
    )
    approved = tab_selection["approved_tabs"]
    assert "Plan Board" in approved.get("402", [])
    assert "INDEX" not in approved.get("402", [])


def test_run_cohort_corpus_resume_from_broad_re_scores_with_new_heuristics(tmp_path: Path):
    """After editing heuristics, resume_from_broad must produce a different tab selection."""
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-13"

    workbook_index_payload = {
        "generated_from": f"drive_discovery_{date_stamp}.json",
        "record_count": 2,
        "records": [
            {
                "year": 2026,
                "workbook_code": "503",
                "spreadsheet_id": "sheet-503",
                "spreadsheet_name": "503 Reference List LSF 2026",
                "folder_path": "Corpus",
                "modified_time": None,
                "tab_count": 0,
            },
            {
                "year": 2026,
                "workbook_code": "601",
                "spreadsheet_id": "sheet-601",
                "spreadsheet_name": "601 Sales Tracker 2026",
                "folder_path": "Corpus",
                "modified_time": None,
                "tab_count": 0,
            },
        ],
    }
    index_path = corpus_out_dir / f"in_scope_workbook_index_{date_stamp}.json"
    index_path.write_text(json.dumps(workbook_index_payload), encoding="utf-8")

    broad_payload = {
        "run_count": 2,
        "success_count": 2,
        "failure_count": 0,
        "results": [],
        "inventory_rows": [
            {
                "spreadsheet_id": "sheet-503",
                "sheet_id": 1,
                "rows": 500,
                "cols": 15,
                "tab_title": "Define Shared Terms",
            },
            {
                "spreadsheet_id": "sheet-503",
                "sheet_id": 2,
                "rows": 10,
                "cols": 4,
                "tab_title": "INDEX",
            },
            {
                "spreadsheet_id": "sheet-601",
                "sheet_id": 3,
                "rows": 200,
                "cols": 12,
                "tab_title": "Sales Summary",
            },
            {
                "spreadsheet_id": "sheet-601",
                "sheet_id": 4,
                "rows": 1000,
                "cols": 25,
                "tab_title": "Weekly Walk",
            },
        ],
    }
    broad_path = corpus_out_dir / f"broad_profile_coverage_{date_stamp}.json"
    broad_path.write_text(json.dumps(broad_payload), encoding="utf-8")

    corpus_config = {
        "folder_id": "drive-folder-1",
        "in_scope_workbooks": ["503", "601"],
        "heuristics": {
            "tab_score": {
                "reference_combo_tokens": [["define", "term"]],
                "support_tokens": ["index"],
            }
        },
    }
    mock_drive = MagicMock()
    mock_sheets = MagicMock()

    with (
        patch(
            "profiler.management.commands.profile_drive_folder.walk_folder"
        ) as mock_walk,
        patch(
            "profiler.tools.cohort_corpus.list_tabs"
        ) as mock_list_tabs,
    ):
        outputs = run_cohort_corpus(
            drive_service=mock_drive,
            sheets_service=mock_sheets,
            config=corpus_config,
            out_dir=corpus_out_dir,
            date_stamp=date_stamp,
            resume_from_broad=True,
            stop_before_deep=True,
        )

    mock_walk.assert_not_called()
    mock_list_tabs.assert_not_called()

    tab_selection = json.loads(
        (corpus_out_dir / f"tab_selection_{date_stamp}.json").read_text(encoding="utf-8")
    )
    approved = tab_selection["approved_tabs"]
    assert "Define Shared Terms" in approved.get("503", [])
    assert "INDEX" not in approved.get("503", [])


def test_run_cohort_corpus_429_aborts_after_max_cooldowns(tmp_path: Path):
    """Too many 429s must abort the deep loop with an error entry and no grid calls after abort."""
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-13"

    workbook_index_payload = {
        "generated_from": f"drive_discovery_{date_stamp}.json",
        "record_count": 3,
        "records": [
            {
                "year": 2026,
                "workbook_code": "402",
                "spreadsheet_id": "sheet-a",
                "spreadsheet_name": "402 A 2026",
                "folder_path": "Corpus",
                "modified_time": None,
                "tab_count": 0,
            },
            {
                "year": 2026,
                "workbook_code": "402",
                "spreadsheet_id": "sheet-b",
                "spreadsheet_name": "402 B 2026",
                "folder_path": "Corpus",
                "modified_time": None,
                "tab_count": 0,
            },
        ],
    }
    index_path = corpus_out_dir / f"in_scope_workbook_index_{date_stamp}.json"
    index_path.write_text(json.dumps(workbook_index_payload), encoding="utf-8")

    broad_payload = {
        "run_count": 2,
        "success_count": 2,
        "failure_count": 0,
        "results": [],
        "inventory_rows": [
            {
                "spreadsheet_id": "sheet-a",
                "sheet_id": 0,
                "rows": 100,
                "cols": 10,
                "tab_title": "Plan Board",
            },
            {
                "spreadsheet_id": "sheet-b",
                "sheet_id": 0,
                "rows": 50,
                "cols": 8,
                "tab_title": "Sales Data",
            },
        ],
    }
    broad_path = corpus_out_dir / f"broad_profile_coverage_{date_stamp}.json"
    broad_path.write_text(json.dumps(broad_payload), encoding="utf-8")

    corpus_config = {
        "folder_id": "drive-folder-1",
        "in_scope_workbooks": ["402"],
        "deep_read_429_cooldown": 0.01,
        "deep_read_429_max_cooldowns": 1,
        "tab_selection_overrides": {
            "402": {"replace": True, "tabs": ["Plan Board", "Sales Data"]}
        },
    }

    from googleapiclient.errors import HttpError

    mock_drive = MagicMock()
    mock_sheets = MagicMock()

    http_error_429 = HttpError(resp=MagicMock(status=429), content=b"Rate limit")
    mock_fetch = MagicMock(side_effect=http_error_429)

    with (
        patch(
            "profiler.management.commands.profile_drive_folder.walk_folder"
        ) as mock_walk,
        patch(
            "profiler.tools.cohort_corpus.list_tabs"
        ) as mock_list_tabs,
        patch(
            "profiler.tools.cohort_corpus.fetch_tab_grid",
            mock_fetch,
        ),
        patch(
            "profiler.tools.cohort_corpus.summarize_tab",
        ),
    ):
        outputs = run_cohort_corpus(
            drive_service=mock_drive,
            sheets_service=mock_sheets,
            config=corpus_config,
            out_dir=corpus_out_dir,
            date_stamp=date_stamp,
            resume_from_broad=True,
            stop_before_deep=False,
        )

    deep_coverage = json.loads(
        (corpus_out_dir / f"deep_profile_coverage_{date_stamp}.json").read_text(
            encoding="utf-8"
        )
    )
    abort_entries = [
        row for row in deep_coverage["results"] if "aborting deep profile" in (row.get("error") or "")
    ]
    assert len(abort_entries) == 1
    assert deep_coverage["failure_count"] > 0


def test_run_cohort_corpus_resume_from_broad_inventory_rows_missing(tmp_path: Path):
    """resume_from_broad must raise when broad coverage lacks inventory_rows."""
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-13"

    workbook_index_payload = {
        "generated_from": f"drive_discovery_{date_stamp}.json",
        "record_count": 1,
        "records": [
            {
                "year": 2026,
                "workbook_code": "402",
                "spreadsheet_id": "sheet-402",
                "spreadsheet_name": "402 Stub",
                "folder_path": "Corpus",
                "modified_time": None,
                "tab_count": 0,
            },
        ],
    }
    index_path = corpus_out_dir / f"in_scope_workbook_index_{date_stamp}.json"
    index_path.write_text(json.dumps(workbook_index_payload), encoding="utf-8")

    broad_path = corpus_out_dir / f"broad_profile_coverage_{date_stamp}.json"
    broad_path.write_text(
        json.dumps({"run_count": 1, "success_count": 1, "failure_count": 0, "results": []}),
        encoding="utf-8",
    )

    mock_drive = MagicMock()
    mock_sheets = MagicMock()

    with pytest.raises(CommandError, match="inventory_rows"):
        run_cohort_corpus(
            drive_service=mock_drive,
            sheets_service=mock_sheets,
            config={"folder_id": "drive-folder-1", "in_scope_workbooks": ["402"]},
            out_dir=corpus_out_dir,
            date_stamp=date_stamp,
            resume_from_broad=True,
        )


def test_run_cohort_corpus_resume_from_broad_continues_to_deep_without_stop(tmp_path: Path):
    """resume_from_broad without stop_before_deep proceeds into deep profiling."""
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-13"

    workbook_index_payload = {
        "generated_from": f"drive_discovery_{date_stamp}.json",
        "record_count": 1,
        "records": [
            {
                "year": 2026,
                "workbook_code": "402",
                "spreadsheet_id": "sheet-402",
                "spreadsheet_name": "402 Planning LSF 2026",
                "folder_path": "Corpus",
                "modified_time": None,
                "tab_count": 0,
            },
        ],
    }
    index_path = corpus_out_dir / f"in_scope_workbook_index_{date_stamp}.json"
    index_path.write_text(json.dumps(workbook_index_payload), encoding="utf-8")

    broad_payload = {
        "run_count": 1,
        "success_count": 1,
        "failure_count": 0,
        "results": [],
        "inventory_rows": [
            {
                "spreadsheet_id": "sheet-402",
                "sheet_id": 1,
                "rows": 100,
                "cols": 10,
                "tab_title": "Plan Board",
            },
        ],
    }
    broad_path = corpus_out_dir / f"broad_profile_coverage_{date_stamp}.json"
    broad_path.write_text(json.dumps(broad_payload), encoding="utf-8")

    corpus_config = {
        "folder_id": "drive-folder-1",
        "in_scope_workbooks": ["402"],
        "tab_selection_overrides": {
            "402": {"replace": True, "tabs": ["Plan Board"]}
        },
    }
    mock_drive = MagicMock()
    mock_sheets = MagicMock()

    with (
        patch(
            "profiler.management.commands.profile_drive_folder.walk_folder"
        ) as mock_walk,
        patch(
            "profiler.tools.cohort_corpus.list_tabs"
        ) as mock_list_tabs,
        patch(
            "profiler.tools.cohort_corpus.fetch_tab_grid",
            return_value={"sheets": [{"data": [{"startRow": 0, "rowData": [{"values": [{"formattedValue": "Name"}]}], "startColumn": 0}]}]},
        ),
        patch(
            "profiler.tools.cohort_corpus.summarize_tab",
            return_value={"formula_cell_count": 0, "functions_used": []},
        ),
    ):
        outputs = run_cohort_corpus(
            drive_service=mock_drive,
            sheets_service=mock_sheets,
            config=corpus_config,
            out_dir=corpus_out_dir,
            date_stamp=date_stamp,
            resume_from_broad=True,
            stop_before_deep=False,
        )

    mock_walk.assert_not_called()
    mock_list_tabs.assert_not_called()

    assert "deep_coverage" in outputs
    assert "column_shortlist" in outputs

    deep_path = corpus_out_dir / f"deep_profile_coverage_{date_stamp}.json"
    assert deep_path.exists()
    deep_payload = json.loads(deep_path.read_text(encoding="utf-8"))
    assert deep_payload["success_count"] >= 1
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


def test_score_tab_exclude_pattern_penalizes_match():
    score, reasons, breakdown = score_tab(
        "Crop Info 201",
        100,
        10,
        tab_score_heuristics={
            "tab_exclude_patterns": [
                {"pattern": "\\b\\d{3}\\b", "penalty": -5}
            ]
        },
    )
    assert score == -5
    assert "tab_exclude_pattern" in reasons
    assert breakdown["exclude_penalties"] == -5


def test_score_tab_exclude_pattern_no_match():
    score, reasons, breakdown = score_tab(
        "Crop Planner",
        100,
        10,
        tab_score_heuristics={
            "tab_exclude_patterns": [
                {"pattern": "\\b\\d{3}\\b", "penalty": -5}
            ]
        },
    )
    assert score == 0
    assert "tab_exclude_pattern" not in reasons


def test_score_tab_expansion_formula_ratio_penalty():
    score, reasons, breakdown = score_tab(
        "Final Report",
        1500,
        200,
        tab_score_heuristics={
            "expansion_formula_penalty": -5,
            "expansion_formula_threshold": 0.5,
        },
        column_formula_patterns={
            "A": "raw", "B": "raw", "C": "expansion_formula",
            "D": "expansion_formula", "E": "expansion_formula",
        },
    )
    # 3 of 5 columns are expansion_formula = 0.6 ratio, exceeding 0.5 threshold
    # Penalty -5 applied
    # Size bonuses: 1500*200 = 300k cells → large_grid(+2), many_rows(+1), wide_sheet(+1) capped at +3
    # Total: -5 + 3 = -2
    assert score == -2
    assert "expansion_formula_ratio" in reasons


def test_score_tab_expansion_formula_ratio_below_threshold():
    score, reasons, breakdown = score_tab(
        "Crop Planner",
        100,
        10,
        tab_score_heuristics={
            "expansion_formula_penalty": -5,
            "expansion_formula_threshold": 0.5,
        },
        column_formula_patterns={
            "A": "raw", "B": "raw", "C": "expansion_formula",
        },
    )
    # 1 of 3 columns = 0.33 ratio, below 0.5 threshold → no penalty
    assert score == 0
    assert "expansion_formula_ratio" not in reasons


def test_score_tab_expansion_formula_ratio_no_patterns_provided():
    score, reasons, breakdown = score_tab(
        "Final Report",
        100,
        10,
        tab_score_heuristics={
            "expansion_formula_penalty": -5,
        },
    )
    # No column_formula_patterns provided → no penalty
    assert score == 0
    assert "expansion_formula_ratio" not in reasons


def test_score_tab_exclude_pattern_multiple_rules():
    score, reasons, breakdown = score_tab(
        "IGNORE Sheet 999",
        100,
        10,
        tab_score_heuristics={
            "tab_exclude_patterns": [
                {"pattern": "^IGNORE", "penalty": -3},
                {"pattern": "\\b\\d{3}\\b", "penalty": -5},
            ]
        },
    )
    assert score == -8
    assert breakdown["exclude_penalties"] == -8
