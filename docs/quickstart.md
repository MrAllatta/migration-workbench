# Quickstart for Consumer Repos

This quickstart is for product repos (for example `farm/backend/`) that want to use `migration-workbench` as an installable chassis while keeping all client-specific logic outside this repo.

## 1) Add dependency in your product repo

Install with an editable local path during development:

```bash
pip install -e ../migration-workbench
```

Or with `uv` in `pyproject.toml`:

```toml
[project]
dependencies = ["migration-workbench"]

[tool.uv.sources]
migration-workbench = { path = "../migration-workbench", editable = true }
```

## 2) Enable workbench apps in Django settings

In your product repo settings, include:

- `connectors`
- `profiler`
- `importer`

Then run:

```bash
python manage.py migrate
```

## 3) Profile source spreadsheets (or Coda docs) before designing import rules

These management commands are the read-only profiling surface.

**Google Sheets / Drive**

- `python manage.py profile_preflight --folder <drive-folder-id-or-url>`
- `python manage.py profile_drive_folder --folder <drive-folder-id-or-url> --out data/profile_snapshots/folder.json`
- `python manage.py profile_tab --spreadsheet-id <sheet-id-or-url>`
- `python manage.py profile_tab --spreadsheet-id <sheet-id-or-url> --tab "<tab title>" --out data/profile_snapshots/tab.json`
- `python manage.py scan_formula_patterns --config scan-config.json --out data/profile_snapshots/formula_matches.json`
- `python manage.py profile_cohort_corpus --config example_data/cohort_corpus.example.json --out-dir data/profile_snapshots`

**Coda**

- `python manage.py profile_coda_doc --doc <doc-url-or-id> --out data/profile_snapshots/coda_doc.json`
- `python manage.py profile_coda_table --doc <doc-url-or-id> --table "<table or view name>" --out data/profile_snapshots/coda_table.json`
- `python manage.py scan_coda_formula_columns --config scan-coda.json --out data/profile_snapshots/coda_formulas.json`

Sheets authentication and shared-service-account setup: `docs/google-auth-runbook.md` (prefer ADC user login plus service-account impersonation over per-client key files).

Coda setup: `docs/coda-runbook.md` (bearer token `CODA_API_TOKEN`, doc URL vs id, formula scanning at column level).

`scan_formula_patterns` expects:

```json
{
  "workbooks": [{"name": "Workbook 601", "spreadsheet_id": "..." }],
  "patterns": [{"name": "importrange", "regex": "IMPORTRANGE\\(" }]
}
```

`scan_coda_formula_columns` expects the same `patterns` array, but each workbook entry uses `doc_url` or `doc_id` instead of `spreadsheet_id` (see `example_data/scan_coda_formula_columns.example.json`).

## 4) Keep client-specific behavior in the product repo

- Put schema decisions in your product docs (for example `docs/schema-contract.md`).
- Put tab mapping/aliasing decisions in product-owned bundle YAMLs.
- Keep product import commands thin subclasses of `importer.base.BaseImportCommand`.
- Avoid editing workbench internals for client-specific normalization rules.

## 5) Run baseline validation

From `migration-workbench`:

```bash
make chassis-gate
```

From your product repo:

```bash
python manage.py check
pytest
```

