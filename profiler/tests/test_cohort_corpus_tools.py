import json
import re
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from profiler.tools.cohort_corpus import (
    ColumnProfile,
    _compile_exclude_regexes,
    apply_tab_selection_overrides,
    auto_select_tabs,
    build_cohort_corpus_index,
    compute_column_profiles,
    enrich_computed_fields,
    enrich_entity_groupings,
    enrich_fk_candidates,
    enrich_import_key_candidates,
    derive_column_candidates,
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
    assert breakdown["size_bonuses"] == {
        "medium_grid": 1,
        "many_rows": 1,
        "wide_sheet": 1,
    }


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

    assert (corpus_out_dir / f"tab_selection_{date_stamp}.json").exists()
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


def test_run_cohort_corpus_resume_from_broad_and_tab_selection_mutual_exclusion(
    tmp_path: Path,
):
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
        patch("profiler.tools.cohort_corpus.list_tabs") as mock_list_tabs,
        patch("profiler.tools.cohort_corpus.fetch_tab_grid") as mock_fetch_grid,
        patch("profiler.tools.cohort_corpus.summarize_tab") as mock_summarize,
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

    assert (corpus_out_dir / f"tab_selection_{date_stamp}.json").exists()
    assert "deep_coverage" not in outputs

    tab_selection = json.loads(
        (corpus_out_dir / f"tab_selection_{date_stamp}.json").read_text(
            encoding="utf-8"
        )
    )
    approved = tab_selection["approved_tabs"]
    assert "Plan Board" in approved.get("402", [])
    assert "INDEX" not in approved.get("402", [])


def test_run_cohort_corpus_resume_from_broad_re_scores_with_new_heuristics(
    tmp_path: Path,
):
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
        patch("profiler.tools.cohort_corpus.list_tabs") as mock_list_tabs,
    ):
        _outputs = run_cohort_corpus(
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
        (corpus_out_dir / f"tab_selection_{date_stamp}.json").read_text(
            encoding="utf-8"
        )
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
        ) as _mock_walk,
        patch("profiler.tools.cohort_corpus.list_tabs") as _mock_list_tabs,
        patch(
            "profiler.tools.cohort_corpus.fetch_tab_grid",
            mock_fetch,
        ),
        patch(
            "profiler.tools.cohort_corpus.summarize_tab",
        ),
    ):
        _outputs = run_cohort_corpus(
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
        row
        for row in deep_coverage["results"]
        if "aborting deep profile" in (row.get("error") or "")
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
        json.dumps(
            {"run_count": 1, "success_count": 1, "failure_count": 0, "results": []}
        ),
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


def test_run_cohort_corpus_resume_from_broad_continues_to_deep_without_stop(
    tmp_path: Path,
):
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
        "tab_selection_overrides": {"402": {"replace": True, "tabs": ["Plan Board"]}},
    }
    mock_drive = MagicMock()
    mock_sheets = MagicMock()

    with (
        patch(
            "profiler.management.commands.profile_drive_folder.walk_folder"
        ) as mock_walk,
        patch("profiler.tools.cohort_corpus.list_tabs") as mock_list_tabs,
        patch(
            "profiler.tools.cohort_corpus.fetch_tab_grid",
            return_value={
                "sheets": [
                    {
                        "data": [
                            {
                                "startRow": 0,
                                "rowData": [{"values": [{"formattedValue": "Name"}]}],
                                "startColumn": 0,
                            }
                        ]
                    }
                ]
            },
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
            "tab_exclude_patterns": [{"pattern": "\\b\\d{3}\\b", "penalty": -5}]
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
            "tab_exclude_patterns": [{"pattern": "\\b\\d{3}\\b", "penalty": -5}]
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
            "A": "raw",
            "B": "raw",
            "C": "expansion_formula",
            "D": "expansion_formula",
            "E": "expansion_formula",
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
            "A": "raw",
            "B": "raw",
            "C": "expansion_formula",
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


class TestColumnProfile:
    def test_dataclass_fields(self):
        cp = ColumnProfile(
            letter="A",
            header_slug="product_sku",
            header_raw="Product SKU",
            inferred_type="text",
            formula_pattern="raw",
            non_empty_cells=10,
        )
        assert cp.letter == "A"
        assert cp.header_slug == "product_sku"
        assert cp.is_section_header is False
        assert cp.pattern_truncated is False

    def test_compute_column_profiles_basic(self):
        summary = {
            "column_formula_patterns": {"A": "raw", "B": "row_formula"},
            "column_candidates": [
                {
                    "letter": "A",
                    "header": "Product SKU",
                    "format_type": "text",
                    "unique_count": 50,
                    "total_count": 50,
                },
                {
                    "letter": "B",
                    "header": "Format",
                    "format_type": "text",
                    "unique_count": 3,
                    "total_count": 50,
                },
            ],
        }
        profiles = compute_column_profiles(summary)
        assert len(profiles) == 2
        assert profiles[0].letter == "A"
        assert profiles[0].header_slug == "product_sku"
        assert profiles[0].formula_pattern == "raw"

    def test_compute_column_patterns_by_slug(self):
        summary = {
            "column_formula_patterns": {"A": "raw", "B": "expansion_formula"},
            "column_candidates": [
                {"letter": "A", "header": "Product SKU", "format_type": "text"},
                {"letter": "B", "header": "Format Code", "format_type": "formula"},
            ],
        }
        patterns = compute_column_profiles(summary, return_patterns_by_slug=True)
        assert "product_sku" in patterns
        assert patterns["product_sku"]["pattern"] == "raw"
        assert patterns["format_code"]["letter"] == "B"

    def test_section_header_detection(self):
        summary = {
            "column_formula_patterns": {"A": "raw"},
            "column_candidates": [
                {
                    "letter": "A",
                    "header": "HARVEST INFO",
                    "format_type": "text",
                    "unique_count": 1,
                    "total_count": 50,
                    "merged_span": 45,
                    "total_columns": 50,
                },
            ],
        }
        profiles = compute_column_profiles(summary)
        assert profiles[0].is_section_header is True


class TestEnrichComputedFields:
    def _make_col(self, formula_pattern="raw", **overrides):
        col = {
            "workbook_code": "402",
            "tab_title": "Plan Board",
            "proposed_canonical_field": "crop_name",
            "priority_score": 0,
            "priority_reasons": [],
            "evidence": {"formula_pattern": formula_pattern},
        }
        col.update(overrides)
        return col

    def test_sets_is_computed_true_for_row_formula(self):
        cols = [self._make_col(formula_pattern="row_formula")]
        enrich_computed_fields(cols)
        assert cols[0]["is_computed"] is True

    def test_sets_is_computed_true_for_expansion_formula(self):
        cols = [self._make_col(formula_pattern="expansion_formula")]
        enrich_computed_fields(cols)
        assert cols[0]["is_computed"] is True

    def test_sets_is_computed_false_for_raw(self):
        cols = [self._make_col(formula_pattern="raw")]
        enrich_computed_fields(cols)
        assert cols[0]["is_computed"] is False

    def test_sets_is_computed_false_for_other_pattern(self):
        cols = [self._make_col(formula_pattern="partial_formula")]
        enrich_computed_fields(cols)
        assert cols[0]["is_computed"] is False

    def test_handles_missing_evidence(self):
        cols = [self._make_col()]
        del cols[0]["evidence"]
        enrich_computed_fields(cols)
        assert cols[0]["is_computed"] is False

    def test_handles_missing_formula_pattern(self):
        cols = [self._make_col()]
        del cols[0]["evidence"]["formula_pattern"]
        enrich_computed_fields(cols)
        assert cols[0]["is_computed"] is False


class TestEnrichFkCandidates:
    def _make_col(self, canonical="farm_id", **overrides):
        col = {
            "workbook_code": "402",
            "tab_title": "Plan Board",
            "proposed_canonical_field": canonical,
            "priority_score": 0,
            "priority_reasons": [],
            "evidence": {"formula_pattern": "raw"},
        }
        col.update(overrides)
        return col

    def test_id_suffix_sets_fk_target(self):
        cols = [self._make_col(canonical="farm_id")]
        enrich_fk_candidates(cols, entity_names={"Farm"})
        assert cols[0]["suggested_fk_target"] == "Farm"

    def test_id_suffix_uses_pascal_case(self):
        cols = [self._make_col(canonical="crop_variety_id")]
        enrich_fk_candidates(cols, entity_names={"CropVariety"})
        assert cols[0]["suggested_fk_target"] == "CropVariety"

    def test_entity_keyword_sets_fk_target(self):
        cols = [self._make_col(canonical="channel")]
        enrich_fk_candidates(cols, entity_names={"Channel"})
        assert cols[0]["suggested_fk_target"] == "Channel"

    def test_cross_sheet_refs_sets_fk_target(self):
        col = self._make_col(canonical="lookup_value")
        col["evidence"]["cross_sheet_refs"] = ["Sheet2!A1"]
        cols = [col]
        enrich_fk_candidates(cols, entity_names=set())
        assert cols[0]["suggested_fk_target"] == "LookupValue"

    def test_no_match_leaves_no_fk_target(self):
        cols = [self._make_col(canonical="description")]
        enrich_fk_candidates(cols, entity_names=set())
        assert cols[0].get("suggested_fk_target") is None

    def test_entity_names_filter_when_provided(self):
        cols = [self._make_col(canonical="farm_id")]
        enrich_fk_candidates(cols, entity_names={"DifferentEntity"})
        assert cols[0].get("suggested_fk_target") is None

    def test_empty_entity_names_allows_all(self):
        cols = [self._make_col(canonical="farm_id")]
        enrich_fk_candidates(cols, entity_names=set())
        assert cols[0]["suggested_fk_target"] == "Farm"

    def test_entity_names_match_allows_fk(self):
        cols = [self._make_col(canonical="farm_id")]
        enrich_fk_candidates(cols, entity_names={"Farm"})
        assert cols[0]["suggested_fk_target"] == "Farm"

    def test_entity_keyword_with_entity_names_match(self):
        cols = [self._make_col(canonical="season")]
        enrich_fk_candidates(cols, entity_names={"Season"})
        assert cols[0]["suggested_fk_target"] == "Season"

    def test_cross_sheet_refs_with_empty_entity_names(self):
        col = self._make_col(canonical="ref_value")
        col["evidence"]["cross_sheet_refs"] = ["Other!B2"]
        cols = [col]
        enrich_fk_candidates(cols, entity_names=set())
        assert cols[0]["suggested_fk_target"] == "RefValue"


class TestEnrichImportKeyCandidates:
    def _make_col(self, canonical="product_id", formula_pattern="raw", **overrides):
        col = {
            "workbook_code": "402",
            "tab_title": "Plan Board",
            "proposed_canonical_field": canonical,
            "priority_score": 0,
            "priority_reasons": [],
            "evidence": {"formula_pattern": formula_pattern},
        }
        col.update(overrides)
        return col

    def test_id_suffix_raw_is_import_key(self):
        cols = [self._make_col(canonical="product_id")]
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is True

    def test_code_suffix_raw_is_import_key(self):
        cols = [self._make_col(canonical="area_code")]
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is True

    def test_key_suffix_raw_is_import_key(self):
        cols = [self._make_col(canonical="sort_key")]
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is True

    def test_exact_name_id_is_import_key(self):
        cols = [self._make_col(canonical="id")]
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is True

    def test_exact_name_name_is_import_key(self):
        cols = [self._make_col(canonical="name")]
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is True

    def test_exact_name_code_is_import_key(self):
        cols = [self._make_col(canonical="code")]
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is True

    def test_exact_name_slug_is_import_key(self):
        cols = [self._make_col(canonical="slug")]
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is True

    def test_exact_name_uid_is_import_key(self):
        cols = [self._make_col(canonical="uid")]
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is True

    def test_exact_name_uuid_is_import_key(self):
        cols = [self._make_col(canonical="uuid")]
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is True

    def test_exact_name_external_id_is_import_key(self):
        cols = [self._make_col(canonical="external_id")]
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is True

    def test_computed_field_is_not_import_key(self):
        cols = [self._make_col(canonical="product_id", formula_pattern="row_formula")]
        enrich_computed_fields(cols)
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is False

    def test_regular_field_is_not_import_key(self):
        cols = [self._make_col(canonical="description")]
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is False

    def test_missing_evidence_defaults_to_raw(self):
        col = self._make_col(canonical="product_id")
        del col["evidence"]
        cols = [col]
        enrich_import_key_candidates(cols)
        assert cols[0]["is_import_key_candidate"] is True


class TestEnrichEntityGroupings:
    def _make_col(
        self,
        workbook_code="402",
        tab_title="Plan Board",
        canonical="farm_id",
        **overrides,
    ):
        col = {
            "workbook_code": workbook_code,
            "tab_title": tab_title,
            "proposed_canonical_field": canonical,
            "priority_score": 0,
            "priority_reasons": [],
            "evidence": {"formula_pattern": "raw"},
        }
        col.update(overrides)
        return col

    def test_tabs_sharing_headers_get_entity(self):
        cols = [
            self._make_col(
                workbook_code="402", tab_title="Plan A", canonical="farm_id"
            ),
            self._make_col(
                workbook_code="402", tab_title="Plan A", canonical="crop_name"
            ),
            self._make_col(
                workbook_code="402", tab_title="Plan B", canonical="farm_id"
            ),
            self._make_col(
                workbook_code="402", tab_title="Plan B", canonical="crop_name"
            ),
        ]
        entity_map = enrich_entity_groupings(cols)
        assert "Plan A" in entity_map
        assert "Plan B" in entity_map
        assert entity_map["Plan A"] == entity_map["Plan B"]
        for col in cols:
            assert col.get("suggested_entity") is not None
            assert col.get("cross_tab_group") is not None

    def test_tabs_not_sharing_headers_no_entity(self):
        cols = [
            self._make_col(
                workbook_code="402", tab_title="Plan A", canonical="farm_id"
            ),
            self._make_col(
                workbook_code="402", tab_title="Plan B", canonical="crop_name"
            ),
        ]
        entity_map = enrich_entity_groupings(cols)
        assert entity_map == {}
        for col in cols:
            assert col.get("suggested_entity") is None
            assert col.get("cross_tab_group") is None

    def test_tabs_sharing_one_header_not_enough(self):
        cols = [
            self._make_col(
                workbook_code="402", tab_title="Plan A", canonical="farm_id"
            ),
            self._make_col(
                workbook_code="402", tab_title="Plan B", canonical="farm_id"
            ),
        ]
        entity_map = enrich_entity_groupings(cols)
        assert entity_map == {}

    def test_different_workbooks_not_grouped(self):
        cols = [
            self._make_col(
                workbook_code="402", tab_title="Plan A", canonical="farm_id"
            ),
            self._make_col(
                workbook_code="402", tab_title="Plan A", canonical="crop_name"
            ),
            self._make_col(
                workbook_code="503", tab_title="Plan A", canonical="farm_id"
            ),
            self._make_col(
                workbook_code="503", tab_title="Plan A", canonical="crop_name"
            ),
        ]
        entity_map = enrich_entity_groupings(cols)
        assert entity_map == {}

    def test_returns_tab_to_entity_map(self):
        cols = [
            self._make_col(
                workbook_code="402", tab_title="Plan A", canonical="farm_id"
            ),
            self._make_col(
                workbook_code="402", tab_title="Plan A", canonical="crop_name"
            ),
            self._make_col(
                workbook_code="402", tab_title="Plan B", canonical="farm_id"
            ),
            self._make_col(
                workbook_code="402", tab_title="Plan B", canonical="crop_name"
            ),
            self._make_col(
                workbook_code="402", tab_title="Plan B", canonical="season_name"
            ),
        ]
        entity_map = enrich_entity_groupings(cols)
        assert isinstance(entity_map, dict)
        assert all(isinstance(v, str) for v in entity_map.values())


from profiler.tools.domain_context import DomainContext  # noqa: E402


def test_score_tab_glossary_expansion():
    """Glossary 'qty → quantity' lets 'qty' in tab title match 'quantity' token."""
    ctx = DomainContext(glossary={"qty": "quantity", "amt": "amount"})
    score, reasons, breakdown = score_tab(
        "Qty Tracker",
        100,
        20,
        tab_score_heuristics={"operational_tokens": ["quantity"]},
        domain_context=ctx,
    )
    assert score > 0
    assert any("operational" in r for r in reasons)


def test_select_tabs_vocabulary_merging():
    """Vocabulary from domain context is merged into heuristic tokens."""
    ctx = DomainContext(
        vocabulary=DomainContext.VocabularyContext(operational=["crop"]),
        year_scope=DomainContext.YearScope(active=[2025], archived=[], forward=[]),
    )
    index_records = [
        {
            "year": 2025,
            "workbook_code": "402",
            "spreadsheet_id": "s1",
            "spreadsheet_name": "402",
        },
    ]
    inventory_rows = [
        {
            "spreadsheet_id": "s1",
            "sheet_id": 1,
            "rows": 500,
            "cols": 20,
            "tab_title": "Crop Planner",
        },
    ]
    selected = select_tabs_from_inventory(
        index_records,
        inventory_rows,
        tab_score_heuristics={},
        domain_context=ctx,
    )
    assert any(r["tab_title"] == "Crop Planner" for r in selected)


def test_select_tabs_coverage_bonus_active_years():
    """Coverage bonus is +1 when tab appears in >=2 active/forward years."""
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(
            active=[2025, 2026], archived=[2023, 2024], forward=[]
        ),
    )
    index_records = [
        {
            "year": 2023,
            "workbook_code": "402",
            "spreadsheet_id": "s1",
            "spreadsheet_name": "402 2023",
        },
        {
            "year": 2024,
            "workbook_code": "402",
            "spreadsheet_id": "s2",
            "spreadsheet_name": "402 2024",
        },
        {
            "year": 2025,
            "workbook_code": "402",
            "spreadsheet_id": "s3",
            "spreadsheet_name": "402 2025",
        },
        {
            "year": 2026,
            "workbook_code": "402",
            "spreadsheet_id": "s4",
            "spreadsheet_name": "402 2026",
        },
    ]
    inventory_rows = [
        {
            "spreadsheet_id": f"s{i}",
            "sheet_id": 1,
            "rows": 500,
            "cols": 20,
            "tab_title": "Crop Planner",
        }
        for i in range(1, 5)
    ]
    selected = select_tabs_from_inventory(
        index_records,
        inventory_rows,
        tab_score_heuristics={"operational_tokens": ["crop"]},
        domain_context=ctx,
    )
    entry = next(r for r in selected if r["tab_title"] == "Crop Planner")
    assert entry["coverage_bonus"] == 1


def test_select_tabs_duplicate_years_annotation():
    """Shortlist entries get duplicate_years annotation when spanning multiple years."""
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(
            active=[2025, 2026], archived=[2023, 2024], forward=[]
        ),
    )
    index_records = [
        {
            "year": 2023,
            "workbook_code": "402",
            "spreadsheet_id": "s1",
            "spreadsheet_name": "402 2023",
        },
        {
            "year": 2026,
            "workbook_code": "402",
            "spreadsheet_id": "s4",
            "spreadsheet_name": "402 2026",
        },
    ]
    inventory_rows = [
        {
            "spreadsheet_id": "s1",
            "sheet_id": 1,
            "rows": 500,
            "cols": 20,
            "tab_title": "Crop Planner",
        },
        {
            "spreadsheet_id": "s4",
            "sheet_id": 1,
            "rows": 500,
            "cols": 20,
            "tab_title": "Crop Planner",
        },
    ]
    selected = select_tabs_from_inventory(
        index_records,
        inventory_rows,
        tab_score_heuristics={"operational_tokens": ["crop"]},
        domain_context=ctx,
    )
    entry = next(r for r in selected if r["tab_title"] == "Crop Planner")
    assert entry.get("duplicate_years") == [2023]


def test_derive_column_candidates_glossary():
    ctx = DomainContext(glossary={"qty": "quantity", "amt": "amount"})
    payload = {
        "summary": {
            "formula_cell_count": 0,
            "functions_used": [],
            "column_formula_patterns": {},
        },
        "raw": {
            "sheets": [
                {
                    "data": [
                        {
                            "startRow": 0,
                            "rowData": [
                                {
                                    "values": [
                                        {"formattedValue": "Qty"},
                                        {"formattedValue": "Item"},
                                        {"formattedValue": "Price"},
                                        {"formattedValue": "Date"},
                                    ]
                                },
                                {
                                    "values": [
                                        {"formattedValue": "5"},
                                        {"formattedValue": "Apple"},
                                        {"formattedValue": "1.00"},
                                        {"formattedValue": "2025-01-01"},
                                    ]
                                },
                            ],
                        }
                    ],
                }
            ],
        },
    }
    candidates = derive_column_candidates(
        workbook_code="402",
        year=2025,
        spreadsheet_id="s1",
        tab_title="Test",
        payload=payload,
        column_score_heuristics={"domain_keyword_tokens": ["quantity"]},
        domain_context=ctx,
    )
    qty_candidates = [c for c in candidates if c["column_header"] == "Qty"]
    assert len(qty_candidates) == 1
    assert "domain_keyword" in qty_candidates[0]["priority_reasons"]


def test_select_tabs_no_domain_context_unchanged():
    """Without domain_context, legacy behavior: coverage bonus, no duplicate_years."""
    index_records = [
        {
            "year": 2023,
            "workbook_code": "402",
            "spreadsheet_id": "s1",
            "spreadsheet_name": "402 2023",
        },
        {
            "year": 2024,
            "workbook_code": "402",
            "spreadsheet_id": "s2",
            "spreadsheet_name": "402 2024",
        },
        {
            "year": 2025,
            "workbook_code": "402",
            "spreadsheet_id": "s3",
            "spreadsheet_name": "402 2025",
        },
    ]
    inventory_rows = [
        {
            "spreadsheet_id": f"s{i}",
            "sheet_id": 1,
            "rows": 500,
            "cols": 20,
            "tab_title": "Crop Planner",
        }
        for i in range(1, 4)
    ]
    selected = select_tabs_from_inventory(
        index_records,
        inventory_rows,
        tab_score_heuristics={"operational_tokens": ["crop"]},
    )
    entry = next(r for r in selected if r["tab_title"] == "Crop Planner")
    assert entry["coverage_bonus"] == 1
    assert "duplicate_years" not in entry


def test_select_tabs_legacy_coverage_bonus_two_years():
    """Legacy mode (no domain context) awards coverage bonus at >=2 years."""
    index_records = [
        {
            "year": 2025,
            "workbook_code": "402",
            "spreadsheet_id": "s1",
            "spreadsheet_name": "402 2025",
        },
        {
            "year": 2026,
            "workbook_code": "402",
            "spreadsheet_id": "s2",
            "spreadsheet_name": "402 2026",
        },
    ]
    inventory_rows = [
        {
            "spreadsheet_id": "s1",
            "sheet_id": 1,
            "rows": 500,
            "cols": 20,
            "tab_title": "Crop Planner",
        },
        {
            "spreadsheet_id": "s2",
            "sheet_id": 1,
            "rows": 500,
            "cols": 20,
            "tab_title": "Crop Planner",
        },
    ]
    selected = select_tabs_from_inventory(
        index_records,
        inventory_rows,
        tab_score_heuristics={"operational_tokens": ["crop"]},
    )
    entry = next(r for r in selected if r["tab_title"] == "Crop Planner")
    assert entry["coverage_bonus"] == 1


def test_run_cohort_corpus_deep_loop_dedup_skips_old_years(tmp_path: Path):
    """Deep loop should skip non-latest years when domain context is active."""
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-20"

    workbook_index_payload = {
        "generated_from": f"drive_discovery_{date_stamp}.json",
        "record_count": 2,
        "records": [
            {
                "year": 2024,
                "workbook_code": "402",
                "spreadsheet_id": "s1",
                "spreadsheet_name": "402 2024",
            },
            {
                "year": 2026,
                "workbook_code": "402",
                "spreadsheet_id": "s2",
                "spreadsheet_name": "402 2026",
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
                "spreadsheet_id": "s1",
                "sheet_id": 0,
                "rows": 100,
                "cols": 10,
                "tab_title": "Plan Board",
            },
            {
                "spreadsheet_id": "s2",
                "sheet_id": 0,
                "rows": 100,
                "cols": 10,
                "tab_title": "Plan Board",
            },
        ],
    }
    broad_path = corpus_out_dir / f"broad_profile_coverage_{date_stamp}.json"
    broad_path.write_text(json.dumps(broad_payload), encoding="utf-8")

    selection_path = corpus_out_dir / f"tab_selection_{date_stamp}.json"
    selection_path.write_text(
        json.dumps({"approved_tabs": {"402": ["Plan Board"]}}),
        encoding="utf-8",
    )

    domain_ctx_path = tmp_path / "domain_context.yaml"
    domain_ctx_path.write_text(
        "domain: test\nyear_scope:\n  active: [2026]\n  archived: [2024]\nvocabulary:\n  operational: [plan]\n",
        encoding="utf-8",
    )
    corpus_config = {
        "folder_id": "drive-folder-1",
        "in_scope_workbooks": ["402"],
        "domain_context": str(domain_ctx_path),
    }
    mock_drive = MagicMock()
    mock_sheets = MagicMock()

    with (
        patch(
            "profiler.management.commands.profile_drive_folder.walk_folder"
        ) as mock_walk,
        patch("profiler.tools.cohort_corpus.list_tabs") as mock_list_tabs,
        patch(
            "profiler.tools.cohort_corpus.fetch_tab_grid", return_value={"sheets": []}
        ),
        patch(
            "profiler.tools.cohort_corpus.summarize_tab",
            return_value={"formula_cell_count": 0},
        ),
    ):
        _outputs = run_cohort_corpus(
            drive_service=mock_drive,
            sheets_service=mock_sheets,
            config=corpus_config,
            out_dir=corpus_out_dir,
            date_stamp=date_stamp,
            resume_from_tab_selection=True,
        )

    mock_walk.assert_not_called()
    mock_list_tabs.assert_not_called()

    deep_coverage = json.loads(
        (corpus_out_dir / f"deep_profile_coverage_{date_stamp}.json").read_text(
            encoding="utf-8"
        )
    )
    assert deep_coverage["success_count"] == 1
    assert "dedup_trace" in deep_coverage
    assert deep_coverage["dedup_trace"]["402"]["profiled_latest_only"] == ["Plan Board"]


# ── Fix 1: tab_exclude_patterns true-exclusion mode ────────────────────────


def test_compile_exclude_regexes_selects_exclude_mode_only():
    """_compile_exclude_regexes returns only entries with ``exclude: true``."""
    heuristics = {
        "tab_exclude_patterns": [
            {"pattern": r"^Sheet\d+$", "exclude": True},
            {"pattern": r"\b\d{3}\b", "penalty": -5},
            {"pattern": "hidden", "exclude": True},
        ]
    }
    regexes = _compile_exclude_regexes(heuristics)
    assert len(regexes) == 2
    assert regexes[0].pattern == r"^Sheet\d+$"
    assert regexes[1].pattern == "hidden"


def test_compile_exclude_regexes_skip_missing_pattern():
    """Entries without a ``pattern`` key are silently skipped."""
    regexes = _compile_exclude_regexes(
        {"tab_exclude_patterns": [{"exclude": True}, {}]}
    )
    assert len(regexes) == 0


def test_compile_exclude_regexes_skip_invalid_regex():
    """Invalid regex patterns are logged but do not crash."""
    regexes = _compile_exclude_regexes(
        {"tab_exclude_patterns": [{"pattern": "[invalid", "exclude": True}]}
    )
    assert len(regexes) == 0


def test_compile_exclude_regexes_backward_compat():
    """Entries without ``exclude: true`` are not returned (penalty-only)."""
    regexes = _compile_exclude_regexes(
        {"tab_exclude_patterns": [{"pattern": "temp", "penalty": -10}]}
    )
    assert len(regexes) == 0


def test_compile_exclude_regexes_none_config():
    """``None`` or empty config returns empty list."""
    assert _compile_exclude_regexes(None) == []
    assert _compile_exclude_regexes({}) == []


def test_select_tabs_from_inventory_exclude_mode_removes_tabs():
    """Tabs matching exclude-mode patterns are removed before scoring."""
    index = [
        {
            "spreadsheet_id": "s1",
            "workbook_code": "402",
            "year": 2026,
            "spreadsheet_name": "402 Plan",
        }
    ]
    inventory = [
        {
            "spreadsheet_id": "s1",
            "sheet_id": 1,
            "rows": 50,
            "cols": 10,
            "tab_title": "Plan Board",
        },
        {
            "spreadsheet_id": "s1",
            "sheet_id": 2,
            "rows": 10,
            "cols": 5,
            "tab_title": "Sheet1",
        },
        {
            "spreadsheet_id": "s1",
            "sheet_id": 3,
            "rows": 5,
            "cols": 3,
            "tab_title": "hidden data",
        },
    ]
    heuristics = {
        "operational_tokens": ["plan", "board"],
        "operational_weight": 3,
        "tab_exclude_patterns": [
            {"pattern": r"^Sheet\d+$", "exclude": True},
            {"pattern": "hidden", "exclude": True},
        ],
    }
    result = select_tabs_from_inventory(
        index, inventory, tab_score_heuristics=heuristics
    )
    titles = [r["tab_title"] for r in result]
    assert "Plan Board" in titles
    assert "Sheet1" not in titles
    assert "hidden data" not in titles


# ── Fix 1b: score_cutoff in auto_select_tabs ───────────────────────────────


def test_auto_select_tabs_score_cutoff_excludes_low_scores():
    """``score_cutoff`` excludes tabs below the threshold even if slots remain."""
    shortlist = [
        {
            "workbook_code": "402",
            "tab_title": "Good",
            "final_score": 5.0,
            "occurrences": 1,
            "avg_score": 5.0,
            "confidence": "high",
            "coverage_bonus": 0,
            "reasons": ["op"],
        },
        {
            "workbook_code": "402",
            "tab_title": "Mid",
            "final_score": 2.0,
            "occurrences": 1,
            "avg_score": 2.0,
            "confidence": "medium",
            "coverage_bonus": 0,
            "reasons": ["ref"],
        },
        {
            "workbook_code": "402",
            "tab_title": "Bad",
            "final_score": -3.0,
            "occurrences": 1,
            "avg_score": -3.0,
            "confidence": "low",
            "coverage_bonus": 0,
            "reasons": ["bad"],
        },
    ]
    approved, details = auto_select_tabs(shortlist, per_workbook=5, score_cutoff=0.0)
    assert "Good" in approved["402"]
    assert "Mid" in approved["402"]
    assert "Bad" not in approved["402"]


def test_auto_select_tabs_score_cutoff_no_effect_when_none():
    """``score_cutoff=None`` behaves as before (no filtering)."""
    shortlist = [
        {
            "workbook_code": "402",
            "tab_title": "A",
            "final_score": -5.0,
            "occurrences": 1,
            "avg_score": -5.0,
            "confidence": "low",
            "coverage_bonus": 0,
            "reasons": [],
        },
        {
            "workbook_code": "402",
            "tab_title": "B",
            "final_score": 3.0,
            "occurrences": 1,
            "avg_score": 3.0,
            "confidence": "high",
            "coverage_bonus": 0,
            "reasons": ["op"],
        },
    ]
    approved, details = auto_select_tabs(shortlist, per_workbook=5, score_cutoff=None)
    assert len(approved["402"]) == 2


# ── Fix 2: tab_details in auto_select_tabs return ──────────────────────────


def test_auto_select_tabs_details_includes_scores_and_reasons():
    """The second return value contains per-tab score data."""
    shortlist = [
        {
            "workbook_code": "402",
            "tab_title": "Plan",
            "final_score": 4.5,
            "occurrences": 2,
            "avg_score": 4.0,
            "confidence": "high",
            "coverage_bonus": 1,
            "reasons": ["op"],
        },
    ]
    approved, details = auto_select_tabs(shortlist, per_workbook=5)
    assert approved["402"] == ["Plan"]
    assert len(details["402"]) == 1
    entry = details["402"][0]
    assert entry["tab_title"] == "Plan"
    assert entry["final_score"] == 4.5
    assert entry["avg_score"] == 4.0
    assert entry["confidence"] == "high"
    assert entry["coverage_bonus"] == 1
    assert entry["reasons"] == ["op"]


def test_auto_select_tabs_details_multiple_workbooks():
    """Details are grouped per workbook code."""
    shortlist = [
        {
            "workbook_code": "402",
            "tab_title": "A",
            "final_score": 5.0,
            "occurrences": 1,
            "avg_score": 5.0,
            "confidence": "high",
            "coverage_bonus": 0,
            "reasons": ["op"],
        },
        {
            "workbook_code": "602",
            "tab_title": "B",
            "final_score": 3.0,
            "occurrences": 2,
            "avg_score": 3.0,
            "confidence": "medium",
            "coverage_bonus": 0,
            "reasons": ["ref"],
        },
    ]
    approved, details = auto_select_tabs(shortlist, per_workbook=5)
    assert "402" in details
    assert "602" in details
    assert details["402"][0]["tab_title"] == "A"
    assert details["602"][0]["tab_title"] == "B"


def test_auto_select_tabs_details_with_score_cutoff():
    """Details only includes tabs that survive the cutoff."""
    shortlist = [
        {
            "workbook_code": "402",
            "tab_title": "High",
            "final_score": 8.0,
            "occurrences": 1,
            "avg_score": 8.0,
            "confidence": "high",
            "coverage_bonus": 0,
            "reasons": ["op"],
        },
        {
            "workbook_code": "402",
            "tab_title": "Low",
            "final_score": -1.0,
            "occurrences": 1,
            "avg_score": -1.0,
            "confidence": "low",
            "coverage_bonus": 0,
            "reasons": ["bad"],
        },
    ]
    approved, details = auto_select_tabs(shortlist, per_workbook=5, score_cutoff=0.0)
    assert len(details["402"]) == 1
    assert details["402"][0]["tab_title"] == "High"


# ── Fix 3: per_workbook_heuristic_overrides ────────────────────────────────


def test_select_tabs_per_workbook_heuristic_overrides():
    """Per-workbook heuristic overrides affect scoring for that workbook only."""
    index = [
        {
            "spreadsheet_id": "s402",
            "workbook_code": "402",
            "year": 2026,
            "spreadsheet_name": "402 Plan",
        },
        {
            "spreadsheet_id": "s602",
            "workbook_code": "602",
            "year": 2026,
            "spreadsheet_name": "602 Harvest",
        },
    ]
    inventory = [
        {
            "spreadsheet_id": "s402",
            "sheet_id": 1,
            "rows": 10,
            "cols": 5,
            "tab_title": "Crop Plan",
        },
        {
            "spreadsheet_id": "s402",
            "sheet_id": 2,
            "rows": 10,
            "cols": 5,
            "tab_title": "Other Data",
        },
        {
            "spreadsheet_id": "s602",
            "sheet_id": 3,
            "rows": 10,
            "cols": 5,
            "tab_title": "Harvest Log",
        },
        {
            "spreadsheet_id": "s602",
            "sheet_id": 4,
            "rows": 10,
            "cols": 5,
            "tab_title": "Temp Ref",
        },
    ]
    base = {
        "operational_tokens": [],
        "reference_tokens": [],
        "support_tokens": [],
        "derived_tokens": [],
    }
    overrides = {
        "402": {"operational_tokens": ["crop", "plan"], "operational_weight": 4},
    }
    result = select_tabs_from_inventory(
        index,
        inventory,
        tab_score_heuristics=base,
        per_workbook_heuristic_overrides=overrides,
    )
    scores = {r["tab_title"]: r["final_score"] for r in result}
    # 402's "Crop Plan" gets +4 from overrides (no other matches)
    assert scores.get("Crop Plan", 0) == 4.0
    # 402's "Other Data" has no operational token match → score 0 → below min → excluded
    assert "Other Data" not in scores
    # 602's tabs have no overrides (no operational tokens in base) → excluded below min
    assert "Harvest Log" not in scores
    assert "Temp Ref" not in scores


def test_select_tabs_per_workbook_exclude_patterns():
    """Per-workbook exclude-mode patterns remove tabs for that workbook only."""
    index = [
        {
            "spreadsheet_id": "s402",
            "workbook_code": "402",
            "year": 2026,
            "spreadsheet_name": "402 Plan",
        },
    ]
    inventory = [
        {
            "spreadsheet_id": "s402",
            "sheet_id": 1,
            "rows": 100,
            "cols": 10,
            "tab_title": "Plan Board",
        },
        {
            "spreadsheet_id": "s402",
            "sheet_id": 2,
            "rows": 10,
            "cols": 5,
            "tab_title": "Sheet1",
        },
    ]
    base = {
        "operational_tokens": ["plan", "board"],
        "operational_weight": 3,
        "reference_tokens": [],
        "support_tokens": [],
        "derived_tokens": [],
    }
    overrides = {
        "402": {"tab_exclude_patterns": [{"pattern": r"^Sheet\d+$", "exclude": True}]}
    }
    result = select_tabs_from_inventory(
        index,
        inventory,
        tab_score_heuristics=base,
        per_workbook_heuristic_overrides=overrides,
    )
    titles = [r["tab_title"] for r in result]
    assert "Plan Board" in titles
    assert "Sheet1" not in titles
