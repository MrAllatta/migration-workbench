# Coda profiling

Use when the source of truth is a **Coda doc** (tables and views), not Google Sheets.

## Prerequisites

- Coda account with access to the doc.
- API token with read access (**Settings → API** in Coda). Set **`CODA_API_TOKEN`** in the environment (never commit).

Token visibility matches the Coda user — the API cannot read docs the user cannot open.

### Auth smoke

```bash
python manage.py profile_coda_preflight
python manage.py profile_coda_preflight --doc "$CODA_DOC_URL"
```

Use `--smoke` for CI without network.

## Doc URL vs doc id

Share links: `https://coda.io/d/<slug>_<suffix>`. Doc id is typically the substring after `_d` ([Coda doc ID help](https://coda.io/api)). Full URLs are resolved via **`GET /resolveBrowserLink`** before fallback parsing (`extract_coda_doc_id` in `connectors/coda_source.py`). Set `doc_id` in config if URL resolution fails.

## Rate limits

HTTP 429 is retried with backoff in `coda_source.py`. Huge docs: `profile_coda_doc --no-columns` first, then `profile_coda_table` per table.

## Recommended sequence

1. **Inventory** — `profile_coda_doc --doc … --out …` (add `--no-columns` if huge).
2. **Per table** — `profile_coda_table --doc … --table "Name" --out …` (omit `--table` to list). Prefer base tables for ETL; views are diagnostic.
3. **Formulas** — column-level `formulaText`; use `scan_coda_formula_columns` with config like `example_data/scan_coda_formula_columns.example.json`.
4. **Corpus** (multi-doc) — `profile_coda_corpus --config example_data/coda_corpus.example.json --out-dir …`; edit `table_selection_<date>.json`, re-run with `--resume-from-table-selection`. Makefile: `profile-coda-corpus` needs `CODA_CORPUS_CONFIG`.
5. **Canvas** — `profile_coda_canvas` (`--use-export` for markdown export). `make profile-coda-canvas` runs `--smoke` only.
6. **Bundle** — `pull_bundle` with live config; see [`examples/coda-live-config.example.json`](examples/coda-live-config.example.json).

Optional env: **`CODA_DOC_VERSION_LATEST=1`** sends `X-Coda-Doc-Version: latest` (may 400 if snapshot not ready — see Coda API “Consistency”).

## Sheets vs Coda

| Topic | Sheets | Coda |
|-------|--------|------|
| Auth | ADC / service account | `CODA_API_TOKEN` |
| Smoke | `profile_preflight` | `profile_coda_preflight` |
| Tab id | spreadsheet id + worksheet title | doc id + table/view name or id |
| Formulas | Cell grid | Column `formulaText` |
| Multi-doc | `profile_cohort_corpus` | `profile_coda_corpus` |

## Troubleshooting

- **`ValueError: Coda API token required`** — set `CODA_API_TOKEN` or `api_token` in live JSON (prefer env).
- **Table not found** — names are case-sensitive; list with `profile_coda_table` without `--table`.
- **Empty grid** — confirm rows exist and the token’s user can see them in the UI.

Implementation: [`connectors/coda.py`](../connectors/coda.py), [`connectors/coda_source.py`](../connectors/coda_source.py), [`profiler/README.md`](../profiler/README.md).
