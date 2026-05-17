# Evolution Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge 5 worktree branches into master, resolve the `admin_generator.py` conflict between FK link methods and time-scoping/status-actions/editable-fields, then update documentation to cover all new features.

**Architecture:** Sequential merge in dependency order: view-manifest-inference (foundation) → admin-time-status → admin-formula-fk (conflict resolution) → pipeline-manifest → rebase docs-coverage on the result + add missing docs.

**Tech Stack:** Python 3.11, Django 5.0+, pytest, interrogate (doc coverage), git worktrees

---

### Task 1: Merge view-manifest-inference into master

**Files:** No file editing — git merge operation.

- [ ] **Step 1: Verify branch state**

```bash
cd /home/user/projects/migration-workbench
git log --oneline master..evolution/view-manifest-inference
# Expect: ec99e65 fix: remove unused _YEAR_FIELD_RE constant
#         36e90c0 feat: infer time_scope and status_values in view manifest (issue #62)
git diff master...evolution/view-manifest-inference --stat
# Expect: workbook/tests/test_view_manifest.py | 135 +++++++++
#          workbook/view_manifest.py            |  60 ++++-
```

- [ ] **Step 2: Merge into master**

```bash
git merge evolution/view-manifest-inference
# Expect: Fast-forward (or merge commit if not ff)
```

- [ ] **Step 3: Run tests**

```bash
make test 2>&1 | tail -20
# Expect: all tests pass
```

- [ ] **Step 4: Verify view_manifest.py has time_scope/status_values inference**

```bash
git diff HEAD~1..HEAD -- workbook/view_manifest.py | head -30
# Expect: _infer_time_scope function, _WEEK_FIELD_RE, _DATE_FIELD_RE, etc.
```

---

### Task 2: Merge admin-time-status into master

**Files:** No file editing — git merge operation (additive changes, no conflicts with master).

- [ ] **Step 1: Verify branch state**

```bash
git log --oneline master..evolution/admin-time-status
# Expect: 18ae3d5 fix: safe slugification and quoting in status action methods
#         e8c3a09 feat: time-scoping, status actions, editable fields in admin
#         (the earlier 2 commits are already in master after Task 1)
git diff master...evolution/admin-time-status --stat
# Expect: workbook/codegen/admin_generator.py    |  82 +++++++
#          workbook/tests/test_admin_generator.py | 207 ++++++++++++++++
```

- [ ] **Step 2: Merge into master**

```bash
git merge evolution/admin-time-status
# Expect: merge commit — automated merge should succeed (no conflicts with master)
```

- [ ] **Step 3: Run tests**

```bash
make test 2>&1 | tail -20
# Expect: all tests pass
```

---

### Task 3: Merge admin-formula-fk into master (with conflict resolution)

**Files:** Modify `workbook/codegen/admin_generator.py` — manual conflict resolution combining FK link methods + time-status features.

- [ ] **Step 1: Verify branch state before merge**

```bash
git log --oneline master..evolution/admin-formula-fk
# Expect: 4cfc81b fix: better FK link short_description, skip unused FK links
#         60a1888 feat: FK link methods for cross-model navigation (issue #64)
git diff master...evolution/admin-formula-fk --stat
# Expect: workbook/codegen/admin_generator.py    |  61 +++++++
#          workbook/tests/test_admin_generator.py | 135 +++++++++++++++
```

- [ ] **Step 2: Attempt merge — expect conflict**

```bash
git merge evolution/admin-formula-fk
# Expect: CONFLICT in workbook/codegen/admin_generator.py
```

- [ ] **Step 3: Replace admin_generator.py with the combined version**

The combined `admin_generator.py` incorporates both branches' changes. Key changes from master (after Task 2) are:

**A) Add `import re` at top (after `from __future__ import annotations`):**

```python
from __future__ import annotations

import re
from typing import Any
```

**B) Add `_render_fk_link_method` function (insert after `_inline_field_names`):**

```python
def _render_fk_link_method(
    field_name: str,
    target_model_name: str,
    app_label: str,
) -> str:
    target_snake = re.sub(r"(?<!^)(?=[A-Z])", "_", target_model_name).lower()
    lines = [
        f"    def {field_name}_link(self, obj):",
        f"        if obj.{field_name}_id:",
        f"            url = reverse('admin:{app_label}_{target_snake}_change', args=[obj.{field_name}_id])",
        f"            return format_html('<a href=\"{{}}\">{{}}</a>', url, obj.{field_name})",
        "        return '-'",
        f"    {field_name}_link.short_description = '{field_name.replace('_', ' ').title()}'",
    ]
    return "\n".join(lines)
```

**C) Combined `_render_admin_class` signature — all 4 new params:**

```python
def _render_admin_class(
    model_name: str,
    display_fields: list[str],
    filter_fields: list[str],
    search_fields: list[str],
    readonly_fields: list[str],
    list_editable_fields: list[str],
    autocomplete_fields_list: list[str],
    inline_classes: list[str],
    verbose_name: str | None,
    admin_base_class: str = "admin.ModelAdmin",
    status_field: str | None = None,
    link_methods: list[str] | None = None,
    time_scope: dict[str, Any] | None = None,
    status_values: list[str] | None = None,
    editable_fields: list[str] | None = None,
) -> str:
```

**D) Combined body of `_render_admin_class` — full method body (replace lines 288-386):**

```python
    """Render a ``ModelAdmin`` class with ``@admin.register``."""
    lines: list[str] = []

    if status_field:
        lines.append(f"# status_field: {status_field}")

    lines.extend([
        "",
        f"@admin.register({model_name})",
        f"class {model_name}Admin({admin_base_class}):",
    ])

    # Ensure year_field from time_scope is in filter_fields
    if time_scope and time_scope.get("year_field"):
        year_field = time_scope["year_field"]
        if year_field not in filter_fields:
            filter_fields = list(filter_fields) + [year_field]

    if display_fields:
        items = ", ".join(repr(f) for f in display_fields)
        lines.append(f"    list_display = [{items}]")

    if link_methods:
        lines.append("")
        lines.extend(link_methods)

    if filter_fields:
        items = ", ".join(repr(f) for f in filter_fields)
        lines.append(f"    list_filter = [{items}]")

    if search_fields:
        items = ", ".join(repr(f) for f in search_fields)
        lines.append(f"    search_fields = [{items}]")

    if list_editable_fields:
        items = ", ".join(repr(f) for f in list_editable_fields)
        lines.append(f"    list_editable = [{items}]")

    if readonly_fields:
        items = ", ".join(repr(f) for f in readonly_fields)
        lines.append(f"    readonly_fields = [{items}]")

    if autocomplete_fields_list:
        items = ", ".join(repr(f) for f in autocomplete_fields_list)
        lines.append(f"    autocomplete_fields = [{items}]")

    if inline_classes:
        items = ", ".join(inline_classes)
        lines.append(f"    inlines = [{items}]")

    # date_hierarchy from time_scope
    if time_scope and time_scope.get("date_field"):
        lines.append(f"    date_hierarchy = '{time_scope['date_field']}'")

    # fields (change form) from editable_fields
    if editable_fields:
        items = ", ".join(repr(f) for f in editable_fields)
        lines.append(f"    fields = [{items}]")

    # get_queryset for current-season default filtering
    if time_scope and time_scope.get("year_field"):
        year_field = time_scope["year_field"]
        lines.extend([
            "",
            "    def get_queryset(self, request):",
            f"        qs = super().get_queryset(request)",
            f"        year = request.GET.get('{year_field}__exact')",
            f"        if not year:",
            f"            qs = qs.filter({year_field}=timezone.now().year)",
            f"        return qs",
        ])

    # Admin action methods from status_values
    if status_values and status_field:
        action_names: list[str] = []
        for value in status_values:
            slugified = re.sub(r'[^a-z0-9_]+', '_', value.lower()).strip('_')
            method_name = f"mark_as_{slugified}"
            action_names.append(method_name)
            lines.extend([
                "",
                f"    @admin.action(description='Mark as {value}')",
                f"    def {method_name}(self, request, queryset):",
                f"        queryset.update({status_field}=\"{value}\")",
            ])
        if action_names:
            items = ", ".join(action_names)
            lines.append(f"    actions = [{items}]")

    if all(
        not x
        for x in [display_fields, filter_fields, search_fields, readonly_fields, list_editable_fields, autocomplete_fields_list, inline_classes]
    ):
        has_new_content = (
            (time_scope and time_scope.get("date_field"))
            or (time_scope and time_scope.get("year_field"))
            or (status_values and status_field)
            or editable_fields
        )
        if not has_new_content:
            lines.append("    pass")

    lines.append("")
    return "\n".join(lines)
```

**E) Combined `_render_imports` signature:**

```python
def _render_imports(tables: list[dict[str, Any]], *, needs_user_admin: bool, needs_fk_links: bool = False, needs_timezone: bool = False) -> str:
    """Render the ``import`` block."""
    model_names = sorted({get_model_name(t) for t in tables})
    imports = ", ".join(model_names)
    lines = ["from django.contrib import admin"]
    if needs_fk_links:
        lines.append("from django.urls import reverse")
        lines.append("from django.utils.html import format_html")
    if needs_user_admin:
        lines.append("from django.contrib.auth.admin import UserAdmin as BaseUserAdmin")
    if needs_timezone:
        lines.append("from django.utils import timezone")
    lines.append(f"from .models import {imports}")
    return "\n".join(lines) + "\n"
```

**F) Combined `render_admin_py` pre-scans and per-table loop:**

The pre-scan block (after `needs_user_admin` and before `parts`):

```python
    # Pre-scan for FK fields that need link methods (two-pass for imports).
    needs_fk_links = any(
        _is_fk_field(f)
        and f["kwargs"].get("to", "")
        and isinstance(f["kwargs"].get("to", ""), str)
        and f["kwargs"]["to"] != "self"
        for t in tables
        for f in get_fields(t)
    )

    # Determine if any view uses time_scope with year_field (needs timezone import).
    needs_timezone = False
    if manifest:
        for table in tables:
            raw_entity = str(table.get("suggested_model_name") or "").lower()
            view = find_view_for_entity(manifest, raw_entity)
            if view:
                ts = view.get("time_scope") or {}
                if ts.get("year_field"):
                    needs_timezone = True
                    break

    parts: list[str] = [
        _render_header(app_label),
        _render_imports(tables, needs_user_admin=needs_user_admin, needs_fk_links=needs_fk_links, needs_timezone=needs_timezone),
    ]
```

The per-table loop additions (after `autocomplete` block, before `admin_class_parts.append`):

```python
        # FK link display methods — generate _link methods and swap into list_display.
        link_methods: list[str] = []
        for field in contract_fields:
            if _is_fk_field(field):
                target = field["kwargs"].get("to", "")
                if target and isinstance(target, str) and target != "self":
                    if field["name"] in display:
                        link_methods.append(
                            _render_fk_link_method(field["name"], target, app_label)
                        )
                        display = [
                            f"{fn}_link" if fn == field["name"] else fn
                            for fn in display
                        ]

        time_scope = view.get("time_scope") if view else None
        status_values = view.get("status_values") if view else None
        editable_fields = view.get("editable_fields") if view else None

        admin_class_parts.append(
            _render_admin_class(
                model_name=model_name,
                display_fields=display,
                filter_fields=filters,
                search_fields=search,
                readonly_fields=readonly,
                list_editable_fields=list_editable,
                autocomplete_fields_list=autocomplete,
                inline_classes=inline_names,
                verbose_name=verbose_name,
                admin_base_class="BaseUserAdmin" if is_user else "admin.ModelAdmin",
                status_field=status_field,
                link_methods=link_methods,
                time_scope=time_scope,
                status_values=status_values,
                editable_fields=editable_fields,
            )
        )
```

- [ ] **Step 4: Apply the combined admin_generator.py**

Open `workbook/codegen/admin_generator.py` and apply all changes from Step 3 (A-F) to produce the combined version.

Run: `python -c "import ast; ast.parse(open('workbook/codegen/admin_generator.py').read()); print('Syntax OK')"`
Expected: `Syntax OK`

- [ ] **Step 5: Verify tests merged cleanly (no conflict)**

```bash
grep -c "^<<<<<<< " workbook/tests/test_admin_generator.py
# Expect: 0 — test method names don't collide between branches
```

- [ ] **Step 6: Add the combined admin_generator.py and commit the merge**

```bash
git add workbook/codegen/admin_generator.py
git commit
# Use merge commit message, e.g.: "Merge branch 'evolution/admin-formula-fk' into master"
```

- [ ] **Step 7: Run tests**

```bash
make test 2>&1 | tail -30
# Expect: all tests pass (including FK link tests and time-status tests)
```

---

### Task 4: Merge pipeline-manifest into master + update generate-all

**Files:** Modify `Makefile` to add `generate-pipeline-manifest` to `generate-all`.

- [ ] **Step 1: Merge the pipeline-manifest branch**

```bash
git merge evolution/pipeline-manifest
# Expect: fast-forward or clean merge — no conflicts with master
```

- [ ] **Step 2: Run tests**

```bash
make test 2>&1 | tail -20
# Expect: all tests pass (including 8 new pipeline-manifest tests)
```

- [ ] **Step 3: Wire generate-pipeline-manifest into generate-all**

Open `Makefile` and find the `generate-all` target. Add `generate-pipeline-manifest` after `generate-import`.

File: `Makefile`

```makefile
generate-all: generate-models generate-view-manifest generate-admin generate-import generate-pipeline-manifest  ## Run all code generators
```

- [ ] **Step 4: Run build check**

```bash
python -c "from workbook.pipeline_manifest import build_pipeline_manifest; print('Import OK')"
# Expect: Import OK
```

---

### Task 5: Rebase docs-coverage on merged master

**Files:** No file editing — git rebase operation.

- [ ] **Step 1: Verify no file overlap**

```bash
git diff master...docs-coverage --name-only | grep -c workbook/
# Expect: 0 — no workbook/ files touched by docs-coverage
git diff master...docs-coverage --name-only | grep -c "\.py$"
# Expect: non-zero (profiler commands, connectors, etc.) but none overlap with evolution changes
```

- [ ] **Step 2: Rebase docs-coverage onto master**

```bash
git checkout docs-coverage
git rebase master
# Expect: clean rebase — no conflicts expected (docs-coverage touched different files)
```

- [ ] **Step 3: Verify tests + doc coverage still pass**

```bash
make test 2>&1 | tail -10
# Expect: all tests pass

make doc-coverage 2>&1 | tail -10
# Expect: interrogate passes (≥80%)
```

- [ ] **Step 4: Merge docs-coverage into master**

```bash
git checkout master
git merge docs-coverage
# Expect: clean merge
```

---

### Task 6: Add view-manifest reference doc

**Files:**
- Create: `docs/view-manifest.md`

- [ ] **Step 1: Write failing test (no test for docs — verify with build)**

```bash
# Verify the docs-coverage CI gate still passes after adding the doc
make doc-coverage
```

- [ ] **Step 2: Write `docs/view-manifest.md`**

```markdown
# View Manifest Reference

> **Artifact:** `build/view-manifest.yaml`
> **Generator:** `python manage.py scaffold_view_manifest`
> **Version:** `view-manifest-draft-1`

A view manifest captures **UI and workflow** concerns for each spreadsheet tab
mapped to a Django admin view. It is a sibling to the schema contract.

## Top-Level Structure

```yaml
version: view-manifest-draft-1
generated_from:
  structure: profiler-output/structure.json
  contract: build/schema-contract.yaml
views:
  - entity: crop_plan_entry
    worksheet_title: Crop Planner
    label: Crop Plan Entry
    status_field: status
    status_values:
      - Planted
      - Growing
      - Harvested
    time_scope:
      year_field: source_bundle_year
      week_field: plan_week
      date_field: planting_date
      default_scope: current_season
    filterable_by:
      - source_bundle_year
      - status
    editable_fields:
      - crop
      - quantity
      - planting_date
    computed_fields:
      - total_cost
```

## Keys

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `version` | yes | string | Always `view-manifest-draft-1` |
| `generated_from` | yes | object | Source artifacts used to build this manifest |
| `views` | yes | array | One entry per spreadsheet tab |

### View Entry Keys

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `entity` | yes | string | Lowercase snake_case model name matching the contract |
| `worksheet_title` | yes | string | The spreadsheet tab title |
| `label` | no | string | Human-readable label for the admin UI |
| `status_field` | no | string | Column that tracks workflow state |
| `status_values` | no | array | Distinct values for the status field; used to generate admin actions |
| `time_scope` | no | object | Temporal field configuration |
| `filterable_by` | no | array | Columns usable as admin list filters |
| `editable_fields` | no | array | Columns editable in the admin change form |
| `computed_fields` | no | array | Columns that are read-only (spreadsheet formulas) |

### time_scope Keys

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `year_field` | no | string | Column containing the bundle year (e.g. `source_bundle_year`) |
| `week_field` | no | string | Integer column for week number |
| `date_field` | no | string | Date/DateTime column for drill-down navigation |
| `default_scope` | yes | string | Default temporal filter (currently always `current_season`) |

## Admin Generation Effects

When used with `generate_admin`, the view manifest controls:

- `list_display` — from `editable_fields` (up to 5)
- `list_filter` — from `filterable_by`; `status_field` is promoted to first position
- `search_fields` — auto-detected text columns; FK fields get `field__name` notation
- `readonly_fields` — from `computed_fields`
- `date_hierarchy` — from `time_scope.date_field`
- `get_queryset` override — when `time_scope.year_field` is set, filters by current year
- `@admin.action` methods — one per `status_values` entry
- FK link display methods — FK columns in `list_display` become clickable links
```

- [ ] **Step 3: Verify the doc is valid YAML and renders correctly**

```bash
python -c "import yaml; yaml.safe_load(open('docs/view-manifest.md').read().split('```yaml')[1].split('```')[0]); print('YAML OK')"
```

---

### Task 7: Add pipeline-manifest reference doc

**Files:**
- Create: `docs/pipeline-manifest.md`

- [ ] **Step 1: Write `docs/pipeline-manifest.md`**

```markdown
# Pipeline Manifest Reference

> **Artifact:** `build/pipeline-manifest.yaml`
> **Generator:** `python manage.py generate_pipeline_manifest`
> **Version:** `1.0`

A pipeline manifest is a machine-generated execution plan that bridges a schema
contract and corpus configuration into per-year, per-table pull/import
instructions. It is **never hand-edited** and can be regenerated at any time.

## Top-Level Structure

```yaml
version: "1.0"
generated_from:
  contract: schema-contract.yaml
  corpus_config: cohort_corpus.json
source:
  provider: google_sheets
  corpus_years: [2025, 2026]
tables:
  - model: crop_plan_entry
    bundle_worksheet_title: Crop Planner
    output_pattern: "{year}/crop_plan_entry.csv"
    default_values:
      source_bundle_year: "{year}"
    required_headers:
      - Block
      - Crop
    years:
      - year: 2025
        spreadsheet_id: 1ABC...
        worksheet_title: Crop Planner
      - year: 2026
        spreadsheet_id: 1DEF...
        worksheet_title: Crop Planner
```

## Keys

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `version` | yes | string | Manifest format version (`1.0`) |
| `generated_from` | yes | object | Source file references |
| `source` | yes | object | Provider metadata |
| `tables` | yes | array | One entry per contract table |

### Table Entry Keys

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `model` | yes | string | Lowercase snake_case model name |
| `bundle_worksheet_title` | yes | string | Spreadsheet tab title for bundle output |
| `output_pattern` | yes | string | CSV output path template (`{year}` placeholder) |
| `default_values` | yes | object | Static column values per row (supports `{year}`) |
| `required_headers` | yes | array | Columns that must exist in source data |
| `years` | yes | array | Per-year spreadsheet resolution |

## Generation

```bash
# Basic usage
python manage.py generate_pipeline_manifest \
  --contract build/schema-contract.yaml \
  --corpus-config config/cohort_corpus.json \
  --out build/pipeline_manifest.yaml

# With corpus index files for spreadsheet ID resolution
python manage.py generate_pipeline_manifest \
  --contract build/schema-contract.yaml \
  --corpus-config config/cohort_corpus.json \
  --corpus-dir config/ \
  --out build/pipeline_manifest.yaml

# Diff against existing (safe for CI)
python manage.py generate_pipeline_manifest \
  --contract build/schema-contract.yaml \
  --corpus-config config/cohort_corpus.json \
  --diff

# Makefile target
CORPUS_CONFIG=config/cohort_corpus.json make generate-pipeline-manifest
PIPELINE_MANIFEST_OUT=build/pipeline_manifest.yaml CORPUS_CONFIG=config/cohort_corpus.json make generate-pipeline-manifest
```
```

---

### Task 8: Update INDEX, README map, and E2E tutorial

**Files:**
- Modify: `docs/INDEX.md`
- Modify: `README.md`
- Modify: `docs/end-to-end-tutorial.md`

- [ ] **Step 1: Update `docs/INDEX.md`**

Add new rows to the Architecture & Design table:

```markdown
| [View Manifest Reference](view-manifest.md) | adopter | View manifest YAML format, admin generation effects |
| [Pipeline Manifest Reference](pipeline-manifest.md) | operator | Machine-generated execution plan format |
```

Also add an Operations entry for pipeline manifest.

Final `docs/INDEX.md` Architecture & Design section:

```markdown
## Architecture & Design

| Doc | Audience | Description |
|-----|----------|-------------|
| [Architecture](architecture.md) | all | Five-layer design, data flow, Django project layout |
| [Schema Design Loop](schema-design-loop.md) | adopter | Contract-first importer workflow |
| [Schema Contract Reference](schema-contract.md) | adopter | YAML contract format reference (v1.0–v1.3) |
| [View Manifest Reference](view-manifest.md) | adopter | View manifest YAML format, admin generation effects |
| [Pipeline Manifest Reference](pipeline-manifest.md) | operator | Machine-generated execution plan format |
| [Roadmap](roadmap.md) | all | Feature history and v1.0 criteria |
```

- [ ] **Step 2: Update `README.md` documentation map table**

Add new rows to the Documentation Map table (after the schema contract row):

```markdown
| Artifact | Generator | Format |
|---|---|---|
| Schema Contract | `generate_contract` | YAML (v1.0–v1.3) |
| View Manifest | `scaffold_view_manifest` | YAML ([ref](docs/view-manifest.md)) |
| Pipeline Manifest | `generate_pipeline_manifest` | YAML ([ref](docs/pipeline-manifest.md)) |
| Django Models | `generate_models` | `.py` |
| Django Admin | `generate_admin` | `.py` |
| Import Command | `generate_import` | `.py` |
```

- [ ] **Step 3: Update `docs/end-to-end-tutorial.md`**

Insert a new step **"Generate the View Manifest"** between Step 5 (harden contract) and Step 6 (generate models/admin/import):

```markdown
## Step 5b: Generate the View Manifest

A view manifest adds UI and workflow concerns on top of the schema contract:
which fields are editable, which column tracks status, which columns drive
temporal scoping, and which columns should appear in admin list filters.

```bash
python manage.py scaffold_view_manifest \
  --structure profiler-output/structure.json \
  --contract build/schema-contract.yaml \
  --out build/view-manifest.yaml
```

> **Tip:** If you ran `pull_bundle --include-structure`, the `structure.json`
> file is already in `profiler-output/`. The view manifest is re-generatable
> at any time by re-running this command.

The generated `build/view-manifest.yaml` contains one entry per spreadsheet
tab. Open it and review:
- **`status_field`** / **`status_values`** — does the correct status column
  have its distinct values listed?
- **`time_scope`** — are the year/week/date columns correctly identified?
- **`editable_fields`** — do these match the columns users should edit?
- **`computed_fields`** — do these match formula columns?

Edit the manifest if needed — it is hand-editable. The admin generator reads
these values to produce `list_display`, `list_filter`, `date_hierarchy`,
`get_queryset` year-scoping, and bulk status actions.

Step numbers after this increase by 1 (old step 6 → step 7, etc.).
```

Insert a new step **"Generate the Pipeline Manifest"** after the generate step:

```markdown
## Step 8: Generate the Pipeline Manifest

A pipeline manifest is an execution plan that maps each contract table to its
source spreadsheets per year. It is used by downstream tooling to orchestrate
pull and import commands across years.

```bash
python manage.py generate_pipeline_manifest \
  --contract build/schema-contract.yaml \
  --corpus-config config/cohort_corpus.json \
  --out build/pipeline-manifest.yaml
```

The generated file is machine-only and should not be hand-edited.
```

Update any cross-references in the tutorial to account for the new step numbering.

- [ ] **Step 4: Verify the documentation coverage gate still passes**

```bash
make doc-coverage 2>&1 | tail -5
# Expect: interrogate passes (≥80%)
```

---

### Task 9: Final verification

- [ ] **Step 1: Full test suite**

```bash
make test 2>&1 | tail -20
# Expect: all tests pass
```

- [ ] **Step 2: Doc coverage**

```bash
make doc-coverage 2>&1 | tail -5
# Expect: ≥80%
```

- [ ] **Step 3: Clean git status**

```bash
git status
# Expect: clean working tree, no uncommitted changes
```

- [ ] **Step 4: Clean up stale worktrees** (optional — confirm with user)

```bash
git worktree list
# The view-manifest-inference and admin-formula-fk worktrees may be
# candidates for removal since their branches are now merged into master.
```
