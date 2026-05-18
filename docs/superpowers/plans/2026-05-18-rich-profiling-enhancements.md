# Rich Profiling Enhancements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the profiler pipeline with four enrichment passes (entity groupings, FK candidates, computed field marking, import key candidates) that populate new fields on existing ColumnProfile and Coda column dicts, then integrate with the scaffold.

**Architecture:** Add enrichment fields to `ColumnProfile` dataclass. Add four enrichment functions that mutate profiles in-place. Call them after `compute_column_profiles()`/`derive_column_candidates()` in both Sheets and Coda paths. Update the scaffold to read the new fields.

**Tech Stack:** Python, Django management commands, pytest.

---

### Task 1: Extend `ColumnProfile` dataclass with enrichment fields

**Files:**
- Modify: `profiler/tools/cohort_corpus.py:60-72`
- Test: `profiler/tests/test_cohort_corpus_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `profiler/tests/test_cohort_corpus_tools.py` in the `TestColumnProfile` class:

```python
def test_column_profile_enrichment_fields_default(self):
    """ColumnProfile enrichment fields default to None/False."""
    cp = ColumnProfile(
        letter="A",
        header_slug="name",
        header_raw="Name",
        inferred_type="text",
        formula_pattern="raw",
        non_empty_cells=10,
    )
    assert cp.suggested_entity is None
    assert cp.suggested_fk_target is None
    assert cp.is_computed is False
    assert cp.is_import_key_candidate is False
    assert cp.cross_tab_group is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest profiler/tests/test_cohort_corpus_tools.py::TestColumnProfile::test_column_profile_enrichment_fields_default -xvs`
Expected: FAILED — `ColumnProfile` doesn't have `suggested_entity` etc.

- [ ] **Step 3: Add enrichment fields to `ColumnProfile`**

At `profiler/tools/cohort_corpus.py:60-72`, add five new fields after the existing fields:

```python
@dataclass
class ColumnProfile:
    letter: str
    header_slug: str
    header_raw: str
    inferred_type: str
    formula_pattern: str
    non_empty_cells: int
    unique_value_sample: list = field(default_factory=list)
    is_section_header: bool = False
    cross_sheet_refs: list = field(default_factory=list)
    pattern_truncated: bool = False
    pattern_hash: str = ""
    suggested_entity: str | None = None
    suggested_fk_target: str | None = None
    is_computed: bool = False
    is_import_key_candidate: bool = False
    cross_tab_group: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest profiler/tests/test_cohort_corpus_tools.py::TestColumnProfile -xvs`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest -x --tb=short 2>&1 | tail -10`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "feat(profiler): add enrichment fields to ColumnProfile dataclass"
```

---

### Task 2: Add `enrich_computed_fields` enrichment pass

**Files:**
- Modify: `profiler/tools/cohort_corpus.py`
- Test: `profiler/tests/test_cohort_corpus_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `profiler/tests/test_cohort_corpus_tools.py`:

```python
from profiler.tools.cohort_corpus import ColumnProfile, enrich_computed_fields


def test_enrich_computed_fields_marks_formula_columns():
    """Columns with row_formula or expansion_formula are marked is_computed=True."""
    profiles = {
        "Crop Planner": [
            ColumnProfile(letter="A", header_slug="name", header_raw="Name",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=10),
            ColumnProfile(letter="B", header_slug="yield_est", header_raw="Yield Est",
                         inferred_type="number", formula_pattern="row_formula", non_empty_cells=10),
            ColumnProfile(letter="C", header_slug="total", header_raw="Total",
                         inferred_type="number", formula_pattern="expansion_formula", non_empty_cells=10),
        ],
    }
    enrich_computed_fields(profiles)
    assert profiles["Crop Planner"][0].is_computed is False
    assert profiles["Crop Planner"][1].is_computed is True
    assert profiles["Crop Planner"][2].is_computed is True


def test_enrich_computed_fields_leaves_raw_unchanged():
    """Columns with raw or hybrid formula_pattern are not marked as computed."""
    profiles = {
        "Tab": [
            ColumnProfile(letter="A", header_slug="x", header_raw="X",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=5),
            ColumnProfile(letter="B", header_slug="y", header_raw="Y",
                         inferred_type="text", formula_pattern="hybrid", non_empty_cells=5),
            ColumnProfile(letter="C", header_slug="z", header_raw="Z",
                         inferred_type="text", formula_pattern="empty", non_empty_cells=5),
        ],
    }
    enrich_computed_fields(profiles)
    for col in profiles["Tab"]:
        assert col.is_computed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest profiler/tests/test_cohort_corpus_tools.py::test_enrich_computed_fields_marks_formula_columns -xvs`
Expected: FAILED — `enrich_computed_fields` doesn't exist

- [ ] **Step 3: Implement `enrich_computed_fields`**

Add after the `ColumnProfile` dataclass in `profiler/tools/cohort_corpus.py`:

```python
def enrich_computed_fields(profiles_by_tab: dict[str, list[ColumnProfile]]) -> None:
    """Mark columns with formula-driven patterns as computed fields.
    
    Sets is_computed=True for columns where formula_pattern is
    'row_formula' or 'expansion_formula'.
    Mutates ColumnProfile objects in-place.
    """
    for _tab, columns in profiles_by_tab.items():
        for col in columns:
            col.is_computed = col.formula_pattern in ("row_formula", "expansion_formula")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest profiler/tests/test_cohort_corpus_tools.py::test_enrich_computed_fields_marks_formula_columns profiler/tests/test_cohort_corpus_tools.py::test_enrich_computed_fields_leaves_raw_unchanged -xvs`
Expected: PASS

- [ ] **Step 5: Run profiler tests for regressions**

Run: `.venv/bin/python -m pytest profiler/tests/ -x --tb=short`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "feat(profiler): add enrich_computed_fields enrichment pass"
```

---

### Task 3: Add `enrich_fk_candidates` enrichment pass

**Files:**
- Modify: `profiler/tools/cohort_corpus.py`
- Test: `profiler/tests/test_cohort_corpus_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `profiler/tests/test_cohort_corpus_tools.py`:

```python
from profiler.tools.cohort_corpus import ColumnProfile, enrich_fk_candidates


def test_enrich_fk_candidates_detects_id_suffix():
    """Columns ending in _id get suggested_fk_target set to PascalCase of the prefix."""
    profiles = {
        "Tab": [
            ColumnProfile(letter="A", header_slug="season_id", header_raw="Season ID",
                         inferred_type="number", formula_pattern="raw", non_empty_cells=10),
            ColumnProfile(letter="B", header_slug="name", header_raw="Name",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=10),
        ],
    }
    entity_names = set()
    enrich_fk_candidates(profiles, entity_names)
    assert profiles["Tab"][0].suggested_fk_target == "Season"
    assert profiles["Tab"][1].suggested_fk_target is None


def test_enrich_fk_candidates_detects_entity_names():
    """Columns named after known entity names get flagged."""
    profiles = {
        "Tab": [
            ColumnProfile(letter="A", header_slug="channel", header_raw="Channel",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=10),
            ColumnProfile(letter="B", header_slug="season", header_raw="Season",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=10),
        ],
    }
    entity_names = {"Channel", "Season"}
    enrich_fk_candidates(profiles, entity_names)
    assert profiles["Tab"][0].suggested_fk_target == "Channel"
    assert profiles["Tab"][1].suggested_fk_target == "Season"


def test_enrich_fk_candidates_detects_cross_sheet_refs():
    """Columns with cross_sheet_refs get suggested_fk_target set."""
    profiles = {
        "Tab": [
            ColumnProfile(letter="A", header_slug="crop_id", header_raw="Crop",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=10,
                         cross_sheet_refs=[{"sheet": "Crop Reference", "count": 5}]),
        ],
    }
    entity_names = set()
    enrich_fk_candidates(profiles, entity_names)
    assert profiles["Tab"][0].suggested_fk_target == "CropReference"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest profiler/tests/test_cohort_corpus_tools.py::test_enrich_fk_candidates_detects_id_suffix -xvs`
Expected: FAILED — `enrich_fk_candidates` doesn't exist

- [ ] **Step 3: Implement `enrich_fk_candidates`**

Add near the other enrichment functions in `profiler/tools/cohort_corpus.py`:

```python
_ENTITY_KEYWORDS = {"channel", "season", "crop", "block", "farm", "field", "variety"}


def _to_pascal_case(raw: str) -> str:
    """Convert a label to PascalCase. Pass through if already PascalCase."""
    if "_" not in raw and "-" not in raw and any(c.isupper() for c in raw[1:]):
        return raw
    return "".join(p.capitalize() for p in raw.replace("-", "_").split("_"))
```

Note: Check if `_to_pascal_case` or a similar function already exists in this module. If so, reuse it instead of adding a duplicate. Also check if `_ENTITY_KEYWORDS` already exists. If not, add it at module level.

```python
def enrich_fk_candidates(
    profiles_by_tab: dict[str, list[ColumnProfile]],
    entity_names: set[str],
) -> None:
    """Flag columns that likely reference other entities.
    
    Detects: columns ending in _id, columns named after entity keywords,
    and columns with cross_sheet_refs.
    Mutates ColumnProfile objects in-place.
    """
    all_entity_names = entity_names | {kw.capitalize() for kw in _ENTITY_KEYWORDS}
    for _tab, columns in profiles_by_tab.items():
        for col in columns:
            name = col.header_slug
            if name.endswith("_id"):
                target = _to_pascal_case(name[:-3])
                col.suggested_fk_target = target
            elif name.lower() in _ENTITY_KEYWORDS:
                target = _to_pascal_case(name)
                col.suggested_fk_target = target
            elif name.capitalize() in all_entity_names:
                col.suggested_fk_target = name.capitalize()
            if not col.suggested_fk_target and col.cross_sheet_refs:
                ref = col.cross_sheet_refs[0].get("sheet", "")
                if ref:
                    col.suggested_fk_target = _to_pascal_case(ref.split()[0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest profiler/tests/test_cohort_corpus_tools.py -k "enrich_fk" -xvs`
Expected: PASS

- [ ] **Step 5: Run profiler tests for regressions**

Run: `.venv/bin/python -m pytest profiler/tests/ -x --tb=short`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "feat(profiler): add enrich_fk_candidates enrichment pass"
```

---

### Task 4: Add `enrich_import_key_candidates` enrichment pass

**Files:**
- Modify: `profiler/tools/cohort_corpus.py`
- Test: `profiler/tests/test_cohort_corpus_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `profiler/tests/test_cohort_corpus_tools.py`:

```python
from profiler.tools.cohort_corpus import ColumnProfile, enrich_import_key_candidates


def test_enrich_import_key_candidates_high_unique_low_null():
    """Columns with high uniqueness and low null rate are import key candidates."""
    profiles = {
        "Tab": [
            ColumnProfile(letter="A", header_slug="name", header_raw="Name",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=100,
                         unique_value_sample=["alpha", "beta", "gamma"]),
            ColumnProfile(letter="B", header_slug="notes", header_raw="Notes",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=20,
                         unique_value_sample=["a", "b"]),
        ],
    }
    enrich_import_key_candidates(profiles)
    # "name" has 3 unique / 100 non_empty = 0.03 uniqueness ratio (low sample vs total)
    # But unique_value_sample has 3 distinct items for ~3% of 100 total
    # Actually we check: len(unique_value_sample) / max(non_empty_cells, 1)
    # For "name": 3/100 = 0.03 — below 0.9 threshold. NOT a candidate.
    # The test needs different numbers. Let me reconsider.
    # Import key candidate: unique_count_sample / non_empty_cells >= 0.9 and null_rate < 0.05
    # But unique_value_sample is a sample list, not a count. We need a count.
    pass
```

Wait — `ColumnProfile` has `unique_value_sample: list` (a sample list), not `unique_count_sample: int`. I need to check how uniqueness is measured. Looking at the dataclass, the field is `unique_value_sample: list`. Let me check `derive_column_candidates` to see if it has a `unique_count_sample` field in the candidate dict.

Looking at the exploration results: `derive_column_candidates` produces `priority_score` and `evidence` with `unique_count_sample`. But `ColumnProfile` only has `unique_value_sample`.

So for `ColumnProfile`, the uniqueness heuristic should use `len(unique_value_sample) / max(non_empty_cells, 1) >= 0.9`. But `unique_value_sample` is capped at a small number (5 items).

This means we can't reliably use `unique_value_sample` for import key detection. We need a different approach or we need to add a `unique_count` field to `ColumnProfile`.

Let me check what data is available. The profiler's `summarize_tab()` in `profile_tab.py` collects column statistics. Let me check if unique count is available.

Actually, looking more carefully: the Coda path already has `unique_count_sample: int` in the column dict. The Sheets path puts sample values in `unique_value_sample: list`. For the Sheets path, we'd need to add a `unique_count` field, or use a different heuristic.

Let me proceed with a two-tier approach:
- For Coda columns: `unique_count_sample / max(data_row_count, 1) >= 0.9`
- For Sheets columns (ColumnProfile): use `non_empty_cells > 0 and formula_pattern == "raw"` as a weaker signal, plus check if the column name looks like an identifier (ends in `_id`, is named `name`, `code`, `id`, etc.)

```python
def test_enrich_import_key_candidates_identifies_keys():
    """Columns with high uniqueness, low null rate, and raw data are import key candidates."""
    profiles = {
        "Tab": [
            ColumnProfile(letter="A", header_slug="planting_id", header_raw="Planting ID",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=100,
                         unique_value_sample=["P001", "P002", "P003", "P004", "P005"]),
            ColumnProfile(letter="B", header_slug="notes", header_raw="Notes",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=20,
                         unique_value_sample=["note1", "note2"]),
            ColumnProfile(letter="C", header_slug="total", header_raw="Total",
                         inferred_type="number", formula_pattern="expansion_formula", non_empty_cells=100,
                         unique_value_sample=["1", "2", "3", "4", "5"]),
        ],
    }
    enrich_import_key_candidates(profiles)
    # planting_id: ends in _id, raw, non_empty > 0 -> candidate
    assert profiles["Tab"][0].is_import_key_candidate is True
    # notes: low non_empty relative to identifier pattern, not _id ending -> not candidate
    assert profiles["Tab"][1].is_import_key_candidate is False
    # total: expansion_formula -> not candidate
    assert profiles["Tab"][2].is_import_key_candidate is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest profiler/tests/test_cohort_corpus_tools.py::test_enrich_import_key_candidates_identifies_keys -xvs`
Expected: FAILED

- [ ] **Step 3: Implement `enrich_import_key_candidates`**

```python
_IDENTIFIER_SUFFIXES = {"_id", "_code", "_key"}
_IDENTIFIER_NAMES = {"id", "name", "code", "slug", "uid", "uuid", "external_id"}


def enrich_import_key_candidates(
    profiles_by_tab: dict[str, list[ColumnProfile]],
) -> None:
    """Flag columns that are likely import key candidates.
    
    Heuristic: columns ending in identifier suffixes, or named after
    identifier patterns, that are raw (not formula) and have data.
    
    For Coda columns with unique_count_sample and data_row_count,
    also check uniqueness ratio >= 0.9.
    """
    for _tab, columns in profiles_by_tab.items():
        for col in columns:
            if col.is_computed:
                col.is_import_key_candidate = False
                continue
            name = col.header_slug.lower()
            is_identifier = (
                any(name.endswith(s) for s in _IDENTIFIER_SUFFIXES)
                or name in _IDENTIFIER_NAMES
                or (col.non_empty_cells > 0 and name == "id")
            )
            col.is_import_key_candidate = is_identifier and col.formula_pattern == "raw"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest profiler/tests/test_cohort_corpus_tools.py -k "enrich_import_key" -xvs`
Expected: PASS

- [ ] **Step 5: Run profiler tests for regressions**

Run: `.venv/bin/python -m pytest profiler/tests/ -x --tb=short`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "feat(profiler): add enrich_import_key_candidates enrichment pass"
```

---

### Task 5: Add `enrich_entity_groupings` enrichment pass

**Files:**
- Modify: `profiler/tools/cohort_corpus.py`
- Test: `profiler/tests/test_cohort_corpus_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `profiler/tests/test_cohort_corpus_tools.py`:

```python
from profiler.tools.cohort_corpus import ColumnProfile, enrich_entity_groupings


def test_enrich_entity_groupings_groups_tabs_by_shared_headers():
    """Tabs sharing 2+ column headers get the same cross_tab_group and entity name."""
    profiles = {
        "Crop Planner 2023": [
            ColumnProfile(letter="A", header_slug="crop", header_raw="Crop",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=10),
            ColumnProfile(letter="B", header_slug="week", header_raw="Week",
                         inferred_type="number", formula_pattern="raw", non_empty_cells=10),
            ColumnProfile(letter="C", header_slug="block", header_raw="Block",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=10),
        ],
        "Crop Planner 2024": [
            ColumnProfile(letter="A", header_slug="crop", header_raw="Crop",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=10),
            ColumnProfile(letter="B", header_slug="week", header_raw="Week",
                         inferred_type="number", formula_pattern="raw", non_empty_cells=10),
            ColumnProfile(letter="C", header_slug="yield", header_raw="Yield",
                         inferred_type="number", formula_pattern="raw", non_empty_cells=10),
        ],
        "Harvest Log": [
            ColumnProfile(letter="A", header_slug="date", header_raw="Date",
                         inferred_type="date", formula_pattern="raw", non_empty_cells=10),
            ColumnProfile(letter="B", header_slug="weight", header_raw="Weight",
                         inferred_type="number", formula_pattern="raw", non_empty_cells=10),
        ],
    }
    workbook_index = {
        "Crop Planner 2023": {"workbook_code": "402"},
        "Crop Planner 2024": {"workbook_code": "402"},
        "Harvest Log": {"workbook_code": "601"},
    }
    result = enrich_entity_groupings(profiles, workbook_index)
    # Crop Planner tabs share "crop" and "week" (2 headers) -> same group
    assert result["Crop Planner 2023"] == result["Crop Planner 2024"]
    # Harvest Log has no overlap -> different group
    assert result.get("Harvest Log") is None or result["Harvest Log"] != result["Crop Planner 2023"]
    # All columns in the group get cross_tab_group set
    assert profiles["Crop Planner 2023"][0].cross_tab_group is not None
    assert profiles["Crop Planner 2024"][0].cross_tab_group is not None
    # suggested_entity is set on columns in groups
    assert profiles["Crop Planner 2023"][0].suggested_entity is not None


def test_enrich_entity_groupings_no_workbook_index():
    """Without workbook_index, no grouping happens."""
    profiles = {
        "Tab A": [
            ColumnProfile(letter="A", header_slug="x", header_raw="X",
                         inferred_type="text", formula_pattern="raw", non_empty_cells=10),
        ],
    }
    result = enrich_entity_groupings(profiles, {})
    assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest profiler/tests/test_cohort_corpus_tools.py::test_enrich_entity_groupings_groups_tabs_by_shared_headers -xvs`
Expected: FAILED

- [ ] **Step 3: Implement `enrich_entity_groupings`**

```python
def enrich_entity_groupings(
    profiles_by_tab: dict[str, list[ColumnProfile]],
    workbook_index: dict[str, dict],
) -> dict[str, str]:
    """Group tabs by workbook series code and shared headers.
    
    Tabs from the same workbook series sharing 2+ column header slugs
    are assigned the same cross_tab_group and a suggested_entity name.
    
    Returns a mapping of tab title -> suggested entity name for tabs
    that were grouped.
    """
    entity_map: dict[str, str] = {}
    
    if not workbook_index:
        return entity_map
    
    # Group tabs by workbook code
    code_groups: dict[str, list[str]] = {}
    for tab_title, meta in workbook_index.items():
        if tab_title not in profiles_by_tab:
            continue
        code = meta.get("workbook_code", "")
        if code:
            code_groups.setdefault(code, []).append(tab_title)
    
    # Within each workbook code, find tabs sharing headers
    group_id = 0
    for code, tab_titles in code_groups.items():
        if len(tab_titles) < 2:
            continue
        header_sets = {}
        for title in tab_titles:
            cols = profiles_by_tab.get(title, [])
            header_sets[title] = {c.header_slug for c in cols}
        
        for i in range(len(tab_titles)):
            for j in range(i + 1, len(tab_titles)):
                shared = header_sets[tab_titles[i]] & header_sets[tab_titles[j]]
                if len(shared) >= 2:
                    group_name = f"{code}_group_{group_id}"
                    group_id += 1
                    entity_name = _to_pascal_case(code + "_" + tab_titles[i].split()[0].lower())
                    
                    for title in [tab_titles[i], tab_titles[j]]:
                        for col in profiles_by_tab.get(title, []):
                            col.cross_tab_group = group_name
                            col.suggested_entity = entity_name
                        entity_map[title] = entity_name
                    break  # One group per code is enough for heuristic purposes
            else:
                continue
            break
    
    return entity_map
```

Note: `_to_pascal_case` was added in Task 3. If a `_to_pascal_case` already exists in this module from Task 3, reuse it. If not, add it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest profiler/tests/test_cohort_corpus_tools.py -k "enrich_entity" -xvs`
Expected: PASS

- [ ] **Step 5: Run profiler tests for regressions**

Run: `.venv/bin/python -m pytest profiler/tests/ -x --tb=short`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "feat(profiler): add enrich_entity_groupings enrichment pass"
```

---

### Task 6: Integrate enrichment into Sheets pipeline (cohort_corpus)

**Files:**
- Modify: `profiler/tools/cohort_corpus.py` (call enrichment passes after `compute_column_profiles` / after `derive_column_candidates`)

- [ ] **Step 1: Find the enrichment call sites**

Read `profiler/tools/cohort_corpus.py` and find:
1. Where `compute_column_profiles()` is called (if it's called in the pipeline, not just tests)
2. Where `derive_column_candidates()` is called in `run_cohort_corpus()`
3. The workbook index structure available at those call sites

As discovered in exploration: `compute_column_profiles()` is NOT called in `run_cohort_corpus()`. The pipeline uses `derive_column_candidates()` which operates on raw summary/payload data, not `ColumnProfile` objects. So enrichment needs to happen differently.

Two options:
a. Add a separate enrichment pass after `derive_column_candidates()` that operates on the `candidate_columns` list of dicts
b. Call `compute_column_profiles()` and enrichment after the deep-profile fetch step

The cleanest approach is (a): operate on the candidate column dicts that `derive_column_candidates()` produces.

Read the output of `derive_column_candidates()` to see its dict structure, then add enrichment calls after each invocation in `run_cohort_corpus()`.

- [ ] **Step 2: Add enrichment calls after `derive_column_candidates()`**

In `run_cohort_corpus()`, after each `derive_column_candidates()` call (lines ~1314-1326 and ~1353-1365), add:

```python
    # Enrichment passes
    profiles_by_tab = {}
    # Build a profiles_by_tab dict from candidate_columns for enrichment
    for tab_title in selected_tabs:
        tab_cols = [c for c in candidate_columns if c.get("tab_title") == tab_title]
        # ... convert to ColumnProfile-compatible dicts and enrich
```

Actually, this approach is getting complex because `derive_column_candidates()` returns a flat list of dicts, not `ColumnProfile` objects per tab. The enrichment functions expect `dict[str, list[ColumnProfile]]`.

A simpler approach: add the enrichment as a **separate step** that operates on the **deep profile payloads** after they're written. Since the deep profiles contain the `ColumnProfile` data, we can load them, enrich, and rewrite.

But that's also complex. The simplest integration: add a helper that enriches the `candidate_columns` list of dicts directly (similar to how `_flag_fk_columns` works on the scaffold side).

Let me pivot: create `enrich_candidate_columns()` that works on the dict format from `derive_column_candidates()`, and call it after the candidates are collected.

```python
def enrich_candidate_columns(candidate_columns: list[dict]) -> None:
    """Apply enrichment passes to candidate column dicts.
    
    This is a convenience wrapper that adds enrichment fields
    to the dict format produced by derive_column_candidates().
    Mutates dicts in-place.
    """
    for col in candidate_columns:
        # Computed fields
        pattern = col.get("formula_pattern") or col.get("evidence", {}).get("formula_pattern")
        col["is_computed"] = pattern in ("row_formula", "expansion_formula")
        
        # FK candidates
        name = col.get("proposed_canonical_field", "")
        if name.endswith("_id"):
            col["suggested_fk_target"] = _to_pascal_case(name[:-3])
        elif name.lower() in _ENTITY_KEYWORDS:
            col["suggested_fk_target"] = _to_pascal_case(name)
        elif col.get("evidence", {}).get("cross_sheet_refs"):
            refs = col["evidence"]["cross_sheet_refs"]
            if refs:
                col["suggested_fk_target"] = _to_pascal_case(refs[0].split()[0])
        
        # Import key candidates
        name_lower = name.lower()
        is_id = (
            any(name_lower.endswith(s) for s in _IDENTIFIER_SUFFIXES)
            or name_lower in _IDENTIFIER_NAMES
        )
        col["is_import_key_candidate"] = is_id and not col.get("is_computed", False)
```

Add this function and call it after `derive_column_candidates()` in both call sites in `run_cohort_corpus()`.

- [ ] **Step 3: Also call the ColumnProfile-based enrichment in `compute_column_profiles()`**

When `compute_column_profiles()` IS called (in tests or standalone usage), it should also run enrichment. Add calls at the end of `compute_column_profiles()`:

```python
    # Enrichment passes
    enrich_computed_fields({tab_title or "default": profiles})
    enrich_fk_candidates({tab_title or "default": profiles}, set())
    enrich_import_key_candidates({tab_title or "default": profiles})
```

But `compute_column_profiles` only processes one tab at a time. The entity grouping enrichment requires cross-tab context, so it can't be called there.

The approach:
- Single-tab enrichment (computed, FK, import key) runs in `compute_column_profiles()` and after `derive_column_candidates()`
- Cross-tab enrichment (entity groupings) runs separately on the full `profiles_by_tab` dict

- [ ] **Step 4: Run profiler tests for regressions**

Run: `.venv/bin/python -m pytest profiler/tests/ -x --tb=short`
Expected: all pass

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest -x --tb=short 2>&1 | tail -10`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "feat(profiler): integrate enrichment passes into Sheets pipeline"
```

---

### Task 7: Integrate enrichment into Coda pipeline

**Files:**
- Modify: `profiler/tools/coda_corpus.py`

- [ ] **Step 1: Find the enrichment call sites in Coda pipeline**

Read `profiler/tools/coda_corpus.py` and find where `derive_column_candidates()` is called in `run_coda_corpus()` (around line 823-830).

Also find where `summarize_coda_table()` results are processed — the column dicts from `summarize_coda_table()` have `is_relation_type` and `ref_tables_seen` which should be used for FK detection.

- [ ] **Step 2: Add enrichment to Coda column dicts**

The Coda column dicts have these fields relevant to enrichment:
- `is_relation_type: bool` — equivalent to FK candidate
- `ref_tables_seen: list` — FK target info
- `has_formula: bool` — computed field indicator
- `null_rate: float` — import key indicator
- `unique_count_sample: int` — import key indicator

Add a function `enrich_coda_columns()` that adds enrichment fields to Coda column dicts:

```python
def enrich_coda_columns(columns: list[dict[str, Any]]) -> None:
    """Add enrichment fields to Coda column dicts."""
    for col in columns:
        # Computed fields: Coda has has_formula, but no specific pattern
        col["is_computed"] = col.get("has_formula", False)
        
        # FK candidates: is_relation_type + ref_tables_seen
        if col.get("is_relation_type") and col.get("ref_tables_seen"):
            ref = col["ref_tables_seen"][0]
            col["suggested_fk_target"] = ref.get("tableName", "")
        elif col.get("name", "").endswith("_id"):
            col["suggested_fk_target"] = col["name"][:-3].replace("_", " ").title().replace(" ", "")
        
        # Import key candidates
        name = col.get("name", "").lower()
        is_id = (
            any(name.endswith(s) for s in _IDENTIFIER_SUFFIXES)
            or name in _IDENTIFIER_NAMES
        )
        unique_ratio = 0
        if col.get("unique_count_sample") and col.get("null_rate") is not None:
            data_rows = max(1, int(col.get("unique_count_sample", 0) / max(1 - col.get("null_rate", 1), 0.01)))
            unique_ratio = col.get("unique_count_sample", 0) / max(data_rows, 1)
        col["is_import_key_candidate"] = (
            is_id or (unique_ratio >= 0.9 and col.get("null_rate", 1) < 0.05)
        ) and not col.get("is_computed", False)
```

Call this function after `derive_column_candidates()` in `run_coda_corpus()` and after column dicts are built in `summarize_coda_table()`.

Note: `_IDENTIFIER_SUFFIXES` and `_IDENTIFIER_NAMES` are defined in `cohort_corpus.py`. You'll need to import them or define them in the coda corpus module as well. If they're module-level constants in `cohort_corpus.py`, import them.

- [ ] **Step 3: Add test**

Add a test in `profiler/tests/test_coda_corpus.py`:

```python
def test_enrich_coda_columns_adds_enrichment_fields():
    """Coda column dicts get enrichment fields for computed, FK, and import key."""
    from profiler.tools.coda_corpus import enrich_coda_columns
    columns = [
        {"name": "season_id", "is_relation_type": False, "has_formula": False,
         "null_rate": 0.01, "unique_count_sample": 100},
        {"name": "total", "is_relation_type": False, "has_formula": True,
         "null_rate": 0.0, "unique_count_sample": 50},
        {"name": "season", "is_relation_type": True,
         "ref_tables_seen": [{"tableId": "tbl1", "tableName": "Seasons"}],
         "has_formula": False, "null_rate": 0.02, "unique_count_sample": 5},
    ]
    enrich_coda_columns(columns)
    assert columns[0]["is_computed"] is False
    assert columns[0]["is_import_key_candidate"] is True  # ends in _id
    assert columns[1]["is_computed"] is True
    assert columns[2]["suggested_fk_target"] == "Seasons"
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest profiler/tests/test_coda_corpus.py -x --tb=short -v`
Expected: all pass

Run: `.venv/bin/python -m pytest profiler/tests/ -x --tb=short`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add profiler/tools/coda_corpus.py profiler/tests/test_coda_corpus.py
git commit -m "feat(profiler): integrate enrichment passes into Coda pipeline"
```

---

### Task 8: Scaffold reads enrichment fields from profiler output

**Files:**
- Modify: `workbook/schema_contract.py`
- Modify: `workbook/management/commands/scaffold_workbook_schema.py`
- Test: `workbook/tests/test_scaffold_workbook_schema.py`
- Test: `workbook/tests/test_schema_contract.py`

- [ ] **Step 1: Update `build_contract()` to pass enrichment fields through**

In `workbook/schema_contract.py`, the `build_contract()` function builds column dicts at lines 342-357. Currently it reads `format_type`, `has_formula`, `formula_pattern` from the profiler column dict. Add the enrichment fields:

Read the current `build_contract()` column-building code. After the existing fields, add:

```python
django_columns.append({
    "source_column": src,
    "suggested_field_name": suggested_field_name(src),
    "profiler_format_type": col.get("format_type"),
    "has_formula": col.get("has_formula"),
    "formula_pattern": col.get("formula_pattern"),
    "django_field_class": hint["django_field_class"],
    "django_field_kwargs": hint["django_field_kwargs"],
    "notes": hint.get("notes") or [],
    "suggested_entity": col.get("suggested_entity"),
    "suggested_fk_target": col.get("suggested_fk_target"),
    "is_computed": col.get("is_computed", False),
    "is_import_key_candidate": col.get("is_import_key_candidate", False),
    "cross_tab_group": col.get("cross_tab_group"),
})
```

- [ ] **Step 2: Update `_build_cohort_contract()` to read enrichment fields**

In `scaffold_workbook_schema.py`, the `_build_cohort_contract()` function builds column dicts at lines 213-235. Currently it sets `has_formula` and `formula_pattern` to `None`. After the heuristics were added (Task 7), the `_flag_computed_fields()` function handles `formula_pattern`. But the deep profile payloads may now contain `is_computed` from the profiler enrichment.

Add the enrichment fields to the column dict:

```python
columns.append({
    "source_column": header.strip(),
    "suggested_field_name": suggested_field_name(header),
    "profiler_format_type": fmt,
    "has_formula": None,
    "formula_pattern": None,
    "django_field_class": hint["django_field_class"],
    "django_field_kwargs": hint["django_field_kwargs"],
    "notes": hint.get("notes") or [],
    "suggested_entity": column_meta.get("suggested_entity"),
    "suggested_fk_target": column_meta.get("suggested_fk_target"),
    "is_computed": column_meta.get("is_computed", False),
    "is_import_key_candidate": column_meta.get("is_import_key_candidate", False),
    "cross_tab_group": column_meta.get("cross_tab_group"),
})
```

- [ ] **Step 3: Update scaffold heuristics to supplement profiler enrichment**

The scaffold already has `_flag_fk_columns()`, `_flag_computed_fields()`, etc. These should supplement (not replace) profiler enrichment. The contract columns now have `suggested_fk_target` and `is_computed` from the profiler. The scaffold heuristics should set these fields if they're not already set:

In `_flag_fk_columns()`: skip columns that already have `suggested_fk_target` from the profiler.
In `_flag_computed_fields()`: skip columns that already have `is_computed = True` from the profiler.

Update `_flag_fk_columns`:

```python
def _flag_fk_columns(columns: list[dict]) -> None:
    for col in columns:
        if col.get("suggested_fk_target"):
            continue  # Already set by profiler enrichment
        name = col.get("suggested_field_name", "")
        # ... existing detection logic ...
```

Update `_flag_computed_fields`:

```python
def _flag_computed_fields(table: dict) -> None:
    columns = table.get("columns", [])
    kept = []
    computed = {}
    for col in columns:
        pattern = col.get("formula_pattern")
        is_computed = col.get("is_computed", False)
        if pattern in ("row_formula", "expansion_formula") or is_computed:
            if col.get("suggested_field_name") not in computed:
                name = col.get("suggested_field_name", col.get("source_column", ""))
                computed[name] = {
                    "return_type": col.get("django_field_class", "models.FloatField"),
                    "expression": f"# TODO: {col.get('source_column', name)} is formula-derived",
                }
        else:
            kept.append(col)
    table["columns"] = kept
    if computed:
        table.setdefault("computed_fields", {}).update(computed)
```

- [ ] **Step 4: Update `_harden_contract` / import key logic**

In `scaffold_workbook_schema.py`, when `--hardened` mode sets `import_config`, check `is_import_key_candidate` and use it for `unique_on` if available.

Find where `_harden_contract()` sets `import_config` values. Add logic to use `is_import_key_candidate` columns as `unique_on` candidates:

```python
    # In _harden_contract, when building import_config:
    for table in contract.get("tables", []):
        import_config = table.setdefault("import_config", {})
        if "unique_on" not in import_config:
            key_candidates = [
                col["suggested_field_name"]
                for col in table.get("columns", [])
                if col.get("is_import_key_candidate")
            ]
            if key_candidates:
                import_config["unique_on"] = key_candidates[:1]  # First candidate
```

- [ ] **Step 5: Write tests**

Add to `workbook/tests/test_scaffold_workbook_schema.py`:

```python
def test_scaffold_passes_through_enrichment_fields():
    """Scaffold passes suggested_entity and is_computed from profiler to contract."""
    bundle = tmp_path / "bundle.json"
    # ... set up bundle and table_profile with enrichment fields ...
    # After scaffolding, verify contract columns have:
    # - suggested_entity
    # - suggested_fk_target
    # - is_computed
    # - is_import_key_candidate
    # - cross_tab_group
```

Actually, this is well-tested enough through the existing `test_scaffold_stores_app_label_in_contract` pattern. Write a similar integration test.

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest -x --tb=short 2>&1 | tail -10`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add workbook/schema_contract.py workbook/management/commands/scaffold_workbook_schema.py workbook/tests/test_scaffold_workbook_schema.py
git commit -m "feat(scaffold): read profiler enrichment fields in contract building"
```

---

### Task 9: Final sweep — run full suite + verify enrichment field propagation

**Files:**
- No new files; verification only

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/python -m pytest -x --tb=short 2>&1 | tail -15`
Expected: all pass (515+ tests)

- [ ] **Step 2: Run profiler tests in isolation**

Run: `.venv/bin/python -m pytest profiler/tests/ -x --tb=short -v`
Expected: all pass (89+ tests)

- [ ] **Step 3: Run scaffold tests in isolation**

Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py -x --tb=short -v`
Expected: all pass (12+ tests)

- [ ] **Step 4: Commit final state**

```bash
git add -A
git commit -m "chore: verify all enrichment field propagation passes full test suite"
```