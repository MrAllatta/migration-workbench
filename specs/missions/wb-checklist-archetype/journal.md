# Journal: wb-checklist-archetype

## 2026-07-11 — Boot

**Decision why this mission:**
`vizcarra-profile-clients` shipped (0.6.0). Track A just proved the Coda profiler end-to-end. The next version (0.6.1) is Track B's first UI codegen archetype. Switching tracks keeps both sides of the pipeline moving. The brief is already written and approved.

**Studied farm_ui references:**
- `views/checklists.py` — 3 class-based ListViews (TaskChecklistView, PlantingChecklistView, NurseryChecklistView) with year/week navigation, HTMX toggle handlers
- `templates/farm_ui/checklist_tasks.html` — header with week nav, data table with status badges, HTMX toggle per row
- `urls.py` — URL patterns for checklist views follow `farm_ui_<name>` naming
- `core/models.py:288` — PlantingPlan (crop, field_block, planned_year, planned_week), TaskPlan (same + category/status), NurserySeedingSchedule (seeding_year, seeding_week, seeded/germinated/thinned)

**Workbench codegen conventions studied:**
- `stub_writer.py` — `*_auto.py` + stub convention (ensure_stub writes import line + marker)
- `python_render.py` — shared rendering utilities (indent, identifier sanitization)
- `model_generator.py` — `render_model()` returns Python source string
- `admin_generator.py` — follows same module pattern

### Plan

Phase 1 — `workbook/codegen/view_generator.py`:
- `generate_checklist_view()` -> view Python source, URL fragment, template HTML
- Generates: `ListView` subclass with year/week `_resolve_week_year()`, `get_queryset()`, `get_context_data()`, prev/next/this-week nav
- Template: `<table>` with configurable fields, status badge for status field, HTMX toggle for boolean field
- Config dict: model name, fields list, year_field, week_field, status_field, toggle_field(s), template_name, url_prefix, url_namespace

Phase 2 — `workbook/management/commands/generate_views.py`:
- Reads schema contract + view manifest
- `--archetype-checklist` flag with config overrides
- Writes to `views_auto.py`, `urls_auto.py`, template file

Phase 3 — Workbench unit test:
- Synthetic contract + view manifest -> generate -> assert valid Python

Phase 4 — Farm real-data test:
- Editable-install workbench in farm, generate view for PlantingPlan, test response

Phase 5 — Squash-merge and release 0.6.1

### Starting state
- Branch: `feat/wb-checklist-archetype`
- make chassis-gate: 1628 passed, 1 warning

## 2026-07-11 — Session 1 (BUILD + FARM TEST)

### Built
- **`workbook/codegen/view_generator.py`** — Core module with:
  - `ChecklistArchetype` dataclass (model, year_field, week_field, columns,
    select_related, ordering, status_field, toggle_field, template, URLs)
  - `render_checklist_view_py()` — generates Django `ListView` with
    `get_queryset()` filtered by year/week, `get_context_data()` with
    prev/next nav
  - `render_toggle_handler_py()` — generates `@require_POST`/`@login_required`
    HTMX toggle handler
  - `render_checklist_template_html()` — generates Django template with
    week nav bar, `<table class="data-table">`, status badges, hx-post toggle
  - `render_views_auto_py()` + `render_urls_auto_py()` — combined
    multi-archetype auto modules
  - `build_archetype_from_contract()` — auto-derives columns,
    select_related, ordering from contract table
- **`workbook/management/commands/generate_views.py`** — Management command
  with `--archetype-checklist auto` (auto-discover) and explicit targets
- **43 unit tests** in `workbook/tests/test_view_generator.py` — covers:
  archetype defaults, view Python (ast-validated), template structure, URL
  patterns, toggle handlers, combined modules, factory from contract, and
  management command end-to-end (call_command)

### Farm real-data test
- Created `feat/test-wb-checklist-archetype` branch in farm repo
- Generated `PlantingPlanChecklistView` via `generate_views` command
- Created `generated/` Django app in farm with views_auto.py, urls_auto.py,
  template (extends farm_ui/base.html), and URL include in root URLconf
- **6 tests pass**: login required, year+week in header, one row per
  PlantingPlan (crop + block), table structure, empty state, week nav

### Gate
- workbench: 1671 passed, 1 warning
- farm: 6/6 passed

### Commits (workbench)
```
0f85b61 feat(views): add checklist archetype view generator with HTMX toggle support
```

### Ready for merge
- Portfolio updated, branch ready for squash-merge to master
- Version bump to 0.6.1, changelog entry, tag v0.6.1 pending
