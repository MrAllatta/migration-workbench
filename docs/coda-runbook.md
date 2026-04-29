# Coda profiling runbook

Use this when the source of truth is a Coda doc (tables and views) instead of Google Sheets.

## Prerequisites

1. A Coda account with access to the target doc.
2. A Coda API token with read access to that doc.
  - In Coda: **Settings → API settings → Generate API token** (or the current equivalent in the product UI).
3. Environment variable `**CODA_API_TOKEN`** set to that token (never commit it; use `.env` locally).

The token can only see docs your Coda user can open in the browser. If profiling returns empty or 403, confirm doc sharing and token scope.

### Auth check

After setting `CODA_API_TOKEN`, verify the token with `**profile_coda_preflight`** (calls `GET /whoami`). Optionally pass `**--doc <url-or-id>**` to confirm a specific doc is readable.

```bash
python manage.py profile_coda_preflight
python manage.py profile_coda_preflight --doc "$CODA_DOC_URL"
```

Use `**--smoke**` for CI-style checks without network calls (no token required).

## Doc URL vs doc id

Share links look like `https://coda.io/d/<slug>_<suffix>`. The Coda API doc id is usually the substring after `_d` in that segment (see the official doc ID help on [coda.io/api](https://coda.io/api)). The workbench also calls `**GET /resolveBrowserLink**` when you pass a full `https://coda.io/...` URL so the resolved doc id is used even when the slug pattern is unusual.

You may set `**doc_id**` in live config to a known-good id from the Coda UI or from `profile_coda_doc` output if URL resolution fails.

## Rate limits

Coda may return HTTP 429. The HTTP client in `connectors/coda_source.py` retries with backoff. For very large docs, prefer `--no-columns` on `profile_coda_doc` first, then profile individual tables.

## Recommended profiling sequence

1. **Doc inventory** — tables, views, row counts, and optional column metadata:
  ```bash
   python manage.py profile_coda_doc --doc "$CODA_DOC_URL" --out data/profile_snapshots/coda_doc.json
  ```
   Add `--no-columns` to skip per-table column calls when the doc is huge.
2. **Per-table drill-down** — column types, formula text, per-column null rate / cardinality sample, cross-table **ref** hints (`ref_tables_seen`), and view vs base metadata:
  ```bash
   python manage.py profile_coda_table --doc "$CODA_DOC_URL" --table "Clients" --out data/profile_snapshots/clients.json
  ```
   Omit `--table` to print a list of table/view ids and names.
   `--focus-col` takes a **column name** (Coda headers are names, not A1 letters).
   Summaries include `**is_view`**, `**parent_table`** (for views), and `**etl_importable**`. Normalized bundle import targets **base tables**; profiling views is still useful to understand filters and injected rows, but ETL should not treat a view as the canonical source sheet.
3. **Formula scan** — Coda exposes formulas at the **column** level (`formulaText`), not per-cell like Sheets. Use:
  ```bash
   python manage.py scan_coda_formula_columns --config scan-coda.json --out data/profile_snapshots/coda_formulas.json
  ```
   Config shape matches `scan_formula_patterns` except each workbook entry uses `doc_url` or `doc_id` instead of `spreadsheet_id`. See `example_data/scan_coda_formula_columns.example.json`.
4. **Multi-doc corpus pipeline** (optional, parity with Sheets `**profile_cohort_corpus`**) — discovery across several docs, base-table-only broad profile, heuristic table selection, deep profiles, and column candidate shortlists:
  ```bash
   python manage.py profile_coda_corpus \
     --config example_data/coda_corpus.example.json \
     --out-dir data/profile_snapshots/coda_corpus_run
  ```
   Artifacts include `coda_discovery_<date>.json` (includes per-doc `doc_meta.docSize`), `coda_table_index_<date>.json` (tables include `parent_page` when the API provides it), `coda_broad_profile_<date>.json`, `table_shortlist_<date>.json`, `table_selection_<date>.json`, `deep/*.json`, `coda_deep_coverage_<date>.json`, `coda_relationship_summary_<date>.json`, optional `coda_canvas_<date>.json` (when `canvas.enabled` is true in config), `column_shortlist_<date>.json`, and `column_selection_<date>.json`. Edit `**table_selection_<date>.json**` (`approved_tables`: doc display name → table names) and re-run with `**--resume-from-table-selection**` to drive the deep pass without regenerating selection.
   Corpus JSON options: **`exclude_views`** (if true, only base tables are listed—overrides **`table_types`**), **`table_types`** (e.g. `["table","view"]`), and **`canvas`** (`enabled`, `max_pages`, `max_chars_per_page`, `max_content_items`, `use_export`). See `example_data/coda_corpus.example.json`.
   From the repo root, `**make profile-coda-corpus**` expects `**CODA_CORPUS_CONFIG**` and optional `**CODA_CORPUS_OUT_DIR**` (see `Makefile`).
5. **Canvas text** — for narrative context (summaries, prompts), export plain text per page or slower full-page markdown export:
  ```bash
   python manage.py profile_coda_canvas --doc "$CODA_DOC_URL" --out data/profile_snapshots/coda_canvas.json
  ```
   Add `**--use-export**` for markdown export via Coda’s async page export API. `**make profile-coda-canvas**` runs `**--smoke**` only (CI).
6. **Normalized bundle** — after `required_headers` are known for each tab, run:
  ```bash
   python manage.py pull_bundle --config coda-live-config.json --output-dir data/bundle
  ```
   Live config example: `docs/examples/coda-live-config.example.json`. Each tab needs `worksheet_title` (table or view **name**) or `table_id`, plus `output_path` and `required_headers` as for Sheets. Optional **`max_rows`** (top-level or per tab) and **`value_format`** (`rich` vs `simple`) limit payload size on large tables.

## Differences from Google Sheets profiling


| Topic                   | Sheets                                 | Coda                                        |
| ----------------------- | -------------------------------------- | ------------------------------------------- |
| Auth                    | Service account / ADC                  | Bearer `CODA_API_TOKEN`                     |
| Auth smoke              | `profile_preflight`                    | `profile_coda_preflight`                    |
| Tab identity            | Spreadsheet id + worksheet title       | Doc id + table or view id/name              |
| Formulas                | Cell-level in grid                     | Column-level `formulaText`                  |
| Multi-source automation | `profile_cohort_corpus` (Drive folder) | `profile_coda_corpus` (config list of docs) |
| `profile_drive_folder`  | Folder tree of workbooks               | N/A — use `profile_coda_doc` per doc        |


## Troubleshooting

- `**ValueError: Coda API token required`** — export `CODA_API_TOKEN` or pass `api_token` in the live JSON config (prefer env for local dev).
- **Table not found** — names are case-sensitive; use `profile_coda_table` without `--table` to list exact names.
- **Empty grid** — confirm the table has rows and that the integration user can see them in the Coda UI.

