from __future__ import annotations

import pytest
from django.core.management.base import CommandError

from profiler.tools.coda_corpus import (
    apply_table_selection_overrides,
    build_coda_table_index,
    enrich_coda_columns,
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


def test_enrich_coda_columns_adds_enrichment_fields():
    columns = [
        {
            "doc_name": "Doc1",
            "table_name": "Orders",
            "column_name": "customer_id",
            "proposed_canonical_field": "customer_id",
            "priority_score": 3,
            "priority_reasons": ["relation_or_ref"],
            "evidence": {
                "null_rate": 0.01,
                "unique_count_sample": 95,
                "format_type": "int",
                "ref_tables_seen": [],
                "non_null_count": 100,
            },
            "has_formula": False,
            "is_relation_type": False,
        },
        {
            "doc_name": "Doc1",
            "table_name": "Orders",
            "column_name": "total",
            "proposed_canonical_field": "total",
            "priority_score": 1,
            "priority_reasons": [],
            "evidence": {
                "null_rate": 0.1,
                "unique_count_sample": 50,
                "format_type": "number",
                "ref_tables_seen": [],
                "non_null_count": 90,
            },
            "has_formula": False,
            "is_relation_type": False,
        },
        {
            "doc_name": "Doc1",
            "table_name": "Products",
            "column_name": "Category",
            "proposed_canonical_field": "category",
            "priority_score": 2,
            "priority_reasons": ["relation_or_ref"],
            "evidence": {
                "null_rate": 0.0,
                "unique_count_sample": 8,
                "format_type": "lookup",
                "ref_tables_seen": [{"tableName": "Categories", "tableId": "t123"}],
                "non_null_count": 200,
            },
            "has_formula": False,
            "is_relation_type": True,
            "ref_tables_seen": [{"tableName": "Categories", "tableId": "t123"}],
        },
        {
            "doc_name": "Doc1",
            "table_name": "Products",
            "column_name": "computed_field",
            "proposed_canonical_field": "computed_field",
            "priority_score": 1,
            "priority_reasons": ["formula_column"],
            "evidence": {
                "null_rate": 0.5,
                "unique_count_sample": 10,
                "format_type": "number",
                "ref_tables_seen": [],
                "non_null_count": 50,
            },
            "has_formula": True,
            "is_relation_type": False,
        },
        {
            "doc_name": "Doc1",
            "table_name": "Users",
            "column_name": "id",
            "proposed_canonical_field": "id",
            "priority_score": 0,
            "priority_reasons": [],
            "evidence": {
                "null_rate": 0.0,
                "unique_count_sample": 200,
                "format_type": "int",
                "ref_tables_seen": [],
                "non_null_count": 200,
            },
            "has_formula": False,
            "is_relation_type": False,
        },
    ]
    enrich_coda_columns(columns)

    col_cust = columns[0]
    assert col_cust["is_computed"] is False
    assert col_cust["suggested_fk_target"] == "Customer"
    assert col_cust["is_import_key_candidate"] is True

    col_total = columns[1]
    assert col_total["is_computed"] is False
    assert col_total["suggested_fk_target"] is None
    assert col_total["is_import_key_candidate"] is False

    col_category = columns[2]
    assert col_category["is_computed"] is False
    assert col_category["suggested_fk_target"] == "Categories"
    assert col_category["is_import_key_candidate"] is False

    col_computed = columns[3]
    assert col_computed["is_computed"] is True
    assert col_computed["is_import_key_candidate"] is False

    col_id = columns[4]
    assert col_id["is_import_key_candidate"] is True
    assert col_id["is_computed"] is False


def test_enrich_coda_columns_import_key_by_uniqueness():
    columns = [
        {
            "doc_name": "Doc1",
            "table_name": "T",
            "column_name": "sku_code",
            "proposed_canonical_field": "sku_code",
            "priority_score": 0,
            "priority_reasons": [],
            "evidence": {
                "null_rate": 0.02,
                "unique_count_sample": 90,
                "format_type": "text",
                "ref_tables_seen": [],
                "non_null_count": 95,
            },
            "has_formula": False,
            "is_relation_type": False,
        },
        {
            "doc_name": "Doc1",
            "table_name": "T",
            "column_name": "regular_col",
            "proposed_canonical_field": "regular_col",
            "priority_score": 0,
            "priority_reasons": [],
            "evidence": {
                "null_rate": 0.02,
                "unique_count_sample": 40,
                "format_type": "text",
                "ref_tables_seen": [],
                "non_null_count": 95,
            },
            "has_formula": False,
            "is_relation_type": False,
        },
    ]
    enrich_coda_columns(columns)

    assert columns[0]["is_import_key_candidate"] is True
    assert columns[1]["is_import_key_candidate"] is False


def test_enrich_coda_columns_fk_from_relation_type():
    columns = [
        {
            "doc_name": "Doc1",
            "table_name": "T",
            "column_name": "Project",
            "proposed_canonical_field": "project",
            "priority_score": 2,
            "priority_reasons": ["relation_or_ref"],
            "evidence": {
                "null_rate": 0.01,
                "unique_count_sample": 10,
                "format_type": "lookup",
                "ref_tables_seen": [{"tableName": "Projects", "tableId": "p1"}],
                "non_null_count": 100,
            },
            "has_formula": False,
            "is_relation_type": True,
            "ref_tables_seen": [{"tableName": "Projects", "tableId": "p1"}],
        },
    ]
    enrich_coda_columns(columns)
    assert columns[0]["suggested_fk_target"] == "Projects"
    assert columns[0]["is_computed"] is False
