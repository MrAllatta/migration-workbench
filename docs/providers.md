# Providers

## Google Sheets (active)

Implementation files:

- `connectors/google_sheets.py`
- `connectors/google_provider.py`

Uses service account credentials from `GOOGLE_APPLICATION_CREDENTIALS` or ADC defaults.

Operational recommendation:

- Prefer ADC user login and service-account impersonation for local workflows.
- Use one workbench-owned service account shared to client Drive folders.
- See `docs/google-auth-runbook.md` for the April 2026 reference setup and WIF migration direction.

## Coda (active)

Implementation files:

- `connectors/coda.py` — `CodaAdapter` for `pull_bundle` / importer flows
- `connectors/coda_source.py` — HTTP session, pagination, doc id parsing, row grid flattening

Authentication: set **`CODA_API_TOKEN`** to a Coda API bearer token (read access to the target doc). Optional per-config override: `api_token` on the live source JSON (prefer env for local development).

Optional read consistency: set **`CODA_DOC_VERSION_LATEST=1`** to send header **`X-Coda-Doc-Version: latest`** on API reads (Coda may return **400** if the doc snapshot is not yet current—see [Coda API](https://coda.io/developers/apis/v1) “Consistency”).

Doc identity: top-level `doc_url` (share link) or `doc_id` in the live config. For HTTP URLs the adapter and profiler commands call **`resolveBrowserLink`** first, then fall back to parsing the `_d…` segment per [Coda’s doc ID guidance](https://coda.io/api) (`extract_coda_doc_id` in `coda_source.py`).

Tabs: each tab entry uses `worksheet_title` (table or view **name**) or `table_id` (stable id from the API), plus `output_path` and `required_headers` like Google Sheets. Views are first-class; row payloads are the view projection.

Large pulls: optional top-level or per-tab **`max_rows`** caps rows fetched from Coda. Optional **`value_format`** (`rich` default, or `simple`) is passed to the rows API—useful for smaller CSV-oriented exports (`docs/examples/coda-live-config.example.json`).

Formulas: Coda returns **column-level** `formulaText`, not per-cell formulas. Use `scan_coda_formula_columns` for regex inventory; see `docs/coda-runbook.md`.

Profiling commands (read-only): **`profile_coda_preflight`** (token / optional doc check), **`profile_coda_doc`**, **`profile_coda_table`** (includes null-rate/ref hints and view vs base flags), **`profile_coda_canvas`** (page/canvas plain text or markdown export for summarization), **`scan_coda_formula_columns`**, and **`profile_coda_corpus`** (multi-doc pipeline; example config `example_data/coda_corpus.example.json`). Corpus runs can emit **`coda_relationship_summary_<date>.json`** (lookup edges from deep profiles) and optional **`coda_canvas_<date>.json`** when `canvas.enabled` is true. Implementation details: `connectors/coda_source.py` (`get_whoami`, `analyze_column_values`, page content helpers, …) and `profiler/tools/coda_corpus.py`.

Operational notes:

- Share-link visibility matches the token’s Coda user; the API cannot read docs the user cannot open.
- Large docs: use `profile_coda_doc --no-columns` first, then `profile_coda_table` per candidate table.