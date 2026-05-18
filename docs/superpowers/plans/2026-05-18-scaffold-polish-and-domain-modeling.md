# Scaffold Polish and Domain-Modeling Workflow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four scaffold bugs and add a domain-modeling workflow that merges profiler output with human-authored domain knowledge to produce structurally sound contract drafts.

**Architecture:** Scaffold bug fixes are single-file template changes. The domain-modeling workflow adds a `--domain-knowledge` flag to `scaffold_workbook_schema.py` and always-on heuristics (FK detection, computed_fields from formula patterns, tab grouping) that enrich the contract output. A new `docs/domain-knowledge.example.yaml` template guides human authors.

**Tech Stack:** Python, Django management commands, PyYAML, argparse.

---

### Task 1: Fix `_to_pascal_case` PascalCase pass-through

**Files:**
- Modify: `workbook/management/commands/scaffold_workbook_schema.py:41-43`
- Test: `workbook/tests/test_scaffold_workbook_schema.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the scaffold_workbook_schema management command."""

from pathlib import Path
from django.core.management import call_command
from workbook.management.commands.scaffold_workbook_schema import _to_pascal_case


def test_to_pascal_case_preserves_pascalcase():
    """Input that is already PascalCase (no underscores/hyphens, internal caps) passes through unchanged."""
    assert _to_pascal_case("SalesChannel") == "SalesChannel"
    assert _to_pascal_case("FarmUser") == "FarmUser"
    assert _to_pascal_case("FieldBlock") == "FieldBlock"


def test_to_pascal_case_converts_snake_case():
    """Standard snake_case to PascalCase conversion still works."""
    assert _to_pascal_case("sales_channel") == "SalesChannel"
    assert _to_pascal_case("farm_user") == "FarmUser"
    assert _to_pascal_case("field_block") == "FieldBlock"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py::test_to_pascal_case_preserves_pascalcase -xvs`
Expected: `FAILED` — `_to_pascal_case("SalesChannel")` returns `"Saleschannel"` not `"SalesChannel"`

- [ ] **Step 3: Fix `_to_pascal_case`**

Replace lines 41-43 of `scaffold_workbook_schema.py`:

Old:
```python
def _to_pascal_case(raw: str) -> str:
    """Convert a label to PascalCase."""
    return "".join(p.capitalize() for p in raw.replace("-", "_").split("_"))
```

New:
```python
def _to_pascal_case(raw: str) -> str:
    """Convert a label to PascalCase.
    
    If the input is already PascalCase (no underscores/hyphens, has uppercase
    after position 0), pass it through unchanged.
    """
    if "_" not in raw and "-" not in raw and any(c.isupper() for c in raw[1:]):
        return raw
    return "".join(p.capitalize() for p in raw.replace("-", "_").split("_"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py::test_to_pascal_case_preserves_pascalcase -xvs`
Expected: `PASSED`

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `.venv/bin/python -m pytest -x --tb=short 2>&1 | tail -10`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add workbook/management/commands/scaffold_workbook_schema.py workbook/tests/test_scaffold_workbook_schema.py
git commit -m "fix(scaffold): _to_pascal_case passes through existing PascalCase names"
```

---

### Task 2: Update scaffolded models.py template with sentinel marker

**Files:**
- Modify: `scripts/new_product.py:338-345`
- Test: `scripts/tests/test_new_product.py`

- [ ] **Step 1: Write the failing test**

Add to `scripts/tests/test_new_product.py`:

```python
def test_render_models_py_includes_stub_marker():
    """The scaffolded models.py includes the custom-models marker and auto import."""
    from scripts.new_product import render_models_py
    content = render_models_py("core", "FarmUser")
    assert "from .models_auto import *  # noqa: F401, F403" in content
    assert "# --- custom models below this line ---" in content
    assert "class FarmUser(AbstractUser):" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py::test_render_models_py_includes_stub_marker -xvs`
Expected: `FAILED` — no marker in output

- [ ] **Step 3: Update `render_models_py`**

Old:
```python
def render_models_py(model_prefix: str, user_model_name: str) -> str:
    return f"""from django.contrib.auth.models import AbstractUser
from django.db import models


class {user_model_name}(AbstractUser):
    pass
"""
```

New:
```python
def render_models_py(model_prefix: str, user_model_name: str) -> str:
    return f"""from django.contrib.auth.models import AbstractUser
from django.db import models

from .models_auto import *  # noqa: F401, F403


class {user_model_name}(AbstractUser):
    pass


# --- custom models below this line ---
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py::test_render_models_py_includes_stub_marker -xvs`
Expected: `PASSED`

- [ ] **Step 5: Run existing tests to check for regressions**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py -x --tb=short`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add scripts/new_product.py scripts/tests/test_new_product.py
git commit -m "fix(scaffold): include sentinel marker in scaffolded models.py template"
```

---

### Task 3: Add root URL redirect to scaffolded urls.py

**Files:**
- Modify: `scripts/new_product.py:296-308` (`render_urls_py`)
- Test: `scripts/tests/test_new_product.py`

- [ ] **Step 1: Write the failing test**

Add to `scripts/tests/test_new_product.py`:

```python
def test_render_urls_py_redirects_root_to_admin():
    """Root URL / redirects to /admin/."""
    from scripts.new_product import render_urls_py
    content = render_urls_py("test-product", "backend")
    assert 'RedirectView.as_view(url="/admin/"' in content
    assert 'path("", RedirectView' in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py::test_render_urls_py_redirects_root_to_admin -xvs`
Expected: `FAILED`

- [ ] **Step 3: Read the current `render_urls_py` to understand exact structure**

Run: `grep -n -A20 'def render_urls_py' scripts/new_product.py`

- [ ] **Step 4: Update `render_urls_py`**

Add at the top of the imports block:
```python
from django.views.generic import RedirectView
```

Add as the first urlpattern inside `urlpatterns = [...]`:
```python
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
```

The resulting function should have the imports block starting with:
```python
from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView
```

And urlpatterns starting with:
```python
urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("admin/", admin.site.urls),
    ...existing patterns...
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py::test_render_urls_py_redirects_root_to_admin -xvs`
Expected: `PASSED`

- [ ] **Step 6: Run all new_product tests**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py -x --tb=short`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add scripts/new_product.py scripts/tests/test_new_product.py
git commit -m "fix(scaffold): root URL redirects to /admin/ in scaffolded urls.py"
```

---

### Task 4: Add createsuperuser make target

**Files:**
- Modify: `workbook/makefile_targets.py` (add new block function)
- Modify: `scripts/new_product.py` (wire into `render_makefile` and `render_env_example`)
- Test: `scripts/tests/test_new_product.py`

- [ ] **Step 1: Write the failing test**

Add to `scripts/tests/test_new_product.py`:

```python
def test_makefile_has_createsuperuser_target():
    """The scaffolded Makefile includes a createsuperuser target."""
    from scripts.new_product import render_makefile
    content = render_makefile("test-product")
    assert "createsuperuser:" in content
    assert "DJANGO_SUPERUSER_USERNAME" in content
    assert "DJANGO_SUPERUSER_PASSWORD" in content


def test_env_example_has_superuser_vars():
    """The scaffolded .env.example includes DJANGO_SUPERUSER_* variables."""
    from scripts.new_product import render_env_example
    content = render_env_example("test-product", "backend")
    assert "DJANGO_SUPERUSER_USERNAME" in content
    assert "DJANGO_SUPERUSER_PASSWORD" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py::test_makefile_has_createsuperuser_target -xvs`
Expected: `FAILED`

- [ ] **Step 3: Read `makefile_targets.py` to understand the pattern**

Run: `grep -n 'def.*block\|def variable' workbook/makefile_targets.py | head -20`

Find an existing block function to understand the pattern (e.g. `codegen_tooling_block`). Blocks return a multi-line string, are parameterized by `MakeContext`, and get added to `full_targets_block()`.

- [ ] **Step 4: Add `createsuperuser_block` to `makefile_targets.py`**

```python
def createsuperuser_block(ctx: MakeContext) -> str:
    """Target for non-interactive superuser creation."""
    return f"""
createsuperuser:
\t@if [ -z "$(DJANGO_SUPERUSER_PASSWORD)" ]; then \\\\n
\t\\t$(MANAGE) createsuperuser; \\\\n
\telse \\\\n
\t\\t$(MANAGE) shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); u, _ = User.objects.get_or_create(username='$(DJANGO_SUPERUSER_USERNAME)'); u.set_password('$(DJANGO_SUPERUSER_PASSWORD)'); u.is_staff = True; u.is_superuser = True; u.save(); print('Superuser created/updated')"; \\\\n
\tfi
"""
```

Add `createsuperuser_block` to the imports/exports at the top of the file, and add it to `full_targets_block()` function.

- [ ] **Step 5: Wire into `render_makefile` in new_product.py**

In `render_makefile()`, after the existing codegen/deploy blocks, add the createsuperuser block. Search for where `full_targets_block` is called or where targets are assembled, and add the new block function call.

- [ ] **Step 6: Add env vars to `render_env_example`**

Find `render_env_example` in `scripts/new_product.py` and add:
```
# Superuser creation (non-interactive via make createsuperuser)
# DJANGO_SUPERUSER_USERNAME=admin
# DJANGO_SUPERUSER_PASSWORD=replace_me
```

- [ ] **Step 7: Run test to verify it passes**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py::test_makefile_has_createsuperuser_target scripts/tests/test_new_product.py::test_env_example_has_superuser_vars -xvs`
Expected: `PASSED`

- [ ] **Step 8: Run all new_product tests**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py -x --tb=short`
Expected: all pass

- [ ] **Step 9: Run full test suite**

Run: `.venv/bin/python -m pytest -x --tb=short 2>&1 | tail -10`
Expected: all pass

- [ ] **Step 10: Commit**

```bash
git add workbook/makefile_targets.py scripts/new_product.py scripts/tests/test_new_product.py
git commit -m "feat(scaffold): add createsuperuser make target with env var support"
```

---

### Task 5: Update schema-contract.md template

**Files:**
- Modify: `scripts/new_product.py:1030-1051` (`render_schema_contract_md`)
- Test: `scripts/tests/test_new_product.py`

- [ ] **Step 1: Write the failing test**

Add to `scripts/tests/test_new_product.py`:

```python
def test_schema_contract_md_includes_entity_guidance():
    """The scaffolded schema-contract.md has structured entity guidance, not just headings."""
    from scripts.new_product import render_schema_contract_md
    content = render_schema_contract_md("test-product")
    assert "**Purpose**" in content
    assert "**Source tabs**" in content
    assert "**Import key**" in content
    assert "domain-knowledge.yaml" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py::test_schema_contract_md_includes_entity_guidance -xvs`
Expected: `FAILED`

- [ ] **Step 3: Rewrite `render_schema_contract_md`**

Replace the current function with:

```python
def render_schema_contract_md(project_name: str) -> str:
    return f"""# Schema contract — {project_name}

Living document for entities, attributes, and sheet/tab mapping. Align with the **schema design loop** in migration-workbench (`docs/schema-design-loop.md`).

## Entity Map YAML

This document is paired with `docs/domain-knowledge.yaml`.
Run the scaffold to merge domain knowledge with profiler data:

    scaffold_workbook_schema --bundle-config ... --domain-knowledge docs/domain-knowledge.yaml

## Sources

- Profile snapshots: `data/profile_snapshots/`
- Bundle configs: `bundles/` (when present)

## Entities

For each entity, document:
- **Purpose** — what real-world concept this represents
- **Source tabs** — which profiler tabs map to this entity
- **Fields** — name, type, constraints, and whether stored or computed
- **FK targets** — which other entities this references
- **Import key** — natural key for idempotent re-import

### Example: Season

```yaml
Season:
  purpose: "Named set of planned plantings"
  source_tabs: ["Crop Planner"]
  fields:
    name: CharField(unique=True)
    year: PositiveIntegerField
  import_key: [name]
```

## Decisions

- Lift / modify / rebuild per area (record rationale).

## Drift

Re-profile after source changes; note date and what changed.
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py::test_schema_contract_md_includes_entity_guidance -xvs`
Expected: `PASSED`

- [ ] **Step 5: Run all new_product tests**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py -x --tb=short`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add scripts/new_product.py scripts/tests/test_new_product.py
git commit -m "feat(scaffold): populate schema-contract.md template with entity structure guidance"
```

---

### Task 6: Add domain-knowledge.example.yaml renderer

**Files:**
- Modify: `scripts/new_product.py` (add `render_domain_knowledge_example_yaml` function)
- Test: `scripts/tests/test_new_product.py`

- [ ] **Step 1: Write the failing test**

Add to `scripts/tests/test_new_product.py`:

```python
def test_domain_knowledge_example_yaml_includes_entities():
    """The domain-knowledge example YAML has populated entity examples."""
    from scripts.new_product import render_domain_knowledge_example_yaml
    content = render_domain_knowledge_example_yaml()
    assert "entities:" in content
    assert "Season:" in content
    assert "Planting:" in content
    assert "import_key:" in content
    assert "fk_to:" in content
    assert "ForeignKey" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py::test_domain_knowledge_example_yaml_includes_entities -xvs`
Expected: `FAILED` — function doesn't exist yet

- [ ] **Step 3: Add `render_domain_knowledge_example_yaml` to `new_product.py`**

Add a new function in `new_product.py` (near `render_env_example`):

```python
def render_domain_knowledge_example_yaml() -> str:
    return """# docs/domain-knowledge.yaml — Entity definitions for contract generation
# Used by: scaffold_workbook_schema --domain-knowledge docs/domain-knowledge.yaml

entities:
  Season:
    description: "Named set of planned plantings — the top-level organizational unit."
    source_tabs: ["Crop Planner"]
    fields:
      name:
        type: CharField
        max_length: 100
        unique: true
      year:
        type: PositiveIntegerField
      is_active:
        type: BooleanField
        default: false
    import_key: [name]
    fk_to: []

  Planting:
    description: "Individual planting record tied to a season and crop."
    source_tabs: ["Crop Planner", "Crop Plan 501+503+801"]
    fields:
      planting_id:
        type: CharField
        max_length: 50
        unique: true
      crop_variety:
        type: CharField
        max_length: 200
      season:
        type: ForeignKey
        to: Season
    import_key: [planting_id]
    fk_to: [Season]
"""
```

- [ ] **Step 4: Wire into the scaffold output**

Find where `render_env_example` is written to the scaffolded product (in `scaffold_config_templates` or the main scaffold function), and add a similar call to write `docs/domain-knowledge.example.yaml`.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py::test_domain_knowledge_example_yaml_includes_entities -xvs`
Expected: `PASSED`

- [ ] **Step 6: Run all new_product tests**

Run: `.venv/bin/python -m pytest scripts/tests/test_new_product.py -x --tb=short`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add scripts/new_product.py scripts/tests/test_new_product.py
git commit -m "feat(scaffold): add domain-knowledge.example.yaml to scaffolded products"
```

---

### Task 7: Add heuristics to scaffold (FK detection, computed_fields, tab grouping)

**Files:**
- Modify: `workbook/management/commands/scaffold_workbook_schema.py`
- Test: `workbook/tests/test_scaffold_workbook_schema.py`

- [ ] **Step 1: Read the table-building pipeline**

Read lines 59-190 of `scaffold_workbook_schema.py` to understand where tables are built and where heuristics should hook in (after `_inject_designed_models` and before `out_path.write_text`).

- [ ] **Step 2: Write tests for each heuristic**

Add to `workbook/tests/test_scaffold_workbook_schema.py`:

```python
from workbook.management.commands.scaffold_workbook_schema import (
    _to_pascal_case,
    _flag_fk_columns,
    _flag_computed_fields,
    _suggest_tab_merges,
)


def test_flag_fk_columns_detects_id_suffix():
    """Columns ending in _id get flagged with suggested_fk_target."""
    columns = [
        {"suggested_field_name": "season_id", "source_column": "Season ID"},
        {"suggested_field_name": "name", "source_column": "Name"},
    ]
    _flag_fk_columns(columns)
    assert columns[0].get("suggested_fk_target") == "Season"
    assert columns[0].get("review_note") is not None
    assert "suggested_fk_target" not in columns[1]


def test_flag_fk_columns_detects_entity_names():
    """Columns named after known entities (channel, season, etc.) get flagged."""
    columns = [
        {"suggested_field_name": "channel", "source_column": "Channel"},
        {"suggested_field_name": "season", "source_column": "Season"},
    ]
    _flag_fk_columns(columns)
    assert columns[0].get("suggested_fk_target") == "Channel"
    assert columns[1].get("suggested_fk_target") == "Season"


def test_flag_computed_fields_moves_formula_columns():
    """Columns with formula_pattern row_formula or expansion_formula move to computed_fields."""
    table = {
        "suggested_model_name": "CropPlan",
        "columns": [
            {"suggested_field_name": "name", "formula_pattern": "raw"},
            {"suggested_field_name": "yield_est", "formula_pattern": "row_formula"},
            {"suggested_field_name": "total", "formula_pattern": "expansion_formula"},
        ],
    }
    _flag_computed_fields(table)
    remaining = {c["suggested_field_name"] for c in table["columns"]}
    assert "name" in remaining
    assert "yield_est" not in remaining
    assert "total" not in remaining
    computed = table.get("computed_fields", {})
    assert "yield_est" in computed
    assert "total" in computed
    assert "return_type" in computed["yield_est"]
    assert "expression" in computed["yield_est"]


def test_flag_computed_fields_skips_missing_pattern():
    """Columns without a formula_pattern field are left as-is."""
    table = {
        "columns": [
            {"suggested_field_name": "name"},
        ],
    }
    _flag_computed_fields(table)
    assert len(table["columns"]) == 1


def test_suggest_tab_merges_groups_by_shared_headers():
    """Tabs from the same workbook sharing 2+ column headers get merge_candidates."""
    tabs = {
        "Crop Planner": {"columns": ["Crop", "Week", "Block", "Variety"]},
        "Crop Plan 501": {"columns": ["Crop", "Week", "Block", "Yield"]},
        "Harvest": {"columns": ["Date", "Weight", "Block"]},
    }
    result = _suggest_tab_merges(tabs)
    # Crop Planner and Crop Plan 501 share "Crop", "Week", "Block" (3 headers)
    assert any(
        r["tabs"] == {"Crop Planner", "Crop Plan 501"}
        for r in result
    )
    # Harvest only shares "Block" with the others (1 header, below threshold)
    assert not any("Harvest" in r["tabs"] for r in result)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py::test_flag_fk_columns_detects_id_suffix -xvs`
Expected: `FAILED` — `_flag_fk_columns` doesn't exist

- [ ] **Step 4: Implement `_flag_fk_columns`**

Add before the `handle()` method in `scaffold_workbook_schema.py`:

```python
_ENTITY_KEYWORDS = {"channel", "season", "crop", "block", "farm", "field", "variety"}


def _flag_fk_columns(columns: list[dict]) -> None:
    """Flag columns that look like FK references with suggested_fk_target.
    
    Detects: columns ending in '_id', or columns named after entity keywords.
    Mutates columns in-place.
    """
    for col in columns:
        name = col.get("suggested_field_name", "")
        if name.endswith("_id"):
            target = _to_pascal_case(name[:-3])
            col["suggested_fk_target"] = target
            col["review_note"] = f"Auto-detected FK: {target}"
        elif name.lower() in _ENTITY_KEYWORDS:
            target = _to_pascal_case(name)
            col["suggested_fk_target"] = target
            col["review_note"] = f"Auto-detected FK: {target}"
```

- [ ] **Step 5: Implement `_flag_computed_fields`**

```python
def _flag_computed_fields(table: dict) -> None:
    """Move formula-derived columns from columns[] to computed_fields{}.
    
    Columns with formula_pattern 'row_formula' or 'expansion_formula' are
    removed from the stored columns list and added as computed field stubs.
    """
    columns = table.get("columns", [])
    kept = []
    computed = {}
    for col in columns:
        pattern = col.get("formula_pattern")
        if pattern in ("row_formula", "expansion_formula"):
            name = col["suggested_field_name"]
            computed[name] = {
                "return_type": col.get("django_field_class", "models.FloatField"),
                "expression": f"# TODO: {col.get('source_column', name)} is formula-derived",
            }
        else:
            kept.append(col)
    table["columns"] = kept
    if computed:
        table.setdefault("computed_fields", {}).update(computed)
```

- [ ] **Step 6: Implement `_suggest_tab_merges`**

```python
def _suggest_tab_merges(tabs: dict[str, dict]) -> list[dict]:
    """Suggest which tabs from the same workbook should be merged into one entity.
    
    Tabs sharing 2+ column header names are merge candidates.
    Returns a list of {tabs: set[str], shared_headers: list[str]} dicts.
    """
    tab_names = list(tabs.keys())
    candidates = []
    for i in range(len(tab_names)):
        for j in range(i + 1, len(tab_names)):
            a_headers = set(tabs[tab_names[i]].get("columns", []))
            b_headers = set(tabs[tab_names[j]].get("columns", []))
            shared = a_headers & b_headers
            if len(shared) >= 2:
                candidates.append({
                    "tabs": {tab_names[i], tab_names[j]},
                    "shared_headers": sorted(shared),
                })
    return candidates
```

- [ ] **Step 7: Hook heuristics into the scaffold pipeline**

In the `handle()` method, after the tables list is built and `_inject_designed_models(tables)` is called (around line 180), add:

```python
    # Always-on heuristics
    for table in tables:
        _flag_fk_columns(table.get("columns", []))
        _flag_computed_fields(table)
    
    # Tab merge suggestions (operates on source tab metadata)
    tab_headers = {}
    if bundle_config:
        for tab in bundle_config.get("tabs", []):
            title = tab.get("worksheet_title", "")
            cols = tab.get("required_headers", [])
            if title:
                tab_headers[title] = cols
    merge_candidates = _suggest_tab_merges(tab_headers)
    if merge_candidates:
        contract["_merge_candidates"] = merge_candidates
```

Add `import yaml` at the top of the file if not already present.

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py::test_flag_fk_columns_detects_id_suffix -xvs`
Expected: `PASSED`

Run all heuristic tests:
Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py -x --tb=short -v`
Expected: all pass

- [ ] **Step 9: Run full test suite for regressions**

Run: `.venv/bin/python -m pytest -x --tb=short 2>&1 | tail -10`
Expected: all pass

- [ ] **Step 10: Commit**

```bash
git add workbook/management/commands/scaffold_workbook_schema.py workbook/tests/test_scaffold_workbook_schema.py
git commit -m "feat(scaffold): add heuristics for FK detection, computed_fields, and tab grouping"
```

---

### Task 8: Add --domain-knowledge flag + merge logic

**Files:**
- Modify: `workbook/management/commands/scaffold_workbook_schema.py`
- Test: `workbook/tests/test_scaffold_workbook_schema.py`

- [ ] **Step 1: Write the failing test**

Add to `workbook/tests/test_scaffold_workbook_schema.py`:

```python
def test_domain_knowledge_merge_overrides_field_types():
    """Domain knowledge field types override profiler-inferred types for matching fields."""
    from workbook.management.commands.scaffold_workbook_schema import _merge_domain_knowledge
    domain = {
        "entities": {
            "Season": {
                "fields": {
                    "name": {"type": "CharField", "max_length": 200},
                    "year": {"type": "PositiveIntegerField"},
                },
                "source_tabs": ["Crop Planner"],
            }
        }
    }
    tables = [
        {
            "suggested_model_name": "Season",
            "bundle_worksheet_title": "Crop Planner",
            "columns": [
                {"suggested_field_name": "name", "django_field_class": "models.TextField"},
                {"suggested_field_name": "year", "django_field_class": "models.TextField"},
                {"suggested_field_name": "notes", "django_field_class": "models.TextField"},
            ],
        }
    ]
    _merge_domain_knowledge(tables, domain)
    season = tables[0]
    cols_by_name = {c["suggested_field_name"]: c for c in season["columns"]}
    # Domain type overrides profiler type
    assert cols_by_name["name"]["django_field_class"] == "CharField"
    assert cols_by_name["name"]["max_length"] == 200
    assert cols_by_name["year"]["django_field_class"] == "PositiveIntegerField"
    # Unmatched profiler column gets a review note
    assert cols_by_name["notes"].get("review_note") is not None


def test_domain_knowledge_merge_warns_unmatched_entities():
    """Domain entities not matched to any profiler tab produce a warning."""
    from workbook.management.commands.scaffold_workbook_schema import _merge_domain_knowledge
    domain = {
        "entities": {
            "GhostEntity": {
                "fields": {"name": {"type": "CharField"}},
                "source_tabs": ["Nonexistent Tab"],
            }
        }
    }
    warnings = []
    _merge_domain_knowledge([], domain, warnings.append)
    assert any("GhostEntity" in w for w in warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py::test_domain_knowledge_merge_overrides_field_types -xvs`
Expected: `FAILED` — `_merge_domain_knowledge` doesn't exist

- [ ] **Step 3: Implement `_merge_domain_knowledge`**

Add before the `handle()` method:

```python
import yaml


def _merge_domain_knowledge(
    tables: list[dict],
    domain_knowledge: dict,
    warn: Callable[[str], None] | None = None,
) -> None:
    """Merge domain-knowledge entity definitions into scaffolded tables.
    
    Domain-knowledge field types override profiler-inferred types for matching
    fields. Profiler columns not mentioned in the domain entity get a
    review_note. Domain entities not matched to any profiler tab produce a
    warning.
    """
    if warn is None:
        warn = lambda _: None
    
    entities = domain_knowledge.get("entities", {})
    
    # Build a map from source_tab name to domain entity
    tab_to_entity: dict[str, tuple[str, dict]] = {}
    for entity_name, entity_def in entities.items():
        for tab in entity_def.get("source_tabs", [tab]):
            tab_to_entity[tab] = (entity_name, entity_def)
    
    # Match tables to domain entities
    for table in tables:
        tab_title = table.get("bundle_worksheet_title", "")
        match = tab_to_entity.get(tab_title)
        if not match:
            continue
        entity_name, entity_def = match
        domain_fields = entity_def.get("fields", {})
        for col in table.get("columns", []):
            field_name = col.get("suggested_field_name", "")
            if field_name in domain_fields:
                # Override type and kwargs from domain knowledge
                df = domain_fields[field_name]
                col["django_field_class"] = df.get("type", col.get("django_field_class"))
                for key, value in df.items():
                    if key != "type":
                        col[key] = value
            else:
                col["review_note"] = f"Not mapped in domain knowledge for {entity_name}"
    
    # Warn about unmatched domain entities
    matched_tabs = {t.get("bundle_worksheet_title", "") for t in tables}
    for entity_name, entity_def in entities.items():
        for tab in entity_def.get("source_tabs", []):
            if tab not in matched_tabs:
                warn(f"Entity '{entity_name}' references tab '{tab}' not found in profiler output")
```

- [ ] **Step 4: Add the `--domain-knowledge` flag to the command**

In the `add_arguments` method of `scaffold_workbook_schema.py`, add:

```python
parser.add_argument(
    "--domain-knowledge",
    default=None,
    help="Path to a domain-knowledge YAML file with entity definitions",
)
```

- [ ] **Step 5: Hook into `handle()`**

In the `handle()` method, after heuristics and before writing the output, add:

```python
    domain_knowledge_path = options.get("domain_knowledge")
    if domain_knowledge_path:
        dk_path = Path(domain_knowledge_path)
        if not dk_path.exists():
            raise CommandError(f"Domain knowledge file not found: {domain_knowledge_path}")
        with dk_path.open() as f:
            domain_knowledge = yaml.safe_load(f) or {}
        _merge_domain_knowledge(tables, domain_knowledge, self.stdout.write)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py::test_domain_knowledge_merge_overrides_field_types -xvs`
Expected: `PASSED`

Run all scaffold tests:
Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py -x --tb=short -v`
Expected: all pass

- [ ] **Step 7: Run full test suite for regressions**

Run: `.venv/bin/python -m pytest -x --tb=short 2>&1 | tail -10`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add workbook/management/commands/scaffold_workbook_schema.py workbook/tests/test_scaffold_workbook_schema.py
git commit -m "feat(scaffold): add --domain-knowledge flag for entity-aware contract generation"
```

---

### Task 9: Final sweep — wire domain-knowledge example into scaffold output + run full suite

**Files:**
- Modify: `scripts/new_product.py` (wire domain-knowledge.example.yaml into scaffold output)
- Test: `scripts/tests/test_new_product.py`

- [ ] **Step 1: Ensure domain-knowledge.example.yaml is written during scaffold**

In `new_product.py`, find `scaffold_config_templates()` or the main function that writes scaffolded files. Add:

```python
    # Domain knowledge example
    dk_example_path = product_dir / "docs" / "domain-knowledge.example.yaml"
    dk_example_path.parent.mkdir(parents=True, exist_ok=True)
    dk_example_path.write_text(render_domain_knowledge_example_yaml())
```

- [ ] **Step 2: Add a test that the example file is included**

```python
def test_scaffold_includes_domain_knowledge_example(tmp_path, monkeypatch):
    """The scaffolded product includes docs/domain-knowledge.example.yaml."""
    from scripts.new_product import scaffold_product, render_domain_knowledge_example_yaml
    # Use a minimal scaffold to verify the file is created
    # (adjust based on how scaffold_product works — may need to call it with minimal args)
```

(Note: adjust test based on how `scaffold_product` is invoked. If it's complex, a simpler approach is to check that the string `"domain-knowledge.example.yaml"` appears in the main scaffold function.)

- [ ] **Step 3: Run the full test suite**

Run: `.venv/bin/python -m pytest -x --tb=short 2>&1 | tail -10`
Expected: all 490+ tests pass

- [ ] **Step 4: Commit**

```bash
git add scripts/new_product.py scripts/tests/test_new_product.py
git commit -m "feat(scaffold): wire domain-knowledge example into scaffold output"
```
