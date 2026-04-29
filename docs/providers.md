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

Doc identity: top-level `doc_url` (share link) or `doc_id` in the live config, same as `extract_coda_doc_id()` in `coda_source.py`.

Tabs: each tab entry uses `worksheet_title` (table or view **name**) or `table_id` (stable id from the API), plus `output_path` and `required_headers` like Google Sheets. Views are first-class; row payloads are the view projection.

Formulas: Coda returns **column-level** `formulaText`, not per-cell formulas. Use `scan_coda_formula_columns` for regex inventory; see `docs/coda-runbook.md`.

Operational notes:

- Share-link visibility matches the token’s Coda user; the API cannot read docs the user cannot open.
- Large docs: use `profile_coda_doc --no-columns` first, then `profile_coda_table` per candidate table.