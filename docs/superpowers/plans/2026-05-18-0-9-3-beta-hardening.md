# 0.9.3 Beta Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close six implementation gaps between v0.9.2 and a frictionless beta pipeline: three code fixes (model_name, makefile_targets wb migration, bundle_path consistency) and three CI/CD hardening items (Fly config, PyPI gating, linter).

**Architecture:** Each item is independent. Code fixes (A1–A3) touch workbook codegen. CI/CD items (B1–B3) touch GitHub workflows and Fly config. Deploy and release (C1–C2) are verification steps, not code changes.

**Tech Stack:** Python 3.11, Django 5.x, Fly.io, GitHub Actions, ruff

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `workbook/schema_contract.py` | Add `model_name` in `build_contract()` (A1) |
| Modify | `workbook/makefile_targets.py` | Replace `$(MANAGE) generate_*` with `wb generate *` (A2) |
| Modify | `workbook/management/commands/scaffold_workbook_schema.py` | Preserve `bundle_path` in `_harden_contract()` (A3) |
| Create | `fly.toml` | Production Fly.io config (B1) |
| Create | `fly.preview.toml` | Preview Fly.io config (B1) |
| Modify | `.github/workflows/deploy.yml` | Fix branch name `main` → `master` (B1) |
| Modify | `.github/workflows/publish-pypi.yml` | Add CI-status gate (B2) |
| Modify | `.github/workflows/ci.yml` | Add lint step (B3) |
| Modify | `pyproject.toml` | Add `ruff` to dev dependencies (B3) |

---

### Task A1: Add `model_name` in `build_contract()`

**Files:**
- Modify: `workbook/schema_contract.py:366-385`
- Test: `workbook/tests/test_schema_contract.py`

- [ ] **Step 1: Write failing test for `model_name` in bundle-config path**

In `workbook/tests/test_schema_contract.py`, add a test that builds a contract via `build_contract()` and verifies every table has `model_name`:

```python
def test_build_contract_adds_model_name():
    config = {
        "source": "test",
        "tabs": [
            {
                "worksheet_title": "Sales Channel",
                "output_path": "reference/sales_channels.csv",
                "required_headers": ["Name"],
            }
        ],
    }
    contract = build_contract(config)
    for table in contract["tables"]:
        assert "model_name" in table
        assert table["model_name"] == "SalesChannel"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest workbook/tests/test_schema_contract.py::test_build_contract_adds_model_name -v`
Expected: FAIL — `model_name` key missing from bundle-config path tables.

- [ ] **Step 3: Implement the fix**

In `workbook/schema_contract.py`:

1. Add import at top of file (after existing imports, around line 32):
```python
from profiler.tools.enrichment_utils import _to_pascal_case
```

2. In `build_contract()`, after constructing the `entry` dict (around line 371, after `"columns": django_columns,`), add `model_name`:

```python
        entry: dict[str, Any] = {
            "bundle_worksheet_title": title,
            "suggested_model_name": model_name_from_output_path(output_path),
            "model_name": _to_pascal_case(model_name_from_output_path(output_path)),
            "bundle_output_path": output_path,
            "columns": django_columns,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest workbook/tests/test_schema_contract.py::test_build_contract_adds_model_name -v`
Expected: PASS

- [ ] **Step 5: Run full workbook test suite**

Run: `pytest workbook/tests/ -v`
Expected: All tests pass (including existing `model_name` validation tests).

- [ ] **Step 6: Commit**

```bash
git add workbook/schema_contract.py workbook/tests/test_schema_contract.py
git commit -m "fix(schema_contract): add model_name in build_contract bundle-config path"
```

---

### Task A2: Migrate `makefile_targets.py` to `wb generate` commands

**Files:**
- Modify: `workbook/makefile_targets.py`
- Test: `workbook/tests/test_makefile_targets.py` (new or existing)

- [ ] **Step 1: Write failing tests for `wb generate` commands in Makefile output**

Create or extend `workbook/tests/test_makefile_targets.py` with tests that verify the generated Makefile uses `wb generate` subcommands instead of `$(MANAGE) generate_*`:

```python
from workbook.makefile_targets import MakeContext, generate_models_block, generate_admin_block, generate_import_block, generate_view_manifest_block, generate_pipeline_manifest_block, full_targets_block


def test_generate_models_uses_wb():
    ctx = MakeContext()
    block = generate_models_block(ctx)
    assert "wb generate models" in block
    assert "$(MANAGE)" not in block


def test_generate_admin_uses_wb():
    ctx = MakeContext()
    block = generate_admin_block(ctx)
    assert "wb generate admin" in block
    assert "$(MANAGE)" not in block


def test_generate_import_uses_wb():
    ctx = MakeContext()
    block = generate_import_block(ctx)
    assert "wb generate import" in block
    assert "$(MANAGE)" not in block


def test_generate_view_manifest_uses_wb():
    ctx = MakeContext()
    block = generate_view_manifest_block(ctx)
    assert "wb generate manifest" in block
    assert "$(MANAGE)" not in block


def test_generate_pipeline_manifest_uses_wb():
    ctx = MakeContext()
    block = generate_pipeline_manifest_block(ctx)
    assert "wb generate manifest" in block
    assert "$(MANAGE)" not in block


def test_full_targets_uses_wb_for_codegen():
    ctx = MakeContext()
    full = full_targets_block(ctx)
    assert "wb generate models" in full
    assert "wb validate contract" in full
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest workbook/tests/test_makefile_targets.py -v`
Expected: FAIL — current code uses `$(MANAGE) generate_*`.

- [ ] **Step 3: Update `generate_models_block()` to use `wb generate models`**

In `workbook/makefile_targets.py`, modify `generate_models_block()` (around lines 103–111). Replace the `$(MANAGE) generate_models` invocation with `wb generate models`:

```python
def generate_models_block(ctx: MakeContext) -> str:
    target = f"generate-models"
    return (
        f"{target}:{ctx.contract}\n"
        f"\twb generate models --contract \"{ctx.contract}\""
        + (f" --app-label {ctx.core}" if ctx.core != "$(CORE)" else "")
        + (" --force" if False else "")
        + (" --diff" if False else "")
        + "\n\n"
    )
```

Note: Remove the `manage` field usage and the `{ctx.manage}` template. Each builder function emits the `wb` command directly. The `--contract` flag takes the context's contract path. Keep `--app-label` conditional.

Exact replacement for the recipe line in `generate_models_block`:
```
_old: f"\t{ctx.manage} generate_models --contract \"{ctx.contract}\""
_new: f"\twb generate models --contract \"{ctx.contract}\""
```

- [ ] **Step 4: Update remaining builder functions similarly**

Apply the same pattern to all builder functions that use `$(MANAGE) generate_*`:

| Function | Old | New |
|----------|-----|-----|
| `generate_models_block` | `{ctx.manage} generate_models` | `wb generate models` |
| `generate_admin_block` (both branches) | `{ctx.manage} generate_admin` | `wb generate admin` |
| `generate_import_block` | `{ctx.manage} generate_import` | `wb generate import` |
| `generate_view_manifest_block` | `{ctx.manage} scaffold_view_manifest` | `wb generate manifest` |
| `generate_pipeline_manifest_block` | `{ctx.manage} generate_pipeline_manifest` | `wb generate manifest --pipeline` |

For `codegen_tooling_block()`, the same replacement applies to the diff/snapshot targets (lines 193, 199, 218, 223, 228). Replace all `$(MANAGE) generate_models` → `wb generate models`, `$(MANAGE) generate_admin` → `wb generate admin`, `$(MANAGE) generate_import` → `wb generate import`.

For `import_blocks()`, `discovery` targets using `$(MANAGE) generate_discovery_interview` should become `wb generate discovery-interview`.

Leave `$(MANAGE)` for non-codegen commands: `migrate`, `shell`, `reset-migrations`, `check`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest workbook/tests/test_makefile_targets.py -v`
Expected: PASS

- [ ] **Step 6: Run scaffold integration test**

Run: `pytest workbook/tests/test_scaffold_workbook_schema.py -k "makefile" -v`
Expected: PASS — scaffolded Makefile contains `wb generate` commands.

- [ ] **Step 7: Commit**

```bash
git add workbook/makefile_targets.py workbook/tests/test_makefile_targets.py
git commit -m "feat(makefile_targets): migrate codegen targets from $(MANAGE) to wb generate"
```

---

### Task A3: Preserve `bundle_path` in `_harden_contract()`

**Files:**
- Modify: `workbook/management/commands/scaffold_workbook_schema.py:321-373`
- Test: `workbook/tests/test_scaffold_workbook_schema.py`

- [ ] **Step 1: Write failing test**

Add a test that verifies `_harden_contract()` preserves an existing `bundle_path` from `build_contract()`:

```python
def test_harden_contract_preserves_bundle_path():
    contract = {
        "tables": [
            {
                "suggested_model_name": "Farm",
                "model_name": "Farm",
                "bundle_worksheet_title": "Farms",
                "columns": [
                    {"suggested_field_name": "name", "source_column": "Name",
                     "django_field_class": "models.CharField",
                     "django_field_kwargs": {"max_length": 120},
                     "notes": []}
                ],
                "import_config": {
                    "bundle_path": "reference/farms.csv",
                    "required_headers": ["Name"],
                    "unique_on": ["name"],
                    "column_map": {"name": "Name"},
                },
            }
        ]
    }
    _harden_contract(contract)
    assert contract["tables"][0]["import_config"]["bundle_path"] == "reference/farms.csv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest workbook/tests/test_scaffold_workbook_schema.py::test_harden_contract_preserves_bundle_path -v`

This should actually PASS because `_compute_bundle_paths()` only sets `bundle_path` if it's missing. But we want to also verify that when `_harden_contract()` replaces `import_config` on line 334, the `bundle_path` is preserved. Let me check: line 334 overwrites `import_config` entirely with only `import_key` and `unique_on`. So paths set by `build_contract()` would be LOST.

To demonstrate the bug, test with a contract that has `import_config.bundle_path` but `import_config` does NOT have `import_key`:

```python
def test_harden_contract_preserves_existing_bundle_path():
    contract = {
        "tables": [
            {
                "suggested_model_name": "Sales Channel",
                "model_name": "SalesChannel",
                "bundle_worksheet_title": "Sales Channels",
                "columns": [
                    {"suggested_field_name": "name", "source_column": "Name",
                     "django_field_class": "models.CharField",
                     "django_field_kwargs": {"max_length": 120},
                     "notes": []}
                ],
                "import_config": {
                    "bundle_path": "reference/sales_channels.csv",
                },
            }
        ]
    }
    _harden_contract(contract)
    assert contract["tables"][0]["import_config"].get("bundle_path") == "reference/sales_channels.csv"
```

Run: `pytest workbook/tests/test_scaffold_workbook_schema.py::test_harden_contract_preserves_existing_bundle_path -v`
Expected: FAIL — `_harden_contract()` overwrites `import_config` losing the `bundle_path`.

- [ ] **Step 3: Implement the fix**

In `workbook/management/commands/scaffold_workbook_schema.py`, modify `_harden_contract()` around line 334 to preserve existing `bundle_path`:

```python
    for table in contract.get("tables", []):
        columns = table.get("columns", [])
        if not columns:
            continue
        first_field = columns[0]["suggested_field_name"]
        import_key_candidates = [
            c["suggested_field_name"]
            for c in columns
            if c.get("is_import_key_candidate")
        ]
        unique_on = import_key_candidates if import_key_candidates else [first_field]
        existing_bundle_path = table.get("import_config", {}).get("bundle_path")
        table["import_config"] = {
            "import_key": unique_on[0] if unique_on else first_field,
            "unique_on": unique_on,
        }
        model_name = table.get("model_name") or table.get("suggested_model_name", "")
        table["import_config"]["bundle_path"] = (
            existing_bundle_path or _derive_bundle_path(model_name)
        )
```

This changes three things:
1. Capture `existing_bundle_path` before overwriting `import_config`
2. Overwrite `import_config` with `import_key` and `unique_on` (as before)
3. Set `bundle_path` in the new `import_config` dict — using the existing value if present, falling back to `_derive_bundle_path(model_name)`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest workbook/tests/test_scaffold_workbook_schema.py::test_harden_contract_preserves_existing_bundle_path -v`
Expected: PASS

- [ ] **Step 5: Run full workbook test suite**

Run: `pytest workbook/tests/ -v`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add workbook/management/commands/scaffold_workbook_schema.py workbook/tests/test_scaffold_workbook_schema.py
git commit -m "fix(scaffold): preserve bundle_path through _harden_contract overwrite"
```

---

### Task B1: Create `fly.toml` and `fly.preview.toml`

**Files:**
- Create: `fly.toml`
- Create: `fly.preview.toml`
- Modify: `.github/workflows/deploy.yml:69-86` (fix `main` → `master`)

- [ ] **Step 1: Create `fly.toml` (production)**

Create `fly.toml` at project root:

```toml
app = "migration-workbench"
primary_region = "sjc"

[build]
  dockerfile = "Dockerfile"

[env]
  DJANGO_SETTINGS_MODULE = "migration_workbench.settings"
  DB_ENGINE = "sqlite"

[deploy]
  release_command = "python manage.py migrate --noinput"

[mounts]
  source = "migration_workbench_data"
  destination = "/data"

[[services]]
  http_checks = []
  internal_port = 8080
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

Note: `internal_port` is `8080` matching the Dockerfile's `EXPOSE 8080` and the entrypoint's Gunicorn bind address. The PORT env var is not included because the entrypoint hardcodes `--bind 0.0.0.0:8080`.

- [ ] **Step 2: Create `fly.preview.toml` (preview)**

Create `fly.preview.toml` at project root — same as production but with preview app name and smaller machine:

```toml
app = "migration-workbench-preview"
primary_region = "sjc"

[build]
  dockerfile = "Dockerfile"

[env]
  DJANGO_SETTINGS_MODULE = "migration_workbench.settings"
  DB_ENGINE = "sqlite"
  DJANGO_DEBUG = "1"

[deploy]
  release_command = "python manage.py migrate --noinput"

[mounts]
  source = "migration_workbench_preview_data"
  destination = "/data"

[[services]]
  http_checks = []
  internal_port = 8080
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

- [ ] **Step 3: Fix deploy.yml branch name**

In `.github/workflows/deploy.yml`, the `Resolve deploy parameters` step (lines 69–86) checks `$BRANCH = "main"`. The repo uses `master`. Fix:

```yaml
      - name: Resolve deploy parameters
        id: params
        run: |
          BRANCH="${{ github.event.workflow_run.head_branch }}"
          if [ "$BRANCH" = "master" ]; then
            ENVIRONMENT="production"
            FLY_CONFIG="fly.toml"
          else
            # Any preview/* branch maps to the shared preview environment.
            ENVIRONMENT="preview"
            FLY_CONFIG="fly.preview.toml"
          fi
          # Template: migration-workbench-{env} from spaces.yml provider.app_name_template
          FLY_APP="migration-workbench-${ENVIRONMENT}"
          echo "environment=${ENVIRONMENT}" >> "$GITHUB_OUTPUT"
          echo "fly_config=${FLY_CONFIG}"   >> "$GITHUB_OUTPUT"
          echo "fly_app=${FLY_APP}"         >> "$GITHUB_OUTPUT"
          echo "Resolved: env=${ENVIRONMENT}  app=${FLY_APP}  config=${FLY_CONFIG}"
```

Changed: `"main"` → `"master"` on line 73.

- [ ] **Step 4: Commit**

```bash
git add fly.toml fly.preview.toml .github/workflows/deploy.yml
git commit -m "infra: add fly.toml configs and fix deploy branch to master"
```

---

### Task B2: Gate PyPI publish on CI passing

**Files:**
- Modify: `.github/workflows/publish-pypi.yml`

- [ ] **Step 1: Add CI-status verification step to publish workflow**

Edit `.github/workflows/publish-pypi.yml`. Keep the `push: tags: v*` trigger but add a step that verifies CI passed for the same SHA before building:

The current file already has:

```yaml
on:
  push:
    tags:
      - "v*"
```

And a version verification step. Add a CI-status check step AFTER checkout and BEFORE version verification. The full updated `steps` section:

```yaml
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Verify CI passed for this SHA
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          SHA="${{ github.sha }}"
          echo "Checking CI status for commit $SHA"
          # Poll for CI workflow runs on this SHA (allow for CI to complete)
          for i in $(seq 1 10); do
            STATUS=$(gh run list -w CI --commit "$SHA" --json conclusion --jq '.[0].conclusion' 2>/dev/null || echo "")
            if [ "$STATUS" = "success" ]; then
              echo "CI passed for $SHA"
              exit 0
            elif [ "$STATUS" = "failure" ] || [ "$STATUS" = "cancelled" ]; then
              echo "CI $STATUS for $SHA — aborting publish."
              exit 1
            fi
            echo "CI status: '$STATUS' — waiting ($i/10)..."
            sleep 30
          done
          echo "CI did not complete within 5 minutes. Aborting publish."
          exit 1
      - name: Verify tag matches pyproject.toml version
        run: |
          TAG="${GITHUB_REF_NAME#v}"
          VER=$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
          if [ "$TAG" != "$VER" ]; then
            echo "::error::Tag ${GITHUB_REF_NAME} expects pyproject version ${TAG}, got ${VER}"
            exit 1
          fi
      - name: Install build tooling
        run: python -m pip install --upgrade pip build
      - name: Build sdist and wheel
        run: python -m build
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/publish-pypi.yml
git commit -m "ci: gate PyPI publish on CI passing"
```

---

### Task B3: Add ruff lint step to CI

**Files:**
- Modify: `pyproject.toml:59-67`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add ruff to dev dependencies in pyproject.toml**

In `pyproject.toml`, add `ruff` to the `dev` extras list (line 60):

```toml
[project.optional-dependencies]
dev = [
  "pytest",
  "pytest-django",
  "black",
  "ruff",
  "build>=1.2",
  "twine>=5.0",
  "interrogate>=1.5",
]
```

- [ ] **Step 2: Add lint step to CI workflow**

In `.github/workflows/ci.yml`, add a lint step between "Install dependencies" and "Run chassis gate":

```yaml
      - name: Install dependencies
        run: |
          python -m venv .venv
          .venv/bin/python -m pip install --upgrade pip
          .venv/bin/python -m pip install -e ".[dev]"
      - name: Lint
        run: |
          .venv/bin/ruff check .
          .venv/bin/ruff format --check .
      - name: Run chassis gate
        run: make chassis-gate
```

Note: Uses `.venv/bin/ruff` to ensure it's available from the dev install.

- [ ] **Step 3: Run ruff locally to see current state**

Run: `pip install ruff && ruff check . && ruff format --check .`
Expected: Some existing code may have lint issues. If so, fix them before committing:
`ruff format .` to auto-format, then `ruff check --fix .` to auto-fix, then review remaining issues.

If there are unfixable lint issues in existing code, add a `pyproject.toml` `[tool.ruff]` section with appropriate excludes for now and file a follow-up issue.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml
git commit -m "ci: add ruff lint and format check to CI"
```

If ruff required fixes to existing code:
```bash
git add -A
git commit -m "style: apply ruff formatting fixes"
```

---

### Task C1: Verify live deploy (manual)

This is a verification step, not a code change. After B1 is merged to master:

- [ ] **Step 1: Create Fly app and volume**

```bash
fly apps create migration-workbench
fly volumes create migration_workbench_data --region sjc --size 1
```

- [ ] **Step 2: Set Fly secrets**

```bash
fly secrets set DJANGO_DEBUG=0 SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(50))") DJANGO_ALLOWED_HOSTS=migration-workbench.fly.dev
```

- [ ] **Step 3: Deploy manually**

```bash
fly deploy --config fly.toml --remote-only
```

- [ ] **Step 4: Verify health endpoint**

```bash
curl -sf https://migration-workbench.fly.dev/healthz && echo "OK"
```

Expected: HTTP 200, body contains `"status": "ok"` or similar.

- [ ] **Step 5: Verify CI deploy works end-to-end**

Push a commit to master. Verify that the deploy workflow triggers and succeeds in GitHub Actions.

---

### Task C2: Verify PyPI release (manual, after version bump)

This is a verification step that happens after all code changes are committed, version bumped to 0.9.3, and tagged.

- [ ] **Step 1: Bump version**

Update `pyproject.toml`: `version = "0.9.3"`

- [ ] **Step 2: Tag and push**

```bash
git add pyproject.toml
git commit -m "release: v0.9.3"
git tag v0.9.3
git push origin master --tags
```

- [ ] **Step 3: Monitor CI**

Verify CI passes: https://github.com/MrAllatta/migration-workbench/actions

- [ ] **Step 4: Monitor PyPI publish**

After CI passes, verify the publish workflow triggers and completes: https://github.com/MrAllatta/migration-workbench/actions

- [ ] **Step 5: Verify on PyPI**

```bash
pip install migration-workbench==0.9.3
python -c "import connectors, profiler, importer, workbook, deployment"
wb --help
```

Expected: All imports succeed, `wb --help` shows subcommands.

---

## Dependency Summary

```
A1 (model_name) → independent
A2 (makefile_targets) → independent
A3 (bundle_path) → independent
B1 (fly.toml) → independent
B2 (PyPI gate) → independent
B3 (ruff lint) → before C1, C2
C1 (live deploy) → after B1
C2 (PyPI release) → after B2, all A tasks, version bump
```

All A and B tasks can proceed in parallel. C1 requires B1. C2 requires B2, all code fixes, and a version bump.