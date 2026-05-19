# 0.9.3 Beta Hardening

**Date:** 2026-05-18
**Status:** Approved
**Applies to:** migration-workbench v0.9.2 → v0.9.3

Six implementation gaps between the current 0.9.2 and a frictionless pipeline
ready for the next live test project.

---

## A1. `model_name` in `build_contract()`

### Problem

`scaffold_workbook_schema._build_cohort_contract()` adds `model_name` to every
table, but `schema_contract.build_contract()` (the bundle-config path) does not.
Contracts produced via the bundle-config path would fail `load_contract()`'s v2
validation, which requires `model_name` on every table.

### Design

After constructing each table dict in `build_contract()`, add:

```python
from profiler.tools.enrichment_utils import _to_pascal_case

table["model_name"] = _to_pascal_case(table["suggested_model_name"])
```

This matches the cohort path's behavior exactly.

### Files changed

| File | Change |
|------|--------|
| `workbook/schema_contract.py` | Add `model_name` to every table in `build_contract()` |

---

## A2. `makefile_targets.py` → `wb generate`

### Problem

The shared module `workbook/makefile_targets.py` generates Makefile recipes
using `$(MANAGE) generate_models`, `$(MANAGE) generate_admin`, etc. The
workbench's own `Makefile` already uses `wb generate models`. Scaffolding a new
product produces Makefiles that call `manage.py` directly for codegen, bypassing
`wb`.

### Design

Replace all `$(MANAGE) generate_*` recipes in `makefile_targets.py` with
`wb generate` subcommands:

| Old | New |
|-----|-----|
| `$(MANAGE) generate_models` | `wb generate models` |
| `$(MANAGE) generate_admin` | `wb generate admin` |
| `$(MANAGE) generate_import` | `wb generate import` |
| `$(MANAGE) generate_view_manifest` | `wb generate manifest` |
| `$(MANAGE) generate_pipeline_manifest` | `wb generate manifest --pipeline` |

The `MANAGE` variable remains in the preamble for non-codegen commands
(`migrate`, `shell`, `reset-migrations`).

### Files changed

| File | Change |
|------|--------|
| `workbook/makefile_targets.py` | Replace `$(MANAGE) generate_*` with `wb generate *` in all builder functions |

---

## A3. `bundle_path` consistency through harden

### Problem

`build_contract()` sets `import_config.bundle_path` from the bundle config's
`output_path`. Then `_harden_contract()` replaces the entire `import_config`
dict, losing that value. It re-derives `bundle_path` via
`_compute_bundle_paths()`, but that function uses tab title slugification
(`seasons.csv`) instead of `_derive_bundle_path()` which uses the model name
(pluralized, e.g. `reference/seasons.csv`).

### Design

In `_harden_contract()`, when constructing the new `import_config` dict:
1. Preserve any existing `bundle_path` from the pre-harden contract.
2. If `bundle_path` is absent, call `_derive_bundle_path(model_name)` to set it.

This makes both paths (`build_contract` and `_harden_contract`) produce
consistent `reference/{plural_model_name}.csv` paths.

### Files changed

| File | Change |
|------|--------|
| `workbook/management/commands/scaffold_workbook_schema.py` | Preserve existing `bundle_path` in `_harden_contract()`; fallback to `_derive_bundle_path(model_name)` |

---

## B1. `fly.toml` + `fly.preview.toml`

### Problem

`.github/workflows/deploy.yml` references `fly.toml` and `fly.preview.toml`,
but neither file exists in the repository. `flyctl deploy` will fail at the
config resolution step.

### Design

Create both files from the existing deployment documentation and Dockerfile.

#### `fly.toml` (production)

```toml
app = "migration-workbench"
primary_region = "sjc"

[build]
  dockerfile = "Dockerfile"

[env]
  DJANGO_SETTINGS_MODULE = "migration_workbench.settings"
  DB_ENGINE = "sqlite"
  PORT = "8000"

[deploy]
  release_command = "python manage.py migrate --noinput"

[mounts]
  source = "migration_workbench_data"
  destination = "/data"

[[services]]
  http_checks = []
  internal_port = 8000
  protocol = "tcp"

  [services.concurrency]
    hard_limit = 25
    soft_limit = 20
    type = "connections"

  [[services.ports]]
    force_https = true
    handlers = ["http"]
    port = 80

  [[services.ports]]
    handlers = ["tls", "http"]
    port = 443

  [[services.tcp_checks]]
    grace_period = "1s"
    interval = "15s"
    restart_limit = 0
    timeout = "2s"
```

#### `fly.preview.toml`

Same as `fly.toml` with:
- `app = "migration-workbench-preview"`
- Smaller machine size (`[vm]` size = `shared-cpu-1x`)

### Files changed

| File | Change |
|------|--------|
| `fly.toml` | New — production Fly config |
| `fly.preview.toml` | New — preview Fly config |

---

## B2. PyPI publish gated on CI

### Problem

`publish-pypi.yml` triggers on any `v*` tag push, independent of CI status.
A tag pushed on a failing branch would publish broken code to PyPI.

### Design

Keep the `push: tags: v*` trigger (needed because `workflow_run` does not fire
on tag pushes), but add a step that verifies CI is green for the same commit SHA
before publishing:

```yaml
on:
  push:
    tags: ["v*"]

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: publish
    permissions:
      id-token: write  # Trusted Publishing (OIDC)

    steps:
      - uses: actions/checkout@v4

      - name: Verify CI passed for this SHA
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          SHA="${{ github.sha }}"
          # Check that the CI workflow succeeded for this commit
          STATUS=$(gh run list -w CI --commit "$SHA" --json conclusion --jq '.[0].conclusion')
          if [ "$STATUS" != "success" ]; then
            echo "CI status for $SHA is '$STATUS', not 'success'. Aborting publish."
            exit 1
          fi

      - name: Verify tag matches pyproject.toml version
        run: |
          TAG_VERSION="${GITHUB_REF#refs/tags/v}"
          PYPROJECT_VERSION=$(python3 -c "
          import tomllib, sys
          with open('pyproject.toml', 'rb') as f:
              print(tomllib.load(f)['project']['version'])")
          if [ "$TAG_VERSION" != "$PYPROJECT_VERSION" ]; then
            echo "Tag $TAG_VERSION does not match pyproject.toml version $PYPROJECT_VERSION"
            exit 1
          fi

      # ... existing build and publish steps ...
```

The `GITHUB_TOKEN` `contents: read` permission (default) is sufficient for
`gh run list`. The `environment: publish` adds an optional manual approval
gate in GitHub.

### Files changed

| File | Change |
|------|--------|
| `.github/workflows/publish-pypi.yml` | Add CI-status check and tag-verification steps; keep tag push trigger |

---

## B3. Linter in CI

### Problem

No code style or static analysis step in CI. Formatting and lint issues are
only caught by manual review.

### Design

Add `ruff` to CI as a step before `chassis-gate`:

```yaml
- name: Lint
  run: |
    pip install ruff
    ruff check .
    ruff format --check .
```

Add `ruff` to `pyproject.toml` dev dependencies if not already present.

### Files changed

| File | Change |
|------|--------|
| `.github/workflows/ci.yml` | Add lint step before `chassis-gate` |
| `pyproject.toml` | Add `ruff` to `[project.optional-dependencies]` dev group |

---

## C1. Live Deploy

After B1 (fly.toml) is in place:

1. `fly apps create migration-workbench`
2. `fly volumes create migration_workbench_data --region sjc --size 1`
3. `fly secrets set DJANGO_DEBUG=0 SECRET_KEY=<gen> ...`
4. `fly deploy` (via CI or manually)
5. Verify `/healthz` returns 200

### Success criteria

- `/healthz` returns 200 on `migration-workbench.fly.dev`
- `fly logs` shows successful migration and Gunicorn startup

---

## C2. PyPI Release

After B2 (gated publish) and a successful live deploy:

1. Bump version in `pyproject.toml` (already done for 0.9.3 in this spec)
2. Tag `v0.9.3`
3. Push tag → CI runs → `publish-pypi.yml` fires after green CI
4. Verify: `pip install migration-workbench==0.9.3`

### Success criteria

- `pip install migration-workbench==0.9.3` succeeds
- `wb --help` works in a fresh venv
- All package imports succeed (`connectors`, `profiler`, `importer`, `workbook`, `deployment`)

---

## Implementation order

All items can proceed in parallel. The only dependency is:
- C1 requires B1 (fly.toml)
- C2 requires B2 (gated publish) and a version bump

Suggested parallel tracks:

| Track | Items | Blocks |
|-------|-------|--------|
| Code fixes | A1, A2, A3 | Nothing |
| CI/CD | B1, B2, B3 | Nothing |
| Deploy | C1 | After B1 |
| Release | C2 | After B1, B2, version bump |