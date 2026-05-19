# Rich Profiling Enhancements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add four enrichment passes (computed field detection, FK candidate detection, import key candidate detection, entity grouping) to the profiler pipeline and propagate the resulting fields through to the scaffold contract.

**Architecture decision:** Enrichment operates on column dicts (the format produced by `derive_column_candidates()`), not on `ColumnProfile` objects, because `compute_column_profiles()` is not called in the production pipeline. The dicts from `derive_column_candidates()` are the real integration point.

---

## Context (what exists now)

**Profiler output per candidate column** (from `derive_column_candidates()` in both `cohort_corpus.py` and `coda_corpus.py`):

| Field | Sheets | Coda |
|---|---|---|
| identifier fields | `workbook_code`, `year`, `spreadsheet_id`, `tab_title` | `doc_name`, `table_name` |
| column identity | `column_header`, `proposed_canonical_field` | `column_name`, `proposed_canonical_field` |
| scoring | `priority_score`, `priority_reasons` | same |
| evidence | `evidence.formula_pattern`, `evidence.functions_used` | `evidence.null_rate`, `evidence.unique_count_sample`, `evidence.format_type`, `evidence.ref_tables_seen` |

**Scaffold already has:**
- `_to_pascal_case()` and `_ENTITY_KEYWORDS` in `scaffold_workbook_schema.py:42-53`
- `_flag_fk_columns()` at line 56 — detects `_id` suffix and entity keyword matches, sets `suggested_fk_target`
- `_flag_computed_fields()` at line 74 — moves `formula_pattern` columns to `computed_fields{}`

The scaffold heuristics work today but rely on scaffold-local logic. The goal is to supplement (not replace) these with profiler-side detection that carries richer signal (e.g. cross-sheet refs, formula functions used, uniqueness ratios from Coda).

**Scaffold contract column dicts** currently have 8 fields (in `build_contract()` and `_build_cohort_contract()`): `source_column`, `suggested_field_name`, `profiler_format_type`, `has_formula`, `formula_pattern`, `django_field_class`, `django_field_kwargs`, `notes`.

---

## Enrichment passes (what each does)

### 1. Computed field detection
**Signal:** `formula_pattern in ("row_formula", "expansion_formula")` for Sheets; `has_formula` for Coda.
**Output field:** `is_computed: bool` on each column dict.

### 2. FK candidate detection
**Signal:** `_id` suffix, entity keyword match, or `cross_sheet_refs` presence.
**Output field:** `suggested_fk_target: str | None` — PascalCase entity name.

### 3. Import key candidate detection
**Signal:** Column name matches identifier patterns, plus (for Coda) uniqueness ratio ≥ 0.9 and null rate < 5%.
**Output field:** `is_import_key_candidate: bool`.

### 4. Entity grouping
**Signal:** Tabs from the same workbook series sharing ≥2 column headers are likely the same entity type.
**Output fields:** `suggested_entity: str | None`, `cross_tab_group: str | None`.

---

## Tasks

### Task 1: Add enrichment functions to `cohort_corpus.py` (Sheets path)

**Files:** `profiler/tools/cohort_corpus.py`, `profiler/tests/test_cohort_corpus_tools.py`

Add four module-level functions that operate on column dicts (the format from `derive_column_candidates()`):

- `enrich_computed_fields(columns: list[dict]) -> None`
- `enrich_fk_candidates(columns: list[dict], entity_names: set[str]) -> None`
- `enrich_import_key_candidates(columns: list[dict]) -> None`

Also add these module-level constants (they don't exist yet in the profiler):
```python
_IDENTIFIER_SUFFIXES = {"_id", "_code", "_key"}
_IDENTIFIER_NAMES = {"id", "name", "code", "slug", "uid", "uuid", "external_id"}
```

Entity grouping (`enrich_entity_groupings`) requires cross-tab context and the workbook index, so it's a separate function:
```python
def enrich_entity_groupings(
    columns: list[dict],
    workbook_index: dict[str, dict],
) -> dict[str, str]:
```
Returns a `{tab_title: entity_name}` mapping for tabs that were grouped.

**Integration:** Call all four enrichment functions after `derive_column_candidates()` accumulates `candidate_columns` in `run_cohort_corpus()` (at both call sites, lines ~1314 and ~1353).

**Tests:** Follow TDD — write a failing test for each enrichment function, then implement. Tests go in `test_cohort_corpus_tools.py`.

---

### Task 2: Add enrichment to `coda_corpus.py` (Coda path)

**Files:** `profiler/tools/coda_corpus.py`, `profiler/tests/test_coda_corpus.py`

Coda column dicts already have `has_formula`, `is_relation_type`, `ref_tables_seen`, `null_rate`, and `unique_count_sample`. Write `enrich_coda_columns(columns: list[dict]) -> None` that adds the same enrichment fields using Coda-native signals:

- `is_computed` ← `has_formula`
- `suggested_fk_target` ← `ref_tables_seen[0].tableName` if `is_relation_type`, else `_id` suffix detection
- `is_import_key_candidate` ← identifier name patterns OR (uniqueness ratio ≥ 0.9 AND null_rate < 0.05), excluding computed fields

Call `enrich_coda_columns()` after `derive_column_candidates()` in `run_coda_corpus()` (line ~824).

Coda has no cross-workbook tab grouping analogue, so entity grouping is not applicable here.

**Tests:** Add `test_enrich_coda_columns_adds_enrichment_fields` to `test_coda_corpus.py`.

---

### Task 3: Propagate enrichment fields through scaffold contract

**Files:** `workbook/schema_contract.py`, `workbook/management/commands/scaffold_workbook_schema.py`, `workbook/tests/test_scaffold_workbook_schema.py`

Three changes:

**A.** Add enrichment fields to the column dict in `build_contract()` (line ~342) and `_build_cohort_contract()` (line ~224):
```python
"suggested_entity": col.get("suggested_entity"),
"suggested_fk_target": col.get("suggested_fk_target"),
"is_computed": col.get("is_computed", False),
"is_import_key_candidate": col.get("is_import_key_candidate", False),
"cross_tab_group": col.get("cross_tab_group"),
```

**B.** Update `_flag_fk_columns()` to skip columns that already have `suggested_fk_target` from the profiler. The profiler's signal (cross-sheet refs) is stronger than the scaffold's suffix/entity-keyword heuristic.

**C.** In `_harden_contract()`, when building `import_config`, use `is_import_key_candidate` columns as `unique_on` candidates if no `unique_on` is already set.

**Tests:** Integration test verifying enrichment fields survive the profiler→scaffold→contract pipeline.

---

### Task 4: Final verification

**Files:** none (verification only)

- Run `profiler/tests/` — all pass
- Run `workbook/tests/test_scaffold_workbook_schema.py` — all pass
- Run full test suite — all pass
- Spot-check: a column with `formula_pattern == "row_formula"` in a deep profile produces `is_computed: true` in the contract; a column named `season_id` produces `suggested_fk_target: "Season"` in the contract.
