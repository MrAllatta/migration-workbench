from __future__ import annotations

import pytest
from django.core.management.base import CommandError

from profiler.tools.coda_corpus import (
    apply_table_selection_overrides,
    build_coda_table_index,
    finalize_relationship_summary,
    score_table,
)


def test_score_table_keywords_and_grid():
    s, reasons = score_table(
        "Crop Planning Main",
        row_count=2000,
        col_count=25,
        table_score_heuristics={
            "prefer_keywords": ["planning"],
            "deprioritize_keywords": ["scratch"],
        },
    )
    assert s >= 4
    assert "prefer_keyword" in reasons
    assert "many_rows" in reasons or "wide_table" in reasons


def test_score_table_deprioritize():
    s, reasons = score_table(
        "scratch pad",
        row_count=5,
        col_count=3,
        table_score_heuristics={"deprioritize_keywords": ["scratch"]},
    )
    assert "deprioritize_keyword" in reasons
    assert s <= 0


def test_finalize_relationship_summary_dedupes_links():
    edges = [
        {
            "doc_name": "D",
            "doc_id": "d1",
            "from_table_id": "a",
            "from_table_name": "A",
            "from_column": "c1",
            "to_table_id": "b",
            "to_table_name": "B",
        },
        {
            "doc_name": "D",
            "doc_id": "d1",
            "from_table_id": "a",
            "from_table_name": "A",
            "from_column": "c2",
            "to_table_id": "b",
            "to_table_name": "B",
        },
    ]
    summary = finalize_relationship_summary(edges)
    assert summary["edge_count"] == 2
    assert summary["unique_table_link_count"] == 1
    assert len(summary["unique_table_links"]) == 1


def test_build_coda_table_index_splits_views():
    discovery = [
        {
            "name": "D1",
            "doc_id": "doc1",
            "tables": [
                {"id": "g1", "name": "Base", "type": "table", "rowCount": 10},
                {"id": "v1", "name": "Filtered", "type": "view", "rowCount": 5, "parentTable": {"id": "g1", "name": "Base"}},
            ],
        }
    ]
    idx = build_coda_table_index(discovery)
    assert len(idx["base_tables"]) == 1
    assert idx["base_tables"][0]["table_id"] == "g1"
    assert idx["base_tables"][0]["is_importable"] is True
    assert len(idx["views"]) == 1
    assert idx["views"][0]["table_id"] == "v1"
    assert idx["views"][0]["is_importable"] is False


def test_apply_table_selection_overrides_replace():
    approved = {"Doc A": ["T1", "T2"]}
    merged = apply_table_selection_overrides(
        approved,
        {"Doc A": {"replace": True, "tables": ["Only"]}},
    )
    assert merged["Doc A"] == ["Only"]


def test_apply_table_selection_overrides_add_remove():
    approved = {"Doc A": ["T1", "T2", "T3"]}
    merged = apply_table_selection_overrides(
        approved,
        {"Doc A": {"remove": ["T2"], "add": ["T4"]}},
    )
    assert merged["Doc A"] == ["T1", "T3", "T4"]


def test_apply_table_selection_overrides_invalid():
    with pytest.raises(CommandError):
        apply_table_selection_overrides({}, {"Doc": "not-a-dict"})
