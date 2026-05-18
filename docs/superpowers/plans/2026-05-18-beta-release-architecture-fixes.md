# Beta Release Architecture Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the 7-section architecture spec for migration-workbench v1.0.0-beta — required `model_name` field, separate generated files, unified `wb` CLI, standalone validation, clean error handling, admin config priority, auto-derived `bundle_path`.

**Architecture:** Each task builds on the previous. Task 1 is the foundation (contract.py changes ripple everywhere). Tasks 2-3 update fixtures and examples to match. Tasks 4-9 layer on independent fixes. The `wb` CLI unification (task 9) is the capstone.

**Tech Stack:** Python 3.11+, Django 5.x, argparse, PyYAML

---

### Task 1: Required `model_name` field — contract.py + conftest.py + primary fixtures

**Files:**
- Create: `workbook/tests/conftest.py`
- Modify: `workbook/codegen/contract.py:134-139, 378-435, 81-131`
- Modify: `workbook/tests/test_model_generator.py` (fixtures + model_name tests)
- Modify: `workbook/tests/test_contract_diff.py` (`_make_table`)
- Modify: `workbook/tests/test_contract_review.py` (inline fixtures)
- Modify: `workbook/tests/test_contract_validation.py` (inline fixtures)
- Modify: `workbook/tests/test_admin_generator.py` (`_contract` + inline fixtures)
- Modify: `workbook/tests/test_import_generator.py` (all fixture functions)
- Modify: `workbook/tests/test_codegen_force_overwrite.py` (`_contract`)
- Modify: `workbook/tests/test_contract_includes.py` (YAML strings)
- Modify: `workbook/tests/test_view_manifest.py` (inline fixtures)
- Modify: `workbook/tests/test_generate_pipeline_manifest.py` (`_contract_yaml`)
- Modify: `workbook/tests/test_pipeline_manifest.py` (`_minimal_contract`)
- Modify: `workbook/tests/test_discovery.py` (inline fixture)
- Modify: `workbook/tests/test_designed_model_detection.py` (inline fixtures)
- Modify: `workbook/tests/test_schema_contract.py` (inline fixtures)
- Modify: `workbook/tests/test_generate_models_command.py` (YAML string)
- Modify: `workbook/tests/test_generate_import_command.py` (YAML string)
- Modify: `workbook/tests/test_generate_source_config.py` (YAML string)
- Modify: `workbook/tests/test_makefile_targets.py` (if it has contract fixtures)

- [ ] **Step 1: Create `workbook/tests/conftest.py`**

```python
"""Shared test helpers for workbook tests."""

from __future__ import annotations

from typing import Any


def make_table(suggested_model_name: str, **overrides: Any) -> dict[str, Any]:
    """Build a minimal contract table dict with required fields.

    Derives model_name from suggested_model_name using PascalCase
    (snake_case input -> PascalCase output).
    """
    model_name = "".join(
        p.capitalize() for p in suggested_model_name.replace("-", "_").split("_")
    )
    return {
        "suggested_model_name": suggested_model_name,
        "model_name": model_name,
        **overrides,
    }
```

- [ ] **Step 2: Update `get_model_name()` in `contract.py:134-139`**

Replace the current function:

```python
def get_model_name(table: dict[str, Any]) -> str:
    """Return the PascalCase Django model class name from *table*.

    Reads the required ``model_name`` field.  Raises KeyError if absent.
    """
    return str(table["model_name"])
```

- [ ] **Step 3: Update `load_contract()` in `contract.py:81-131` to validate model_name**

After loading and normalizing the contract, add a validation pass:

```python
def _validate_contract_v2(contract: dict[str, Any]) -> None:
    """Check v2.0 contract requirements.  Raises ValueError on violation."""
    for table in contract.get("tables", []):
        label = table.get("suggested_model_name", "?")
        if "model_name" not in table:
            raise ValueError(
                f"Table '{label}' is missing required field 'model_name'"
            )
        mn = str(table["model_name"]).strip()
        if not mn:
            raise ValueError(
                f"Table '{label}' has empty 'model_name'"
            )
```

Call `_validate_contract_v2(contract)` at the end of `load_contract()`.

- [ ] **Step 4: Update `validate_contract_tables()` in `contract.py:378-435`**

The function already uses `get_model_name(t)` for its index (line 393). Add a check for `model_name` presence (belt-and-suspenders — load_contract also checks):

```python
def validate_contract_tables(contract: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    tables = list(contract.get("tables") or [])

    for table in tables:
        if "model_name" not in table:
            warnings.append(
                f"Table '{table.get('suggested_model_name', '?')}' "
                f"missing required 'model_name'"
            )
            continue

    table_names = {get_model_name(t) for t in tables if "model_name" in t}

    for table in tables:
        if "model_name" not in table:
            continue
        name = get_model_name(table)
        fields = get_fields(table)
        field_names = {f["name"] for f in fields}

        for field in fields:
            if field["class"] != "models.ForeignKey":
                continue
            fk_to = field["kwargs"].get("to")
            if fk_to and fk_to not in table_names and fk_to != "self":
                warnings.append(
                    f"{name}.{field['name']}: FK target \"{fk_to}\" "
                    f"is not a table in the contract"
                )

        import_cfg = get_import_config(table)
        if import_cfg:
            fk_lookup = import_cfg.get("fk_lookup") or {}
            for fk_field, fk_cfg in fk_lookup.items():
                if fk_field not in field_names:
                    warnings.append(
                        f"{name}.import_config.fk_lookup.{fk_field}: "
                        f"references a field not in the model"
                    )
                target = fk_cfg.get("model")
                if target and target not in table_names:
                    warnings.append(
                        f"{name}.import_config.fk_lookup.{fk_field}: "
                        f"FK target \"{target}\" is not a table in the contract"
                    )

            unique_on = import_cfg.get("unique_on") or []
            seen: set[str] = set()
            for f in unique_on:
                if f in seen:
                    warnings.append(
                        f"{name}.import_config.unique_on: \"{f}\" appears more than once"
                    )
                seen.add(f)

    return warnings
```

- [ ] **Step 5: Update `test_model_generator.py` fixtures + tests**

Add `model_name` to `_contract_v1_0()` and `_contract_v1_1()`:

```python
def _contract_v1_0():
    return {
        "version": "1.0",
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [...],
            },
            {
                "suggested_model_name": "planting",
                "model_name": "Planting",
                "columns": [...],
            },
        ]
    }
```

Update `test_get_model_name` (line 306):

```python
def test_get_model_name():
    table = {"suggested_model_name": "crop_block", "model_name": "CropBlock"}
    assert get_model_name(table) == "CropBlock"

    table2 = {"suggested_model_name": "sales_channel", "model_name": "SalesChannel"}
    assert get_model_name(table2) == "SalesChannel"
```

Remove the old `_to_pascal_case` test if it existed (the derivation logic now lives only in the test helper).

- [ ] **Step 6: Update `test_contract_diff.py`**

The `_make_table()` helper at line 11:

```python
def _make_table(suggested_model_name, **overrides):
    model_name = "".join(
        p.capitalize() for p in suggested_model_name.replace("-", "_").split("_")
    )
    return {
        "suggested_model_name": suggested_model_name,
        "model_name": model_name,
        **overrides,
    }
```

- [ ] **Step 7: Update all remaining fixtures in task-1 test files**

For each fixture function in the files listed above, add `"model_name": "<PascalCase>"` to every table dict.  The mapping from snake_case `suggested_model_name` to PascalCase `model_name` is mechanical:

| suggested_model_name | model_name |
|---|---|
| crop | Crop |
| planting | Planting |
| widget | Widget |
| farm_user | FarmUser |
| order | Order |
| crop_block | CropBlock |
| crop_plan_entry | CropPlanEntry |
| field_block | FieldBlock |
| market_entry | MarketEntry |
| field_record | FieldRecord |
| example_crop | ExampleCrop |
| example_block | ExampleBlock |
| inventory | Inventory |
| person | Person |
| orders | Orders |
| crop_plan | CropPlan |

For YAML-string fixtures (test_contract_includes.py, test_generate_models_command.py, etc.), add `model_name` inline in the YAML:

```yaml
tables:
  - suggested_model_name: Widget
    model_name: Widget
    columns: [...]
```

- [ ] **Step 8: Run tests to verify everything passes**

Run: `cd /home/user/migration-workbench && python -m pytest workbook/tests/ -x --tb=short 2>&1 | tail -40`
Expected: all tests pass.  If failures occur, the most likely cause is a fixture missing `model_name` — add it.

- [ ] **Step 9: Run the full test suite**

Run: `cd /home/user/migration-workbench && python -m pytest -x --tb=short 2>&1 | tail -40`
Expected: All Django tests pass (importers, connectors, profiler, etc.)

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: require model_name field on all contract tables

get_model_name() now reads model_name directly with no fallback.
load_contract() validates model_name presence.
All test fixtures updated to include model_name."
```

---

### Task 2: Update example contract + FK targets

**Files:**
- Modify: `example_data/import_pipeline_contract.example.yaml`
- Modify: `workbook/codegen/admin_generator.py` (view entity lookup)

- [ ] **Step 1: Update `example_data/import_pipeline_contract.example.yaml`**

Add `model_name` to each table and change FK targets from dotted to bare:

```yaml
tables:
  - suggested_model_name: ExampleFarm
    model_name: ExampleFarm
    bundle_worksheet_title: Farms
    columns:
      - source_column: "Farm Name"
        suggested_field_name: name
        ...
      # FK columns use bare model_name:
      - source_column: Farm
        suggested_field_name: farm
        django_field_class: models.ForeignKey
        django_field_kwargs:
          to: ExampleFarm    # was: examples.ExampleFarm
          on_delete: models.CASCADE
          related_name: fields
    import_config:
      ...
      fk_lookup:
        farm: { model: "ExampleFarm", on: name }  # was: examples.ExampleFarm
```

Apply to all three tables and all FK targets.  `examples.ExampleFarm` → `ExampleFarm`, `examples.ExampleCrop` → `ExampleCrop`.

- [ ] **Step 2: Update view entity lookup in `admin_generator.py`**

At line 509, the manifest lookup uses `suggested_model_name` lowercased:

```python
raw_entity = str(table.get("suggested_model_name") or "").lower()
```

Change to use `model_name`:

```python
raw_entity = get_model_name(table).lower()
```

Also update the inline-override lookup at line 526:

```python
ref_entity = str(ref_table.get("suggested_model_name") or "").lower()
```

Change to:

```python
ref_entity = get_model_name(ref_table).lower()
```

- [ ] **Step 3: Verify the example contract loads**

Run: `cd /home/user/migration-workbench && python -c "
from workbook.codegen.contract import load_contract
c = load_contract('example_data/import_pipeline_contract.example.yaml')
for t in c['tables']:
    print(t['model_name'], '-', len(t['columns']), 'columns')
"`

Expected: three tables print with correct model names.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: update example contract with model_name and bare FK targets"
```

---

### Task 3: Scaffold — model_name output + bundle_path auto-derive

**Files:**
- Modify: `workbook/management/commands/scaffold_workbook_schema.py`
- Test: `workbook/tests/test_scaffold_workbook_schema.py`

- [ ] **Step 1: Add `_derive_bundle_path()` and `_to_pascal_case()` to scaffold**

Near the top of `scaffold_workbook_schema.py`, add:

```python
def _to_pascal_case(raw: str) -> str:
    """Convert a label to PascalCase."""
    return "".join(p.capitalize() for p in raw.replace("-", "_").split("_"))


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

- [ ] **Step 2: Populate `model_name` in the scaffold's table builder**

Find where each table dict is built in the scaffold (look for where `suggested_model_name` is assigned).  After setting `suggested_model_name`, add:

```python
table_entry["model_name"] = _to_pascal_case(
    table_entry.get("suggested_model_name", "")
)
```

- [ ] **Step 3: Auto-derive `bundle_path` outside the hardened guard**

Find the section where `import_config` is populated.  Currently `bundle_path` is only set inside the `if self.hardened:` block.  Move it outside:

```python
import_config = table_entry.setdefault("import_config", {})
if "bundle_path" not in import_config:
    import_config["bundle_path"] = _derive_bundle_path(
        table_entry.get("suggested_model_name", "")
    )
```

Leave the rest of the `--hardened` logic unchanged (data types, constraints, field transforms, etc.).

- [ ] **Step 4: Update scaffold test to verify model_name and bundle_path**

Read `test_scaffold_workbook_schema.py` to understand the existing test
pattern (it reads from JSON profile files and checks the output contract).
Then add a test that:

```python
def test_scaffold_output_includes_model_name_and_bundle_path(tmp_path):
    """Every scaffold output table has model_name and bundle_path."""
    from django.core.management import call_command
    # Use the same profile fixture files as existing tests.
    # (The test runner provides actual JSON fixture paths via a fixture
    #  or conftest — locate the pattern used by the file.)
    ...
    contract = load_contract(str(out_path))
    for table in contract["tables"]:
        assert "model_name" in table, f"missing model_name in {table}"
        ic = table.get("import_config") or {}
        if ic:
            assert "bundle_path" in ic, f"missing bundle_path in {table['model_name']}"
```

Use the same fixture files and invocation pattern as existing tests in
`test_scaffold_workbook_schema.py`.  Place the assertion inline using
those fixtures.

- [ ] **Step 5: Run scaffold tests**

Run: `cd /home/user/migration-workbench && python -m pytest workbook/tests/test_scaffold_workbook_schema.py -x --tb=short 2>&1 | tail -30`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: scaffold always outputs model_name and auto-derives bundle_path"
```

---

### Task 4: generate_import error handling for missing bundle_path

**Files:**
- Modify: `workbook/management/commands/generate_import.py`

- [ ] **Step 1: Wrap `render_import_py()` in try/except**

In `generate_import.py` around line 124, replace:

```python
source = render_import_py(contract, app_label=app_label)
```

With:

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

- [ ] **Step 2: Write a test for the error path**

In `test_generate_import_command.py`, add:

```python
def test_generate_import_missing_bundle_path(tmp_path, capsys):
    """generate_import emits a clean error when bundle_path is missing."""
    from io import StringIO
    from django.core.management import call_command
    from django.core.management.base import CommandError

    contract = tmp_path / "contract.yaml"
    contract.write_text("""\
version: "2.0"
tables:
  - suggested_model_name: Widget
    model_name: Widget
    columns:
      - source_column: Name
        suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 200}
    import_config:
      tier: 1
      # no bundle_path
""")

    out = tmp_path / "import_test.py"
    with pytest.raises(CommandError, match="bundle_path"):
        call_command("generate_import", contract=str(contract), out=str(out))
```

- [ ] **Step 3: Run the test**

Run: `cd /home/user/migration-workbench && python -m pytest workbook/tests/test_generate_import_command.py -x --tb=short -v 2>&1 | tail -20`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "fix: clean error message for missing bundle_path in generate_import"
```

---

### Task 5: validate_contract management command

**Files:**
- Create: `workbook/management/commands/validate_contract.py`
- Delete: `scripts/validate_contract.py`
- Modify: `deployment/wb_cli.py` (wire into CLI)
- Test: `workbook/tests/test_contract_validation.py` (add command tests)

- [ ] **Step 1: Create `workbook/management/commands/validate_contract.py`**

```python
"""Validate a schema-contract YAML without generating code.

Usage:
    python manage.py validate_contract --contract build/schema-contract.yaml

Exits 0 when clean, 1 when warnings exist.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from workbook.codegen.contract import load_contract, validate_contract_tables


class Command(BaseCommand):
    help = "Validate a schema-contract YAML without generating code."

    def add_arguments(self, parser):
        parser.add_argument(
            "--contract",
            required=True,
            help="Path to schema-contract YAML (e.g. build/schema-contract.yaml)",
        )

    def handle(self, *args, **options):
        contract_path = Path(options["contract"])
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")

        try:
            contract = load_contract(str(contract_path))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        warnings = validate_contract_tables(contract)

        if not warnings:
            count = len(contract.get("tables", []))
            self.stdout.write(
                self.style.SUCCESS(
                    f"Contract is valid: {count} table(s)"
                )
            )
            return

        for w in warnings:
            self.stdout.write(self.style.WARNING(f"  {w}"))

        raise CommandError(f"{len(warnings)} validation warning(s) found")
```

- [ ] **Step 2: Write tests for the command**

In `test_contract_validation.py`, add:

```python
def test_validate_contract_command_valid(tmp_path):
    """A valid contract passes validation."""
    from io import StringIO
    from django.core.management import call_command

    contract = tmp_path / "valid.yaml"
    contract.write_text("""\
version: "2.0"
tables:
  - suggested_model_name: Widget
    model_name: Widget
    columns:
      - source_column: Name
        suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 200}
""")

    out = StringIO()
    call_command("validate_contract", contract=str(contract), stdout=out)
    assert "Contract is valid" in out.getvalue()


def test_validate_contract_command_missing_model_name(tmp_path):
    """A contract missing model_name fails validation."""
    from io import StringIO
    from django.core.management import call_command
    from django.core.management.base import CommandError

    contract = tmp_path / "missing.yaml"
    contract.write_text("""\
version: "2.0"
tables:
  - suggested_model_name: Widget
    # no model_name
    columns: []
""")

    with pytest.raises(CommandError, match="model_name"):
        call_command("validate_contract", contract=str(contract))


def test_validate_contract_command_fk_target_not_found(tmp_path):
    """FK target that doesn't match any model_name produces a warning."""
    from io import StringIO
    from django.core.management import call_command
    from django.core.management.base import CommandError

    contract = tmp_path / "bad_fk.yaml"
    contract.write_text("""\
version: "2.0"
tables:
  - suggested_model_name: Crop
    model_name: Crop
    columns:
      - source_column: Name
        suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 200}
  - suggested_model_name: Planting
    model_name: Planting
    columns:
      - source_column: Crop
        suggested_field_name: crop
        django_field_class: models.ForeignKey
        django_field_kwargs:
          to: NonExistent    # doesn't match any model_name
          on_delete: models.CASCADE
""")

    with pytest.raises(CommandError, match="FK target"):
        call_command("validate_contract", contract=str(contract))
```

- [ ] **Step 3: Remove `scripts/validate_contract.py`**

Delete the file.  It's superseded by the management command.

- [ ] **Step 4: Run tests**

Run: `cd /home/user/migration-workbench && python -m pytest workbook/tests/test_contract_validation.py -x --tb=short -v 2>&1 | tail -20`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add validate_contract management command; remove old validate script"
```

---

### Task 6: Admin config priority — contract as source of truth

**Files:**
- Modify: `workbook/codegen/admin_generator.py`
- Modify: `workbook/management/commands/generate_admin.py`
- Test: `workbook/tests/test_admin_generator.py`

- [ ] **Step 1: Understand current `_pick_display_fields` signature**

Read `admin_generator.py:90-150` and related `_pick_*` functions.  Note the `authoritative` parameter that already exists.

- [ ] **Step 2: Update `_pick_display_fields` priority**

In `admin_generator.py`, modify `_pick_display_fields()` (around line 90):

```python
def _pick_display_fields(
    view: dict[str, Any] | None,
    contract_fields: list[dict[str, Any]],
    admin_cfg: dict[str, Any] | None = None,
    max_count: int = 5,
    *,
    authoritative: bool = False,
) -> list[str]:
    """Pick ``list_display`` field names for a model.

    Priority:
    1. Contract ``admin.list_display`` (if set, authoritative)
    2. Manifest suggested_display_fields (if no explicit admin config)
    3. Auto-detect from field type (name, date, FK fields)
    """
    if admin_cfg:
        explicit = admin_cfg.get("list_display")
        if explicit:
            return list(explicit)

    if view:
        suggested = view.get("suggested_display_fields") or view.get("display_fields") or []
        if suggested:
            # Filter to valid field names only
            valid = {f["name"] for f in contract_fields}
            return [f for f in suggested if f in valid][:max_count]

    if admin_cfg and authoritative:
        return []

    # Auto-detect: prefer name/title, date, FK in that order
    ordered = _auto_detect_display_fields(contract_fields)
    return ordered[:max_count]
```

Apply the same pattern to `_pick_filter_fields()`, `_pick_search_fields()`, `_pick_readonly_fields()`.

- [ ] **Step 3: Update admin generator's manifest-awareness**

In the `render_admin_py()` loop (around line 505-546), the `authoritative` flag is currently only set for `AbstractUser` models.  Change to set `authoritative` when the contract's `admin` block has the relevant key:

```python
admin_cfg = get_admin_config(table)
is_user = _is_abstract_user_model(table)
is_authoritative = bool(admin_cfg) or is_user

display = _pick_display_fields(view, contract_fields, admin_cfg, authoritative=is_authoritative)
filters = _pick_filter_fields(view, contract_fields, admin_cfg, authoritative=is_authoritative)
search = _pick_search_fields(contract_fields, rev_fks, admin_cfg, authoritative=is_authoritative)
readonly = _pick_readonly_fields(view, contract_fields, admin_cfg, authoritative=is_authoritative)
```

- [ ] **Step 4: Remove the "No --manifest" warning in `generate_admin.py`**

Replace lines 94-99:

```python
if not options.get("manifest"):
    self.stderr.write(self.style.WARNING(
        "No --manifest provided. Admin will lack list_display, list_filter, "
        "and readonly_fields. Re-run with --manifest after 'make pull-bundle' "
        "and 'make generate-view-manifest' for a richer admin."
    ))
```

With nothing (delete the block entirely).  The contract admin blocks are sufficient — the manifest is optional enrichment.

- [ ] **Step 5: Fix `generate_admin.py` `app_label` auto-detection**

Around line 44-47, replace:

```python
parser.add_argument(
    "--app-label",
    default="core",
    help="Django app label for model imports (default: core)",
)
```

With:

```python
parser.add_argument(
    "--app-label",
    default=None,
    help="Django app label for model imports (default: auto-detect from contract, fallback 'core')",
)
```

And in `handle()` (after loading the contract), add the same auto-detection logic that `generate_models.py:66-78` uses:

```python
if app_label is None:
    for table in contract.get("tables", []):
        meta = table.get("model_meta") or {}
        if meta.get("app_label"):
            app_label = meta["app_label"]
            break
if app_label is None:
    app_label = "core"
```

- [ ] **Step 6: Run admin generator tests**

Run: `cd /home/user/migration-workbench && python -m pytest workbook/tests/test_admin_generator.py -x --tb=short -v 2>&1 | tail -30`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: contract admin blocks are authoritative; fix generate_admin app_label detection"
```

---

### Task 7: Separate generated files — stub_writer + generators

**Files:**
- Create: `workbook/codegen/stub_writer.py`
- Modify: `workbook/management/commands/generate_models.py`
- Modify: `workbook/management/commands/generate_admin.py`
- Test: `workbook/tests/test_codegen_force_overwrite.py` (update for _auto pattern)
- Test: `workbook/tests/test_generate_models_command.py` (add stub tests)
- Test: `workbook/tests/test_admin_generator.py` (add stub tests if needed)

- [ ] **Step 1: Create `workbook/codegen/stub_writer.py`**

```python
"""Write or update auto-generated stub files that re-export from *_auto modules."""

from __future__ import annotations

from pathlib import Path


MARKER = "# --- custom models below this line ---"
IMPORT_LINE = "from .{module} import *  # noqa: F401, F403"


def ensure_stub(
    stub_path: str | Path,
    auto_module: str,
    marker: str = MARKER,
) -> Path:
    """Write or update a stub file that re-exports from an ``*_auto`` module.

    Args:
        stub_path: Path to the stub file (e.g. ``models.py``).
        auto_module: Module name to import from (e.g. ``models_auto``).
        marker: Comment that separates auto-generated imports from custom code.

    Returns:
        The Path to the stub file.

    If the file already exists, the import line is refreshed and everything
    below the marker is preserved unchanged.  If no marker exists, it's
    appended at the end.
    """
    path = Path(stub_path)
    import_line = IMPORT_LINE.format(module=auto_module)

    if not path.exists():
        path.write_text(f"{import_line}\n\n\n{marker}\n", encoding="utf-8")
        return path

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

    # Find or replace the import line (first line starting with "from .")
    new_lines: list[str] = []
    import_written = False
    marker_found = False
    custom_section: list[str] = []

    for line in lines:
        if line.startswith("from .") and not import_written:
            new_lines.append(f"{import_line}\n")
            import_written = True
        elif line.strip() == marker.strip():
            marker_found = True
            new_lines.append(line)
        elif marker_found:
            custom_section.append(line)
        else:
            new_lines.append(line)

    if not import_written:
        new_lines.insert(0, f"{import_line}\n\n")

    if not marker_found:
        new_lines.append(f"\n\n{marker}\n")
    else:
        new_lines.extend(custom_section)

    path.write_text("".join(new_lines), encoding="utf-8")
    return path
```

- [ ] **Step 2: Update `generate_models.py`**

Make `--out` optional with default `models_auto.py`:

```python
parser.add_argument(
    "--out",
    default=None,
    help="Output path for models_auto.py (default: <app_dir>/models_auto.py)",
)
```

In `handle()`, derive default path and always write stub.  Use the same
`Path.cwd() / "backend" / "apps" / app_label` convention as
`generate_import.py:98-104`:

```python
out_path = options.get("out")
if out_path is None:
    app_dir = Path.cwd() / "backend" / "apps" / app_label
    out_path = str(app_dir / "models_auto.py")
    stub_path = str(app_dir / "models.py")
else:
    stub_path = None

out_path = Path(out_path).resolve()

# ... write generated source to out_path ...

# Always create/update the stub if we used the default path
if stub_path:
    from workbook.codegen.stub_writer import ensure_stub
    ensure_stub(stub_path, "models_auto")
```

Note: if the app directory doesn't exist, the user must pass `--out`
explicitly.  The default is a convenience for the standard product layout.

- [ ] **Step 3: Update `generate_admin.py`**

Same pattern — make `--out` optional, default to `admin_auto.py`, always write stub `admin.py`:

```python
parser.add_argument(
    "--out",
    default=None,
    help="Output path for admin_auto.py (default: <app_dir>/admin_auto.py)",
)
```

In `handle()`:

```python
out_path = options.get("out")
if out_path is None:
    app_dir = Path.cwd() / "backend" / "apps" / app_label
    out_path = str(app_dir / "admin_auto.py")
    stub_path = str(app_dir / "admin.py")
else:
    stub_path = None

out_path = Path(out_path).resolve()

# ... write generated source to out_path ...

if stub_path:
    from workbook.codegen.stub_writer import ensure_stub
    ensure_stub(stub_path, "admin_auto")
```

- [ ] **Step 4: Write tests for stub_writer**

Create a new test section (can go in `test_codegen_force_overwrite.py` or a new file):

```python
"""Tests for stub_writer.py."""

from pathlib import Path
from workbook.codegen.stub_writer import ensure_stub, MARKER


def test_stub_creates_new_file(tmp_path):
    stub = ensure_stub(tmp_path / "models.py", "models_auto")
    assert stub.exists()
    content = stub.read_text()
    assert "from .models_auto import *" in content
    assert MARKER in content


def test_stub_preserves_custom_code(tmp_path):
    stub = tmp_path / "models.py"
    stub.write_text("""\
from .models_auto import *  # noqa: F401, F403

# --- custom models below this line ---

class FarmUser(AbstractUser):
    pass
""")

    ensure_stub(stub, "models_auto")
    content = stub.read_text()
    assert "class FarmUser(AbstractUser):" in content
    assert "pass" in content


def test_stub_updates_import_line(tmp_path):
    stub = tmp_path / "models.py"
    stub.write_text("""\
from .old_module import *

# --- custom models below this line ---
class Custom: pass
""")

    ensure_stub(stub, "models_auto")
    content = stub.read_text()
    assert "from .models_auto import *" in content
    assert "from .old_module import *" not in content
    assert "class Custom: pass" in content


def test_stub_handles_no_marker(tmp_path):
    stub = tmp_path / "models.py"
    stub.write_text("from .old_module import *")

    ensure_stub(stub, "models_auto")
    content = stub.read_text()
    assert MARKER in content
```

Run these: `cd /home/user/migration-workbench && python -m pytest workbook/tests/test_codegen_force_overwrite.py -x --tb=short -v 2>&1 | tail -20`
(If the stub tests are in a separate file, substitute the filename.)

- [ ] **Step 5: Update existing `generate_models` tests to reflect new defaults**

In `test_generate_models_command.py`, update `CONTRACT_WITH_APP_LABEL` to include `model_name` and adjust test expectations (the output path changes from `models.py` to `models_auto.py`).

- [ ] **Step 6: Run all codegen-related tests**

```bash
cd /home/user/migration-workbench
python -m pytest workbook/tests/test_model_generator.py -x --tb=short -v | tail -20
python -m pytest workbook/tests/test_admin_generator.py -x --tb=short -v | tail -20
python -m pytest workbook/tests/test_codegen_force_overwrite.py -x --tb=short -v | tail -20
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: generate to models_auto.py/admin_auto.py with stub re-export files"
```

---

### Task 8: Unified wb CLI + Makefile

**Files:**
- Modify: `deployment/wb_cli.py`
- Modify: `Makefile`
- Test: `deployment/tests/` (run existing CLI tests)

- [ ] **Step 1: Add `generate` subcommand tree to `wb_cli.py`**

In `build_parser()`, after the existing subcommand registrations (around line 680), add:

```python
def _build_generate_parser(sub):
    """Add 'generate {models,admin,import,manifest}' subcommands to *sub*."""
    gen_cmd = sub.add_parser("generate", help="Generate code from a schema contract")
    gen_sub = gen_cmd.add_subparsers(dest="generate_command", required=True)

    # generate models
    models_cmd = gen_sub.add_parser("models", help="Generate Django models.py")
    models_cmd.add_argument("--contract", required=True)
    models_cmd.add_argument("--out", default=None)
    models_cmd.add_argument("--app-label", default=None)
    models_cmd.add_argument("--force", action="store_true")
    models_cmd.add_argument("--diff", action="store_true")
    models_cmd.add_argument("--django-settings", default=None)
    models_cmd.set_defaults(func=_generate_models)

    # generate admin
    admin_cmd = gen_sub.add_parser("admin", help="Generate Django admin.py")
    admin_cmd.add_argument("--contract", required=True)
    admin_cmd.add_argument("--manifest", default=None)
    admin_cmd.add_argument("--out", default=None)
    admin_cmd.add_argument("--app-label", default=None)
    admin_cmd.add_argument("--force", action="store_true")
    admin_cmd.add_argument("--diff", action="store_true")
    admin_cmd.add_argument("--django-settings", default=None)
    admin_cmd.set_defaults(func=_generate_admin)

    # generate import
    import_cmd = gen_sub.add_parser("import", help="Generate Django import command")
    import_cmd.add_argument("--contract", required=True)
    import_cmd.add_argument("--out", default=None)
    import_cmd.add_argument("--app-label", default=None)
    import_cmd.add_argument("--force", action="store_true")
    import_cmd.add_argument("--diff", action="store_true")
    import_cmd.add_argument("--django-settings", default=None)
    import_cmd.set_defaults(func=_generate_import)

    # generate manifest
    manifest_cmd = gen_sub.add_parser("manifest", help="Generate view manifest")
    manifest_cmd.add_argument("--contract", required=True)
    manifest_cmd.add_argument("--out", default=None)
    manifest_cmd.add_argument("--structure", default=None)
    manifest_cmd.add_argument("--django-settings", default=None)
    manifest_cmd.set_defaults(func=_generate_manifest)
```

Add the handler functions (near `_contract_review`, around line 127):

```python
def _generate_models(args: argparse.Namespace) -> int:
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command
    from workbook.management.commands.generate_models import Command

    kwargs = {
        "contract": args.contract,
        "out": args.out,
        "app_label": args.app_label,
        "force": args.force,
        "diff": args.diff,
    }
    # Filter None values so management command defaults apply
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command(Command, **kwargs)
    return 0


def _generate_admin(args: argparse.Namespace) -> int:
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command
    from workbook.management.commands.generate_admin import Command

    kwargs = {
        "contract": args.contract,
        "manifest": args.manifest,
        "out": args.out,
        "app_label": args.app_label,
        "force": args.force,
        "diff": args.diff,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command(Command, **kwargs)
    return 0


def _generate_import(args: argparse.Namespace) -> int:
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command
    from workbook.management.commands.generate_import import Command

    kwargs = {
        "contract": args.contract,
        "out": args.out,
        "app_label": args.app_label,
        "force": args.force,
        "diff": args.diff,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command(Command, **kwargs)
    return 0


def _generate_manifest(args: argparse.Namespace) -> int:
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command
    from workbook.management.commands.generate_view_manifest import Command

    kwargs = {
        "structure": args.structure,
        "out": args.out,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command(Command, **kwargs)
    return 0
```

- [ ] **Step 2: Add `validate contract` to wb CLI**

Add a new subcommand to the `contract` subparser (alongside `review`, `diff`, `safety`):

In `build_parser()`:

```python
validate_cmd = contract_sub.add_parser(
    "validate", help="Validate a schema contract (structural checks)"
)
validate_cmd.add_argument("--contract", required=True)
validate_cmd.add_argument("--json", action="store_true")
validate_cmd.add_argument("--exit-zero", action="store_true")
validate_cmd.add_argument("--django-settings", default=None)
validate_cmd.set_defaults(func=_contract_validate)
```

Add handler:

```python
def _contract_validate(args: argparse.Namespace) -> int:
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command
    from workbook.management.commands.validate_contract import Command

    try:
        call_command(Command, contract=args.contract)
        return 0
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
```

- [ ] **Step 3: Wire the generate subparser into `build_parser()`**

In `build_parser()`, add the call:

```python
_build_generate_parser(sub)
```

- [ ] **Step 4: Update the Makefile**

Replace codegen and validation targets to use `wb`:

```makefile
CONTRACT ?= build/schema-contract.yaml
OUT ?= build/out.py

validate-contract:
	wb validate contract --contract "$(CONTRACT)"

diff-generated:
	wb generate models --contract $(CONTRACT) --out $(OUT) --diff

generate-models:
	wb generate models --contract $(CONTRACT) --out $(OUT) $(if $(FORCE),--force)

generate-admin-light:
	wb generate admin --contract $(CONTRACT) --out $(OUT) $(if $(FORCE),--force)

generate-admin:
	wb generate admin --contract $(CONTRACT) --manifest $(MANIFEST) --out $(OUT) $(if $(FORCE),--force)

generate-import:
	wb generate import --contract $(CONTRACT) --out $(OUT) $(if $(FORCE),--force)

generate-view-manifest:
	wb generate manifest --contract $(CONTRACT) $(if $(FORCE),--force)

generate-all: generate-models generate-view-manifest generate-admin generate-import generate-pipeline-manifest
	@echo "All code generation complete."
```

Also add `generate-models`, `generate-view-manifest`, `generate-import` to `.PHONY` (they're already listed at line 11, so no change needed).

- [ ] **Step 5: Run deployment tests (wb CLI tests)**

Run: `cd /home/user/migration-workbench && python -m pytest deployment/tests/ -x --tb=short -v 2>&1 | tail -20`

- [ ] **Step 6: Run chassis-gate (full integration smoke)**

Run: `cd /home/user/migration-workbench && DB_ENGINE=sqlite python -m pytest -x --tb=short 2>&1 | tail -30`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: unify wb CLI with generate subcommands; update Makefile"
```

---

### Verification

After all tasks are complete, run the full test suite:

```bash
cd /home/user/migration-workbench
DB_ENGINE=sqlite python -m pytest -x --tb=short 2>&1 | tail -50
```

Then run the chassis-gate (which exercises the full pipeline):

```bash
DB_ENGINE=sqlite make chassis-gate
```

Expected: all tests pass, no `Skipped` or `FAILED` entries.
