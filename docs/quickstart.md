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

## 3) Profile source spreadsheets before designing import rules

These management commands are the read-only profiling surface:

- `python manage.py profile_preflight --folder <drive-folder-id-or-url>`
- `python manage.py profile_drive_folder --folder <drive-folder-id-or-url> --out data/profile_snapshots/folder.json`
- `python manage.py profile_tab --spreadsheet-id <sheet-id-or-url>`
- `python manage.py profile_tab --spreadsheet-id <sheet-id-or-url> --tab "<tab title>" --out data/profile_snapshots/tab.json`
- `python manage.py scan_formula_patterns --config scan-config.json --out data/profile_snapshots/formula_matches.json`
- `python manage.py profile_multiyear --config example_data/profile_multiyear.farm.example.json --out-dir data/profile_snapshots`

Authentication and shared-service-account setup guidance lives in `docs/google-auth-runbook.md`.
Prefer ADC user login plus service-account impersonation over per-client key files.

`scan_formula_patterns` expects a config JSON shaped like:

```json
{
  "workbooks": [{"name": "Workbook 601", "spreadsheet_id": "..." }],
  "patterns": [{"name": "importrange", "regex": "IMPORTRANGE\\(" }]
}
```

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

