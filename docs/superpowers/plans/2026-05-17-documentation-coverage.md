# Documentation Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Achieve 100% PEP 257 docstring coverage, add 5 standalone narrative/reference docs, and enforce coverage via CI.

**Architecture:** Three parallel tracks — Track 1 fills docstring gaps in priority order (profiler → connectors → deployment → boilerplate), Track 2 writes standalone docs (schema-contract, pull-bundle, tutorial, contributing, troubleshooting), Track 3 adds CI enforcement (interrogate config, Makefile target, CI step, docs/INDEX.md).

**Tech Stack:** Python 3.11+, Django 5.x, interrogate for coverage checking, Google-style docstrings.

---

## Track 1: PEP 257 Docstring Fill

### Task 1: Profiler management commands — module + Command class + handle() docstrings

**Files:**
- Modify: `profiler/management/commands/pull_bundle.py`
- Modify: `profiler/management/commands/profile_preflight.py`
- Modify: `profiler/management/commands/snapshot_bundle.py`
- Modify: `profiler/management/commands/profile_cohort_corpus.py`
- Modify: `profiler/management/commands/profile_coda_preflight.py`
- Modify: `profiler/management/commands/profile_coda_canvas.py`
- Modify: `profiler/management/commands/profile_coda_corpus.py`

These 7 files have no module docstring, no Command class docstring, and no handle()/add_arguments() method docstrings. Their `help` attribute already serves as the class docstring text. The pattern for each is:

```python
"""<One-sentence description of what the management command does.>

Artifacts are written to ``--out-dir`` (default ``data/profile_snapshots/``).
"""
```

Add a Command class docstring that repeats the `help` text:

```python
class Command(BaseCommand):
    """<Same text as help attribute>."""
    help = "<same text>"
```

Add an `add_arguments` docstring:

```python
    def add_arguments(self, parser):
        """Add command-line arguments for <command name>."""
```

Add a `handle` docstring:

```python
    def handle(self, *args, **options):
        """Execute the <command name> pipeline.

        Reads the config specified by ``--config``, connects to the
        <provider> API, and writes profiling artifacts to ``--out-dir``.
        """
```

Specific texts for each file:

- **pull_bundle.py**: Module: `"""Fetch provider tabs and normalize them into a local bundle directory."""` / Command: `"""Fetch provider tabs and normalize them into a bundle."""` / handle: `"""Execute the pull-bundle pipeline. Reads source config from ``--config``, routes through the configured provider adapter, normalizes rows, and writes CSV + ``manifest.json`` to ``--output-dir``."""`

- **profile_preflight.py**: Module: `"""Validate profiling auth/runtime prerequisites (credentials + optional folder access)."""` / Command: `"""Validate profiling auth/runtime prerequisites (credentials + optional folder access)."""` / handle: `"""Execute the preflight check. Verifies Google Sheets/Drive credentials and optionally tests folder access."""

- **snapshot_bundle.py**: Module: `"""Normalize local tab snapshots into an offline bundle directory."""` / Command: `"""Normalize local tab snapshots into an offline bundle."""` / handle: `"""Execute the snapshot-bundle pipeline. Reads local CSV/JSON snapshots from ``--config`` and normalizes them into a bundle directory at ``--output-dir``."""`

- **profile_cohort_corpus.py**: Module: `"""Run cohort-corpus profiling pipeline for config-driven workbook sets."""` / Command: `"""Run cohort-corpus profiling pipeline for config-driven workbook sets."""` / handle: `"""Execute the cohort-corpus profiling pipeline. Discovers, scores, and profiles workbook tabs across multiple years, writing artifacts to ``--out-dir``."""`

- **profile_coda_preflight.py**: Module: `"""Validate Coda API token and optional doc access (read-only)."""` / Command: `"""Validate Coda API token and optional doc access (read-only)."""` / handle: `"""Execute the Coda preflight check. Verifies the CODA_API_TOKEN and optionally tests access to a specific Coda document."""`

- **profile_coda_canvas.py**: Module: `"""Extract plain text from Coda canvas pages (content API) or optional markdown export."""` / Command: `"""Extract plain text from Coda canvas pages (content API) or optional markdown export."""` / handle: `"""Execute the Coda canvas extraction pipeline. Reads pages from the configured Coda document and writes extracted content to ``--out-dir``."""`

- **profile_coda_corpus.py**: Module: `"""Run multi-doc Coda profiling pipeline (discovery → index → broad → deep → column candidates)."""` / Command: `"""Run multi-doc Coda profiling pipeline (discovery → index → broad → deep → column candidates)."""` / handle: `"""Execute the Coda corpus profiling pipeline. Orchestrates discovery, indexing, broad profiling, deep profiling, and column candidate derivation for each configured Coda document."""`

- [ ] **Step 1: Add docstrings to the 7 management command files listed above**

Edit each file to add: module docstring (immediately after the module-level comment if any, before imports), Command class docstring, `add_arguments` docstring, `handle` docstring using the specific texts provided.

- [ ] **Step 2: Run tests to verify nothing broke**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
.venv/bin/python -m pytest profiler/tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add profiler/management/commands/pull_bundle.py profiler/management/commands/profile_preflight.py profiler/management/commands/snapshot_bundle.py profiler/management/commands/profile_cohort_corpus.py profiler/management/commands/profile_coda_preflight.py profiler/management/commands/profile_coda_canvas.py profiler/management/commands/profile_coda_corpus.py
git commit -m "docs: add docstrings to profiler management commands (batch 1)"
```

---

### Task 2: Profiler management commands — files with standalone functions

**Files:**
- Modify: `profiler/management/commands/profile_tab.py`
- Modify: `profiler/management/commands/profile_drive_folder.py`
- Modify: `profiler/management/commands/profile_coda_doc.py`
- Modify: `profiler/management/commands/profile_coda_table.py`
- Modify: `profiler/management/commands/scan_formula_patterns.py`
- Modify: `profiler/management/commands/scan_coda_formula_columns.py`

These files have standalone helper functions in addition to the Command class, all undocumented. Add module, class, and method docstrings as in Task 1, plus docstrings for each standalone function.

**profile_tab.py** functions (add after `def` line, before body):

- `list_tabs(sheets_service, spreadsheet_id)` → `"""List sheet metadata dicts for the given spreadsheet."""`
- `fetch_tab_grid(sheets_service, spreadsheet_id, tab_title)` → `"""Fetch the full grid data for a specific tab. Returns the Sheets API response dict for the requested range."""`
- `formula_skeleton(formula)` → `"""Reduce a formula string to its function name and argument structure, stripping cell references."""`
- `extract_references(formula)` → `"""Extract cross-sheet and cross-workbook references from a formula string. Returns a dict with keys ``sheets`` and ``workbooks``."""`
- `summarize_tab(tab_payload, focus_col_letter)` → `"""Produce a structured summary dict from a tab grid payload, including column profiles and formula analysis. Optionally focus on a specific column identified by ``focus_col_letter``."""`
- `render_markdown(summary)` → `"""Render a tab summary dict as a Markdown string suitable for writing to a profile artifact file."""`
- Module: `"""Profile one workbook tab or list workbook tabs (Google Sheets)."""` / Command: `"""Profile one workbook tab, or list workbook tabs."""` / handle: `"""Execute the tab profiling pipeline. Connects to Sheets API, fetches grid data, analyzes formulas and structure, and writes a Markdown + JSON profile artifact."""`

**profile_drive_folder.py** functions:

- `list_children(drive_service, folder_id)` → `"""List direct children of a Drive folder, returning file resource dicts."""`
- `list_tabs(sheets_service, spreadsheet_id)` → `"""List sheet metadata dicts for the given spreadsheet."""`
- `walk_folder(drive_service, sheets_service, folder_id, *, include_tabs, max_depth)` → `"""Recursively walk a Drive folder tree, building a nested dict of folders and spreadsheet metadata. Returns a tree dict suitable for ``render_tree``."""`
- `render_tree(node, *, name, heading_level)` → `"""Render a folder tree dict as a Markdown list with heading levels."""`
- Module: `"""Enumerate a Drive folder tree and list spreadsheet tabs."""` / Command: `"""Enumerate a Drive folder tree and list spreadsheet tabs."""` / handle: `"""Execute the drive folder profiling pipeline. Walks the specified folder tree, collecting spreadsheet and tab metadata, and renders a Markdown tree artifact."""`

**profile_coda_doc.py** functions:

- `summarize_table_meta(table, columns)` → `"""Produce a summary dict for a Coda table from its metadata and column list."""`
- `render_doc_tree(doc_meta, tables_payload)` → `"""Render a Coda document's tables and pages as a Markdown tree string."""`
- Module: `"""Enumerate tables and views in a Coda doc (and optionally column metadata)."""` / Command: `"""Enumerate tables and views in a Coda doc (and optionally column metadata)."""` / handle: `"""Execute the Coda doc profiling pipeline. Connects to the Coda API, enumerates tables and pages, and writes a Markdown tree + JSON artifact."""`

**profile_coda_table.py** functions:

- `_table_meta_for_id(tables, table_id)` → `"""Look up a table metadata dict by table ID. Returns ``None`` if not found."""`
- `_parent_table_summary(meta)` → `"""Extract a summary dict from a parent table's metadata, or ``None`` if no parent."""`
- `summarize_coda_table(...) → `"""Produce a structured summary dict from a Coda table, including column profiles, row counts, and formula analysis."""`
- `render_markdown(summary)` → `"""Render a Coda table summary dict as a Markdown string."""`
- Module: `"""Profile one Coda table or view, or list tables in a doc."""` / Command: `"""Profile one Coda table or view, or list tables in a doc."""` / handle: `"""Execute the Coda table profiling pipeline. Fetches rows and columns from the specified table, analyzes formula structure and data types, and writes a Markdown + JSON profile artifact."""`

**scan_formula_patterns.py** functions:

- `execute_with_retry(request, max_retries)` → `"""Execute a Google API request with exponential backoff retry on transient failures."""`
- `load_patterns(config)` → `"""Load regex pattern tuples from a scan config dict. Returns list of ``(name, compiled_pattern)`` pairs."""`
- `load_workbooks(config)` → `"""Load workbook ID/title pairs from a scan config dict."""`
- `scan_workbook(svc, spreadsheet_id, patterns)` → `"""Scan a single workbook for cells matching the given regex patterns. Returns a list of match dicts."""`
- Module: `"""Scan configured workbooks for formula regex patterns."""` / Command: `"""Scan configured workbooks for formula regex patterns."""` / handle: `"""Execute the formula scan pipeline. Reads workbook and pattern config, scans each workbook cell for pattern matches, and writes results to ``--out``."""`

**scan_coda_formula_columns.py** functions:

- `load_coda_workbooks(session, config)` → `"""Load Coda doc ID/name pairs from the scan config. Returns list of ``(name, doc_id)`` tuples."""`
- `scan_doc_for_formula_columns(session, doc_id, patterns)` → `"""Scan a Coda document's columns for formula text matching the given regex patterns. Returns a list of match dicts."""`
- Module: `"""Scan Coda docs for column-level formula text matching regex patterns."""` / Command: `"""Scan Coda docs for column-level formula text matching regex patterns."""` / handle: `"""Execute the Coda formula scan pipeline. Connects to the Coda API, scans column formula text for pattern matches, and writes results to ``--out``."""`

- [ ] **Step 1: Add docstrings to all 6 management command files with standalone functions**

Edit each file: add module docstring, Command class docstring, add_arguments docstring, handle docstring, and per-function docstrings as specified above.

- [ ] **Step 2: Run tests**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
.venv/bin/python -m pytest profiler/tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add profiler/management/commands/profile_tab.py profiler/management/commands/profile_drive_folder.py profiler/management/commands/profile_coda_doc.py profiler/management/commands/profile_coda_table.py profiler/management/commands/scan_formula_patterns.py profiler/management/commands/scan_coda_formula_columns.py
git commit -m "docs: add docstrings to profiler commands with standalone helpers (batch 2)"
```

---

### Task 3: Profiler tools — coda_corpus.py and cohort_corpus.py

**Files:**
- Modify: `profiler/tools/coda_corpus.py`
- Modify: `profiler/tools/cohort_corpus.py`
- Modify: `profiler/management/commands/_config_helpers.py`
- Modify: `profiler/contracts.py`

**coda_corpus.py** undocumented functions (10):

- `make_slug(text)` → `"""Convert arbitrary text into a filesystem-safe slug (lowercase alphanumeric + underscores, max 50 chars). Falls back to ``"table"`` if empty."""`
- `score_table(table_name, row_count, col_count, *, table_score_heuristics)` → `"""Heuristically score a Coda table for import priority. Returns ``(score, reasons)`` where reasons is a list of descriptive labels."""`
- `build_coda_table_index(discovery_docs)` → `"""Split raw discovery data into base tables and views, marking views as non-importable. Returns a dict with ``base_tables`` and ``views`` keys."""`
- `select_tables_from_inventory(base_tables, *, min_final_score, table_score_heuristics)` → `"""Score, filter, and sort base tables by heuristic score. Assigns confidence labels and filters by ``min_final_score``."""`
- `auto_select_tables(shortlist, *, per_doc)` → `"""Group shortlisted tables by doc, sort by score descending, and pick the top ``per_doc`` per doc. Returns ``{doc_name: [table_names]}``."""`
- `derive_column_candidates(*, doc_name, table_name, summary, column_score_heuristics)` → `"""Score each column in a Coda table summary for domain relevance. Produces a list of candidate dicts with canonical field name proposals."""`
- `write_json(path, payload)` → `"""Create parent directories if needed and write *payload* as pretty-printed JSON to *path*."""`
- `load_coda_docs_from_config(session, config)` → `"""Resolve each doc entry in the corpus config to a ``(display_name, doc_id)`` pair. Raises ``CommandError`` if any entry lacks a resolvable doc ID."""`
- `collect_relationship_edges_from_summary(doc_name, doc_id, from_table_id, from_table_name, summary)` → `"""Scan a table summary's columns for cross-table relation references. Returns a list of edge dicts linking source columns to target tables."""`
- `finalize_relationship_summary(edges)` → `"""Deduplicate raw relationship edges by ``(doc_id, from_table, to_table)`` and return a summary dict with total/unique counts."""`

**cohort_corpus.py** undocumented functions (7):

- `compute_column_profiles(summary, return_patterns_by_slug)` → `"""Build ``ColumnProfile`` instances from a tab summary, classifying each column's formula pattern, type, and section-header status. Returns a list of profiles or a slug-to-pattern dict."""`
- `select_tabs_from_inventory(index_records, inventory_rows, *, min_final_score, tab_score_heuristics)` → `"""Score, aggregate across years, and filter inventory tabs by final score. Applies coverage bonus for tabs appearing in 3+ years. Returns a sorted shortlist."""`
- `auto_select_tabs(tab_shortlist, *, per_workbook, per_code_overrides)` → `"""Group shortlisted tabs by workbook code, sort by score/occurrences, and pick the top N per workbook. Returns ``{workbook_code: [tab_titles]}``."""`
- `make_slug(text)` → `"""Convert arbitrary text into a filesystem-safe slug (lowercase alphanumeric + underscores, max 50 chars). Falls back to ``"tab"`` if empty."""`
- `derive_column_candidates(*, workbook_code, year, spreadsheet_id, tab_title, payload, column_score_heuristics)` → `"""Extract column headers from a raw sheet payload and score each by domain keywords and formula density. Returns a list of candidate dicts with canonical field name proposals."""`
- `write_json(path, payload)` → `"""Create parent directories if needed and write *payload* as pretty-printed JSON to *path*."""`
- `parse_tab_inventory_output(text)` → `"""Parse a text inventory format like ``[ 1] sheetId=123 rows=45 cols=6 TabName`` into structured dicts."""`

**_config_helpers.py**: Already has a docstring on its one function. Add module docstring:

```python
"""Shared configuration-loading helpers for profiler management commands."""
```

**contracts.py**: Add module docstring replacing the existing comment block. The file starts with comments about source_config. Replace with a proper module docstring:

```python
"""Live-source normalizer contract and structure schema version for bundle artifacts.

Defines ``LIVE_SOURCE_NORMALIZER_CONTRACT`` — the column/handler contract used
by the normalizer when processing live source data — and ``STRUCTURE_SCHEMA_VERSION``,
the version tag applied to ``structure.json`` bundle artifacts.
"""
```

- [ ] **Step 1: Add docstrings to coda_corpus.py, cohort_corpus.py, _config_helpers.py, and contracts.py**

- [ ] **Step 2: Run tests**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
.venv/bin/python -m pytest profiler/tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add profiler/tools/coda_corpus.py profiler/tools/cohort_corpus.py profiler/management/commands/_config_helpers.py profiler/contracts.py
git commit -m "docs: add docstrings to profiler tools and contracts (batch 3)"
```

---

### Task 4: Connectors — google_sheets.py

**Files:**
- Modify: `connectors/google_sheets.py`

Add module docstring:

```python
"""Google Sheets API helpers for spreadsheet row fetching, ID extraction, and Drive folder traversal.

Provides service-account credential helpers, spreadsheet/tab resolution, and
``SheetsThrottle`` for API rate limiting.
"""
```

Add docstrings to all public functions:

- `extract_drive_folder_id(value)` → `"""Extract a Drive folder ID from a URL or return the value unchanged if already an ID."""`
- `extract_spreadsheet_id(value)` → `"""Extract a spreadsheet ID from a URL or return the value unchanged if already an ID."""`
- `get_service_account_credentials(scopes=None)` → `"""Build Google service-account credentials from ``GOOGLE_SA_JSON`` or ``GOOGLE_APPLICATION_CREDENTIALS`` env vars. Optionally restrict to *scopes* (defaults to Sheets and Drive scopes)."""`
- `build_google_service(service_name, version, scopes)` → `"""Build an authenticated Google API service object for the given *service_name* and *version* using service-account credentials with *scopes*."""`
- `list_spreadsheets_in_folder(folder_id, drive_service)` → `"""List spreadsheet file resources in a Drive folder. Returns a list of file dicts with ``id`` and ``name``."""`
- `list_child_folder_ids(folder_id, drive_service)` → `"""List child folder IDs immediately under *folder_id* in Drive."""`
- `resolve_spreadsheet(tab, drive_service, folder_id, search_descendants)` → `"""Resolve a spreadsheet ID from a tab config dict. Tries ``tab.spreadsheet_id`` first, then ``tab.spreadsheet_url``, then folder+name search (optionally recursive)."""`
- `fetch_tab_rows(spreadsheet_id, worksheet_title, sheets_service, *, throttle)` → `"""Fetch all rows from a specific worksheet tab as a list of dicts keyed by header names. Uses *sheets_service* for the API call and optional *throttle* for rate limiting."""`
- `SheetsThrottle.__init__` → `"""Initialize throttle with an optional *min_interval* in seconds between requests."""`
- `SheetsThrottle.wait` → `"""Block until at least *min_interval* seconds have elapsed since the last call to ``wait``."""`

Also add docstrings to these private functions (for completeness):

- `_fill_merged_cell_headers(headers)` → `"""Fill ``None`` entries in a header row by carrying forward the last non-None value. Handles merged cells in Sheets header rows."""`
- `_extract_id_from_url(url, marker)` → `"""Extract the segment after *marker* from a URL path component."""`
- `_execute_with_retry(execute_fn, max_retries, base_delay)` → `"""Execute a Sheets API request with exponential backoff retry on transient failures."""`
- `fetch_sheet_structure_data(sheets_service, spreadsheet_id, worksheet_title, *, throttle)` → Already has a docstring.

- [ ] **Step 1: Add docstrings to google_sheets.py**

- [ ] **Step 2: Run tests**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
.venv/bin/python -m pytest connectors/tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add connectors/google_sheets.py
git commit -m "docs: add docstrings to connectors/google_sheets.py"
```

---

### Task 5: Connectors — coda.py and coda_source.py

**Files:**
- Modify: `connectors/coda.py`
- Modify: `connectors/coda_source.py`

**coda.py** — Add module docstring:

```python
"""Coda provider adapter implementing the ``ProviderAdapter`` interface.

``CodaAdapter`` fetches tab rows and structure from Coda documents via the
Coda API, normalizing them into the row/structure format expected by the
profiler and importer pipeline.
"""
```

Add class/method docstrings:

- `class CodaAdapter(ProviderAdapter)` → `"""Coda provider adapter for the profiler/importer pipeline."""`
- `CodaAdapter.__init__(self, config)` → `"""Initialize the adapter from a source config dict. Validates API token and resolves the document."""`
- `CodaAdapter.fetch_tab_rows(self, tab_config)` → `"""Fetch rows from a Coda table identified by *tab_config*. Returns a dict with ``rows`` and ``headers`` keys."""`
- `CodaAdapter._ensure_table_index(self)` → `"""Build an internal lookup index mapping table names to table metadata dicts."""`
- `CodaAdapter._resolve_table(self, tab_config)` → `"""Resolve a tab config entry to a Coda table, returning the table metadata dict."""`

**coda_source.py** — Add docstrings to undocumented public functions:

- `build_coda_session(api_token=None)` → `"""Build and return a ``requests.Session`` authenticated with the Coda API token. Falls back to the ``CODA_API_TOKEN`` environment variable if *api_token* is ``None``."""`
- `list_columns(session, doc_id, table_id)` → `"""List column metadata dicts for the given Coda table. Returns the API's column list response."""`
- `get_doc(session, doc_id)` → `"""Fetch document metadata for *doc_id* from the Coda API. Returns a dict with ``name``, ``id``, and other doc-level fields."""`
- `get_page_export_status(session, doc_id, page_id_or_name, request_id)` → `"""Poll the status of an async page export request. Returns the API status dict (``status`` key will be ``"complete"`` or ``"in_progress"``)."""`
- `column_has_formula(column)` → `"""Return ``True`` if the Coda *column* dict indicates the column has a formula."""`
- `formula_text(column)` → `"""Return the formula text from a Coda *column* dict, or an empty string if none."""`

Also add docstrings to private functions:

- `_cell_to_str(cell)` → `"""Convert a Coda cell value to a string, handling ``None``, lists, and rich text payloads."""`
- `_request_with_retry(session, method, url, *, params, json_body, max_retries)` → `"""Execute an HTTP request with exponential backoff on 429/5xx responses. Returns the parsed JSON response dict."""`
- `_doc_segment_from_url(url)` → `"""Extract the Coda document segment (``d{doc_id}``) from a Coda URL."""`

- [ ] **Step 1: Add docstrings to coda.py and coda_source.py**

- [ ] **Step 2: Run tests**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
.venv/bin/python -m pytest connectors/tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add connectors/coda.py connectors/coda_source.py
git commit -m "docs: add docstrings to connectors/coda.py and coda_source.py"
```

---

### Task 6: Connectors — google_provider.py

**Files:**
- Modify: `connectors/google_provider.py`

Add class/method docstrings:

- `class GoogleSheetsAdapter(ProviderAdapter)` → `"""Google Sheets provider adapter for the profiler/importer pipeline."""`
- `GoogleSheetsAdapter.__init__(self, config, throttle)` → `"""Initialize the adapter from a source config dict. Optionally accepts a ``SheetsThrottle`` instance for API rate limiting."""`
- `GoogleSheetsAdapter.fetch_tab_rows(self, tab_config)` → `"""Fetch rows from a Google Sheets tab identified by *tab_config*. Resolves the spreadsheet by ID, URL, or folder search, then fetches and normalizes rows.""" `

- [ ] **Step 1: Add docstrings to google_provider.py**

- [ ] **Step 2: Run tests**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
.venv/bin/python -m pytest connectors/tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add connectors/google_provider.py
git commit -m "docs: add docstrings to connectors/google_provider.py"
```

---

### Task 7: Deployment models and importer errors

**Files:**
- Modify: `deployment/models.py`
- Modify: `importer/errors.py`

**deployment/models.py** — Add module docstring and class docstring:

```python
"""Django models for deployment release tracking.

Stores ``ReleaseRecord`` instances recording each deploy's outcome, health
status, and metadata for the ``wb deploy`` lifecycle.
"""

class ReleaseRecord(models.Model):
    """Record of a deployment event: space, environment, release ID, and outcome.

    Used by the ``wb`` CLI to track deploy history and health checks per space/environment.
    """
```

**importer/errors.py** — Add module docstring (the file is a constant dict, no functions):

```python
"""Structured failure-signature ownership mapping for the import pipeline.

``FAILURE_SIGNATURE_OWNERSHIP`` maps error categories to their owning area,
team, severity, escalation path, and recovery instructions.
"""
```

- [ ] **Step 1: Add docstrings to deployment/models.py and importer/errors.py**

- [ ] **Step 2: Run tests**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
.venv/bin/python -m pytest deployment/tests importer/tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add deployment/models.py importer/errors.py
git commit -m "docs: add module docstrings to deployment/models and importer/errors"
```

---

### Task 8: Django boilerplate module docstrings

**Files:**
- Modify: `connectors/apps.py`, `connectors/models.py`, `connectors/views.py`, `connectors/admin.py`
- Modify: `importer/apps.py`, `importer/views.py`, `importer/admin.py`
- Modify: `profiler/apps.py`, `profiler/models.py`
- Modify: `workbook/apps.py`
- Modify: `deployment/apps.py`

Add one-liner module docstrings to each:

| File | Module docstring |
|------|-----------------|
| `connectors/apps.py` | `"""Django app configuration for the connectors package."""` |
| `connectors/models.py` | `"""Django models for the connectors package (placeholder)."""` |
| `connectors/views.py` | `"""Django views for the connectors package (placeholder)."""` |
| `connectors/admin.py` | `"""Django admin configuration for the connectors package (placeholder)."""` |
| `importer/apps.py` | `"""Django app configuration for the importer package."""` |
| `importer/views.py` | `"""Django views for the importer package (placeholder)."""` |
| `importer/admin.py` | `"""Django admin configuration for the importer package (placeholder)."""` |
| `profiler/apps.py` | `"""Django app configuration for the profiler package."""` |
| `profiler/models.py` | `"""Django models for the profiler package (placeholder)."""` |
| `workbook/apps.py` | `"""Django app configuration for the workbook package."""` |
| `deployment/apps.py` | `"""Django app configuration for the deployment package."""` |

- [ ] **Step 1: Add one-liner module docstrings to all 11 boilerplate files**

Insert the docstring as the first line of each file (before any imports).

- [ ] **Step 2: Run chassis-gate**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add connectors/apps.py connectors/models.py connectors/views.py connectors/admin.py importer/apps.py importer/views.py importer/admin.py profiler/apps.py profiler/models.py workbook/apps.py deployment/apps.py
git commit -m "docs: add module docstrings to Django boilerplate files"
```

---

## Track 2: Standalone Narrative & Reference Docs

### Task 9: docs/schema-contract.md

**Files:**
- Create: `docs/schema-contract.md`
- Read: `workbook/README.md` (for contract format details to extract)

Write the schema contract reference document with these sections:

1. **Introduction** — What a schema contract is, how it fits in the pipeline
2. **Contract versions** — v1.0 baseline, v1.1 enums/admin, v1.2 computed_fields/model_base/richer Meta, v1.3 import_config/source_tab null
3. **Top-level structure** — `models` list, global `meta`, `!include` composition
4. **Model definition** — `table_name`, `app_label`, `model_name`, `source_tab`, `fields`, `computed_fields`, `model_meta`, `admin`, `import_config`, `is_abstract`
5. **Field types** — `CharField`, `IntegerField`, `BooleanField`, `DateField`, `DateTimeField`, `DecimalField`, `ForeignKey`, `ManyToManyField`, `TextField` with supported options
6. **computed_fields** — rendered as `@property` methods
7. **model_meta** — `unique_together`, `ordering`, `verbose_name`, `verbose_name_plural`
8. **admin configuration** — `list_display`, `list_filter`, `search_fields`, `autocomplete_fields`, `list_editable`, `inlines`
9. **import_config** — `column_map`, `field_transforms`, `field_parsers`, `source_tab` override, `unique_on`, `tier`
10. **!include composition** — syntax, path resolution, cyclic include detection
11. **Version changelog** — which fields were added in each version

Reference `workbook/README.md` for the command reference and cross-link to it.

- [ ] **Step 1: Write docs/schema-contract.md**

- [ ] **Step 2: Verify the file renders correctly in Markdown**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
cat docs/schema-contract.md | head -5
```

Expected: file starts with `# Schema Contract Reference`.

- [ ] **Step 3: Commit**

```bash
git add docs/schema-contract.md
git commit -m "docs: add schema contract reference document"
```

---

### Task 10: docs/pull-bundle.md

**Files:**
- Create: `docs/pull-bundle.md`
- Read: `profiler/README.md`, `connectors/README.md`, `importer/README.md` for current documentation of pull/snapshot commands

Write the pull-bundle guide with these sections:

1. **Overview** — The bundle is the normalized artifact between profiling and importing
2. **Source config JSON** — `provider`, `spreadsheet_id`/`doc_url`, `tabs[]`, `required_headers`, multi-source options — link to example configs in `docs/examples/`
3. **Live mode: pull_bundle** — command syntax, env vars (`GOOGLE_SA_JSON`, `CODA_API_TOKEN`), output directory
4. **Offline mode: snapshot_bundle** — command syntax, local CSV/JSON input
5. **The manifest.json** — structure: `structure_schema_version`, `tabs[]` with `tab_name`, `source`, `row_count`, `headers`
6. **The normalized bundle directory** — layout: one CSV per tab, manifest, structure
7. **Validating pulled data** — checksums, row counts, header presence
8. **Troubleshooting** — auth failures, missing tabs, rate limits — link to `docs/google-auth.md` and `docs/coda.md`

- [ ] **Step 1: Write docs/pull-bundle.md**

- [ ] **Step 2: Verify file exists**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
cat docs/pull-bundle.md | head -5
```

Expected: file starts with `# Pull Bundle Guide`.

- [ ] **Step 3: Commit**

```bash
git add docs/pull-bundle.md
git commit -m "docs: add pull-bundle and snapshot-bundle guide"
```

---

### Task 11: docs/end-to-end-tutorial.md

**Files:**
- Create: `docs/end-to-end-tutorial.md`

Write the end-to-end tutorial with these steps:

1. **Prerequisites** — Python 3.11+, venv, `pip install "migration-workbench[dev]"`, env vars, a test spreadsheet
2. **Step 1: Profile preflight** — `python manage.py profile_preflight --smoke`, what it checks
3. **Step 2: Profile tab** — `python manage.py profile_tab`, what artifacts it produces
4. **Step 3: Pull bundle** — `python manage.py pull_bundle --config ... --output-dir ...`, what the output looks like
5. **Step 4: Scaffold workbook schema** — `python manage.py scaffold_workbook_schema`, review the generated contract YAML
6. **Step 5: Harden the contract** — editing the YAML, adding `import_config`, field types, unique constraints
7. **Step 6: Generate models, admin, import** — the three generate commands
8. **Step 7: Run import** — `--validate-only`, `--dry-run`, live; reading the summary JSON
9. **Next steps** — link to schema-design-loop, deployment docs
10. **Coda alternative** — brief note on using Coda commands instead of Sheets commands in steps 1-3

- [ ] **Step 1: Write docs/end-to-end-tutorial.md**

- [ ] **Step 2: Verify file exists**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
cat docs/end-to-end-tutorial.md | head -5
```

Expected: file starts with `# End-to-End Tutorial`.

- [ ] **Step 3: Commit**

```bash
git add docs/end-to-end-tutorial.md
git commit -m "docs: add end-to-end tutorial"
```

---

### Task 12: docs/contributing.md

**Files:**
- Create: `docs/contributing.md`

Write the contributor guide with these sections:

1. **Project layout** — five Django apps (connectors, profiler, importer, workbook, deployment), what each owns
2. **Development setup** — venv, `pip install -e ".[dev]"`, `.env`, `python manage.py migrate`, `make chassis-gate`
3. **Test suite** — where tests live (`*/tests/`), running a single test (`pytest path/to/test.py::test_name`), full gate (`make chassis-gate`)
4. **Adding a new provider** — implement `ProviderAdapter` interface, register in `router.py`, add tests
5. **Docstring conventions** — Google-style, `interrogate` CI check, coverage threshold
6. **PR expectations** — `make chassis-gate` green, `make doc-coverage` green, descriptive PR title
7. **Commit and version conventions** — conventional commit style, semantic versioning, changelog in README

- [ ] **Step 1: Write docs/contributing.md**

- [ ] **Step 2: Verify file exists**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
cat docs/contributing.md | head -5
```

Expected: file starts with `# Contributing to migration-workbench`.

- [ ] **Step 3: Commit**

```bash
git add docs/contributing.md
git commit -m "docs: add contributor guide"
```

---

### Task 13: docs/troubleshooting.md

**Files:**
- Create: `docs/troubleshooting.md`

Write the consolidated troubleshooting FAQ with these sections:

1. **Auth failures** — Google SA not found, impersonation errors, Coda token invalid
2. **Profiler failures** — rate limits (429), empty tabs, Drive folder permission, Coda doc not found
3. **Import failures** — constraint violations, type mismatches, FK lookups failing, sample guard triggers, summary JSON error codes
4. **Deployment failures** — Fly secrets missing, health check timeouts, Litestream replication errors, Docker build failures
5. **Bundle validation failures** — missing headers, checksum mismatches, manifest structure errors
6. **Each entry format**: **Symptom** → **Cause** → **Fix**

Link to `docs/google-auth.md`, `docs/coda.md`, `docs/deployment.md` for deeper dives.

- [ ] **Step 1: Write docs/troubleshooting.md**

- [ ] **Step 2: Verify file exists**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
cat docs/troubleshooting.md | head -5
```

Expected: file starts with `# Troubleshooting Guide`.

- [ ] **Step 3: Commit**

```bash
git add docs/troubleshooting.md
git commit -m "docs: add consolidated troubleshooting FAQ"
```

---

### Task 14: Cross-link updates

**Files:**
- Modify: `README.md` (documentation map table)
- Modify: `docs/architecture.md` (add links to new docs)

In `README.md`, update the Documentation Map table to add rows for: `docs/schema-contract.md`, `docs/pull-bundle.md`, `docs/end-to-end-tutorial.md`, `docs/contributing.md`, `docs/troubleshooting.md`.

In `docs/architecture.md`, add a "Further reading" section linking to the new docs that are architecture-adjacent (pull-bundle guide, tutorial, contributing guide).

- [ ] **Step 1: Update README.md documentation map and docs/architecture.md**

- [ ] **Step 2: Run tests to verify nothing broke**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/architecture.md
git commit -m "docs: add cross-links to new documentation in README and architecture"
```

---

## Track 3: CI Enforcement & Doc Map

### Task 15: Add interrogate dependency and config

**Files:**
- Modify: `pyproject.toml`

Add `interrogate>=1.5` to the `dev` optional dependencies in `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
  "pytest",
  "pytest-django",
  "black",
  "build>=1.2",
  "twine>=5.0",
  "interrogate>=1.5",
]
```

Add `[tool.interrogate]` config in `pyproject.toml`:

```toml
[tool.interrogate]
fail-under = 80
exclude = ["migrations", "setup.py", "conftest.py"]
ignore-init-method = true
ignore-init-module = true
ignore-magic = true
verbose = 1
```

- [ ] **Step 1: Update pyproject.toml with interrogate dependency and config**

- [ ] **Step 2: Install and verify**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
.venv/bin/pip install -e ".[dev]" -q
.venv/bin/interrogate -v connectors profiler importer workbook deployment
```

Expected: shows coverage percentage, exits with status based on 80% threshold (will fail initially since we haven't added all docstrings yet from the worktree; that's OK — this step just verifies `interrogate` is installed and runs).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "ci: add interrogate dev dependency and config for doc coverage"
```

---

### Task 16: Add Makefile target for doc coverage

**Files:**
- Modify: `Makefile`

Add `doc-coverage` to the `.PHONY` line and add the target:

```makefile
doc-coverage:  ## Check PEP 257 docstring coverage (threshold: 80%)
	$(VENV)/bin/interrogate -v --fail-under 80 connectors profiler importer workbook deployment
```

Also add `doc-coverage` to the `.PHONY` line.

- [ ] **Step 1: Add doc-coverage target to Makefile**

- [ ] **Step 2: Verify the target runs**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
make doc-coverage
```

Expected: runs interrogate, reports coverage, may fail if under 80% (that's OK at this stage).

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "ci: add doc-coverage Makefile target"
```

---

### Task 17: Add doc coverage step to CI workflow

**Files:**
- Modify: `.github/workflows/ci.yml`

Add a new step after the existing "Run chassis gate" step in the `chassis-gate` job:

```yaml
      - name: Doc coverage gate
        run: make doc-coverage
```

This runs in the same job, after `make chassis-gate`, using the same venv that was set up by the `Install dependencies` step (interrogate is a dev dependency).

- [ ] **Step 1: Add doc coverage step to ci.yml**

- [ ] **Step 2: Verify YAML is valid**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add doc coverage gate to CI workflow"
```

---

### Task 18: Create docs/INDEX.md

**Files:**
- Create: `docs/INDEX.md`

Write the documentation index:

```markdown
# Documentation Index

## Getting Started

| Doc | Audience | Description |
|-----|----------|-------------|
| [README.md](../README.md) | all | Project orientation, pipeline overview, roadmap |
| [End-to-End Tutorial](end-to-end-tutorial.md) | adopter | Step-by-step walkthrough from profiling to import |
| [Contributing](contributing.md) | contributor | Dev setup, test suite, PR expectations |

## Architecture & Design

| Doc | Audience | Description |
|-----|----------|-------------|
| [Architecture](architecture.md) | all | Five-layer design, data flow, Django project layout |
| [Schema Design Loop](schema-design-loop.md) | adopter | Contract-first importer workflow |
| [Schema Contract Reference](schema-contract.md) | adopter | YAML contract format reference (v1.0–v1.3) |
| [Roadmap](roadmap.md) | all | Feature history and v1.0 criteria |

## Operations

| Doc | Audience | Description |
|-----|----------|-------------|
| [Deployment](deployment.md) | operator | Fly.io, Litestream, CI/CD, health checks |
| [Pull Bundle Guide](pull-bundle.md) | operator | Source config, live/offline modes, bundle validation |
| [Google Auth](google-auth.md) | operator | Sheets/Drive profiling auth setup |
| [Google Corpus](google-corpus.md) | operator | Multi-workbook Drive folder profiling |
| [Coda](coda.md) | operator | Coda profiling |
| [Troubleshooting](troubleshooting.md) | all | Consolidated FAQ for common errors |

## Per-Package READMEs

| Doc | App | Description |
|-----|-----|-------------|
| [connectors/README.md](../connectors/README.md) | connectors | Provider adapter surfaces |
| [profiler/README.md](../profiler/README.md) | profiler | Profiling commands and artifacts |
| [importer/README.md](../importer/README.md) | importer | Import chassis and summary JSON |
| [workbook/README.md](../workbook/README.md) | workbook | Schema contract and codegen |
| [deployment/README.md](../deployment/README.md) | deployment | CLI and manifest validation |
```

- [ ] **Step 1: Write docs/INDEX.md**

- [ ] **Step 2: Verify file exists**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
cat docs/INDEX.md | head -5
```

Expected: file starts with `# Documentation Index`.

- [ ] **Step 3: Commit**

```bash
git add docs/INDEX.md
git commit -m "docs: add documentation index"
```

---

### Task 19: Final verification — run full gate

**Files:** None

Run the full test suite and doc coverage check to verify everything is clean:

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
.venv/bin/python -m pytest -q
make doc-coverage
```

Expected: all 444+ tests pass, interrogate shows >80% coverage (should be ~95%+ after all docstring additions).

- [ ] **Step 1: Run full test suite**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run doc coverage check**

```bash
cd /home/user/projects/migration-workbench/.worktrees/docs-coverage
make doc-coverage
```

Expected: coverage >80%, target threshold met.

- [ ] **Step 3: Final commit if needed**

If any minor fixups were needed during verification, commit them.

```bash
git add -A
git commit -m "docs: final fixups from verification pass"
```