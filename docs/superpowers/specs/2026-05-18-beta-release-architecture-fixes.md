# Beta Release: Architecture Fixes and CLI Unification

**Date:** 2026-05-18
**Status:** Draft
**Applies to:** migration-workbench v0.9.2 → v1.0.0-beta

## Overview

Eight friction points from a full workflow walkthrough reveal deeper
architectural issues in the codegen pipeline.  This spec describes the fixes
as a ground-up redesign of the naming contract, output convention, CLI entry
points, and error handling.  No backward-compatibility constraints apply.

---

## 1. Contract Schema: Required `model_name` Field

### Problem

`get_model_name()` derives the Python class name from `suggested_model_name`
using `.capitalize()`, which mangles PascalCase: `SalesChannel` →
`Saleschannel`.  FK targets use dotted qualified names (`examples.ExampleFarm`)
that don't round-trip through `get_model_name()`.  The validator compares
against raw `suggested_model_name` values, not resolved model names,
producing false-positive FK warnings.

`suggested_model_name` conflates two concerns: (1) a human-readable label for
the table, and (2) the exact Python identifier for the model class.  These
should be separate.

### Design

Every table **must** have a `model_name` field holding the exact PascalCase
class name:

```yaml
tables:
  - suggested_model_name: Sales Channel    # human label — anything goes
    model_name: SalesChannel               # exact Python class name
```

#### `get_model_name()` — required, no fallback

```python
def get_model_name(table: dict[str, Any]) -> str:
    return str(table["model_name"])
```

No derivation.  No fallback.  If `model_name` is missing, the KeyError
propagates and is caught by the management command with a clear message
("table 'Sales Channel' is missing required field 'model_name'").

#### `suggested_model_name` — label only

`suggested_model_name` becomes a purely human-readable label.  It is:
- Displayed in progress messages and validation output
- Used as the seed for auto-deriving `bundle_path` (Section 7)
- Not used for any codegen resolution

#### Resolution everywhere uses `model_name`

`model_name` stores the bare PascalCase class name — no app-label prefix.

**Before:** `to: examples.ExampleFarm`  (dotted, fragile, duplicated)
**After:**  `to: ExampleFarm`            (bare, matches model_name exactly)

Cross-app imports are resolved at generation time using each table's
`model_meta.app_label`.

- FK targets in `django_field_kwargs.to` and `import_config.fk_lookup.model`
  use `model_name` values (bare, no prefix)
- `validate_contract_tables()` builds its index from `get_model_name(t)` and
  compares FK targets against it
- `_build_fk_index()` in `admin_generator.py` uses `get_model_name()` for
  target and source names
- View manifest entity lookup uses `model_name` (lowercased), not
  `suggested_model_name`

#### Validator also checks `model_name` presence

```python
def validate_contract_tables(contract):
    warnings = []
    for table in contract.get("tables", []):
        if "model_name" not in table:
            warnings.append(
                f"Table '{table.get('suggested_model_name', '?')}' "
                f"missing required 'model_name'"
            )
    # ... existing FK checks using get_model_name() ...
```

#### Scaffold

`scaffold_workbook_schema` always outputs `model_name` in every table,
derived from `suggested_model_name` by removing spaces and ensuring
PascalCase.

#### Contract version

Bump to v2.0.  `load_contract()` rejects contracts with missing `model_name`
on any table.  All existing contract fixtures and test data in the repo are
updated to include `model_name`.

### Files changed

| File | Change |
|------|--------|
| `workbook/codegen/contract.py` | Make `get_model_name()` a simple accessor. Update `validate_contract_tables()`. Add version-migration warning for v1.x contracts |
| `workbook/codegen/admin_generator.py` | Align `_build_fk_index()` and view-entity lookup to use `get_model_name()` |
| `workbook/management/commands/scaffold_workbook_schema.py` | Always output `model_name` |
| `scripts/validate_contract.py` | Update to report `model_name` presence per table |

---

## 2. Codegen Output: Separate Generated Files

### Problem

`generate_models --force` overwrites the entire `models.py`, destroying
hand-authored models like `FarmUser(AbstractUser)`.

### Design

All generated code goes into `*_auto.py` files.  Hand-authored code stays in
the base file and re-exports from generated files via an auto-maintained stub.

#### Output path defaults

| Command | Output file |
|---------|-------------|
| `generate_models` | `models_auto.py` |
| `generate_admin` | `admin_auto.py` |
| `generate_import` | `import_<app_label>.py` (unchanged — already separate) |

`--out` is optional on all commands.  When omitted, the path is derived from
`--app-label` (or auto-detected from the contract).  `--out` exists for
explicit redirection (`/dev/null`, build directories) but is not required.

#### Stub generation (always on)

Every generator creates or updates a companion stub file that re-exports the
generated classes:

**`models.py`:**
```python
# Auto-generated — do not edit manually.
from .models_auto import *  # noqa: F401, F403

# --- custom models below this line ---
```

**`admin.py`:**
```python
# Auto-generated — do not edit manually.
from .admin_auto import *  # noqa: F401, F403
```

If the stub file already exists:
- The `from .*_auto import *` line is updated to point at the current
  auto-generated file
- Everything below the `# --- custom ... ---` marker is preserved unchanged
- If the marker comment is missing, it's appended at the end of the file

#### `generate_admin` app_label fix

The command auto-detects `app_label` from the contract's `model_meta`
(like `generate_models` and `generate_import` already do), instead of
hardcoding `default="core"`.

### Files changed

| File | Change |
|------|--------|
| `workbook/management/commands/generate_models.py` | Make `--out` optional. Always generate stub `models.py`. Change default to `models_auto.py` |
| `workbook/management/commands/generate_admin.py` | Same + fix hardcoded `app_label="core"` to auto-detect from contract |
| New: `workbook/codegen/stub_writer.py` | Shared logic for writing/updating stub import files with marker preservation |

---

## 3. Unified `wb` CLI

### Problem

Codegen is only accessible via `manage.py` commands.  The `wb` CLI exists
(for deployment) but has no codegen subcommands.  The Makefile target for
contract validation uses a standalone script instead of `wb`.

### Design

`wb` becomes the canonical entry point for all workbench operations —
codegen, validation, and deployment.

#### New subcommands

```
wb generate models --contract build/schema-contract.yaml
  [--out build/models_auto.py] [--app-label core] [--force] [--diff]

wb generate admin --contract build/schema-contract.yaml
  [--out build/admin_auto.py] [--manifest build/view-manifest.yaml]
  [--app-label core] [--force] [--diff]

wb generate import --contract build/schema-contract.yaml
  [--out build/import_data.py] [--app-label core] [--force] [--diff]

wb generate manifest --contract build/schema-contract.yaml
  [--out build/view-manifest.yaml]

wb validate contract --contract build/schema-contract.yaml
  [--json] [--exit-zero]
```

#### Wrapper pattern

Each subcommand calls `_setup_django()` then invokes the management command
via `call_command()`:

```python
def _generate_models(args: argparse.Namespace) -> int:
    _setup_django()
    from workbook.management.commands.generate_models import Command
    call_command(Command, contract=args.contract, out=args.out,
                 app_label=args.app_label, force=args.force, diff=args.diff)
    return 0
```

Stdout from the management command passes through naturally.

#### Makefile

All codegen and validation targets use `wb`:

```makefile
validate-contract:
	wb validate contract --contract "$(CONTRACT)"

generate-models:
	wb generate models --contract $(CONTRACT) --out $(OUT) $(if $(FORCE),--force)

generate-admin-light:
	wb generate admin --contract $(CONTRACT) --out $(OUT) $(if $(FORCE),--force)

generate-admin:
	wb generate admin --contract $(CONTRACT) --manifest $(MANIFEST) --out $(OUT) $(if $(FORCE),--force)

generate-import:
	wb generate import --contract $(CONTRACT) --out $(OUT) $(if $(FORCE),--force)
```

Also fix the `generate-all` target to actually define the `generate-models`,
`generate-view-manifest`, and `generate-import` targets (currently listed in
`.PHONY` with no recipe — `make generate-all` silently skips them).

#### Existing `wb contract review`

The existing `wb contract review` subcommand (`wb_cli.py:681`) calls
`review_contract()` which runs design-review checks.  The new `wb validate
contract` calls `validate_contract_tables()` for structural validation.  Both
coexist.

### Files changed

| File | Change |
|------|--------|
| `deployment/wb_cli.py` | Add `generate` subcommand tree with `{models,admin,import,manifest}` and `validate contract` subcommand |
| `Makefile` | Replace `$(MANAGE)` and `$(PYTHON) scripts/...` with `wb`. Add missing `generate-models`, `generate-view-manifest`, `generate-import` targets |

---

## 4. Management Command: `validate_contract`

### Problem

No standalone validation command.  Validation only runs as a side effect of
code generation.

### Design

New management command that loads and validates a contract without generating
any code:

`workbook/management/commands/validate_contract.py`:

```python
class Command(BaseCommand):
    help = "Validate a schema-contract YAML without generating code."

    def add_arguments(self, parser):
        parser.add_argument("--contract", required=True)

    def handle(self, *args, **options):
        contract_path = Path(options["contract"])
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")

        try:
            contract = load_contract(str(contract_path))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        warnings = validate_contract_tables(contract)
        for w in warnings:
            self.stdout.write(self.style.WARNING(f"  {w}"))

        if not warnings:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Contract is valid: "
                    f"{len(contract.get('tables', []))} table(s)"
                )
            )
            return

        raise CommandError(f"{len(warnings)} validation warning(s) found")
```

The command exits 0 when clean, 1 when warnings exist (useful for CI gating).

Canonical invocation is `wb validate contract --contract ...` (Section 3).

### Files changed

| File | Change |
|------|--------|
| New: `workbook/management/commands/validate_contract.py` | Full command |
| `deployment/wb_cli.py` | Wire `validate contract` to `call_command()` |
| `scripts/validate_contract.py` | Remove — superseded by management command |

---

## 5. Error Handling: Missing `bundle_path`

### Problem

`_render_import_method()` raises a raw `ValueError` when
`import_config.bundle_path` is missing, producing an ugly Python traceback
with no remediation guidance.

### Design

Catch the `ValueError` in `generate_import.handle()` and emit a clean,
actionable error:

```python
try:
    source = render_import_py(contract, app_label=app_label)
except ValueError as exc:
    if "bundle_path" in str(exc):
        raise CommandError(
            "Import generation failed — bundle_path is missing.\n\n"
            "Each table with import_config needs a bundle_path:\n"
            "  import_config:\n"
            "    bundle_path: reference/<table_name>.csv\n\n"
            "Re-generate the contract from the scaffold, which now\n"
            "auto-generates bundle_path from the model name."
        )
    raise
```

### Files changed

| File | Change |
|------|--------|
| `workbook/management/commands/generate_import.py` | Wrap `render_import_py()` in try/except |

---

## 6. Admin Config: Contract as Source of Truth

### Problem

`generate_admin` ignores the contract's `admin:` blocks when no `--manifest`
is provided, printing a warning that the output will be bare.  When a
manifest IS provided, manifest values unconditionally override the contract's
admin config, even though the contract is the user's explicit configuration.

### Design

The contract's `admin:` blocks are authoritative.  The manifest enriches
(provides fields the contract doesn't explicitly set) but never overrides.

#### No-manifest case

`_pick_display_fields()`, `_pick_filter_fields()`, `_pick_search_fields()`,
`_pick_readonly_fields()` already accept `admin_cfg`.  When no manifest:

- `admin_cfg` is passed as-is from `get_admin_config(table)`
- `authoritative=True` when `admin_cfg` has relevant keys (list_display etc.)
- No warning about missing manifest — the contract is sufficient

#### Manifest-present case

Manifest fills gaps the contract admin block leaves open:

```python
# Contract admin block fields stay as authored.
# Manifest adds fields for positions the admin block doesn't set.
explicit = admin_cfg.get("list_display", [])
manifest_fields = view.get("suggested_display_fields", [])
# Merge: explicit fields keep their position and value,
# manifest fields are appended when not already present.
```

#### Warning removed

The "No --manifest provided. Admin will lack list_display..." message is
removed.  The contract is the source of truth.  The manifest is an optional
enrichment.

### Files changed

| File | Change |
|------|--------|
| `workbook/codegen/admin_generator.py` | Update `_pick_display_fields()` and related to prefer contract admin over manifest; remove manifest-dependency for `authoritative` |
| `workbook/management/commands/generate_admin.py` | Remove the no-manifest warning; fix `app_label` auto-detection |

---

## 7. Scaffold: Auto-derive `bundle_path`

### Problem

`scaffold_workbook_schema` produces columns but no `import_config.bundle_path`.
The `--hardened` flag adds it but is not the default.  Generated contracts
can't be used for import generation without manual editing.

### Design

`bundle_path` is always auto-derived from `suggested_model_name` (the
human-readable label), regardless of `--hardened`:

```python
def _derive_bundle_path(label: str) -> str:
    """Derive a default CSV bundle_path from a suggested model name.

    Sales Channel  -> reference/sales_channels.csv
    Farm           -> reference/farms.csv
    Address        -> reference/addresses.csv
    Business Unit  -> reference/business_units.csv
    """
    stem = label.strip().lower().replace(" ", "_")
    plural = stem + "es" if stem.endswith("s") else stem + "s"
    return f"reference/{plural}.csv"
```

When `import_config` already has an explicit `bundle_path` (from a table
profile or bundle config), the scaffold respects it.  Auto-derive is the
fallback.

The `--hardened` flag continues to control other production defaults (data
types, constraints, field transforms) but no longer controls `bundle_path`.

### Files changed

| File | Change |
|------|--------|
| `workbook/management/commands/scaffold_workbook_schema.py` | Add `_derive_bundle_path()`; call for each table's `import_config` outside the hardened guard |

---

## Implementation Order

Each step builds on the previous.  No step should break the test suite.

1. **`model_name` field** (Section 1) — contract.py, admin_generator.py, scaffold.
   Update example contracts and tests.  Run all tests.
2. **`bundle_path` auto-derive** (Section 7) — scaffold only.  Small, trivial.
3. **Error handling** (Section 5) — generate_import.py catch.  Small.
4. **`validate_contract` command** (Section 4) — new file, independent.
5. **Admin config priority** (Section 6) — admin_generator.py logic change.
6. **Separate generated files** (Section 2) — generators + new stub_writer.py.
7. **Unified wb CLI** (Section 3) — wb_cli.py + Makefile.
