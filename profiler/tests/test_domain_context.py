"""Tests for domain context loading, vocabulary merging, and index deduplication."""

from pathlib import Path

import pytest

from profiler.tools.domain_context import (
    DomainContext,
    deduplicate_index_records,
    has_meaningful_vocabulary,
    load_domain_context,
    merge_vocabulary,
)


def test_load_domain_context_from_yaml(tmp_path):
    ctx_file = tmp_path / "domain_context.yaml"
    ctx_file.write_text(
        "domain: farm_management\n"
        "description: Farm ops tracking\n"
        "year_scope:\n"
        "  active: [2025, 2026]\n"
        "  archived: [2023, 2024]\n"
        "deduplication:\n"
        "  strategy: latest_year\n"
        "  exceptions: []\n"
        "vocabulary:\n"
        "  operational: [planting, harvest]\n"
        "  reference: [variety, crop]\n"
        "  support: [index]\n"
        "  derived: [summary, pivot]\n"
        "glossary:\n"
        "  qty: quantity\n"
        "scope_notes: Active year is 2025\n"
    )
    ctx = load_domain_context(ctx_file)
    assert ctx is not None
    assert ctx.domain == "farm_management"
    assert ctx.year_scope.active == [2025, 2026]
    assert ctx.vocabulary.operational == ["planting", "harvest"]
    assert ctx.glossary == {"qty": "quantity"}


def test_load_domain_context_missing_file(tmp_path):
    assert load_domain_context(tmp_path / "nonexistent.yaml") is None


def test_load_domain_context_strips_underscore_keys(tmp_path):
    ctx_file = tmp_path / "domain_context.yaml"
    ctx_file.write_text("_doc: ignored\ndomain: test\n")
    ctx = load_domain_context(ctx_file)
    assert ctx is not None
    assert ctx.domain == "test"


def test_merge_vocabulary_with_context():
    ctx = DomainContext(
        vocabulary=DomainContext.VocabularyContext(
            operational=["planting", "harvest"], reference=["variety"]
        )
    )
    heuristics = {
        "operational_tokens": ["nursery"],
        "reference_tokens": ["reference"],
        "support_tokens": ["index"],
        "derived_tokens": ["summary"],
    }
    merged = merge_vocabulary(heuristics, ctx)
    assert "planting" in merged["operational_tokens"]
    assert "nursery" in merged["operational_tokens"]
    assert merged["operational_tokens"].count("planting") == 1


def test_merge_vocabulary_no_context():
    heuristics = {"operational_tokens": ["nursery"]}
    assert merge_vocabulary(heuristics, None) == heuristics


def test_deduplicate_index_records_filters_archived():
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(active=[2025, 2026], archived=[2023, 2024], forward=[]),
        deduplication=DomainContext.DeduplicationContext(strategy="latest_year", exceptions=[]),
    )
    records = [
        {"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 2023"},
        {"year": 2024, "workbook_code": "402", "spreadsheet_id": "s2", "spreadsheet_name": "402 2024"},
        {"year": 2025, "workbook_code": "402", "spreadsheet_id": "s3", "spreadsheet_name": "402 2025"},
        {"year": 2026, "workbook_code": "402", "spreadsheet_id": "s4", "spreadsheet_name": "402 2026"},
    ]
    approved = {"402": ["Crop Planner"]}
    filtered = deduplicate_index_records(records, approved, ctx)
    assert len(filtered) == 2
    assert {r["year"] for r in filtered} == {2025, 2026}


def test_deduplicate_index_records_archived_filter():
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(active=[2025], archived=[2023], forward=[]),
        deduplication=DomainContext.DeduplicationContext(strategy="latest_year", exceptions=[]),
    )
    records = [
        {"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 2023"},
        {"year": 2025, "workbook_code": "402", "spreadsheet_id": "s3", "spreadsheet_name": "402 2025"},
    ]
    approved = {"402": ["Crop Planner"]}
    filtered = deduplicate_index_records(records, approved, ctx)
    assert len(filtered) == 1
    assert filtered[0]["year"] == 2025


def test_deduplicate_index_records_no_domain_context():
    records = [{"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1"}]
    approved = {"402": ["Crop Planner"]}
    filtered = deduplicate_index_records(records, approved, None)
    assert len(filtered) == 1


def test_has_meaningful_vocabulary_empty():
    ctx = DomainContext()
    assert not has_meaningful_vocabulary(ctx)


def test_has_meaningful_vocabulary_with_operational():
    ctx = DomainContext()
    ctx.vocabulary.operational = ["crop"]
    assert has_meaningful_vocabulary(ctx)


def test_has_meaningful_vocabulary_with_reference():
    ctx = DomainContext()
    ctx.vocabulary.reference = ["variety"]
    assert has_meaningful_vocabulary(ctx)


def test_has_meaningful_vocabulary_none():
    assert not has_meaningful_vocabulary(None)
