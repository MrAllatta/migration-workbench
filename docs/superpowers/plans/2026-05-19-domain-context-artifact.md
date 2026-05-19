# Domain Context Artifact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a `domain_context.yaml` artifact that the profiler reads at scoring time, enabling year-aware deduplication, vocabulary-to-token mapping, and glossary synonym expansion. Fix four pipeline friction points along the way.

**Architecture:** A new `DomainContext` dataclass in `profiler/tools/domain_context.py` loads from a YAML file referenced by `cohort_corpus.json`. It flows into `select_tabs_from_inventory()`, `score_tab()`, and `derive_column_candidates()` via optional parameters (backward-compatible). Year scoping filters inventory rows before scoring. Deduplication collapses structural duplicates across years. Vocabulary merges into heuristic tokens. Glossary expands column matching.

**Tech Stack:** Python 3.11+, Django, pytest, PyYAML (already a dependency)

---

### Task 1: DomainContext dataclass and loader

**Files:**
- Create: `profiler/tools/domain_context.py`
- Create: `profiler/tests/test_domain_context.py`

- [ ] **Step 1: Write failing tests for DomainContext**

Create `profiler/tests/test_domain_context.py`:

```python
"""Tests for domain context loading and vocabulary merging."""

import pytest
from pathlib import Path

from profiler.tools.domain_context import DomainContext, load_domain_context, merge_vocabulary


def test_load_domain_context_from_yaml(tmp_path):
    ctx_file = tmp_path / "domain_context.yaml"
    ctx_file.write_text(
        "domain: farm_management\n"
        "description: Farm ops tracking\n"
        "year_scope:\n"
        "  active: [2025, 2026]\n"
        "  archived: [2023, 2024]\n"
        "  forward: []\n"
        "deduplication:\n"
        "  strategy: latest_year\n"
        "  exceptions: []\n"
        "entities:\n"
        "  - name: Season\n"
        "    tabs: [Crop Planner]\n"
        "    operational: true\n"
        "    description: Top-level season org\n"
        "vocabulary:\n"
        "  operational: [planting, harvest]\n"
        "  reference: [variety, crop]\n"
        "  support: [index]\n"
        "  derived: [summary, pivot]\n"
        "glossary:\n"
        "  qty: quantity\n"
        "  amt: amount\n"
        "scope_notes: Active year is 2025\n"
    )
    ctx = load_domain_context(ctx_file)
    assert ctx is not None
    assert ctx.domain == "farm_management"
    assert ctx.year_scope.active == [2025, 2026]
    assert ctx.year_scope.archived == [2023, 2024]
    assert ctx.deduplication.strategy == "latest_year"
    assert len(ctx.entities) == 1
    assert ctx.entities[0]["name"] == "Season"
    assert ctx.vocabulary.operational == ["planting", "harvest"]


def test_load_domain_context_missing_file(tmp_path):
    ctx = load_domain_context(tmp_path / "nonexistent.yaml")
    assert ctx is None


def test_load_domain_context_empty_values(tmp_path):
    ctx_file = tmp_path / "domain_context.yaml"
    ctx_file.write_text("domain: ''\n")
    ctx = load_domain_context(ctx_file)
    assert ctx is not None
    assert ctx.domain == ""
    assert ctx.year_scope.active == []
    assert ctx.year_scope.archived == []
    assert ctx.year_scope.forward == []
    assert ctx.deduplication.strategy == "latest_year"
    assert ctx.deduplication.exceptions == []
    assert ctx.vocabulary.operational == []


def test_load_domain_context_strips_documentation_keys(tmp_path):
    ctx_file = tmp_path / "domain_context.yaml"
    ctx_file.write_text(
        "_doc:\n"
        "  note: This key should be ignored\n"
        "domain: test\n"
        "_another_private_key: also ignored\n"
    )
    ctx = load_domain_context(ctx_file)
    assert ctx is not None
    assert ctx.domain == "test"


def test_merge_vocabulary_combines_tokens():
    ctx = DomainContext(
        vocabulary=DomainContext.VocabularyContext(
            operational=["planting", "harvest"],
            reference=["variety"],
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
    assert "variety" in merged["reference_tokens"]
    assert "reference" in merged["reference_tokens"]
    assert "index" in merged["support_tokens"]
    assert "summary" in merged["derived_tokens"]


def test_merge_vocabulary_no_duplicates():
    ctx = DomainContext(
        vocabulary=DomainContext.VocabularyContext(
            operational=["planting"],
        )
    )
    heuristics = {
        "operational_tokens": ["planting"],
        "reference_tokens": [],
        "support_tokens": [],
        "derived_tokens": [],
    }
    merged = merge_vocabulary(heuristics, ctx)
    assert merged["operational_tokens"].count("planting") == 1


def test_merge_vocabulary_preserves_config_when_no_context():
    heuristics = {
        "operational_tokens": ["nursery"],
        "reference_tokens": ["reference"],
        "support_tokens": ["index"],
        "derived_tokens": ["summary"],
    }
    merged = merge_vocabulary(heuristics, None)
    assert merged == heuristics


def test_domain_context_active_years():
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(active=[2025, 2026], archived=[2023], forward=[])
    )
    assert ctx.active_years() == {2025, 2026, 2023}


def test_domain_context_is_archived_year():
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(active=[2025], archived=[2023, 2024], forward=[])
    )
    assert ctx.is_archived_year(2023) is True
    assert ctx.is_archived_year(2025) is False
    assert ctx.is_archived_year(2027) is False


def test_domain_context_deduplication_exceptions():
    ctx = DomainContext(
        deduplication=DomainContext.DeduplicationContext(
            strategy="latest_year",
            exceptions=[{"tab_title": "Sales Actuals", "reason": "Changes yearly"}]
        )
    )
    assert ctx.is_deduplication_exception("Sales Actuals") is True
    assert ctx.is_deduplication_exception("Crop Planner") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_domain_context.py -v 2>&1 | head -20`
Expected: Import error — `profiler.tools.domain_context` module not found.

- [ ] **Step 3: Implement DomainContext, load_domain_context, merge_vocabulary**

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
        """Return all years that should be included in profiling (active + archived + forward)."""
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
    """Load a domain context YAML file. Return None if the file does not exist."""
    file_path = Path(path)
    if not file_path.exists():
        return None
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    # Strip documentation keys (prefixed with _)
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
    """Merge domain context vocabulary into heuristic token lists.

    Tokens from ``domain_context.vocabulary`` are appended to the corresponding
    heuristic token lists without duplication. When ``domain_context`` is None,
    returns ``heuristics`` unchanged.
    """
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_domain_context.py -v`
Expected: All 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add profiler/tools/domain_context.py profiler/tests/test_domain_context.py
git commit -m "feat: add DomainContext dataclass, loader, and vocabulary merger"
```

---

### Task 2: Year-aware deduplication and coverage bonus in select_tabs_from_inventory

**Files:**
- Modify: `profiler/tools/cohort_corpus.py` (select_tabs_from_inventory)
- Modify: `profiler/tests/test_cohort_corpus_tools.py`

- [ ] **Step 1: Write failing tests for year-aware deduplication**

Append to `profiler/tests/test_cohort_corpus_tools.py`:

```python
def test_select_tabs_deduplicates_by_latest_year():
    """When domain_context deduplication is latest_year, only the latest year's tab is kept."""
    index_records = [
        {"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 Farm 2023"},
        {"year": 2024, "workbook_code": "402", "spreadsheet_id": "s2", "spreadsheet_name": "402 Farm 2024"},
        {"year": 2025, "workbook_code": "402", "spreadsheet_id": "s3", "spreadsheet_name": "402 Farm 2025"},
        {"year": 2026, "workbook_code": "402", "spreadsheet_id": "s4", "spreadsheet_name": "402 Farm 2026"},
    ]
    inventory_rows = [
        {"spreadsheet_id": "s1", "sheet_id": 1, "rows": 500, "cols": 20, "tab_title": "Crop Planner"},
        {"spreadsheet_id": "s2", "sheet_id": 1, "rows": 600, "cols": 22, "tab_title": "Crop Planner"},
        {"spreadsheet_id": "s3", "sheet_id": 1, "rows": 700, "cols": 25, "tab_title": "Crop Planner"},
        {"spreadsheet_id": "s4", "sheet_id": 1, "rows": 750, "cols": 26, "tab_title": "Crop Planner"},
    ]
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(active=[2025, 2026], archived=[2023, 2024], forward=[]),
        deduplication=DomainContext.DeduplicationContext(strategy="latest_year", exceptions=[]),
    )
    selected = select_tabs_from_inventory(
        index_records,
        inventory_rows,
        tab_score_heuristics={"operational_tokens": ["crop"]},
        domain_context=ctx,
    )
    crop_planner_entries = [row for row in selected if row["tab_title"] == "Crop Planner"]
    assert len(crop_planner_entries) == 1
    entry = crop_planner_entries[0]
    assert entry["years"] == [2023, 2024, 2025, 2026]
    assert "duplicate_years" in entry
    assert set(entry["duplicate_years"]) == {2023, 2024, 2025}


def test_select_tabs_deduplication_exception_keeps_all_years():
    """When a tab is in deduplication.exceptions, all years are retained."""
    index_records = [
        {"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 Farm 2023"},
        {"year": 2025, "workbook_code": "402", "spreadsheet_id": "s3", "spreadsheet_name": "402 Farm 2025"},
    ]
    inventory_rows = [
        {"spreadsheet_id": "s1", "sheet_id": 1, "rows": 500, "cols": 20, "tab_title": "Sales Actuals"},
        {"spreadsheet_id": "s3", "sheet_id": 1, "rows": 700, "cols": 25, "tab_title": "Sales Actuals"},
    ]
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(active=[2025], archived=[2023], forward=[]),
        deduplication=DomainContext.DeduplicationContext(
            strategy="latest_year",
            exceptions=[{"tab_title": "Sales Actuals", "reason": "Changes yearly"}],
        ),
    )
    selected = select_tabs_from_inventory(
        index_records,
        inventory_rows,
        tab_score_heuristics={"operational_tokens": ["sales"]},
        domain_context=ctx,
    )
    sales_entries = [row for row in selected if row["tab_title"] == "Sales Actuals"]
    assert len(sales_entries) == 2


def test_select_tabs_coverage_bonus_from_active_years():
    """Coverage bonus is +1 when tab appears in >=2 active or forward years, not from archived years alone."""
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(active=[2025, 2026], archived=[2023, 2024], forward=[]),
        deduplication=DomainContext.DeduplicationContext(strategy="latest_year", exceptions=[]),
    )
    index_records = [
        {"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 2023"},
        {"year": 2024, "workbook_code": "402", "spreadsheet_id": "s2", "spreadsheet_name": "402 2024"},
        {"year": 2025, "workbook_code": "402", "spreadsheet_id": "s3", "spreadsheet_name": "402 2025"},
        {"year": 2026, "workbook_code": "402", "spreadsheet_id": "s4", "spreadsheet_name": "402 2026"},
    ]
    inventory_rows = [
        {"spreadsheet_id": "s1", "sheet_id": 1, "rows": 500, "cols": 20, "tab_title": "Crop Planner"},
        {"spreadsheet_id": "s2", "sheet_id": 1, "rows": 600, "cols": 22, "tab_title": "Crop Planner"},
        {"spreadsheet_id": "s3", "sheet_id": 1, "rows": 700, "cols": 25, "tab_title": "Crop Planner"},
        {"spreadsheet_id": "s4", "sheet_id": 1, "rows": 750, "cols": 26, "tab_title": "Crop Planner"},
    ]
    selected = select_tabs_from_inventory(
        index_records,
        inventory_rows,
        tab_score_heuristics={"operational_tokens": ["crop"]},
        domain_context=ctx,
    )
    entry = next(row for row in selected if row["tab_title"] == "Crop Planner")
    assert entry["coverage_bonus"] == 1


def test_select_tabs_no_dedup_without_domain_context():
    """Without domain_context, legacy behavior is preserved (all years, old coverage bonus)."""
    index_records = [
        {"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 2023"},
        {"year": 2024, "workbook_code": "402", "spreadsheet_id": "s2", "spreadsheet_name": "402 2024"},
        {"year": 2025, "workbook_code": "402", "spreadsheet_id": "s3", "spreadsheet_name": "402 2025"},
    ]
    inventory_rows = [
        {"spreadsheet_id": "s1", "sheet_id": 1, "rows": 500, "cols": 20, "tab_title": "Crop Planner"},
        {"spreadsheet_id": "s2", "sheet_id": 1, "rows": 600, "cols": 22, "tab_title": "Crop Planner"},
        {"spreadsheet_id": "s3", "sheet_id": 1, "rows": 700, "cols": 25, "tab_title": "Crop Planner"},
    ]
    selected = select_tabs_from_inventory(
        index_records,
        inventory_rows,
        tab_score_heuristics={"operational_tokens": ["crop"]},
    )
    crop_entries = [row for row in selected if row["tab_title"] == "Crop Planner"]
    assert len(crop_entries) == 1
    assert crop_entries[0]["occurrences"] == 3
    assert crop_entries[0]["coverage_bonus"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_deduplicates_by_latest_year profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_deduplication_exception_keeps_all_years profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_coverage_bonus_from_active_years profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_no_dedup_without_domain_context -v 2>&1 | tail -10`
Expected: FAIL — `select_tabs_from_inventory` does not yet accept `domain_context` parameter, and `DomainContext` import is not yet added to the test file.

- [ ] **Step 3: Modify select_tabs_from_inventory to accept and apply domain context**

In `profiler/tools/cohort_corpus.py`:

1. Add the import at the top of the file (after the existing `from profiler.tools.enrichment_utils import` block, around line 64):

```python
from profiler.tools.domain_context import DomainContext, merge_vocabulary
```

2. Modify `select_tabs_from_inventory` signature (line 538) to add `domain_context: DomainContext | None = None`:

Change the function signature from:
```python
def select_tabs_from_inventory(
    index_records: list[dict],
    inventory_rows: list[dict],
    *,
    min_final_score: float = 2.0,
    tab_score_heuristics: dict | None = None,
) -> list[dict]:
```
to:
```python
def select_tabs_from_inventory(
    index_records: list[dict],
    inventory_rows: list[dict],
    *,
    min_final_score: float = 2.0,
    tab_score_heuristics: dict | None = None,
    domain_context: DomainContext | None = None,
) -> list[dict]:
```

3. At the start of `select_tabs_from_inventory`, after the docstring, add year-aware filtering:

```python
    if domain_context is not None:
        active_years = domain_context.active_years()
        if active_years:
            index_records = [
                rec for rec in index_records if rec["year"] in active_years
            ]
            active_sheet_ids = {rec["spreadsheet_id"] for rec in index_records}
            inventory_rows = [
                row for row in inventory_rows
                if row["spreadsheet_id"] in active_sheet_ids
            ]
```

4. Merge vocabulary into heuristics before scoring. After the year filtering above, add:

```python
    effective_heuristics = merge_vocabulary(tab_score_heuristics or {}, domain_context)
```

Then change the call to `score_tab` inside the loop (around line 552) from:
```python
        score, reasons, breakdown = score_tab(
            row["tab_title"],
            row["rows"],
            row["cols"],
            tab_score_heuristics=tab_score_heuristics,
        )
```
to:
```python
        score, reasons, breakdown = score_tab(
            row["tab_title"],
            row["rows"],
            row["cols"],
            tab_score_heuristics=effective_heuristics,
        )
```

5. Replace the coverage bonus calculation in the aggregate loop (around line 605). Change:

```python
        coverage_bonus = 1 if len(bucket["years"]) >= 3 else 0
```

to:

```python
        if domain_context is not None:
            active_or_forward_years = (
                set(domain_context.year_scope.active) | set(domain_context.year_scope.forward)
            )
            years_in_active_or_forward = len(bucket["years"] & active_or_forward_years)
            coverage_bonus = 1 if years_in_active_or_forward >= 2 else 0
        else:
            coverage_bonus = 1 if len(bucket["years"]) >= 3 else 0
```

6. Add deduplication after aggregation, before sorting. After the `breakdown_summary` dict is built (around line 628) and before `selected.append(...)`, add the deduplication logic:

After the line `selected.sort(key=lambda row: ...)` (line 646), and before `return selected`, add deduplication:

Actually, the deduplication should happen *after* aggregation but *before* the `min_final_score` filter and the `selected.append`. The simplest approach: add the dedup *after* the full `selected` list is built and before the sort. Change the flow to build selected, then apply dedup, then sort.

The cleanest place is after the `selected` list is fully built. After the loop that builds `selected` (line 644), before the sort (line 646), add:

```python
    if domain_context is not None and domain_context.deduplication.strategy == "latest_year":
        deduped: list[dict] = []
        seen: dict[tuple[str, str], dict] = {}
        for entry in selected:
            key = (entry["workbook_code"], entry["tab_title"])
            if key not in seen:
                seen[key] = entry
            else:
                existing = seen[key]
                existing_years = existing.get("years", [])
                entry_years = entry.get("years", [])
                max_year = max(existing_years + entry_years) if existing_years + entry_years else 0
                combined_years = sorted(set(existing_years + entry_years))
                existing["years"] = combined_years
                existing["occurrences"] = existing.get("occurrences", 1) + entry.get("occurrences", 1)
        for key, entry in seen.items():
            if not domain_context.is_deduplication_exception(key[1]):
                years = entry.get("years", [])
                if len(years) > 1:
                    latest_year = max(years)
                    entry["duplicate_years"] = [y for y in years if y != latest_year]
                    entry["years"] = [latest_year]
                    entry["occurrences"] = 1
                    deduped.append(entry)
                else:
                    deduped.append(entry)
            else:
                deduped.append(entry)
        selected = deduped
```

Wait, this approach is wrong because aggregation has already combined the years into a single `years` list per `(workbook_code, tab_title)` group. Deduplication should happen at that point — we need to decide which year's instance to keep in the shortlist.

Let me reconsider. The current `select_tabs_from_inventory` aggregates by `(workbook_code, tab_title)` into a single entry that has `years: [2023, 2024, 2025, 2026]` and `occurrences: 4`. For deduplication with `latest_year` strategy, we want to:
- Keep entry's `years` as `[2023, 2024, 2025, 2026]` for informational purposes (showing all available years)
- Set `occurrences` to 1 (only profiling one year)
- Add `duplicate_years: [2023, 2024, 2025]` (the years not being profiled)
- Adjust the `examples` list to only include the latest year

After the aggregation loop and before sorting, add deduplication. Inside the loop that builds `selected` entries (around line 630), add the dedup fields:

After the `breakdown_summary` dict and before `selected.append(...)`:

```python
        # Deduplication fields (set later if domain_context is present)
        entry_duplicate_years: list[int] | None = None
        entry_occurrences_override: int | None = None
```

Then after the loop completes and before the sort, apply deduplication in a separate pass. Actually, the simplest correct approach is to handle this entirely after the aggregation loop. The `selected` list has one entry per `(workbook_code, tab_title)`. We modify entries in-place:

After `selected.sort(...)` (line 646), but before `return selected` (line 649), add:

```python
    if domain_context is not None and domain_context.deduplication.strategy == "latest_year":
        for entry in selected:
            if domain_context.is_deduplication_exception(entry["tab_title"]):
                continue
            years = entry.get("years", [])
            if len(years) > 1:
                latest_year = max(years)
                entry["duplicate_years"] = sorted(y for y in years if y != latest_year)
                entry["years"] = [latest_year]
                entry["occurrences"] = 1

    return selected
```

- [ ] **Step 4: Add DomainContext import to test file**

At the top of `profiler/tests/test_cohort_corpus_tools.py`, add to the imports:

```python
from profiler.tools.domain_context import DomainContext
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_deduplicates_by_latest_year profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_deduplication_exception_keeps_all_years profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_coverage_bonus_from_active_years profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_no_dedup_without_domain_context -v`
Expected: All 4 new tests pass.

- [ ] **Step 6: Run existing tests to confirm no regression**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_cohort_corpus_tools.py -v`
Expected: All existing tests pass (the `domain_context=None` default preserves existing behavior).

- [ ] **Step 7: Commit**

```bash
git add profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "feat: year-aware dedup, coverage bonus, and vocab merging in select_tabs_from_inventory"
```

---

### Task 3: Glossary synonym expansion in token matching and column scoring

**Files:**
- Modify: `profiler/tools/enrichment_utils.py`
- Modify: `profiler/tools/cohort_corpus.py` (score_tab, _token_match, derive_column_candidates)
- Modify: `profiler/tests/test_cohort_corpus_tools.py`

- [ ] **Step 1: Write failing test for glossary matching in score_tab**

Append to `profiler/tests/test_cohort_corpus_tools.py`:

```python
def test_score_tab_matches_glossary_synonyms():
    """Glossary entries expand token matching so 'qty' matches 'Quantity Tracker'."""
    from profiler.tools.domain_context import DomainContext
    ctx = DomainContext(
        glossary={"qty": "quantity", "amt": "amount"},
    )
    score, reasons, breakdown = score_tab(
        "Qty Tracker",
        100,
        20,
        tab_score_heuristics={"operational_tokens": ["quantity"]},
        domain_context=ctx,
    )
    assert score > 0
    assert any("operational" in r for r in reasons)


def test_derive_column_candidates_matches_glossary():
    """Column headers matching glossary synonyms get domain_keyword score."""
    from profiler.tools.domain_context import DomainContext
    ctx = DomainContext(
        glossary={"qty": "quantity", "amt": "amount"},
    )
    payload = {
        "summary": {"formula_cell_count": 0, "functions_used": [], "column_formula_patterns": {}},
        "raw": {},
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
    assert qty_candidates[0]["priority_score"] == 3
    assert "domain_keyword" in qty_candidates[0]["priority_reasons"]
```

Also add `domain_context` parameter to `score_tab` calls and `derive_column_candidates` in the test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_cohort_corpus_tools.py::test_score_tab_matches_glossary_synonyms profiler/tests/test_cohort_corpus_tools.py::test_derive_column_candidates_matches_glossary -v 2>&1 | tail -10`
Expected: FAIL — `score_tab` and `derive_column_candidates` do not yet accept `domain_context`.

- [ ] **Step 3: Implement glossary expansion in enrichment_utils.py**

Add to `profiler/tools/enrichment_utils.py`:

```python
def glossary_expand(text: str, glossary: dict[str, str]) -> set[str]:
    """Return all forms of glossary keys found in text, plus their expanded values.

    If *text* contains a glossary key (case-insensitive substring match), the
    expansion includes both the key and its mapped value. This allows "Qty"
    to match the domain keyword "quantity" when glossary maps "qty" → "quantity".
    """
    lowered = text.lower()
    expansions: set[str] = set()
    for abbr, full_form in glossary.items():
        if abbr.lower() in lowered:
            expansions.add(abbr.lower())
            expansions.add(full_form.lower())
    return expansions
```

- [ ] **Step 4: Modify score_tab to accept domain_context and use glossary**

In `profiler/tools/cohort_corpus.py`, modify `score_tab` signature (around line 371) to add `domain_context: DomainContext | None = None`.

Inside `score_tab`, after the token matching section, add glossary expansion. Find the `_token_match` call section. The current code iterates over token categories and calls `_token_match(token, lowered_title, match_mode)`. Add a glossary expansion step:

After `lowered_title = tab_title.lower()` (which already exists), add:

```python
    glossary = domain_context.glossary if domain_context is not None else {}
    title_expansions = glossary_expand(lowered_title, glossary) if glossary else set()
```

Then in the token matching loop, when checking each token, also check if the token matches any expansion:

In each token category loop (operational, reference, etc.), modify the matching condition. Currently:
```python
if _token_match(token, lowered_title, match_mode):
```

Change to:
```python
if _token_match(token, lowered_title, match_mode) or token.lower() in title_expansions:
```

This requires modifying each of the 5 token category sections in `score_tab`. To avoid repetition, create a helper:

Actually, the simplest approach is to expand `lowered_title` to include glossary expansions. After computing `title_expansions`, also check if any token matches the expanded forms:

In each token category section, instead of just checking `_token_match(token, lowered_title, match_mode)`, also check `any(_token_match(token, exp, match_mode) for exp in title_expansions)`. But since `title_expansions` contains the expanded forms, we can just check if the token is in `title_expansions`:

Wait, the `title_expansions` set contains the expanded full forms (e.g., "quantity" when "qty" is in the title). The domain tokens should match these expanded forms. So in each category section, change the condition from:

```python
if _token_match(token, lowered_title, match_mode):
```

to:

```python
if _token_match(token, lowered_title, match_mode) or (title_expansions and _token_match(token, " ".join(title_expansions), match_mode)):
```

Actually, simpler: just add the expanded terms to the title for matching purposes:

```python
effective_title = lowered_title
if title_expansions:
    effective_title = lowered_title + " " + " ".join(title_expansions)
```

Then use `effective_title` instead of `lowered_title` in all `_token_match` calls within `score_tab`. This is the cleanest approach and requires minimal code change.

- [ ] **Step 5: Modify derive_column_candidates to accept domain_context and use glossary**

In `profiler/tools/cohort_corpus.py`, modify `derive_column_candidates` signature (line 774) to add `domain_context: DomainContext | None = None`.

Inside `derive_column_candidates`, add glossary expansion for column headers. After extracting headers and computing `lowered = header.lower()`, add:

```python
    glossary = domain_context.glossary if domain_context is not None else {}
```

In the domain keyword matching section (around line 813):

```python
        if domain_keyword_tokens and any(
            token in lowered for token in domain_keyword_tokens
        ):
```

Change to:

```python
        header_expansions = glossary_expand(lowered, glossary) if glossary else set()
        expanded_lowered = lowered
        if header_expansions:
            expanded_lowered = lowered + " " + " ".join(header_expansions)
        if domain_keyword_tokens and any(
            token in expanded_lowered for token in domain_keyword_tokens
        ):
```

- [ ] **Step 6: Add imports for glossary_expand**

In `profiler/tools/cohort_corpus.py`, update the import from enrichment_utils:

```python
from profiler.tools.enrichment_utils import (
    _ENTITY_KEYWORDS,
    _IDENTIFIER_NAMES,
    _IDENTIFIER_SUFFIXES,
    _to_pascal_case,
    glossary_expand,
)
```

- [ ] **Step 7: Run all tests**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/test_cohort_corpus_tools.py -v`
Expected: All tests pass, including new glossary tests.

- [ ] **Step 8: Commit**

```bash
git add profiler/tools/enrichment_utils.py profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "feat: glossary synonym expansion in score_tab and derive_column_candidates"
```

---

### Task 4: Domain context loading in run_cohort_corpus and summary output

**Files:**
- Modify: `profiler/tools/cohort_corpus.py` (run_cohort_corpus function)
- Modify: `profiler/management/commands/profile_cohort_corpus.py`

- [ ] **Step 1: Load domain_context in run_cohort_corpus**

In `profiler/tools/cohort_corpus.py`, inside `run_cohort_corpus()` (after line 1117 where heuristics are extracted), add domain context loading:

```python
    domain_context_path = config.get("domain_context")
    domain_context = None
    if domain_context_path:
        domain_context = load_domain_context(domain_context_path)
        if domain_context is not None:
            logger.info("Loaded domain context from %s: domain=%s", domain_context_path, domain_context.domain)
```

Then pass `domain_context=domain_context` to all calls of `select_tabs_from_inventory()` in the function (there are two call sites: the `resume_from_broad` branch at line 1222, and the main branch at line 1346).

- [ ] **Step 2: Add selection_summary to tab shortlist output**

In `run_cohort_corpus`, after the `tab_shortlist` is computed and before writing `tab_shortlist_path` (around line 1351), build the summary dict:

```python
        # Build selection summary for quick inspection of year distribution
        selection_summary: dict = {
            "by_workbook_by_year": {},
            "original_count": len(tab_shortlist),
            "deduplicated_count": len(tab_shortlist),
        }
        if domain_context is not None:
            by_wb_by_year: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
            active_or_forward = set(domain_context.year_scope.active) | set(domain_context.year_scope.forward)
            for row in tab_shortlist:
                for yr in row.get("years", []):
                    if yr in active_or_forward or not active_or_forward:
                        by_wb_by_year[row["workbook_code"]][str(yr)] += 1
            selection_summary["by_workbook_by_year"] = {
                wb: dict(years) for wb, years in by_wb_by_year.items()
            }
            dedup_count = sum(1 for r in tab_shortlist if len(r.get("years", [])) <= 1)
            dup_reduced = sum(
                len(r.get("duplicate_years", []))
                for r in tab_shortlist
                if r.get("duplicate_years")
            )
            selection_summary["deduplicated_count"] = len(tab_shortlist) - dup_reduced
            if domain_context.deduplication.strategy == "latest_year":
                selection_summary["deduplication_note"] = (
                    f"latest_year strategy applied; {dup_reduced} structural duplicates collapsed"
                )
```

Then modify the `write_json` call for `tab_shortlist_path` to include the summary:

```python
        shortlist_output = {
            "generated_from": broad_path.name,
            "candidate_count": len(
                {(row["workbook_code"], row["tab_title"]) for row in tab_shortlist}
            ),
            "selected_count": len(tab_shortlist),
            "selection_summary": selection_summary,
            "selected": tab_shortlist,
        }
        write_json(tab_shortlist_path, shortlist_output)
```

- [ ] **Step 3: Verify no regressions**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/ -v --tb=short 2>&1 | tail -30`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add profiler/tools/cohort_corpus.py
git commit -m "feat: load domain context in run_cohort_corpus and add selection_summary to shortlist"
```

---

### Task 5: Empty models_auto.py stub on scaffold

**Files:**
- Modify: `workbook/codegen/stub_writer.py`
- Modify: `workbook/tests/test_stub_writer.py`

- [ ] **Step 1: Write failing test for models_auto.py stub creation**

Append to `workbook/tests/test_stub_writer.py`:

```python
def test_ensure_stub_creates_models_auto_when_missing(tmp_path):
    """ensure_stub should write an empty models_auto.py stub if it doesn't exist."""
    auto_path = tmp_path / "models_auto.py"
    stub_path = tmp_path / "models.py"
    ensure_stub(stub_path, "models_auto")
    assert auto_path.exists()
    content = auto_path.read_text()
    assert "Auto-generated" in content or "make generate-models" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest workbook/tests/test_stub_writer.py::test_ensure_stub_creates_models_auto_when_missing -v`
Expected: FAIL — `ensure_stub` does not create the auto module file.

- [ ] **Step 3: Implement models_auto.py stub creation**

In `workbook/codegen/stub_writer.py`, add a constant and modify `ensure_stub`:

Add after the `MARKER` constant (line 8):

```python
AUTO_STUB_CONTENT = "# Auto-generated by make new-product. Populated by make generate-models.\n"
```

Modify `ensure_stub` to also create the auto module file if it doesn't exist. At the end of the function, before `return path`, add:

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
git commit -m "fix: scaffold creates empty models_auto.py stub to prevent Django startup crash"
```

---

### Task 6: Config documentation key and broad coverage summary

**Files:**
- Modify: `example_data/cohort_corpus.example.json`
- Create: `example_data/domain_context.example.yaml`
- Modify: `profiler/tools/cohort_corpus.py` (add coverage summary artifact)
- Modify: `scripts/new_product.py` (add _documentation and domain_context path to scaffold)

- [ ] **Step 1: Update cohort_corpus.example.json with _documentation key and domain_context path**

Replace `example_data/cohort_corpus.example.json` content with:

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
    "tab_exclude_patterns": "Regex patterns to block tabs from selection. Each entry: {\"pattern\": \"regex\", \"penalty\": -5}.",
    "year_regex": "Used to group workbooks by year. Set year_scope in domain_context.yaml to limit profiling to active years.",
    "domain_context": "Path to a domain_context.yaml file providing vocabulary, year scoping, deduplication, and glossary."
  },
  "domain_context": "config/domain_context.yaml",
  "folder_name": "Corpus Root Folder",
  "workbook_id_regex": "\\b(\\d{3})\\b",
  "year_regex": "\\b(20\\d{2})\\b",
  "in_scope_workbooks": ["REPLACE_WITH_CODES_MATCHED_BY_REGEX"],
  "tab_auto_limit": 3,
  "column_min_score": 4,
  "tab_selection_overrides": {},
  "deep_read_delay_seconds": 1.0,
  "deep_skip_existing": true,
  "heuristics": {
    "tab_score": {
      "operational_tokens": [],
      "reference_tokens": [],
      "reference_combo_tokens": [],
      "support_tokens": [],
      "derived_tokens": [],
      "operational_weight": 3,
      "reference_weight": 3,
      "derived_weight": -4,
      "support_weight": -2,
      "reference_combo_weight": 3,
      "match_mode": "substring",
      "tab_exclude_patterns": [],
      "expansion_formula_penalty": 0,
      "expansion_formula_threshold": 0.5
    },
    "column_score": {
      "domain_keyword_tokens": []
    }
  }
}
```

- [ ] **Step 2: Create domain_context.example.yaml**

Create `example_data/domain_context.example.yaml`:

```yaml
# Domain context — the profiler's model of the business domain.
# Loaded by the profiler at Phase 1 start. Populated from raw notes and drive tree inspection.
# See docs/orientation.md for the Orient step workflow.

domain: ""                       # e.g., "farm_management"
description: ""                  # What does this business do?

year_scope:
  active: []                     # Years to profile in full  e.g., [2025, 2026]
  archived: []                   # Years to skip/deprioritize  e.g., [2023, 2024]
  forward: []                    # Future years for forward-looking tabs  e.g., [2026]

deduplication:
  strategy: latest_year          # "latest_year" profiles only the latest year per (workbook_code, tab_title)
  exceptions: []                  # Tab titles to always profile per-year  e.g., [{"tab_title": "Sales Actuals", "reason": "Changes yearly"}]

entities: []                      # e.g., [{"name": "Season", "tabs": ["Crop Planner"], "operational": true, "description": "..."}]

vocabulary:
  operational: []                # Words your domain uses for primary data-entry tabs
  reference: []                  # Words for lookup/reference tabs
  support: []                    # Words for helper/index tabs
  derived: []                    # Words for auto-generated/summary tabs

glossary: {}                     # Synonym expansion  e.g., {"qty": "quantity", "amt": "amount"}

scope_notes: ""                  # Freeform notes from orientation
```

- [ ] **Step 3: Add coverage summary artifact to Phase 1 output**

In `profiler/tools/cohort_corpus.py`, inside `run_cohort_corpus()`, after the `write_json` call for the broad coverage file (around line 1344), add:

```python
        coverage_summary_path = out_dir / f"broad_profile_coverage_summary_{date_stamp}.json"
        workbook_tab_names: dict[str, list[str]] = {}
        year_workbook_map: dict[str, list[str]] = defaultdict(list)
        for row in inventory_rows:
            meta = by_sheet_id.get(row["spreadsheet_id"])
            if meta is None:
                continue
            wb_code = meta["workbook_code"]
            year_str = str(meta["year"])
            tab_title = row["tab_title"]
            if wb_code not in workbook_tab_names:
                workbook_tab_names[wb_code] = []
            if tab_title not in workbook_tab_names[wb_code]:
                workbook_tab_names[wb_code].append(tab_title)
            if wb_code not in year_workbook_map.get(year_str, []):
                year_workbook_map.setdefault(year_str, [])
                if wb_code not in year_workbook_map[year_str]:
                    year_workbook_map[year_str].append(wb_code)
        write_json(
            coverage_summary_path,
            {
                "generated_from": discovery_path.name if not resume_from_broad else broad_path.name,
                "workbook_codes": workbook_tab_names,
                "year_coverage": dict(year_workbook_map),
            },
        )
```

Note: `by_sheet_id` is already available in this scope (it's computed from index_records at line 546 in `select_tabs_from_inventory`, but in `run_cohort_corpus` we need to compute it ourselves — it's derived from the index_records that are available in the main branch). Actually, looking at the code more carefully, in the main branch (the `else` block at line 1258), `inventory_rows` is built in the loop at line 1308. We need to compute the summary after the loop completes and before the `select_tabs_from_inventory` call.

Add the `by_sheet_id` computation right before the summary building. Since `index_records` is available in that scope, compute it directly:

```python
        by_sheet_id = {record["spreadsheet_id"]: record for record in index_records}
```

This line should be added right after the broad coverage write (around line 1344) and before the new summary code.

Also, add `coverage_summary` to the artifacts dict (around line 1387):

```python
    artifacts: dict[str, str] = {
        "discovery": str(discovery_path),
        "index": str(index_path),
        "broad_coverage": str(broad_path),
        "broad_coverage_summary": str(coverage_summary_path),
        "tab_shortlist": str(tab_shortlist_path),
        "tab_selection": str(tab_selection_path),
    }
```

- [ ] **Step 4: Update config reader to strip _documentation key**

In `profiler/management/commands/profile_cohort_corpus.py`, after loading the config (line 90), add:

```python
    config = {k: v for k, v in config.items() if not k.startswith("_")}
```

- [ ] **Step 5: Update new_product.py scaffold to include domain_context.yaml and _documentation**

In `scripts/new_product.py`, find the `scaffold_config_templates` function (around line 1241). After the existing `copy_file` for `cohort_corpus.example.json` (line 1257-1260), add:

```python
    copy_file(
        script_dir.parent / "example_data" / "domain_context.example.yaml",
        output_dir / "config" / "domain_context.yaml",
        force=force,
    )
```

- [ ] **Step 6: Run tests**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/ workbook/tests/test_stub_writer.py -v --tb=short 2>&1 | tail -30`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add example_data/cohort_corpus.example.json example_data/domain_context.example.yaml profiler/tools/cohort_corpus.py profiler/management/commands/profile_cohort_corpus.py scripts/new_product.py
git commit -m "feat: config documentation key, domain context example, and broad coverage summary artifact"
```

---

### Task 7: Drive folder timeout documentation and orientation docs in scaffold

**Files:**
- Modify: `workbook/makefile_targets.py` (add timeout note to profile-drive-folder)
- Modify: `scripts/new_product.py` (add Phase 0 orientation to operator.md and AGENTS.md)

- [ ] **Step 1: Add timeout documentation to profile-drive-folder**

In `workbook/makefile_targets.py`, the `profile_blocks` function (line 368) renders the `profile-drive-folder` target. Add a comment noting expected runtime. Change the `profile-drive-folder` block from:

```python
        + "profile-drive-folder:\n"
        + _indent(
            "DB_ENGINE=sqlite $(MANAGE) profile_drive_folder "
            '--folder "$${DRIVE_FOLDER_ID:?DRIVE_FOLDER_ID required}" '
            '--config "$${COHORT_CORPUS_CONFIG}" '
            '--out "$${DRIVE_FOLDER_OUT:-data/profile_snapshots/drive_tree.json}"'
        )
```

to:

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

- [ ] **Step 2: Add Phase 0 Orientation section to scaffold AGENTS.md**

In `scripts/new_product.py`, find the `render_agents_md` function. It contains the 3-phase profiling workflow section (around line 599-644). Add a Phase 0 section before Phase 1. Find the line that starts the Phase 1 content and insert before it.

The current Phase 1 section in the rendered AGENTS.md starts with `### Profiling (read-only discovery)` and then `#### Phase 1 — Discovery + tab selection`. I need to add a Phase 0 section before that.

Find the section that renders the profiling workflow (the `Phase 1 — Discovery` section). It's in the rendered markdown returned by the function. Add a Phase 0 section before it. This is inside a large string literal. Find the text `#### Phase 1 — Discovery + tab selection` and add a Phase 0 section before it:

```markdown
#### Phase 0 — Orient

Before running Phase 1, populate `config/domain_context.yaml`:

1. **Read raw notes** in `data/raw_notes/` — extract entity names, relationships, and temporal scope.
2. **Inspect drive tree** from `make profile-drive-folder` — identify workbook codes and year distribution.
3. **Set year_scope** — mark active years (profile in full), archived years (skip or deprioritize), and forward years (include for planning).
4. **Populate vocabulary** — list domain words for operational, reference, support, and derived tabs.
5. **Add glossary** entries for abbreviations (e.g., `qty: quantity`).
6. **Review deduplication** — by default, tabs appearing across multiple years are profiled only for the latest year. Add exceptions for tabs that change meaning across years.

```

- [ ] **Step 3: Run tests**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest scripts/tests/test_new_product.py workbook/tests/test_makefile_targets.py -v --tb=short 2>&1 | tail -20`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add workbook/makefile_targets.py scripts/new_product.py
git commit -m "docs: drive folder timeout note, Phase 0 orientation in scaffold"
```

---

### Task 8: Integration test and lint check

**Files:**
- No new files; verify all changes work together.

- [ ] **Step 1: Run full test suite**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest profiler/tests/ workbook/tests/ scripts/tests/test_new_product.py -v --tb=short 2>&1 | tail -40`
Expected: All tests pass.

- [ ] **Step 2: Run linter**

Run: `cd /home/user/migration-workbench && python -m ruff check profiler/tools/domain_context.py profiler/tools/cohort_corpus.py profiler/tools/enrichment_utils.py profiler/management/commands/profile_cohort_corpus.py workbook/codegen/stub_writer.py scripts/new_product.py 2>&1`
Expected: No errors. If there are errors, fix them.

- [ ] **Step 3: Final commit if needed**

```bash
git add -A
git commit -m "chore: lint fixes for domain context implementation" || echo "No changes needed"
```