# Beta Release: Architecture Fixes and CLI Unification

**Date:** 2026-05-18
**Status:** Draft
**Applies to:** migration-workbench v0.9.1 → v1.0.0-beta

## Overview

Eight friction points encountered during a full workflow walkthrough reveal deeper
architectural issues in the migration-workbench codegen pipeline. This spec
describes the foundation changes needed to resolve them.  All changes are
designed to be **backward-compatible**: existing contracts continue to work with
no modifications.

---

## 1. Contract Schema: Explicit `model_name` Field

### Problem

`get_model_name()` (workbook/codegen/contract.py:134-139) derives the Python
class name from `suggested_model_name` via `.capitalize()`, which mangles
PascalCase: `SalesChannel` → `Saleschannel`. FK targets use dotted qualified
names (`examples.ExampleFarm`) that don't round-trip through
`get_model_name()`. The validator (`validate_contract_tables()` at
contract.py:378-435) compares against raw `suggested_model_name` values, not
the resolved model names, producing false-positive FK warnings.

### Design

Add an optional `model_name` field to each table entry in the schema contract:

```yaml
tables:
  - suggested_model_name: SalesChannel
    model_name: SalesChannel
```

#### `get_model_name()` changes (contract.py:134-139)

```python
def _to_pascal_case(raw: str) -> str:
    """Convert snake_case or kebab-case to PascalCase."""
    parts = raw.replace("-", "_").split("_")
    return "".join(p.capitalize() for p in parts if p) or "Model"

def get_model_name(table: dict[str, Any]) -> str:
    explicit = table.get("model_name")
    if explicit and isinstance(explicit, str):
        return explicit
    raw = str(table.get("suggested_model_name") or "model")
    return _to_pascal_case(raw)
```

#### `validate_contract_tables()` changes (contract.py:378-435)

Build the table-names index from `get_model_name(t)` instead of
`suggested_model_name`. Compare FK targets against this resolved index.
The `table_names` set at line 393 already calls `get_model_name()` — this is
correct but the *field-level* FK target (`field["kwargs"].get("to")`) may
still use `suggested_model_name`. The `_build_fk_index()` helper in
admin_generator.py also needs alignment.

#### Scaffold changes (scaffold_workbook_schema.py)

The scaffold auto-populates `model_name` by running `_to_pascal_case()` on
`suggested_model_name` when no explicit `model_name` is provided in the bundle
config.

#### Contract versioning

The `model_name` field is optional — contracts without it continue to work via
the fallback path.  No version bump required.  FH targets that use
`suggested_model_name` values (rather than `model_name`) continue to resolve
correctly because `get_model_name()` is the single source of truth.

### Files changed

| File | Change |
|------|--------|
| `workbook/codegen/contract.py` | Add `_to_pascal_case()`. Modify `get_model_name()`. Align `validate_contract_tables()` |
| `workbook/codegen/admin_generator.py` | Align `_build_fk_index()` to use `get_model_name()` for target comparison |
| `workbook/management/commands/scaffold_workbook_schema.py` | Populate `model_name` from `suggested_model_name` |
| `workbook/codegen/import_generator.py` | Verify FK target references use consistent naming |

---

## 2. Codegen Output: Separate Generated Files

### Problem

`generate_models --force` overwrites the entire `models.py`, destroying
hand-authored models like `FarmUser(AbstractUser)`. Django immediately fails
with `ImproperlyConfigured: AUTH_USER_MODEL refers to model 'core.FarmUser'
that has not been installed`.

### Design

Generated code goes into `*_auto.py` files. Hand-authored code stays in the
base file and imports from generated files.

#### Output path defaults

| Command | Old default | New default |
|---------|-------------|-------------|
| `generate_models` | `models.py` (required `--out`) | `models_auto.py` (omittable `--out`) |
| `generate_admin` | `admin.py` (required `--out`) | `admin_auto.py` (omittable `--out`) |
| `generate_import` | `import_<label>.py` (auto-derived) | Unchanged (already separate) |

#### `--out` behavior

- When `--out PATH` is provided explicitly, write to that exact path (current
  behavior, fully backward-compatible).
- When `--out` is omitted, write to `{app_dir}/{models_auto,admin_auto}.py`.
  If the `--app-label` directory doesn't exist, error with guidance.

#### `--with-stub` flag (both commands)

Generates (or updates) the companion base file that re-exports everything:

**`models.py`:**
```python
# Auto-generated stub — do not edit manually.
from .models_auto import *  # noqa: F401, F403

# --- custom models below this line ---
```

If `models.py` already exists, only the first line is updated (the import
line), preserving any hand-authored models below the marker comment.  If no
marker comment exists, it's appended at the end.

**`admin.py`:**
```python
# Auto-generated stub — do not edit manually.
from .admin_auto import *  # noqa: F401, F403
```

#### Backward compatibility

Existing workflows that pass `--out backend/apps/core/models.py` continue to
write to that exact path.  Only users who omit `--out` (or migrate to the new
default) get the separate-file behavior.  The `--force` flag works identically
on both paths.

### Files changed

| File | Change |
|------|--------|
| `workbook/management/commands/generate_models.py` | Make `--out` optional. Add `--with-stub`. Change default to `models_auto.py` |
| `workbook/management/commands/generate_admin.py` | Same changes + fix hardcoded `app_label="core"` to auto-detect from contract |
| New helper: `workbook/codegen/stub_writer.py` | Shared logic for writing/updating stub import files |
| `Makefile` | Update `generate-admin-light`, `generate-admin` targets if needed |

---

## 3. Unified `wb` CLI

### Problem

Codegen is only accessible via `manage.py` commands while `wb` is a separate
deployment CLI.  The Makefile target for contract validation uses
`scripts/validate_contract.py` instead of `wb`.  Users must know two entry
points and have the package installed.

### Design

Add `generate` and `validate` subcommands to `wb` that thin-wrap the Django
management commands:

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

#### Wrapper pattern (wb_cli.py)

Each `generate` subcommand:
1. Calls `_setup_django()` with the project's settings module
2. Calls `call_command(CommandClass, **kwargs)` with the Django management
   command's class directly
3. Stdout/stderr pass through naturally

```python
def _generate_models(args: argparse.Namespace) -> int:
    _setup_django()
    from workbook.management.commands.generate_models import Command
    call_command(Command, contract=args.contract, out=args.out,
                 app_label=args.app_label, force=args.force, diff=args.diff)
    return 0
```

#### Makefile alignment

```makefile
CONTRACT ?= build/schema-contract.yaml
OUT ?= build/out.py

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

#### Existing `wb contract review` command

The `wb contract review` subcommand already exists at `wb_cli.py:681-685` and
calls `review_contract()` (different from `validate_contract_tables()` —
design review checks vs structural validation).  The new `wb validate contract`
is a separate code path that wraps the management command.  Both coexist.

### Files changed

| File | Change |
|------|--------|
| `deployment/wb_cli.py` | Add `generate` and `validate` subcommand trees with wrappers |
| `Makefile` | Replace `$(MANAGE)` and `$(PYTHON) scripts/...` with `wb` equivalents |
| `pyproject.toml` | No change needed — `wb` entry point already registered |

---

## 4. Management Command: `validate_contract`

### Problem

No standalone validation command.  Validation only runs as a side effect of
`generate_models` / `generate_import` / `generate_admin` — coupling validation
to code generation.

### Design

New management command at
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
            self.stdout.write(self.style.WARNING(f"  validation: {w}"))

        if not warnings:
            self.stdout.write(
                self.style.SUCCESS(f"Contract is valid: {len(contract.get('tables',[]))} table(s)")
            )
        else:
            raise CommandError(f"{len(warnings)} validation warning(s) found")
```

Also available as `wb validate contract` (see Section 3).

### Files changed

| File | Change |
|------|--------|
| New: `workbook/management/commands/validate_contract.py` | Full command implementation |
| `deployment/wb_cli.py` | Wire `validate contract` to use `call_command(Command, ...)` |

---

## 5. Error Handling: Missing `bundle_path`

### Problem

`_render_import_method()` (import_generator.py:393-398) raises a raw
`ValueError` when `import_config.bundle_path` is missing, which propagates
as an ugly Python traceback with no remediation guidance.

### Design

Catch the `ValueError` in `generate_import.handle()` and emit a clean error:

```python
try:
    source = render_import_py(contract, app_label=app_label)
except ValueError as exc:
    if "bundle_path" in str(exc):
        raise CommandError(
            f"Import generation failed: {exc}\n\n"
            "To fix, run:\n"
            f"  manage.py scaffold_workbook_schema --hardened --out config/contract.yaml\n"
            "Or add bundle_path to each table's import_config section in the contract."
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

When `generate_admin` runs with no `--manifest`, the contract's `admin:`
blocks (which can include `list_display`, `list_filter`, `search_fields`,
`readonly_fields`, `inlines`, etc.) are ignored.  The command prints a
warning implying the output will be bare.

When a manifest IS provided, manifest values unconditionally override the
contract's admin config, even though the contract is the user's explicit
configuration.

### Design

#### No-manifest case (admin_generator.py)

`_pick_display_fields()`, `_pick_filter_fields()`, `_pick_search_fields()`,
`_pick_readonly_fields()` already accept `admin_cfg` as a parameter.  When no
manifest is provided at all:

- Pass `admin_cfg=get_admin_config(table)` (already done)
- Pass `view=None` (already done)
- The `authoritative` flag becomes `True` when `admin_cfg` is non-empty,
  meaning the contract's `admin:` fields are used as-is rather than being
  auto-inferred from field types

This is already partially implemented — the `authoritative` parameter exists.
The change is to set `authoritative=True` when `admin_cfg` has the relevant
keys (list_display, etc.), even without a manifest.

#### Manifest-present case (admin_generator.py)

Change priority: contract admin block values take precedence over manifest
values for the same field name.  Manifest values fill in fields that the
contract admin block doesn't explicitly set.

In `_pick_display_fields()` and friends:

```python
# If admin_cfg explicitly sets list_display, those are authoritative.
# Manifest fields are added only for positions not in the admin list.
if admin_cfg.get("list_display"):
    return list(admin_cfg["list_display"])
# Otherwise, prefer explicit admin fields to inferred manifest fields.
```

#### Warning message update (generate_admin.py)

Change from:
```
No --manifest provided. Admin will lack list_display, list_filter,
and readonly_fields.
```

To:
```
No --manifest provided. Using contract admin: blocks for admin config.
Re-run with --manifest after 'make pull-bundle' to enrich with
field-level hints from bundle data.
```

### Files changed

| File | Change |
|------|--------|
| `workbook/codegen/admin_generator.py` | Update `_pick_display_fields()` and related to prefer contract admin over manifest |
| `workbook/management/commands/generate_admin.py` | Update warning message, fix `app_label` default detection |

---

## 7. Scaffold: Auto-derive `bundle_path`

### Problem

`scaffold_workbook_schema` produces columns but no `import_config.bundle_path`.
The `--hardened` flag adds it but is not the default and its purpose isn't
documented in the command help.  Generated contracts can't be used for import
generation without manual editing.

### Design

Even in non-hardened mode, auto-derive `bundle_path` from
`suggested_model_name`:

```python
def _derive_bundle_path(suggested_model_name: str) -> str:
    """Derive a default CSV bundle_path from a suggested model name.

    Examples:
        SalesChannel -> reference/sales_channels.csv
        Farm         -> reference/farms.csv
        Address      -> reference/addresses.csv
        Person       -> reference/persons.csv
    """
    rough = suggested_model_name.replace(" ", "_").lower()
    # Crude pluralization: add "es" if ends in s, add "s" otherwise.
    if rough.endswith("s"):
        plural = rough + "es"
    else:
        plural = rough + "s"
    return f"reference/{plural}.csv"
```

The logic is intentionally simple and predictable — users override it in their
contract when needed.  The key is that the scaffold produces a *working*
contract out of the box.

When `import_config` already has an explicit `bundle_path` (from a table
profile or bundle config), the scaffold respects it.  Only auto-derive when
no `bundle_path` exists.

### Files changed

| File | Change |
|------|--------|
| `workbook/management/commands/scaffold_workbook_schema.py` | Add `_derive_bundle_path()`, call for each table's `import_config` block |
| `workbook/management/commands/scaffold_workbook_schema.py` | Update `--help` to mention bundle_path auto-generation |

---

## Implementation Order

The changes should be implemented in this order (each step builds on the
previous):

1. **`model_name` field** (Section 1) — foundation contract change
2. **`bundle_path` auto-derive** (Section 7) — trivial addition on scaffold
3. **Error handling** (Section 5) — small, self-contained catch
4. **`validate_contract` command** (Section 4) — new command, no side effects
5. **Admin config priority** (Section 6) — codegen logic change
6. **Separate generated files** (Section 2) — output convention change
7. **Unified wb CLI** (Section 3) — CLI entry points + Makefile update

---

## Compatibility Notes

- **Contract v1.0–1.3**: All existing contracts remain valid.  The `model_name`
  field is optional.  The fallback path in `get_model_name()` is designed to
  produce the same output as current code for snake_case input.
- **Existing generated files**: Files at explicit `--out` paths are unchanged.
  Only users who omit `--out` see the new default paths.
- **Existing Makefiles**: Targets using `manage.py` continue to work.  The
  Makefile changes in this spec are additions/new defaults, not removals.
- **`wb` CLI**: The existing `wb contract review` subcommand is unchanged.
  New subcommands are additive.
