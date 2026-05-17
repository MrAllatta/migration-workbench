# Contributing

## Project layout

Five Django apps, each in its own top-level package:

| App | Responsibility |
| --- | -------------- |
| [`connectors/`](../connectors/README.md) | Provider adapters (Google Sheets, Coda) that fetch raw tab rows from upstream sources. |
| [`profiler/`](../profiler/README.md) | Read-only profiling — normalises tabular rows into deterministic CSV bundle artifacts. |
| [`importer/`](../importer/README.md) | `BaseImportCommand` chassis, preflight/apply lifecycle, structured failure summaries. |
| [`workbook/`](../workbook/README.md) | Turns profiler JSON and bundle config into schema-contract YAML and optional `models.py` stubs. |
| [`deployment/`](../deployment/README.md) | Manifest validation, release metadata, `wb` CLI (`manifest lint`, `deploy --dry-run`). |

The root [`manage.py`](../manage.py) uses `migration_workbench.settings` for development and the
`chassis-gate`.  Product repos install `migration-workbench` from PyPI and provide their own
`manage.py` and settings module.

## Development setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env    # or source .env.example
.venv/bin/python manage.py migrate
make chassis-gate
```

The `[dev]` extra installs pytest, pytest-django, black, build, and twine.  All `make` targets
expect the venv at `.venv/`.

## Test suite

Tests live alongside their app in `*/tests/` directories:

```
connectors/tests/
profiler/tests/
importer/tests/
workbook/tests/
deployment/tests/
examples/tests/
scripts/tests/
```

Run a single test:

```bash
.venv/bin/python -m pytest profiler/tests/test_profile_commands.py::test_name
```

Run the full gate (migrate, all tests, lint, smoke commands):

```bash
make chassis-gate
```

## Adding a new provider

1. **Implement the adapter.**  Create a new module under `connectors/` that subclasses
   [`ProviderAdapter`](../connectors/base.py) and implements `fetch_tab_rows()`.  Optionally
   override `fetch_tab_structure()` for structural metadata.

2. **Register the adapter.**  Add an import and a branch to
   [`build_provider_adapter()`](../connectors/router.py):

   ```python
   if provider == "my_source":
       return MySourceAdapter(config)
   ```

3. **Add tests.**  Create or extend `connectors/tests/` with tests for your adapter.

See the existing adapters ([`google_provider.py`](../connectors/google_provider.py),
[`coda.py`](../connectors/coda.py)) for reference implementations.

## Docstring conventions

- **Style:** [Google-style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
  docstrings with `Args:`, `Returns:`, and `Raises:` sections where applicable.
- **Enforcement:** CI runs [`interrogate`](https://interrogate.readthedocs.io/) via
  `make doc-coverage` with an 80 % coverage threshold.

## PR expectations

Before opening a pull request:

- `make chassis-gate` passes (migrate, tests, lint, smoke commands).
- `make doc-coverage` passes (docstring coverage ≥ 80 %).
- The PR title is descriptive and prefixed with the affected area where useful
  (e.g. `connectors:`, `importer:`, `docs:`, `ci:`).

## Commit and version conventions

- **Commits:** Follow [Conventional Commits](https://www.conventionalcommits.org/),
  e.g. `feat:`, `fix:`, `docs:`, `refactor:`, `ci:`.
- **Versioning:** [Semantic versioning](https://semver.org/) (`major.minor.patch`).
  Breaking changes are allowed on `0.x` — pin ranges in product repos.
- **Changelog:** Maintained at the bottom of the [README](../README.md#changelog),
  under a `## Changelog` heading.  Each release adds a new `### x.y.z` entry.
