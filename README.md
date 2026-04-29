# migration_workbench

Reusable profiler and importer chassis for tabular workbook-to-app migrations.

## Quickstart

1. `python3 -m venv .venv`
2. `.venv/bin/pip install -e ".[dev]"`
3. `. ./.env.example` (or create `.env`)
4. `.venv/bin/python manage.py migrate`
5. `make chassis-gate`

## Core Commands

- `python manage.py pull_bundle --config docs/examples/live-config.example.json --output-dir /tmp/bundle`
- `python manage.py snapshot_bundle --config docs/examples/offline-config.example.json --output-dir /tmp/bundle`
- `python manage.py import_reference_example example_data --validate-only`
- `python manage.py import_reference_example example_data`

Profiling (Google Sheets, Drive, Coda) lives under `manage.py`; see **`docs/quickstart.md`** and **`docs/coda-runbook.md`**. Makefile targets **`profile-coda-preflight`** and **`profile-coda-corpus`** wrap the Coda smoke flows (`CODA_CORPUS_CONFIG` / `CODA_CORPUS_OUT_DIR` for the latter).

Schema scaffolding (**workbook** app): `python manage.py scaffold_workbook_schema --bundle-config example_data/scaffold_workbook_bundle.example.json --table-profile example_data/scaffold_workbook_table_profile.example.json --out /tmp/schema-contract.yaml` (writes YAML for product repos to refine into Django models; see **`docs/architecture.md`**).

## Database Modes

- `DB_ENGINE=sqlite` (default)
- `DB_ENGINE=postgres` with `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
