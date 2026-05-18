# Rich Profiling Enhancements

> **Date:** 2026-05-18
> **Status:** Draft
> **Philosophy:** Human-in-the-loop — profiler produces richer data, domain-knowledge authors review and override, scaffold consumes both.

## Goal

Extend the existing profiler pipeline to produce cross-tab entity groupings, FK relationship candidates, computed field marking, and import key candidates — all within the existing column profile output. No new commands, no new JSON artifacts.

## Current State

The profiler produces per-tab column metadata in isolation. Each tab's `ColumnProfile` (Sheets) or column dict (Coda) contains `format_type`, `formula_pattern`, `inferred_type`, `null_rate`, `unique_count_sample`, and `is_relation_type` (Coda only). The scaffold's heuristics (`_flag_fk_columns`, `_flag_computed_fields`, `_suggest_tab_merges`) operate on the already-flattened contract, not on the profiler's richer output.

The Coda profiler already detects `is_relation_type` and `ref_tables_seen` per column, but these aren't surfaced to the scaffold. The Sheets profiler has `cross_sheet_refs` but doesn't use them for FK detection.

## Design

### ColumnProfile Extension

Add five enrichment fields to `ColumnProfile` (Sheets) and parallel fields in the Coda column dict:

| Field | Type | Meaning |
|-------|------|---------|
| `suggested_entity` | `str \| None` | PascalCase entity name derived from workbook series (e.g., `"Planting"`) |
| `suggested_fk_target` | `str \| None` | PascalCase entity this column likely references (e.g., `"Season"`) |
| `is_computed` | `bool` | `True` if `formula_pattern` is `row_formula` or `expansion_formula` |
| `is_import_key_candidate` | `bool` | `True` if high uniqueness + low null rate |
| `cross_tab_group` | `str \| None` | Workbook series code for entity grouping (e.g., `"402_crop_plan"`) |

These fields default to `None`/`False` and are populated by enrichment passes.

### Enrichment Pass 1: Entity Groupings

**Function:** `enrich_entity_groupings(profiles_by_tab: dict[str, list[ColumnProfile]], workbook_index: dict) -> dict[str, str]`

Input: all tab profiles keyed by tab title, plus the workbook index (which maps tab titles to workbook codes).

Logic:
1. Group tabs by workbook series code (e.g., all `"402"` tabs together)
2. Within each group, find tabs sharing 2+ column headers (same as `_suggest_tab_merges` logic already in the scaffold)
3. For each merge group, derive an entity name from the most common column header pattern or workbook code
4. Set `cross_tab_group` on each column in the group to the group ID
5. Set `suggested_entity` on each column to the PascalCase entity name

Returns: a mapping of tab title → suggested entity name.

### Enrichment Pass 2: FK Candidates

**Function:** `enrich_fk_candidates(profiles_by_tab: dict[str, list[ColumnProfile]], entity_names: set[str]) -> None`

Mutates `ColumnProfile` objects in-place.

For Sheets columns:
- Columns ending in `_id` → `suggested_fk_target = _to_pascal_case(name[:-3])`
- Columns with `cross_sheet_refs` present → `suggested_fk_target` = the referenced sheet name PascalCased
- Columns named after known entity names (from `entity_names` set) → `suggested_fk_target = _to_pascal_case(name)`

For Coda columns:
- `is_relation_type == True` → `suggested_fk_target` from `ref_tables_seen[0].tableName`
- Columns ending in `_id` → same as Sheets logic

### Enrichment Pass 3: Computed Fields

**Function:** `enrich_computed_fields(profiles_by_tab: dict[str, list[ColumnProfile]]) -> None`

Mutates `ColumnProfile` objects in-place.

Sets `is_computed = True` where `formula_pattern` is `"row_formula"` or `"expansion_formula"`.

This is the same logic the scaffold's `_flag_computed_fields` uses, but now computed at profile time. The scaffold still runs `_flag_computed_fields` for backwards compatibility, but domain-knowledge authors reviewing profiler output can see which columns are computed before they write the contract.

### Enrichment Pass 4: Import Key Candidates

**Function:** `enrich_import_key_candidates(profiles_by_tab: dict[str, list[ColumnProfile]]) -> None`

Mutates `ColumnProfile` objects in-place.

A column is an import key candidate when:
- `unique_count_sample / max(non_empty_cells, 1) >= 0.9` (high uniqueness relative to non-empty count)
- `null_rate < 0.05` (rarely null)
- `formula_pattern` is `"raw"` or absent (not a formula)

The `_infer_format_type_from_samples` function already computes `null_rate` equivalents. The import key candidate flag helps domain-knowledge authors choose `unique_on` fields for their entity definitions.

### Pipeline Integration

**Sheets path** (`cohort_corpus.py`):
- After `compute_column_profiles()` in `run_cohort_corpus()`, call all four enrichment passes on the `ColumnProfile` objects
- The `ColumnProfile` dataclass is serialized to JSON in the deep profile output, so enrichment fields are preserved automatically

**Coda path** (`coda_corpus.py`):
- After `summarize_coda_table()` builds column dicts, call all four enrichment passes on those dicts
- The column dicts are serialized to JSON in the deep profile output

**Scaffold path** (`scaffold_workbook_schema.py`):
- `build_contract()` and `_build_cohort_contract()` already read profiler column metadata
- When `is_computed` is present in the column data, the scaffold sets `computed_fields` instead of adding the column to `columns[]`
- When `suggested_fk_target` is present, the scaffold sets `suggested_fk_target` on the contract column (already done by `_flag_fk_columns`; the profiler data supplements this)
- When `suggested_entity` is present, the scaffold sets `suggested_entity` on the contract table
- When `is_import_key_candidate` is present, the scaffold adds it to `import_config.unique_on` under `--hardened` mode

### Data Shape

The column profile output changes from:

```json
{
  "source_column": "Season ID",
  "suggested_field_name": "season_id",
  "profiler_format_type": "number",
  "has_formula": false,
  "formula_pattern": "raw",
  "django_field_class": "models.IntegerField",
  "django_field_kwargs": {},
  "notes": []
}
```

To:

```json
{
  "source_column": "Season ID",
  "suggested_field_name": "season_id",
  "profiler_format_type": "number",
  "has_formula": false,
  "formula_pattern": "raw",
  "django_field_class": "models.IntegerField",
  "django_field_kwargs": {},
  "notes": [],
  "suggested_entity": "Planting",
  "suggested_fk_target": "Season",
  "is_computed": false,
  "is_import_key_candidate": true,
  "cross_tab_group": "402_crop_plan"
}
```

## Files Changed

| File | Change |
|------|--------|
| `profiler/tools/cohort_corpus.py` | Add enrichment fields to `ColumnProfile`; add `enrich_entity_groupings`, `enrich_fk_candidates`, `enrich_computed_fields`, `enrich_import_key_candidates`; call them after `compute_column_profiles()` |
| `profiler/tools/coda_corpus.py` | Add enrichment fields to Coda column dicts; call enrichment functions after `summarize_coda_table()` |
| `workbook/management/commands/scaffold_workbook_schema.py` | Read enrichment fields from profiler output; supplement `_flag_fk_columns` and `_flag_computed_fields` with profiler data; set `suggested_entity` on contract tables |
| `workbook/schema_contract.py` | Accept `suggested_entity`, `is_import_key_candidate` in contract column schema |
| `profiler/tests/test_cohort_corpus_tools.py` | Tests for enrichment functions |
| `profiler/tests/test_coda_corpus.py` | Tests for Coda enrichment |
| `workbook/tests/test_scaffold_workbook_schema.py` | Tests for scaffold reading enrichment fields |

## Non-Goals

- **New CLI commands** — enrichment happens inside existing pipeline functions
- **New JSON artifacts** — enrichment fields go into existing column profiles
- **Automatic entity naming** — `suggested_entity` is a heuristic suggestion, not a final name. Domain-knowledge authors override it.
- **Rewrite of the profiler's core scoring logic** — we extend, not replace
- **Model training or ML-based prediction** — all enrichment uses simple heuristics