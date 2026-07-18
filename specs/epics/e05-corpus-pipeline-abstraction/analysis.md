# e05 — Corpus Pipeline Abstraction: Shared Pattern Analysis

**Analyzed files:**
- `profiler/tools/cohort_corpus.py` (1958 lines — Google Sheets cohort corpus)
- `profiler/tools/coda_corpus.py` (1003 lines — Coda corpus)

**Analysis date:** 2026-07-16

---

## 1. Pipeline phase comparison

Both implementations follow the same seven-phase pipeline structure with nearly
identical phase boundaries:

| # | Phase | Sheets (`cohort_corpus`) | Coda (`coda_corpus`) |
|---|-------|--------------------------|----------------------|
| 1 | **Discovery** | Walk Drive folder tree; list workbooks and their tabs | List all tables in each doc; capture row/col metadata |
| 2 | **Indexing** | Filter by in-scope workbook codes via regex; extract year from folder/filename | Split into base tables vs views; mark views as non-importable |
| 3 | **Broad profile** | List tabs for every in-scope spreadsheet | Fetch column metadata for every base table |
| 4 | **Scoring / shortlist** | Heuristic score by row/col counts, name keywords, domain context | Heuristic score by row/col counts, name keywords |
| 5 | **Selection** | Top N per workbook code; override add/remove/replace | Top N per doc; override add/remove/replace |
| 6 | **Deep profile** | Fetch tab grid via Sheets API + `summarize_tab` | `summarize_coda_table` per selected table |
| 7 | **Column candidates** | Score headers by domain keywords, formula density | Score columns by domain keywords, relation types, formula presence |
| 8 | **Artifact output** | Date-stamped JSON + Markdown summary | Date-stamped JSON |

Both write all intermediate artifacts as date-stamped JSON files under `out_dir/`
with non-destructive naming.

---

## 2. Shared interface surface (candidates for abstraction)

### 2.1 Scoring functions — nearly identical signature pattern

```python
# cohort_corpus.py
def score_tab(title, rows, cols, *, tab_score_heuristics=None,
              column_formula_patterns=None, domain_context=None) -> tuple[int, list[str], dict]

# coda_corpus.py
def score_table(table_name, row_count, col_count, *, table_score_heuristics=None) -> tuple[int, list[str]]
```

**Differences:**
- Sheets returns a three-element tuple (score, reasons, breakdown_dict); Coda returns (score, reasons).
- Sheets has `column_formula_patterns` and `domain_context` parameters; Coda does not.
- Sheets has much richer keyword matching (combo tokens, exclude patterns, expansion-formula penalty).

**Abstraction possible:** A `ScoreFn` protocol accepting `(name, row_count, col_count, heuristics) → (score, reasons)` where provider-specific enrichments are injected via the heuristics dict.

### 2.2 Selection auto-pick — same algorithm, different grouping key

```python
# cohort_corpus.py
def auto_select_tabs(shortlist, *, per_workbook=3, per_code_overrides=None, score_cutoff=None) -> tuple[dict[str, list[str]], dict[str, list[dict]]]

# coda_corpus.py
def auto_select_tables(shortlist, *, per_doc=5) -> dict[str, list[str]]
```

**Differences:**
- Grouping key: `workbook_code` vs `doc_name`.
- Coda version is simpler: no overrides, no score cutoff, no per-grouping detail dicts.
- Both group, sort by score descending, and return `{key: [names]}`.

**Abstraction possible:** `select_top(shortlist, group_key, per_limit) → dict[str, list[str]]` where group_key is a callable or field name. Provider complexity variations (cutoffs, per-group overrides) can be passed as optional config.

### 2.3 Selection override logic — identical pattern, different domain vocabulary

```python
# cohort_corpus.py
TABLE_SELECTION_OVERRIDE_KEYS = frozenset({"add", "remove", "replace", "tabs"})
def apply_tab_selection_overrides(approved_tabs, overrides) -> dict[str, list[str]]

# coda_corpus.py
TABLE_SELECTION_OVERRIDE_KEYS = frozenset({"add", "remove", "replace", "tables"})
def apply_table_selection_overrides(approved_tables, overrides) -> dict[str, list[str]]
```

**Differences:**
- Only the constant key name differs (`"tabs"` vs `"tables"`).
- Error message check IDs differ (`PROFILER-OVERRIDE-001` vs `PROFILER-CODA-001`).
- Implementation is line-for-line identical (same validation logic, same merge rules).
- Coda uses `doc_name` as outer key; Sheets uses `workbook_code`.

**Abstraction possible:** A single generic `apply_selection_overrides(approved, overrides, item_key="tabs", check_id_prefix="PROFILER")`.

### 2.4 Column candidate derivation — similar intent, different provider context

```python
# cohort_corpus.py
def derive_column_candidates(*, workbook_code, year, spreadsheet_id, tab_title,
                             payload, column_score_heuristics=None, domain_context=None) -> list[dict]

# coda_corpus.py
def derive_column_candidates(*, doc_name, table_name, summary,
                             column_score_heuristics=None) -> list[dict]
```

**Differences:**
- Sheets passes a `raw + summary` payload dict; Coda passes a pre-digested `summary` dict.
- Sheets context includes `workbook_code`, `year`, `spreadsheet_id`; Coda has `doc_name`.
- Coda adds relation/reference scoring; Sheets adds formula-rich-tab boost.
- Both produce the same `proposed_canonical_field` via identical regex.
- Both return `list[dict]` with similar keys (`proposed_canonical_field`, `priority_score`, `priority_reasons`, `evidence`).

**Abstraction possible:** Canonical field name generation is identical and extractable. Domain keyword scoring is identical. Formula/relation scoring is provider-specific. The `Evidence` dict shape needs standardisation.

### 2.5 Column enrichment — same three categories, different code structure

| Enrichment | Sheets | Coda |
|-----------|--------|------|
| Computed field detection | `enrich_computed_fields()` separate function | Inline in `enrich_coda_columns()` |
| FK target suggestion | `enrich_fk_candidates()` separate function | Inline in `enrich_coda_columns()` |
| Import key candidate | `enrich_import_key_candidates()` separate function | Inline in `enrich_coda_columns()` |

**Differences:**
- Sheets has four separate functions (computed, fk, import_key, entity_groupings).
- Coda has one combined function `enrich_coda_columns()` that also adds high-uniqueness detection.
- FK detection: Sheets uses `_ENTITY_KEYWORDS` + cross_sheet_refs; Coda uses `ref_tables_seen` + `is_relation_type`.
- Import key: Sheets uses `_IDENTIFIER_SUFFIXES` + `_IDENTIFIER_NAMES` (shared constants); Coda adds high-uniqueness heuristic.
- `is_computed` detection: Sheets checks formula pattern strings; Coda checks `has_formula` boolean field.

**Abstraction possible:**
- Shared: import key detection via `_IDENTIFIER_SUFFIXES`/`_IDENTIFIER_NAMES` (already shared constants).
- Provider-specific: computed detection, FK target resolution.
- Each enrichment becomes a pluggable hook the adapter implements.

### 2.6 De-duplication and column selection — identical algorithm

Both implementations:
1. Deduplicate candidates by `(group_key, tab/table_name, proposed_canonical_field)` — keep highest `priority_score`.
2. Sort by descending `priority_score` + group identifiers.
3. Filter by `column_min_score`.

The deduplication tuple differs only in the provider key (`workbook_code` vs `doc_name`).

### 2.7 Write JSON utility — identical

Both define `write_json(path, payload)` with exactly the same implementation:
- `path.parent.mkdir(parents=True, exist_ok=True)`
- `path.write_text(json.dumps(payload, indent=2), encoding="utf-8")`

(Coda adds `default=str` to handle non-serializable types.)

### 2.8 Slug maker — nearly identical

```python
# cohort_corpus.py
def make_slug(text):
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return slug[:50] or "tab"

# coda_corpus.py
def make_slug(text):
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return slug[:50] or "table"
```

Only the fallback suffix differs (`"tab"` vs `"table"`).

---

## 3. Operations unique to each provider

### 3.1 Sheets-only (`cohort_corpus.py`)

| Operation | Function | Reason provider-specific |
|-----------|----------|-------------------------|
| Drive folder tree walk | Part of `run_cohort_corpus()`, calls `walk_folder()` from `profile_drive_folder` | Google Drive folder hierarchy; needs `drive_service` + `sheets_service` |
| Regex-based code/year extraction | `build_cohort_corpus_index()` | Workbook codes and years embedded in filenames; Coda uses doc IDs from config |
| Per-workbook heuristic overrides | `select_tabs_from_inventory()`, `per_workbook_heuristic_overrides` | Cohort corpus has multiple workbooks per run, each may need different scoring |
| Tab classification | `select_tabs_from_inventory()` delegates to `tab_classifier.classify_tabs_batch()` | No Coda equivalent |
| Year-aware deduplication | `deduplicate_index_records()` + dedup trace | Cohort corpus indexes same tab across multiple years; Coda docs lack this dimension |
| HTTP 429 cooldown/retry | `run_cohort_corpus()` deep phase | Google Sheets API rate limiting; Coda uses a different API with different limits |
| Markdown summary rendering | `_render_corpus_summary()` | Sheets-specific output format |
| Column profiling | `compute_column_profiles()` — detailed `ColumnProfile` dataclass with formula pattern analysis | Sheets has richer formula data (expansion_formula, row_formula patterns) |
| Cache-on-disk deep reuse | `run_cohort_corpus()` — `reuse_cached_deep` / `skip_existing_deep` | Phase 3 resume logic with year-aware tab validation |
| Domain context integration | `select_tabs_from_inventory()` via `DomainContext` | Domain context provides glossary expansion and year-scope for coverage bonuses |

### 3.2 Coda-only (`coda_corpus.py`)

| Operation | Function | Reason provider-specific |
|-----------|----------|-------------------------|
| Doc resolution | `load_coda_docs_from_config()` | Coda docs identified by doc ID/URL; Sheets uses Drive folder ID |
| View detection + base/views split | `build_coda_table_index()` | Coda distinguishes tables from views; Sheets has no view concept |
| Relationship edge collection | `collect_relationship_edges_from_summary()` → `finalize_relationship_summary()` | Coda columns have `ref_tables_seen` for cross-table refs; Sheets lacks native relation metadata |
| Canvas/page text export | `build_canvas_artifact_for_doc()` | Coda has page content API; Sheets has no page/rich-text concept |
| Row count backfill | `enrich_table_row_counts()` | Coda list API sometimes omits rowCount, needs per-table detail requests |
| Formula detection via API | `column_has_formula()` from `connectors.coda_source` | Coda API provides `has_formula` boolean; Sheets infers via pattern analysis |

---

## 4. Adapter shape proposal

Based on the analysis above, the common abstraction should expose:

```python
class CorpusAdapter(Protocol):
    """Provider-specific adapter for one step of the corpus pipeline."""

    # --- Phase 1-2: Discovery + Indexing ---
    def discover(self, config: dict, **kwargs) -> DiscoveryPayload
    def build_index(self, discovery_payload, config: dict) -> list[IndexRecord]

    # --- Phase 3: Broad profile ---
    def broad_profile(self, index_records, config: dict) -> BroadProfileResult

    # --- Phase 4-5: Scoring + Selection ---
    def score_item(self, name, row_count, col_count, *, heuristics=None, **kwargs) -> tuple[int, list[str]]
    def auto_select(self, shortlist, *, per_limit, **kwargs) -> dict[str, list[str]]
    def apply_overrides(self, approved, overrides) -> dict[str, list[str]]

    # --- Phase 6: Deep profile ---
    def deep_profile_one(self, index_record, item_name, config: dict) -> DeepProfileResult

    # --- Phase 7: Column candidates ---
    def derive_column_candidates(self, *, item_name, summary, heuristics=None) -> list[dict]
    def enrich_columns(self, columns) -> None

    # --- Utilities ---
    @staticmethod
    def make_slug(text: str) -> str
    @staticmethod
    def write_json(path, payload)
```

### 4.1 What stays shared (in `CorpusPipeline`)

- Orchestration loop (discover → index → broad → score → select → deep → candidates → artifacts)
- JSON artifact output naming scheme (date-stamped, non-destructive)
- Column deduplication + final selection logic
- Heuristics normalization infrastructure
- `write_json()` utility
- Shared import-key detection constants (`_IDENTIFIER_SUFFIXES`, `_IDENTIFIER_NAMES`)

### 4.2 What stays provider-specific (in adapter)

- API client setup and authentication
- Discovery traversal logic (Drive folder tree vs Coda doc list)
- Tab/table metadata extraction (regex patterns vs API fields)
- Deep profile fetch + summarize (Sheets `fetch_tab_grid`/`summarize_tab` vs `summarize_coda_table`)
- Rate limiting / quota management (429 handling unique to Sheets)
- Relationship/canvas exports (unique to Coda)

### 4.3 Key abstraction boundary decisions

1. **Scoring heuristics** should remain opaque dicts passed to the adapter, not a common schema. Sheets has `operational_weight`, `expansion_formula_penalty`, etc. that Coda would never use.

2. **Index records** should be `dict` with provider-specific keys, not a fixed dataclass. The pipeline only needs the `group_key` field plus whatever the adapter's score/select functions need.

3. **Resume modes** are inherently provider-specific (Sheets has three-phase resume; Coda has one). The pipeline exposes `resume_mode: str` and leaves validation to the adapter.

4. **Phase skipping** (`stop_before_deep`) is a universal pipeline concern and should live in the shared orchestrator, not each adapter.

---

## 5. Proposed module layout

```
profiler/pipeline/
├── __init__.py            # Re-export public API
├── protocol.py            # CorpusAdapter Protocol class
├── pipeline.py            # CorpusPipeline orchestrator (run method + shared artifact logic)
├── adapters/
│   ├── __init__.py
│   ├── sheets.py          # SheetsCorpusAdapter (moved from cohort_corpus.py)
│   └── coda.py            # CodaCorpusAdapter (moved from coda_corpus.py)
├── selection.py           # Shared: auto_select, apply_overrides, dedup+filter
├── scoring.py             # Shared: score helpers, heuristics normalization
└── enrichment.py          # Shared: import key detection (IDENTIFIER_SUFFIXES/NAMES)
```

The legacy module paths keep their public API:
- `profiler.tools.cohort_corpus.run_cohort_corpus` → delegates to pipeline
- `profiler.tools.coda_corpus.run_coda_corpus` → delegates to pipeline

---

## 6. Migration risk assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Sheets three-phase resume tightly coupled to Drive discovery | High | Adapter exposes `resume_mode` enum; pipeline dispatches accordingly |
| Coda enrichment merges 3 concerns into 1 function | Medium | Split into `enrich_computed` / `enrich_fk` / `enrich_import_key`; call from adapter |
| `_corpus_regex_from_config()` is Sheets-only | Low | Keep in adapter; pipeline doesn't need regex compilation |
| 429 handling is Sheets-only | Low | Keep in adapter; pipeline provides generic retry signal the adapter can raise |
| Coda canvas export is fully provider-specific | Low | Optional phase; adapter indicates support via `supports_canvas: bool` |

**Overall migration difficulty:** Medium. The seven-phase pipeline is the same
structure; the differences are in parameter shapes and provider-specific
sub-steps. The adapter protocol cleanly captures the boundary.
