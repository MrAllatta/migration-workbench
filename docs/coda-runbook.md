# Coda profiling runbook

Use this when the source of truth is a Coda doc (tables and views) instead of Google Sheets.

## Prerequisites

1. A Coda account with access to the target doc.
2. A Coda API token with read access to that doc.
   - In Coda: **Settings → API settings → Generate API token** (or the current equivalent in the product UI).
3. Environment variable **`CODA_API_TOKEN`** set to that token (never commit it; use `.env` locally).

The token can only see docs your Coda user can open in the browser. If profiling returns empty or 403, confirm doc sharing and token scope.

## Doc URL vs doc id

Share links look like `https://coda.io/d/<slug>_<suffix>`. The Coda API doc id is usually the substring after `_d` in that segment (see the official doc ID help on [coda.io/api](https://coda.io/api)). The workbench also calls **`GET /resolveBrowserLink`** when you pass a full `https://coda.io/...` URL so the resolved doc id is used even when the slug pattern is unusual.

You may set **`doc_id`** in live config to a known-good id from the Coda UI or from `profile_coda_doc` output if URL resolution fails.

## Rate limits

Coda may return HTTP 429. The HTTP client in `connectors/coda_source.py` retries with backoff. For very large docs, prefer `--no-columns` on `profile_coda_doc` first, then profile individual tables.

## Recommended profiling sequence

1. **Doc inventory** — tables, views, row counts, and optional column metadata:

   ```bash
   python manage.py profile_coda_doc --doc "$CODA_DOC_URL" --out data/profile_snapshots/coda_doc.json
   ```

   Add `--no-columns` to skip per-table column calls when the doc is huge.

2. **Per-table drill-down** — column types, formula text, and a bounded row sample:

   ```bash
   python manage.py profile_coda_table --doc "$CODA_DOC_URL" --table "Clients" --out data/profile_snapshots/clients.json
   ```

   Omit `--table` to print a list of table/view ids and names.

   `--focus-col` takes a **column name** (Coda headers are names, not A1 letters).

3. **Formula scan** — Coda exposes formulas at the **column** level (`formulaText`), not per-cell like Sheets. Use:

   ```bash
   python manage.py scan_coda_formula_columns --config scan-coda.json --out data/profile_snapshots/coda_formulas.json
   ```

   Config shape matches `scan_formula_patterns` except each workbook entry uses `doc_url` or `doc_id` instead of `spreadsheet_id`. See `example_data/scan_coda_formula_columns.example.json`.

4. **Normalized bundle** — after `required_headers` are known for each tab, run:

   ```bash
   python manage.py pull_bundle --config coda-live-config.json --output-dir data/bundle
   ```

   Live config example: `docs/examples/coda-live-config.example.json`. Each tab needs `worksheet_title` (table or view **name**) or `table_id`, plus `output_path` and `required_headers` as for Sheets.

## Differences from Google Sheets profiling

| Topic | Sheets | Coda |
| --- | --- | --- |
| Auth | Service account / ADC | Bearer `CODA_API_TOKEN` |
| Tab identity | Spreadsheet id + worksheet title | Doc id + table or view id/name |
| Formulas | Cell-level in grid | Column-level `formulaText` |
| `profile_drive_folder` | Folder tree of workbooks | N/A — use `profile_coda_doc` |

## Troubleshooting

- **`ValueError: Coda API token required`** — export `CODA_API_TOKEN` or pass `api_token` in the live JSON config (prefer env for local dev).
- **Table not found** — names are case-sensitive; use `profile_coda_table` without `--table` to list exact names.
- **Empty grid** — confirm the table has rows and that the integration user can see them in the Coda UI.
