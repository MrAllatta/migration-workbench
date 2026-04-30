# migration_workbench

Reusable profiler and importer chassis for tabular workbook-to-app migrations.

**PyPI:** [`migration-workbench`](https://pypi.org/project/migration-workbench/) — `pip install migration-workbench` (import package `migration_workbench` uses underscores).

## Using this project

**As a library (recommended for product repos)**  
Add the Django apps you need to `INSTALLED_APPS` and wire URLs/commands in **your** Django project. Set **`DJANGO_SETTINGS_MODULE`** to your project’s settings module (not `migration_workbench.settings`) in production. Host apps typically depend on a released version, for example `migration-workbench>=0.1.0,<1`.

**Developing this repository (full chassis checkout)**  
Clone the repo and use an editable install so `manage.py`, docs examples, and `make chassis-gate` match upstream:

1. `python3 -m venv .venv`
2. `.venv/bin/pip install -e ".[dev]"` (contributors: `.venv/bin/pip install -e ".[dev,release]"` to build wheels locally)
3. `. ./.env.example` (or create `.env`)
4. `.venv/bin/python manage.py migrate`
5. `make chassis-gate`

## Quickstart (install from PyPI)

For tooling and Django apps without cloning:

1. `python3 -m venv .venv`
2. `.venv/bin/pip install "migration-workbench[dev]"` (omit `[dev]` if you do not need pytest/black)
3. Use `wb` on your PATH, or import apps (`connectors`, `profiler`, `importer`, `workbook`, `deployment`, …) from your own Django project.

If your index does not have a release yet, install from a local checkout instead: `.venv/bin/pip install -e /path/to/migration-workbench`.

Note: The bundled **`migration_workbench.settings`** resolves paths relative to the installed package; for deployments use your own settings module and database configuration.

## Releases

Versions follow **semantic versioning**; **`0.x`** may include breaking changes.

To publish a release:

1. Bump **`version`** in [`pyproject.toml`](pyproject.toml).
2. Commit and push tag **`v` + version** (e.g. `v0.1.0` must match `version = "0.1.0"`).
3. Configure **Trusted Publishing** on [PyPI](https://pypi.org/manage/account/publishing/) for this GitHub repository (see [`.github/workflows/publish-pypi.yml`](.github/workflows/publish-pypi.yml)).
4. The **Publish package** workflow uploads the sdist and wheel to PyPI.

Dry-run uploads can be done manually with `twine upload --repository testpypi dist/*` after `python -m build` (optional `[release]` extra installs `build` and `twine`).

## Core Commands

- `python manage.py pull_bundle --config docs/examples/live-config.example.json --output-dir /tmp/bundle`
- `python manage.py snapshot_bundle --config docs/examples/offline-config.example.json --output-dir /tmp/bundle`
- `python manage.py import_reference_example example_data --validate-only`
- `python manage.py import_reference_example example_data`

Profiling (Google Sheets, Drive, Coda) lives under `manage.py`; see **`docs/quickstart.md`** and **`docs/coda-runbook.md`**. Makefile targets **`profile-coda-preflight`** and **`profile-coda-corpus`** wrap the Coda smoke flows (`CODA_CORPUS_CONFIG` / `CODA_CORPUS_OUT_DIR` for the latter).

Schema scaffolding (**workbook** app): `python manage.py scaffold_workbook_schema --bundle-config example_data/scaffold_workbook_bundle.example.json --table-profile example_data/scaffold_workbook_table_profile.example.json --out /tmp/schema-contract.yaml` (writes YAML for product repos to refine into Django models; see **`docs/architecture.md`**).

Deployment control plane:

- `wb manifest lint --manifest deploy/spaces.yml`
- `wb deploy <space> --env <preview|production> --dry-run`

## Deployment

- Spec: `docs/deployment-spec-v0.2.md`
- Acceptance criteria: `docs/deployment-acceptance-criteria.md`
- Space manifest baseline: `deploy/spaces.yml`
- Pipeline narrative: `docs/pipeline.md`

## Database Modes

- `DB_ENGINE=sqlite` (default)
- `DB_ENGINE=postgres` with `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
