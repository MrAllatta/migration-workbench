# Pipeline Hardening: Full 22-Issue Design

> **Approach:** Layer-by-layer (bottom-up), respecting dependency chains from profiler → schema → codegen → multi-year → scaffold/deploy.

> **For agentic workers:** Each layer is independently testable and shippable. Layers must be implemented in order (L0 → L6) because higher layers depend on lower layers.

## Context

After an end-to-end autonomous pipeline exercise, we filed 22 issues (MrAllatta/migration-workbench #32–#55) covering bugs and enhancements across the full pipeline: connectors, profiler, schema generation, codegen, multi-year corpus support, scaffold, and deployment.

Two ad-hoc fixes exist in the working tree:
- `connectors/google_sheets.py`: Rate throttling (`_throttle()`) and double-encoding fix (removing `quote()`)
- `importer/parsing.py`: Additional date formats in `parse_iso_date`

This spec formalizes those fixes and addresses all 22 issues systematically.

---

## L0: Connector Fixes (Issues #40, #41, #48)

### #40: Double-encoding range strings

**Problem:** `fetch_tab_rows` and `fetch_sheet_structure_data` use `urllib.parse.quote()` on range strings, which double-encodes them (the Google API client already percent-encodes, turning `%20` into `%2520`).

**Fix:** Remove `quote()` calls. Keep the SQL-style apostrophe escaping (`worksheet_title.replace("'", "''")`), which is correct.

**Files:**
- Modify: `connectors/google_sheets.py` — `fetch_tab_rows()`, `fetch_sheet_structure_data()`

Test: Range strings with spaces, apostrophes, and `+` characters no longer trigger 403/400 errors.

### #41/#48: Rate throttling — configurable, not hardcoded

**Problem:** `fetch_tab_rows` and `fetch_sheet_structure_data` make Sheets API calls with no rate limiting, causing 429 Quota Exceeded. The ad-hoc fix uses a module-level `_throttle()` with a hardcoded 1.5s floor.

**Fix:** Replace with a configurable `SheetsThrottle` class:

```python
class SheetsThrottle:
    """Rate limiter for Google Sheets API calls."""

    def __init__(self, min_interval: float = 1.0):
        self._min_interval = min_interval
        self._last = 0.0

    def wait(self):
        elapsed = time.monotonic() - self._last
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last = time.monotonic()
```

- Default `min_interval=1.0` (conservatively under the 60 req/min quota)
- Configurable via `GOOGLE_SHEETS_THROTTLE_INTERVAL` env var (parsed as float)
- Both `fetch_tab_rows` and `fetch_sheet_structure_data` accept an optional `throttle` parameter
- A module-level `default_throttle = SheetsThrottle()` is used when no explicit throttle is passed (backward compatible)
- Add exponential backoff with retry on 429 responses (up to 3 retries, base delay 2s)

**Files:**
- Modify: `connectors/google_sheets.py` — add `SheetsThrottle` class, update function signatures
- Modify: `connectors/google_provider.py` — pass throttle through to adapter methods

Test: Unit tests for `SheetsThrottle.wait()`, integration test that 429 triggers retry.

---

## L1: Profiler Improvements (Issues #32, #33, #38)

### #32: Structured column profiles instead of raw API data

**Problem:** Deep profile output (`deep/*.json`) stores raw Google Sheets API `sheets[].data[].rowData[]` payloads. Downstream consumers must manually parse frozen rows, cross-reference column letters, and extract type information.

**Fix:** After fetching grid data, compute a structured `column_profiles[]` array per tab:

```python
@dataclass
class ColumnProfile:
    letter: str                # "A", "B", etc.
    header_slug: str           # "product_sku" (normalized lower-snake)
    header_raw: str            # "Product SKU" (original display text)
    inferred_type: str         # "text" | "number" | "date" | "boolean" | "formula" | "empty"
    formula_pattern: str       # "raw" | "empty" | "hybrid" | "expansion_formula" | "row_formula"
    non_empty_cells: int
    unique_value_sample: list  # first 5 unique non-empty formattedValues
    is_section_header: bool   # True if merged-cell section divider
    cross_sheet_refs: list    # [("SheetName", count), ...] from formula references
```

Store `column_profiles` in the summary dict alongside the existing `column_formula_patterns`. Keep `column_formula_patterns` as a computed dict derived from `column_profiles` for backward compatibility, but mark it as deprecated.

**Files:**
- Modify: `profiler/tools/cohort_corpus.py` — add `ColumnProfile` dataclass, `compute_column_profiles()` function
- Modify: `profiler/management/commands/profile_tab.py` — use `compute_column_profiles()` in deep profile output

### #33: Formula patterns keyed by header name, not letter

**Problem:** `summary.column_formula_patterns` uses column letters as keys, which are meaningless without positional alignment.

**Fix:** Emit `column_formula_patterns` keyed by `header_slug` with the column letter as metadata:

```json
"column_formula_patterns": {
    "product_sku": {"letter": "A", "pattern": "raw"},
    "format": {"letter": "B", "pattern": "row_formula"}
}
```

**Files:**
- Modify: `profiler/tools/cohort_corpus.py` — update `column_formula_patterns` construction

### #38: Truncate long formula patterns

**Problem:** Formula patterns (especially `ARRAYFORMULA(QUERY(…))` headers) can exceed 2000 characters, bloating profile JSON.

**Fix:** Truncate pattern strings longer than 200 characters. Store the full pattern in a separate file `<slug>_full_pattern.txt` in the deep profile directory. In `ColumnProfile`, add `pattern_truncated: bool` and `pattern_hash: str` (first 8 chars of SHA-256).

**Files:**
- Modify: `profiler/tools/cohort_corpus.py` — truncation logic in `compute_column_profiles()`

---

## L2: Schema/Hardening (Issues #34, #35, #36, #37, #39)

### #34: Section-header row detection

**Problem:** `scaffold_workbook_schema` includes merged-cell section dividers (e.g., "HARVEST INFO", "FIELD PLAN") as data columns.

**Fix:** Use `ColumnProfile.is_section_header` from L1 to filter section headers. Detection heuristic:
- Column has >80% identical non-empty values
- Fewer than 3 unique values total
- Header is all uppercase or matches common divider patterns
- Column has very high merged-cell span (>50% of total columns)

When `--hardened`, skip section-header columns entirely. When not hardened, include them with `section_header: true` annotation.

**Files:**
- Modify: `workbook/schema_contract.py` — add `_filter_section_headers()`
- Modify: `workbook/management/commands/scaffold_workbook_schema.py` — call filter during column candidate generation

### #35: FK resolutions from column overlap

**Problem:** `--hardened` produces no `fk_resolutions` section, even when identical column names appear across selected tabs.

**Fix:** When `--hardened`, scan all tables for shared column names. For each shared column where the reference table's column has high uniqueness (>80% unique non-empty), emit:

```yaml
fk_resolutions:
  - field: block
    target_model: FieldBlock
    target_field: block
    confidence: high
    source: "column_overlap"
```

**Files:**
- Modify: `workbook/schema_contract.py` — add `_compute_fk_resolutions()`

### #36: import_key / natural key suggestions

**Problem:** Generated `import_config` blocks have empty `import_keys: []`.

**Fix:** For each table, suggest `import_key` based on columns with high uniqueness from `column_profiles`. Weight columns whose slug contains `sku`, `code`, `id`, `name`, `key`. Emit:

```yaml
import_key:
  fields: [crop, block, plan_field_year]
  confidence: medium
  note: "Autogenerated from uniqueness analysis — review recommended"
```

**Files:**
- Modify: `workbook/schema_contract.py` — add `_suggest_import_keys()`

### #37: Cross-sheet references as FK hints

**Problem:** `cross_sheet_refs` is collected by the profiler but not consumed by `scaffold_workbook_schema`.

**Fix:** Consume `column_profiles[].cross_sheet_refs` from L1. When a column references another tab that's also in the selected tab set, add it as a FK resolution candidate with `confidence: medium` and `source: "cross_sheet_formula"`.

**Files:**
- Modify: `workbook/schema_contract.py` — extend `_compute_fk_resolutions()` to include cross-sheet refs

### #39: source_bundle_year field

**Problem:** Multi-year corpus data loses year context during import. The scaffolder doesn't add `source_bundle_year` to the contract.

**Fix:** In `_build_cohort_contract()`, detect the year from workbook index metadata. Add `source_bundle_year: IntegerField` as a suggested field with `default: <year>` in `import_config.defaults`.

**Files:**
- Modify: `workbook/schema_contract.py` — add `_add_source_bundle_year()`

---

## L3: Import Codegen (Issues #44, #50, #51, #52)

### #44: Propagate import_key to unique_on

**Problem:** `import_key` at contract table level isn't propagated to `import_config.unique_on`, resulting in `update_or_create(, defaults=data)` syntax errors.

**Fix:** In `import_generator.render_import_py()`, resolve `unique_on` with fallback chain:
1. `import_config.unique_on` (explicit, highest priority)
2. `import_key.fields` from table level
3. If neither exists, emit a warning and skip the `update_or_create` call

**Files:**
- Modify: `workbook/codegen/import_generator.py` — update `unique_on` resolution logic

### #50: generate_import output to management/commands/

**Problem:** `generate_import` outputs to app directory, not Django's discoverable `management/commands/` path. `python manage.py import_core` produces "Unknown command".

**Fix:** Change `generate_import` default behavior:
- If `--out` is explicitly provided, use it as-is (backward compatible)
- If `--out` is omitted, derive path from `--app-label`: `<app_dir>/management/commands/import_<app_label>.py`
- Create `__init__.py` files in `management/` and `management/commands/` if missing
- Update `scripts/new_product.py` scaffold Makefile template accordingly

**Files:**
- Modify: `workbook/management/commands/generate_import.py` — change default `--out`
- Modify: `scripts/new_product.py` — update Makefile template

### #51/#52: Auto-generate bundle_path, eliminate TODO_bundle_path

**Problem:** contracts lack `import_config.bundle_path`, so `generate_import` produces `TODO_bundle_path.csv` placeholders.

**Fix:** In `scaffold_workbook_schema --hardened`, compute `import_config.bundle_path` from `bundle_worksheet_title`:

```python
slug = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')
if source_bundle_year:
    path = f"{source_bundle_year}/{slug}.csv"
else:
    path = f"{slug}.csv"
```

When `bundle_path` is still absent at import generation time, emit a clear `ValueError` instead of a silent placeholder.

**Files:**
- Modify: `workbook/schema_contract.py` — add `_compute_bundle_paths()`
- Modify: `workbook/codegen/import_generator.py` — replace `TODO_bundle_path` with error

---

## L4: Multi-year Corpus Support (Issues #46, #55, #43)

### #55: Year-specific worksheet title aliases

**Problem:** The same conceptual tab has different names in different years (e.g., "Products" in 2023, "Products 302 + 602" in 2024–2026). Currently requires duplicating tab entries.

**Fix:** Extend `source_config.json` tab schema with `worksheet_title_by_year`:

```json
{
    "canonical_name": "Products",
    "worksheet_title": "Products 302 + 602",
    "worksheet_title_by_year": {
        "2023": "Products",
        "2024": "Products 302 + 602",
        "2025": "Products 302 + 602"
    }
}
```

`pull_bundle` resolves title via `worksheet_title_by_year[source_bundle_year]` if present, falls back to `worksheet_title`.

**Files:**
- Modify: `connectors/contracts.py` — update source_config schema
- Modify: `profiler/management/commands/pull_bundle.py` — resolve year-specific titles
- Modify: `connectors/google_provider.py` — pass resolved title

### #46: First-class multi-year corpus support

**Problem:** Labelling source config requires one tab entry per (year, tab) pair — 45+ entries for a 4-year corpus.

**Fix:** Extend `source_config.json` with top-level `years` mapping:

```json
{
    "provider": "google_sheets",
    "source_id": "farm_operations",
    "years": {
        "2023": {"spreadsheet_id": "1abc...", "source_bundle_year": 2023},
        "2024": {"spreadsheet_id": "1def...", "source_bundle_year": 2024}
    },
    "tabs": [...]
}
```

When `years` is present, `pull_bundle` iterates over each year, resolving `spreadsheet_id` per-year. `source_bundle_year` becomes a default injected into each tab's `default_values`. Output paths become `{year}/{slug}.csv`.

**Files:**
- Modify: `connectors/contracts.py` — update source_config schema
- Modify: `profiler/management/commands/pull_bundle.py` — year iteration logic
- Modify: `connectors/google_provider.py` — year-aware spreadsheet resolution

### #43: Auto-generate source_config

**Problem:** Building `source_config.json` requires hand-assembling 200+ lines of Python.

**Fix:** New management command `generate_source_config`:
- Reads `in_scope_workbook_index_*.json` (spreadsheet IDs per year)
- Reads contract YAML (required headers, column maps, import_config)
- Reads optional `tab_selection_*.json` / `column_selection_*.json`
- Emits `source_config.json` with all tab entries pre-filled
- Includes `worksheet_title_by_year` when year-specific titles are detected

**Files:**
- Create: `workbook/management/commands/generate_source_config.py`
- Create: `workbook/tests/test_generate_source_config.py`

---

## L5: Scaffold/Deploy (Issues #42, #47, #49, #54)

### #42: Copy run_import.sh during scaffold

**Problem:** The scaffolded Makefile references `scripts/run_import.sh` but the script isn't copied into the product repo.

**Fix:** In `scripts/new_product.py`, copy `migration-workbench/scripts/run_import.sh` into `<product>/scripts/run_import.sh`.

**Files:**
- Modify: `scripts/new_product.py` — add file copy step

### #47: Production data loading path

**Problem:** No Makefile target or documented workflow for loading imported data into production.

**Fix:** Add `load-data` and `push-data` Makefile targets:

```makefile
DATA_DIR ?= example_data
load-data:
	$(MANAGE) import_core $(DATA_DIR) --summary-json build/import-summary.json

push-data:
	gzip -c db.sqlite3 | flyctl ssh console -a $(FLY_APP) -C "gunzip > /data/db.sqlite3"
```

Also update `new_product.py` scaffold template with these targets.

**Files:**
- Modify: `Makefile` — add `load-data` and `push-data` targets
- Modify: `scripts/new_product.py` — add targets to scaffold template

### #49: Stale initial migration handling

**Problem:** After `manage.py startapp core` creates `0001_initial.py`, regenerating models and re-running `makemigrations` detects no changes because the old migration hash is recorded in `django_migrations`.

**Fix:** In `new_product.py` scaffold:
- Delete the auto-created `0001_initial.py` migration after `startapp`
- Add a Makefile target `reset-migrations` that removes all migration files and re-runs `makemigrations`
- Document: `make generate-models` → `make reset-migrations` → `make migrate`

**Files:**
- Modify: `scripts/new_product.py` — delete initial migration, add Makefile target

### #54: Re-run admin after contract hardening

**Problem:** Users who run `make generate` before pulling a bundle get admin without manifest hints, and no reminder to regenerate.

**Fix:**
1. Add Makefile target `generate-all` that runs the pipeline in order:
   ```makefile
   generate-all: generate-models generate-view-manifest generate-admin generate-import
   ```
2. In `generate_admin`, when `--manifest` is not provided, emit a warning suggesting re-running after `pull-bundle` and `generate-view-manifest`.

**Files:**
- Modify: `Makefile` — add `generate-all` target
- Modify: `workbook/management/commands/generate_admin.py` — add warning

---

## L6: Date Parsing (Issue #45)

### #45: Additional date formats in parse_iso_date

**Problem:** `parse_iso_date` rejects `M/D`, `M-D-YY`, and `M-D-YYYY` formats common in spreadsheets.

**Fix:** Formalize the ad-hoc fix:
- Add `%m/%d` (month/day without year): parse with `datetime.strptime(cleaned, "%m/%d")` which defaults to 1900, then replace year with `datetime.now().year`
- Add `%m-%d-%y` and `%m-%d-%Y`
- Add `%-m/%-d/%Y` and `%-m/%-d/%y` variants where single-digit months/days are accepted (Python's `strptime` on Linux supports `%-m` but this is platform-dependent; instead, zero-pad the input if needed)
- Add exhaustive tests covering all format variants with edge cases (leap years, single-digit months, Feb 29, etc.)

**Files:**
- Modify: `importer/parsing.py` — extend `parse_iso_date`
- Modify: `importer/tests/test_parsing.py` — add comprehensive date format tests

---

## Dependency Graph

```
L0: Connector (#40, #41, #48)
 ├── L1: Profiler (#32, #33, #38)
 │    └── L2: Schema (#34, #35, #36, #37, #39)
 │         ├── L3: Codegen (#44, #50, #51, #52)
 │         └── L4: Multi-year (#46, #55, #43) ← also depends on L0
 └── L5: Scaffold (#47 — uses L0 throttling)

L6: Date parsing (#45) — independent, can land in any layer
L5: Scaffold (#42, #49, #54) — partially independent of L0-L4
```

## Ad-hoc Fixes to Formalize

The current working tree has two modified files that need to be committed as proper implementations of L0 and L6:

1. `connectors/google_sheets.py` — Replace the ad-hoc `_throttle()` with `SheetsThrottle` class, remove `quote()` calls → L0
2. `importer/parsing.py` — Extend with proper tests and year-defaulting for `%m/%d` → L6

These existing changes should be preserved as starting points, not discarded.