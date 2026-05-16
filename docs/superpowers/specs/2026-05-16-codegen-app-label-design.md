# Codegen App Label Pipeline — Design

**Date:** 2026-05-16
**Status:** Draft

## Summary

Fix the `chassis-gate` CI failure caused by `generate_import` producing `from core.models import Clients` when `core` is not a Django app in this project. Address both the immediate smoke test breakage and the underlying architectural issue: the scaffold → codegen pipeline doesn't pass the app_label through the contract.

## Current state

- `scaffold_workbook_schema` accepts `--models-app-label` (default `"domain"`) but only uses it for the optional models stub `db_table` prefix — it is NOT stored in the contract YAML.
- `generate_import --app-label` defaults to `"core"` (no connection to the scaffold's default).
- `generate_models --app-label` defaults to `"core"` (ditto).
- The `chassis-gate` Makefile target (line 142) runs `generate_import` on a scaffolded contract without `--app-label`. The generated code says `from core.models import Clients`. The validation step (line 143) fails with `ModuleNotFoundError: No module named 'core'`.

The contract already supports per-table `model_meta.app_label` (used by `get_db_table_name()` in `contract.py:160`), but nothing writes it.

## Part 1: Store app_label in contract during scaffold

**File:** `workbook/management/commands/scaffold_workbook_schema.py`

Before writing the contract YAML, inject `model_meta.app_label` into each table entry using the value from `--models-app-label`.

```python
# In handle(), before YAML dump:
app_label = options["models_app_label"]
for table in contract.get("tables", []):
    meta = table.setdefault("model_meta", {})
    meta.setdefault("app_label", app_label)  # don't override if already set
```

**Contract before:**
```yaml
tables:
  - suggested_model_name: "Clients"
    columns: [...]
```

**Contract after:**
```yaml
tables:
  - suggested_model_name: "Clients"
    columns: [...]
    model_meta:
      app_label: "domain"
```

This makes the contract self-describing. No new CLI arguments needed.

## Part 2: Codegen reads app_label from contract

### `workbook/management/commands/generate_import.py`

Change app_label resolution from:
1. `options["app_label"]` (CLI arg, default `"core"`)

To:
1. `options["app_label"]` — explicit CLI override (if passed)
2. Per-table `model_meta.app_label` from contract — for each table with `import_config`
3. `"core"` — backward-compatible fallback if contract lacks app_label

In practice this means: after loading the contract, extract the app_label from the contract tables. If all tables with `import_config` share the same app_label, use that. Otherwise fall back to the CLI arg.

Implementation: change `--app-label` default from `"core"` to `None`, then resolve in `handle()`:

```python
# parser.add_argument("--app-label", default=None, ...)
app_label = options["app_label"]
if app_label is None:
    # Try to read from contract tables
    for table in contract.get("tables", []):
        meta = table.get("model_meta") or {}
        if meta.get("app_label"):
            app_label = meta["app_label"]
            break
    if app_label is None:
        app_label = "core"  # backward-compatible fallback
```

Changed files:
- `workbook/management/commands/generate_import.py` — app_label resolution logic
- `workbook/codegen/import_generator.py` — no change needed (already uses `app_label` parameter)

### `workbook/management/commands/generate_models.py`

Same pattern: read `model_meta.app_label` from the contract when `--app-label` is not explicitly provided.

Changed files:
- `workbook/management/commands/generate_models.py` — app_label resolution logic
- `workbook/codegen/model_generator.py` — no change needed (already uses `app_label` parameter)

## Part 3: chassis-gate smoke test fix

**File:** `Makefile` (lines 139, 142-143)

After scaffold generates the contract with `app_label: "domain"`, the smoke test needs a real `domain` Django app for the import validation.

### Step 1 — Create temp app and generate models

Replace line 139 (currently `generate_models --out /dev/null`) with generating into a temp app:

```makefile
mkdir -p build/_out/domain
touch build/_out/domain/__init__.py
DB_ENGINE=sqlite $(MANAGE) generate_models \
    --contract build/_out/schema-contract-smoke.yaml \
    --out build/_out/domain/models.py --force
```

(The app_label `"domain"` is now read automatically from the contract — no `--app-label` needed.)

### Step 2 — Write custom settings & migrate

```makefile
printf 'import os, sys\nsys.path.insert(0, os.path.dirname(__file__))\nfrom migration_workbench.settings import *\nINSTALLED_APPS = list(INSTALLED_APPS) + ["domain"]\n' \
    > build/_out/chassis_gate_settings.py
DB_ENGINE=sqlite DJANGO_SETTINGS_MODULE=chassis_gate_settings \
    PYTHONPATH=build/_out:$$PYTHONPATH \
    $(MANAGE) migrate domain --run-syncdb
```

This creates a temporary settings module that extends the real settings and adds `domain` to `INSTALLED_APPS`.

### Step 3 — Generate import (reads domain from contract automatically)

Line 142 stays similar but no longer needs `--app-label`:

```makefile
DB_ENGINE=sqlite $(MANAGE) generate_import \
    --contract build/_out/schema-contract-smoke.yaml \
    --out build/_out/import_data.py --force
```

### Step 4 — Validate against the temp app

```makefile
DB_ENGINE=sqlite DJANGO_SETTINGS_MODULE=chassis_gate_settings \
    PYTHONPATH=build/_out:$$PYTHONPATH \
    $(MANAGE) shell -c "from import_data import Command; from importer.base import BaseImportCommand; assert issubclass(Command, BaseImportCommand); print('import validation: OK')"
```

### Cleanup

The `build/_out/` directory is ephemeral (already cleaned by CI). No cleanup needed.

## File change summary

| File | Change |
|------|--------|
| `workbook/management/commands/scaffold_workbook_schema.py` | Store `--models-app-label` in each table's `model_meta.app_label` before writing YAML |
| `workbook/management/commands/generate_import.py` | Read `model_meta.app_label` from contract when `--app-label` not explicitly provided |
| `workbook/management/commands/generate_models.py` | Same — read `model_meta.app_label` from contract when `--app-label` not explicitly provided |
| `Makefile` | Replace `/dev/null` models gen with temp app; add settings override, migrate, and validation steps |

## Testing

- Existing unit tests for `generate_import` and `generate_models` that pass `--app-label` should continue to work unchanged.
- The `chassis-gate` target is the functional test — verify green CI after changes.
- Contracts without `model_meta.app_label` still fall back to `"core"` (backward compat).
