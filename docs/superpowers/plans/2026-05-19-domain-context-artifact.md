# Domain Context Artifact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a `domain_context.yaml` artifact that the profiler reads at scoring time, enabling period-aware deduplication, vocabulary-to-token mapping, and glossary synonym expansion. Fix four pipeline friction points along the way.

**Architecture:** A `DomainContext` dataclass loaded from YAML is referenced by `cohort_corpus.json`. It flows into `select_tabs_from_inventory()`, `score_tab()`, and `derive_column_candidates()` via optional parameters (backward-compatible). The schema uses `periods.profile/skip` (not `year_scope.active/archived`) to generalize across years, quarters, months, or editions. A separate `deduplicate_index_records()` filters the index before Phase 3 so structural duplicates across periods are profiled only for the latest period. Vocabulary merges into heuristic tokens. Glossary expands column matching.

**Tech Stack:** Python 3.11+, Django, pytest, PyYAML (add to pyproject.toml if missing)

**Key architectural insight — why dedup is NOT inside select_tabs_from_inventory:** The deep profiling loop (line 1412) iterates over `index_records` directly, not the shortlist. Writing `duplicate_years` on shortlist entries only changes display — Phase 3 still sees all 4 index records for "Crop Planner" and profiles all 4 spreadsheets. The fix: a standalone `deduplicate_index_records()` called in `run_cohort_corpus` between tab selection and deep profiling. Shortlist dedup annotation is informational only; the real filtering happens at the index level.

**Why `periods.profile/skip` not `year_scope.active/archived`:** The regex in `cohort_corpus.json` extracts a numeric period value from spreadsheet names. For farms that's a year. For monthly reports it's `202501`. For editions it's `1,2,3,4`. The dedup logic (`max(rec["year"])`) works for any numeric monotonic period. The schema names communicate the universal concept, not the farm-specific instance. `forward` is removed — it duplicates `profile` (if you want to profile a period, add it to `profile`).

---

### Task 1: DomainContext dataclass and loader

**Files:**
- Create: `profiler/tools/domain_context.py`
- Create: `profiler/tests/test_domain_context.py`
- Check: `pyproject.toml` for `pyyaml` dependency

- [ ] **Step 1: Verify PyYAML is in pyproject.toml**

Run: `cd /home/user/migration-workbench && grep -i yaml pyproject.toml`
If missing, add `"pyyaml"` to the `dependencies` list in `pyproject.toml`.

- [ ] **Step 2: Write failing tests**

Create `profiler/tests/test_domain_context.py`:

```python
"""Tests for domain context loading, vocabulary merging, and index deduplication."""

from pathlib import Path

import pytest

from profiler.tools.domain_context import (
    DomainContext,
    deduplicate_index_records,
    load_domain_context,
    merge_vocabulary,
)


def test_load_domain_context_from_yaml(tmp_path):
    ctx_file = tmp_path / "domain_context.yaml"
    ctx_file.write_text(
        "domain: farm_management\n"
        "description: Farm ops tracking\n"
        "periods:\n"
        "  profile: [2025, 2026]\n"
        "  skip: [2023, 2024]\n"
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


def test_deduplicate_index_records_latest_year():
    """4 records for same (workbook_code, tab_title) across years → keep latest only."""
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
    # Need to associate each record with tabs — inventory data isn't in index_records
    # The dedup function groups records by workbook_code and for each tab_title in
    # approved_tabs, deduplicates based on the index records for that workbook_code
    filtered = deduplicate_index_records(records, approved, ctx)
    assert len(filtered) == 1
    assert filtered[0]["year"] == 2026
    assert filtered[0]["spreadsheet_id"] == "s4"


def test_deduplicate_index_records_exception():
    """Dedup exception tab keeps all years."""
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(active=[2025], archived=[2023], forward=[]),
        deduplication=DomainContext.DeduplicationContext(
            strategy="latest_year",
            exceptions=[{"tab_title": "Sales Actuals", "reason": "Changes yearly"}],
        ),
    )
    records = [
        {"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 2023"},
        {"year": 2025, "workbook_code": "402", "spreadsheet_id": "s3", "spreadsheet_name": "402 2025"},
    ]
    approved = {"402": ["Sales Actuals"]}
    filtered = deduplicate_index_records(records, approved, ctx)
    assert len(filtered) == 2


def test_deduplicate_index_records_archived_filter():
    """Archived years are removed regardless of dedup strategy."""
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
    """Without domain context, records pass through unchanged."""
    records = [{"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1"}]
    approved = {"402": ["Crop Planner"]}
    filtered = deduplicate_index_records(records, approved, None)
    assert len(filtered) == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_domain_context.py -v 2>&1 | head -15`
Expected: ImportError — module not found.

- [ ] **Step 4: Implement DomainContext, load_domain_context, merge_vocabulary, deduplicate_index_records**

Create `profiler/tools/domain_context.py`:

```python
"""Domain context artifact: the profiler's model of the business domain.

Loaded from a YAML file referenced by ``cohort_corpus.json``, the domain context
provides vocabulary (mapped to heuristic tokens), year scoping, structural
deduplication, and synonym expansion. When absent, all profiler behavior is
identical to the pre-domain-context baseline.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class DomainContext:
    """Structured domain knowledge consumed by the profiler at scoring time."""

    @dataclass
    class YearScope:
        active: list[int] = field(default_factory=list)
        archived: list[int] = field(default_factory=list)
        forward: list[int] = field(default_factory=list)

    @dataclass
    class DeduplicationContext:
        strategy: str = "latest_year"
        exceptions: list[dict] = field(default_factory=list)

    @dataclass
    class VocabularyContext:
        operational: list[str] = field(default_factory=list)
        reference: list[str] = field(default_factory=list)
        support: list[str] = field(default_factory=list)
        derived: list[str] = field(default_factory=list)

    domain: str = ""
    description: str = ""
    year_scope: YearScope = field(default_factory=YearScope)
    deduplication: DeduplicationContext = field(default_factory=DeduplicationContext)
    entities: list[dict] = field(default_factory=list)
    vocabulary: VocabularyContext = field(default_factory=VocabularyContext)
    glossary: dict[str, str] = field(default_factory=dict)
    scope_notes: str = ""

    def active_years(self) -> set[int]:
        years: set[int] = set(self.year_scope.active)
        years.update(self.year_scope.archived)
        years.update(self.year_scope.forward)
        return years

    def is_archived_year(self, year: int) -> bool:
        return year in self.year_scope.archived

    def is_deduplication_exception(self, tab_title: str) -> bool:
        for exc in self.deduplication.exceptions:
            if exc.get("tab_title") == tab_title:
                return True
        return False


def load_domain_context(path: str | Path) -> DomainContext | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    raw = {k: v for k, v in raw.items() if not k.startswith("_")}

    year_scope_data = raw.get("year_scope") or {}
    dedup_data = raw.get("deduplication") or {}
    vocab_data = raw.get("vocabulary") or {}

    return DomainContext(
        domain=str(raw.get("domain", "")),
        description=str(raw.get("description", "")),
        year_scope=DomainContext.YearScope(
            active=year_scope_data.get("active") or [],
            archived=year_scope_data.get("archived") or [],
            forward=year_scope_data.get("forward") or [],
        ),
        deduplication=DomainContext.DeduplicationContext(
            strategy=str(dedup_data.get("strategy", "latest_year")),
            exceptions=dedup_data.get("exceptions") or [],
        ),
        entities=raw.get("entities") or [],
        vocabulary=DomainContext.VocabularyContext(
            operational=vocab_data.get("operational") or [],
            reference=vocab_data.get("reference") or [],
            support=vocab_data.get("support") or [],
            derived=vocab_data.get("derived") or [],
        ),
        glossary=raw.get("glossary") or {},
        scope_notes=str(raw.get("scope_notes", "")),
    )


def merge_vocabulary(
    heuristics: dict,
    domain_context: DomainContext | None,
) -> dict:
    if domain_context is None:
        return heuristics
    token_keys = {
        "operational_tokens": domain_context.vocabulary.operational,
        "reference_tokens": domain_context.vocabulary.reference,
        "support_tokens": domain_context.vocabulary.support,
        "derived_tokens": domain_context.vocabulary.derived,
    }
    merged = dict(heuristics)
    for hkey, vocab_list in token_keys.items():
        existing = set(merged.get(hkey) or [])
        for token in vocab_list:
            existing.add(token.lower())
        merged[hkey] = sorted(existing)
    return merged


def deduplicate_index_records(
    index_records: list[dict],
    approved_tabs: dict[str, list[str]],
    domain_context: DomainContext | None,
) -> list[dict]:
    """Filter index records for Phase 3 deep profiling.

    1. Remove records for archived years.
    2. For each ``(workbook_code, tab_title)`` in *approved_tabs* that appears
       across multiple years and is **not** a dedup exception, keep only the
       latest year's record.

    When *domain_context* is ``None``, returns *index_records* unchanged.
    """
    if domain_context is None:
        return list(index_records)

    # Step 1: remove archived years
    filtered = [
        rec
        for rec in index_records
        if not domain_context.is_archived_year(rec.get("year"))
    ]

    # Step 2: group by workbook_code, deduplicate tabs across years
    grouped: dict[str, list[dict]] = defaultdict(list)
    for rec in filtered:
        grouped[rec["workbook_code"]].append(rec)

    result: list[dict] = []
    for workbook_code, wb_records in grouped.items():
        tab_titles = approved_tabs.get(workbook_code, [])
        for tab_title in tab_titles:
            if domain_context.is_deduplication_exception(tab_title):
                # Keep all records for this tab
                result.extend(
                    rec for rec in wb_records
                    if rec.get("spreadsheet_id")
                )
            else:
                # Keep only the latest year's record for this tab
                latest = max(
                    (rec for rec in wb_records),
                    key=lambda r: r.get("year") or 0,
                    default=None,
                )
                if latest is not None:
                    result.append(latest)

    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_domain_context.py -v`
Expected: All 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add profiler/tools/domain_context.py profiler/tests/test_domain_context.py
git commit -m "feat: DomainContext dataclass, loader, vocabulary merger, and index deduplicator"
```

---

### Task 2: Domain context integration in select_tabs_from_inventory + score_tab

**Files:**
- Modify: `profiler/tools/cohort_corpus.py` (score_tab, select_tabs_from_inventory)
- Modify: `profiler/tests/test_cohort_corpus_tools.py`

**What changes inside each function:**

`score_tab()` — gains `domain_context: DomainContext | None = None`:
- Appends glossary expansions to the tab title text so "Qty Tracker" matches operational token "quantity"
- No other behavioral change

`select_tabs_from_inventory()` — gains `domain_context: DomainContext | None = None`:
- Merges vocabulary into heuristics via `merge_vocabulary()`
- Replaces coverage bonus: `>= 3 years regardless` → `>= 2 active/forward years` (when domain_context present)
- Annotates shortlist entries with `duplicate_years` when dedup would collapse them (informational only; actual filtering happens in Task 4)

- [ ] **Step 1: Write failing tests**

Append to `profiler/tests/test_cohort_corpus_tools.py`:

```python
from profiler.tools.domain_context import DomainContext


def test_score_tab_glossary_expansion():
    """Glossary 'qty → quantity' lets 'qty' in tab title match 'quantity' token."""
    ctx = DomainContext(glossary={"qty": "quantity", "amt": "amount"})
    score, reasons, breakdown = score_tab(
        "Qty Tracker", 100, 20,
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
        {"year": 2025, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402"},
    ]
    inventory_rows = [
        {"spreadsheet_id": "s1", "sheet_id": 1, "rows": 500, "cols": 20, "tab_title": "Crop Planner"},
    ]
    selected = select_tabs_from_inventory(
        index_records, inventory_rows,
        tab_score_heuristics={},
        domain_context=ctx,
    )
    assert any(r["tab_title"] == "Crop Planner" for r in selected)


def test_select_tabs_coverage_bonus_active_years():
    """Coverage bonus is +1 when tab appears in >=2 active/forward years."""
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(active=[2025, 2026], archived=[2023, 2024], forward=[]),
    )
    index_records = [
        {"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 2023"},
        {"year": 2024, "workbook_code": "402", "spreadsheet_id": "s2", "spreadsheet_name": "402 2024"},
        {"year": 2025, "workbook_code": "402", "spreadsheet_id": "s3", "spreadsheet_name": "402 2025"},
        {"year": 2026, "workbook_code": "402", "spreadsheet_id": "s4", "spreadsheet_name": "402 2026"},
    ]
    inventory_rows = [
        {"spreadsheet_id": f"s{i}", "sheet_id": 1, "rows": 500, "cols": 20, "tab_title": "Crop Planner"}
        for i in range(1, 5)
    ]
    selected = select_tabs_from_inventory(
        index_records, inventory_rows,
        tab_score_heuristics={"operational_tokens": ["crop"]},
        domain_context=ctx,
    )
    entry = next(r for r in selected if r["tab_title"] == "Crop Planner")
    assert entry["coverage_bonus"] == 1


def test_select_tabs_duplicate_years_annotation():
    """Shortlist entries get duplicate_years annotation when spanning multiple years."""
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(active=[2025, 2026], archived=[2023, 2024], forward=[]),
    )
    index_records = [
        {"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 2023"},
        {"year": 2026, "workbook_code": "402", "spreadsheet_id": "s4", "spreadsheet_name": "402 2026"},
    ]
    inventory_rows = [
        {"spreadsheet_id": "s1", "sheet_id": 1, "rows": 500, "cols": 20, "tab_title": "Crop Planner"},
        {"spreadsheet_id": "s4", "sheet_id": 1, "rows": 500, "cols": 20, "tab_title": "Crop Planner"},
    ]
    selected = select_tabs_from_inventory(
        index_records, inventory_rows,
        tab_score_heuristics={"operational_tokens": ["crop"]},
        domain_context=ctx,
    )
    entry = next(r for r in selected if r["tab_title"] == "Crop Planner")
    assert entry.get("duplicate_years") == [2023]


def test_select_tabs_no_domain_context_unchanged():
    """Without domain_context, legacy behavior: old coverage bonus, no duplicate_years."""
    index_records = [
        {"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 2023"},
        {"year": 2024, "workbook_code": "402", "spreadsheet_id": "s2", "spreadsheet_name": "402 2024"},
        {"year": 2025, "workbook_code": "402", "spreadsheet_id": "s3", "spreadsheet_name": "402 2025"},
    ]
    inventory_rows = [
        {"spreadsheet_id": f"s{i}", "sheet_id": 1, "rows": 500, "cols": 20, "tab_title": "Crop Planner"}
        for i in range(1, 4)
    ]
    selected = select_tabs_from_inventory(
        index_records, inventory_rows,
        tab_score_heuristics={"operational_tokens": ["crop"]},
    )
    entry = next(r for r in selected if r["tab_title"] == "Crop Planner")
    assert entry["coverage_bonus"] == 1
    assert "duplicate_years" not in entry
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_cohort_corpus_tools.py::test_score_tab_glossary_expansion profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_vocabulary_merging profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_coverage_bonus_active_years profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_duplicate_years_annotation profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_no_domain_context_unchanged -v 2>&1 | tail -10`
Expected: FAIL — function signatures don't accept `domain_context`, `DomainContext` not importable in test.

- [ ] **Step 3: Implement changes in cohort_corpus.py**

**3a.** Add imports (after existing `from profiler.tools.enrichment_utils import ...`):

```python
from profiler.tools.domain_context import DomainContext, merge_vocabulary
from profiler.tools.enrichment_utils import (
    _ENTITY_KEYWORDS,
    _IDENTIFIER_NAMES,
    _IDENTIFIER_SUFFIXES,
    _to_pascal_case,
    glossary_expand,
)
```

**3b.** Modify `score_tab` signature (around line 371) to add `domain_context: DomainContext | None = None`.

Inside `score_tab`, after `lowered_title = tab_title.lower()`, insert glossary expansion:

```python
    if domain_context is not None and domain_context.glossary:
        from profiler.tools.enrichment_utils import glossary_expand
        title_expansions = glossary_expand(lowered_title, domain_context.glossary)
        if title_expansions:
            lowered_title = lowered_title + " " + " ".join(title_expansions)
```

All downstream `_token_match` calls use `lowered_title` naturally — no per-category changes needed.

**3c.** Modify `select_tabs_from_inventory` signature to add `domain_context: DomainContext | None = None`.

After the docstring, before scoring, add vocabulary merging:

```python
    effective_heuristics = merge_vocabulary(tab_score_heuristics or {}, domain_context)
```

Replace `tab_score_heuristics=tab_score_heuristics` (line 1346 in the main call and line 1222 in resume_from_broad) with `tab_score_heuristics=effective_heuristics`.

Replace the coverage bonus (line 605):

```python
        if domain_context is not None:
            active_or_forward = (
                set(domain_context.year_scope.active) | set(domain_context.year_scope.forward)
            )
            bonus_years = len(bucket["years"] & active_or_forward)
            coverage_bonus = 1 if bonus_years >= 2 else 0
        else:
            coverage_bonus = 1 if len(bucket["years"]) >= 3 else 0
```

After building the `selected` list and before sorting, add dedup annotation:

```python
    if domain_context is not None:
        for entry in selected:
            years = entry.get("years", [])
            if len(years) > 1:
                active_or_forward = set(domain_context.year_scope.active) | set(domain_context.year_scope.forward)
                non_active = sorted(y for y in years if y not in active_or_forward)
                if non_active:
                    entry["duplicate_years"] = non_active
```

(This annotates only years outside active/forward, not all duplicates — cleaner signal for the human.)

- [ ] **Step 4: Add glossary_expand to enrichment_utils.py**

Add to `profiler/tools/enrichment_utils.py`:

```python
def glossary_expand(text: str, glossary: dict[str, str]) -> set[str]:
    """Return expanded forms of glossary keys found in *text*."""
    lowered = text.lower()
    expansions: set[str] = set()
    for abbr, full_form in glossary.items():
        if abbr.lower() in lowered:
            expansions.add(full_form.lower())
    return expansions
```

- [ ] **Step 5: Run tests**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_cohort_corpus_tools.py::test_score_tab_glossary_expansion profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_vocabulary_merging profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_coverage_bonus_active_years profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_duplicate_years_annotation profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_no_domain_context_unchanged -v`
Expected: All 5 new tests pass.

- [ ] **Step 6: Run full test file to confirm no regression**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_cohort_corpus_tools.py -v --tb=short 2>&1 | tail -20`
Expected: All tests pass (domain_context=None default preserves existing behavior).

- [ ] **Step 7: Commit**

```bash
git add profiler/tools/enrichment_utils.py profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "feat: domain context integration in score_tab and select_tabs_from_inventory"
```

---

### Task 3: Domain context integration in derive_column_candidates

**Files:**
- Modify: `profiler/tools/cohort_corpus.py` (derive_column_candidates)
- Modify: `profiler/tests/test_cohort_corpus_tools.py`

- [ ] **Step 1: Write failing test**

Append to `profiler/tests/test_cohort_corpus_tools.py`:

```python
def test_derive_column_candidates_glossary():
    ctx = DomainContext(glossary={"qty": "quantity", "amt": "amount"})
    payload = {
        "summary": {"formula_cell_count": 0, "functions_used": [], "column_formula_patterns": {}},
        "raw": {},
    }
    candidates = derive_column_candidates(
        workbook_code="402", year=2025, spreadsheet_id="s1", tab_title="Test",
        payload=payload,
        column_score_heuristics={"domain_keyword_tokens": ["quantity"]},
        domain_context=ctx,
    )
    qty_candidates = [c for c in candidates if c["column_header"] == "Qty"]
    assert len(qty_candidates) == 1
    assert "domain_keyword" in qty_candidates[0]["priority_reasons"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_cohort_corpus_tools.py::test_derive_column_candidates_glossary -v 2>&1 | tail -5`
Expected: FAIL — `derive_column_candidates` does not accept `domain_context`.

- [ ] **Step 3: Implement changes**

In `cohort_corpus.py`, modify `derive_column_candidates` signature to add `domain_context: DomainContext | None = None`. Also add `glossary_expand` to the imports.

Inside the function, after computing `lowered = header.lower()` (line 810) and before the domain keyword check (line 813), add:

```python
        if domain_context is not None and domain_context.glossary:
            header_expanded = glossary_expand(lowered, domain_context.glossary)
            if header_expanded:
                lowered = lowered + " " + " ".join(header_expanded)
```

The existing domain keyword matching `any(token in lowered for token in domain_keyword_tokens)` now sees the expanded terms.

- [ ] **Step 4: Add the import**

Ensure `glossary_expand` is imported at the top of `cohort_corpus.py`:

```python
from profiler.tools.enrichment_utils import (
    _ENTITY_KEYWORDS,
    _IDENTIFIER_NAMES,
    _IDENTIFIER_SUFFIXES,
    _to_pascal_case,
    glossary_expand,
)
```

- [ ] **Step 5: Pass domain_context at all call sites in run_cohort_corpus**

There are two calls to `derive_column_candidates` in the deep profiling loop (lines 1450 and 1489). In Task 4, when we add domain_context loading, we need to pass it through. For now, change both call sites to pass:

```python
                        derive_column_candidates(
                            ...
                            column_score_heuristics=column_score_heuristics,
                            domain_context=domain_context,
                        )
```

- [ ] **Step 6: Run tests**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_cohort_corpus_tools.py::test_derive_column_candidates_glossary -v`
Expected: PASS.

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_cohort_corpus_tools.py -v --tb=short 2>&1 | tail -20`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "feat: glossary synonym expansion in derive_column_candidates"
```

---

### Task 4: Domain context loading + index dedup in run_cohort_corpus

**Files:**
- Modify: `profiler/tools/cohort_corpus.py` (run_cohort_corpus function)
- Modify: `profiler/management/commands/profile_cohort_corpus.py`

**The critical fix:** After tab selection is finalized but before the deep profiling loop (line 1398), we call `deduplicate_index_records()` on the index. This ensures Phase 3 iterates only over the latest year's records for deduplicated tabs.

- [ ] **Step 1: Load domain_context and add selection_summary**

In `run_cohort_corpus()` (after line 1117 where heuristics are extracted), add:

```python
    domain_context_path = config.get("domain_context")
    domain_context: DomainContext | None = None
    if domain_context_path:
        domain_context = load_domain_context(domain_context_path)
        if domain_context is not None:
            logger.info("Domain context loaded: domain=%s", domain_context.domain)
```

Then pass `domain_context=domain_context` to all three `select_tabs_from_inventory` call sites (lines 1222, 1346) and both `derive_column_candidates` call sites (lines 1450, 1489).

After each `tab_shortlist` is built and written (fresh run path around line 1361, resume_from_broad path around line 1237), add selection_summary to the shortlist output:

```python
        selection_summary: dict = {
            "by_workbook_by_year": {},
            "candidate_count": len(tab_shortlist),
        }
        if domain_context is not None:
            by_wb_by_year: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for row in tab_shortlist:
                for yr in row.get("years", []):
                    by_wb_by_year[row["workbook_code"]][str(yr)] = (
                        by_wb_by_year[row["workbook_code"]].get(str(yr), 0) + 1
                    )
            selection_summary["by_workbook_by_year"] = {
                wb: dict(years) for wb, years in by_wb_by_year.items()
            }
            dup_total = sum(
                len(r.get("duplicate_years", [])) for r in tab_shortlist
            )
            if dup_total:
                selection_summary["deduplication_note"] = (
                    f"{dup_total} structural duplicates collapsed via latest_year strategy"
                )

        write_json(tab_shortlist_path, {
            **shortlist_base,
            "selection_summary": selection_summary,
        })
```

(The `shortlist_base` is the existing payload dict — merge with `selection_summary`.)

- [ ] **Step 2: Deduplicate index before Phase 3**

Right before the deep profiling loop (before line 1398), add:

```python
    index_records = deduplicate_index_records(index_records, approved_tabs, domain_context)
```

This single line ensures Phase 3 profiles only deduplicated records. Works in all three branches (fresh run, resume_from_broad, resume_from_tab_selection) because `index_records` and `approved_tabs` are available in all three.

- [ ] **Step 3: Strip _documentation from config**

In `profiler/management/commands/profile_cohort_corpus.py`, after line 90 where config is loaded:

```python
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config = {k: v for k, v in config.items() if not k.startswith("_")}
```

- [ ] **Step 4: Add coverage_summary artifact to Phase 1 main branch**

In `run_cohort_corpus`, in the main branch (after the broad coverage write at line 1344), add:

```python
        by_sheet_id = {rec["spreadsheet_id"]: rec for rec in index_records}
        coverage_summary_path = out_dir / f"broad_profile_coverage_summary_{date_stamp}.json"
        workbook_tab_names: dict[str, set[str]] = defaultdict(set)
        year_workbook_map: dict[str, set[str]] = defaultdict(set)
        for row in inventory_rows:
            meta = by_sheet_id.get(row["spreadsheet_id"])
            if meta is None:
                continue
            workbook_tab_names[meta["workbook_code"]].add(row["tab_title"])
            year_workbook_map[str(meta["year"])].add(meta["workbook_code"])
        write_json(
            coverage_summary_path,
            {
                "generated_from": discovery_path.name,
                "workbook_codes": {wb: sorted(tabs) for wb, tabs in sorted(workbook_tab_names.items())},
                "year_coverage": {yr: sorted(wbs) for yr, wbs in sorted(year_workbook_map.items())},
            },
        )
```

Add `"broad_coverage_summary": str(coverage_summary_path)` to the artifacts dict (line 1382).

- [ ] **Step 5: Run tests**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/ -v --tb=short 2>&1 | tail -30`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add profiler/tools/cohort_corpus.py profiler/management/commands/profile_cohort_corpus.py
git commit -m "feat: load domain context, deduplicate index before Phase 3, shortlist summary output"
```

---

### Task 5: Empty models_auto.py stub on scaffold

**Files:**
- Modify: `workbook/codegen/stub_writer.py`
- Modify: `workbook/tests/test_stub_writer.py`

- [ ] **Step 1: Write failing test**

Append to `workbook/tests/test_stub_writer.py`:

```python
def test_ensure_stub_creates_auto_module(tmp_path):
    auto_path = tmp_path / "models_auto.py"
    stub_path = tmp_path / "models.py"
    ensure_stub(stub_path, "models_auto")
    assert auto_path.exists()
    content = auto_path.read_text()
    assert "Auto-generated" in content or "Populated by" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest workbook/tests/test_stub_writer.py::test_ensure_stub_creates_auto_module -v`
Expected: FAIL — `ensure_stub` does not create the auto module file.

- [ ] **Step 3: Implement models_auto.py stub creation**

In `workbook/codegen/stub_writer.py`, add after `MARKER`:

```python
AUTO_STUB_CONTENT = "# Auto-generated by make new-product. Populated by make generate-models.\n"
```

At the end of `ensure_stub`, before `return path`, add:

```python
    auto_path = path.parent / f"{auto_module}.py"
    if not auto_path.exists():
        auto_path.write_text(AUTO_STUB_CONTENT, encoding="utf-8")

    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest workbook/tests/test_stub_writer.py -v`
Expected: All 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add workbook/codegen/stub_writer.py workbook/tests/test_stub_writer.py
git commit -m "fix: scaffold writes empty models_auto.py stub to prevent Django startup crash"
```

---

### Task 6: Config documentation, domain context example, scaffold update

**Files:**
- Modify: `example_data/cohort_corpus.example.json`
- Create: `example_data/domain_context.example.yaml`
- Modify: `scripts/new_product.py`

- [ ] **Step 1: Update cohort_corpus.example.json**

Replace content with version that adds `_documentation` key and `domain_context` path. Append to top of file before `folder_name`:

```json
{
  "_documentation": {
    "in_scope_workbooks": "Run 'make profile-drive-folder' first, then extract workbook codes from the drive tree output that match workbook_id_regex.",
    "operational_tokens": "Words from your domain that indicate primary data-entry tabs. Consider the operational loop in your raw notes.",
    "reference_tokens": "Words indicating lookup/reference tabs (variety lists, crop codes, etc.).",
    "reference_combo_tokens": "Lists of words that must all appear for a reference combo match.",
    "support_tokens": "Words indicating helper/index/validation tabs (penalized in scoring).",
    "derived_tokens": "Words indicating auto-generated/pivot/summary tabs (penalized in scoring).",
    "tab_auto_limit": "Maximum tabs auto-selected per workbook code. Use tab_selection_overrides to hand-pick important tabs.",
    "tab_exclude_patterns": "Regex patterns to block tabs. Each entry: {\"pattern\": \"regex\", \"penalty\": -5}.",
    "year_regex": "Used to group workbooks by year. Set year_scope in domain_context.yaml to limit profiling to active years.",
    "domain_context": "Path to a domain_context.yaml file providing vocabulary, year scoping, deduplication, and glossary."
  },
  "domain_context": "config/domain_context.yaml",
  "folder_name": "Corpus Root Folder",
```

Keep everything else from the existing file unchanged.

- [ ] **Step 2: Create domain_context.example.yaml**

Create `example_data/domain_context.example.yaml`:

```yaml
# Domain context — the profiler's model of the business domain.
# Populated from raw notes and drive tree inspection BEFORE Phase 1.
# Follow the Orient step in AGENTS.md to fill this in.

domain: ""                       # e.g., "farm_management"
description: ""                  # What does this business do?

year_scope:
  active: []                     # Years to profile in full  e.g., [2025, 2026]
  archived: []                   # Years to skip/deprioritize  e.g., [2023, 2024]
  forward: []                    # Future years for forward-looking tabs  e.g., [2026]

deduplication:
  strategy: latest_year          # "latest_year" profiles only the latest year per (workbook_code, tab_title)
  exceptions: []                  # Tab titles to always profile per-year (e.g., Sales Actuals changes yearly)

entities: []                      # Sparse pre-profiling; populated after Phase 1

vocabulary:
  operational: []                # Words for primary data-entry tabs (e.g., planting, harvest, order)
  reference: []                  # Words for lookup tabs (e.g., variety, crop, price)
  support: []                    # Words for helper tabs (e.g., index, validation)
  derived: []                    # Words for summary/pivot tabs (e.g., totals, rollup)

glossary: {}                     # Synonym expansion  e.g., {"qty": "quantity", "amt": "amount"}

scope_notes: ""                  # Freeform notes from orientation
```

- [ ] **Step 3: Update new_product.py scaffold**

In `scaffold_config_templates` function (line 1241), after the `copy_file` for `cohort_corpus.example.json`:

```python
    copy_file(
        script_dir.parent / "example_data" / "domain_context.example.yaml",
        output_dir / "config" / "domain_context.yaml",
        force=force,
    )
```

- [ ] **Step 4: Add Phase 0 Orient section to AGENTS.md in scaffold**

In `render_agents_md` (around line 599), find the text `#### Phase 1 — Discovery + tab selection` and insert a Phase 0 section before it:

```python
        + "#### Phase 0 — Orient\n\n"
        + "Before running Phase 1, populate `config/domain_context.yaml`:\n\n"
        + "1. **Read raw notes** in `data/raw_notes/` — extract entity names, relationships, and temporal scope.\n"
        + "2. **Inspect drive tree** from `make profile-drive-folder` — identify workbook codes and year distribution.\n"
        + "3. **Set year_scope** — mark active years (profile in full), archived years (skip), and forward years.\n"
        + "4. **Populate vocabulary** — list domain words for operational, reference, support, and derived tabs.\n"
        + "5. **Add glossary** entries for abbreviations (e.g., `qty: quantity`).\n"
        + "6. **Review deduplication** — by default, tabs appearing across multiple years are profiled only for the latest year.\n"
        + "   Add exceptions for tabs that change meaning across years (e.g., Sales Actuals).\n\n"
```

- [ ] **Step 5: Add timeout note to profile-drive-folder**

In `workbook/makefile_targets.py`, `profile_blocks` function, change the `profile-drive-folder` block to include a runtime comment:

```python
        + "# Expected runtime: 2-3 minutes for folders with 20+ spreadsheets.\n"
        + "profile-drive-folder:\n"
        + _indent(
            "DB_ENGINE=sqlite $(MANAGE) profile_drive_folder "
            '--folder "$${DRIVE_FOLDER_ID:?DRIVE_FOLDER_ID required}" '
            '--config "$${COHORT_CORPUS_CONFIG}" '
            '--out "$${DRIVE_FOLDER_OUT:-data/profile_snapshots/drive_tree.json}"'
        )
```

- [ ] **Step 6: Run tests**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/ workbook/tests/ scripts/tests/ -v --tb=short 2>&1 | tail -30`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add example_data/cohort_corpus.example.json example_data/domain_context.example.yaml scripts/new_product.py workbook/makefile_targets.py
git commit -m "feat: config docs, domain context example, Phase 0 orientation, drive folder timeout note"
```

---

### Task 7: Integration verification and lint

**Files:** No changes — verification only.

- [ ] **Step 1: Lint all changed files**

Run: `cd /home/user/migration-workbench && python -m ruff check profiler/tools/domain_context.py profiler/tools/cohort_corpus.py profiler/tools/enrichment_utils.py profiler/management/commands/profile_cohort_corpus.py workbook/codegen/stub_writer.py scripts/new_product.py`
Expected: Clean. Fix any issues.

- [ ] **Step 2: Full test suite**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/ workbook/tests/ -v --tb=short 2>&1 | tail -40`
Expected: All tests pass.

- [ ] **Step 3: Final commit if needed**

```bash
git add -A && git commit -m "chore: lint and test fixes for domain context implementation" || echo "Clean"
```