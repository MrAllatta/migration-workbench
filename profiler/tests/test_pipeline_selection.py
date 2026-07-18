"""Tests for shared corpus pipeline selection logic."""

import pytest
from django.core.management.base import CommandError

from profiler.pipeline.selection import (
    TAB_SELECTION_OVERRIDE_KEYS,
    apply_tab_selection_overrides,
    auto_select_tabs,
)


class TestAutoSelectTabs:
    def test_basic_selection(self):
        shortlist = [
            {"workbook_code": "101", "tab_title": "Plan", "final_score": 8, "occurrences": 2},
            {"workbook_code": "101", "tab_title": "Log", "final_score": 5, "occurrences": 1},
            {"workbook_code": "101", "tab_title": "Ref", "final_score": 3, "occurrences": 1},
            {"workbook_code": "201", "tab_title": "Summary", "final_score": 9, "occurrences": 3},
        ]
        approved, details = auto_select_tabs(shortlist, per_workbook=2)
        assert approved["101"] == ["Plan", "Log"]
        assert approved["201"] == ["Summary"]
        assert len(details["101"]) == 2

    def test_per_code_overrides(self):
        shortlist = [
            {"workbook_code": "101", "tab_title": "A", "final_score": 8, "occurrences": 1},
            {"workbook_code": "101", "tab_title": "B", "final_score": 7, "occurrences": 1},
            {"workbook_code": "101", "tab_title": "C", "final_score": 6, "occurrences": 1},
        ]
        approved, _ = auto_select_tabs(shortlist, per_workbook=1, per_code_overrides={"101": 3})
        assert len(approved["101"]) == 3

    def test_score_cutoff(self):
        shortlist = [
            {"workbook_code": "101", "tab_title": "A", "final_score": 8, "occurrences": 1},
            {"workbook_code": "101", "tab_title": "B", "final_score": 2, "occurrences": 1},
        ]
        approved, _ = auto_select_tabs(shortlist, per_workbook=5, score_cutoff=5)
        assert approved["101"] == ["A"]

    def test_empty_shortlist(self):
        approved, details = auto_select_tabs([], per_workbook=3)
        assert approved == {}
        assert details == {}


class TestApplyTabSelectionOverrides:
    def test_no_overrides_returns_copy(self):
        approved = {"101": ["Plan", "Log"]}
        result = apply_tab_selection_overrides(approved, None)
        assert result == {"101": ["Plan", "Log"]}
        result["101"].append("X")
        assert approved["101"] == ["Plan", "Log"]  # original unchanged

    def test_add_tabs(self):
        approved = {"101": ["Plan"]}
        overrides = {"101": {"add": ["Log", "Ref"]}}
        result = apply_tab_selection_overrides(approved, overrides)
        assert result["101"] == ["Plan", "Log", "Ref"]

    def test_add_deduplicates(self):
        approved = {"101": ["Plan"]}
        overrides = {"101": {"add": ["Plan", "Log"]}}
        result = apply_tab_selection_overrides(approved, overrides)
        assert result["101"] == ["Plan", "Log"]

    def test_remove_tabs(self):
        approved = {"101": ["Plan", "Log", "Ref"]}
        overrides = {"101": {"remove": ["Log"]}}
        result = apply_tab_selection_overrides(approved, overrides)
        assert result["101"] == ["Plan", "Ref"]

    def test_replace_tabs(self):
        approved = {"101": ["Plan", "Log"]}
        overrides = {"101": {"replace": True, "tabs": ["Ref", "Summary"]}}
        result = apply_tab_selection_overrides(approved, overrides)
        assert result["101"] == ["Ref", "Summary"]

    def test_rejects_unknown_keys(self):
        with pytest.raises(CommandError, match="unknown keys"):
            apply_tab_selection_overrides({"101": ["Plan"]}, {"101": {"bogus": True}})

    def test_rejects_tabs_without_replace(self):
        with pytest.raises(CommandError, match="tabs.*without.*replace"):
            apply_tab_selection_overrides({"101": ["Plan"]}, {"101": {"tabs": ["X"]}})

    def test_rejects_replace_without_tabs(self):
        with pytest.raises(CommandError, match="requires 'tabs'"):
            apply_tab_selection_overrides(
                {"101": ["Plan"]}, {"101": {"replace": True}}
            )

    def test_rejects_non_mapping_entry(self):
        with pytest.raises(CommandError, match="must be a mapping"):
            apply_tab_selection_overrides({"101": ["Plan"]}, {"101": "bad"})

    def test_override_keys_constant(self):
        assert TAB_SELECTION_OVERRIDE_KEYS == {"add", "remove", "replace", "tabs"}
