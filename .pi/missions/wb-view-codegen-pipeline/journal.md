# journal: wb-view-codegen-pipeline

Track B mission to wire `wb generate views` into the CLI and `generate-all`,
and add template package / product-skin override blocks for all archetypes.

## Status
RELEASED. Squash-merged to master, tagged v0.7.3.

## Branch
`feat/wb-view-codegen-pipeline` (deleted after merge)

## Log

### 2026-07-12 — Boot
- Chosen from portfolio Next table (priority order: 0.7.3).
- `wb-dashboard-archetype` (0.7.2) already merged to master and tagged.
- Portfolio updated: extraction backlog dashboard item marked done,
  `wb-view-codegen-pipeline` marked Active on master.
- Feature branch created from master.
- Brief written and committed.

### 2026-07-12 — Implementation
- Added `base_template` to `ChecklistArchetype` and `LandingArchetype`
  (already on `DashboardArchetype`).
- Updated all three template renderers to emit `{% block %}` override
  points: `title`, `content`, archetype-specific (`checklist_heading`,
  `checklist_week_nav`, `checklist_table`, `checklist_bottom_links`,
  `landing_heading`, `landing_summary_cards`, `dashboard_heading`,
  `dashboard_alert_cards`, `dashboard_sections`).
- Added `_resolve_template_source()` helper and `--template-package` flag
  to `generate_views` management command; if a file exists at the same
  relative path in the template package, its content is used at generation
  time.
- Added `_generate_views()` handler and `views` subcommand parser to
  `wb_cli.py`, mirroring the `wb generate {models,admin,import}` pattern.
- Added `generate_views_block()` to `workbook/makefile_targets.py`; wired
  into `generate-all` dependencies and `phonies` list. Updated main
  `Makefile` with `generate-views` target, `VIEWS_DIR` and
  `TEMPLATE_PACKAGE` variables.

### 2026-07-12 — Tests
- 23 new workbench unit tests: `base_template` defaults on all three
  archetypes, template block override points, `wb generate views` argument
  forwarding, `generate_views_block` Makefile target, `generate-all`
  includes `generate-views`, `_resolve_template_source` package override
  logic.
- 2 new farm real-data tests (`test_template_package_override.py`):
  override template is used when `--template-package` has a matching file;
  default is used when no override exists.
- Workbench: 1743 passed, 1 warning. Farm: 21 generated archetype tests
  pass (6 checklist + 6 landing + 7 dashboard + 2 template-package).

### 2026-07-12 — Release
- Version bumped 0.7.2 → 0.7.3. Changelog updated in README.md.
- Squash-merged `feat/wb-view-codegen-pipeline` → `master`.
- Tagged `v0.7.3`.
- Local feature branch deleted. Master is clean.
- `make hygiene`: all clean.

## Final State
- Workbench: master at 311619a (tag: v0.7.3)
- Farm: main at 65d0f66 (regenerated dashboard template + template-package test)
- Gate: 1743 passed, 1 warning (green)

## Follow-ups
- Track B pipeline is complete: `wb generate views` wired into `generate-all`
  with template package / product-skin overrides. Next: `vizcarra-generated-ui`
  (0.8.1) consumes this to run Vizcarra on workbench-generated views.
- Per-archetype module name support in the generator still pending (avoids
  manual file rename when mixing archetypes).

### 2026-07-12 — Working tree state (snapshot)
At review time, the working tree contains uncommitted changes toward all three
brief deliverables:
- **`deployment/wb_cli.py`** — `_generate_views()` handler + `views` subcommand
  parser added (deliverable #1: CLI command).
- **`workbook/codegen/view_generator.py`** — `base_template` field added to
  `ChecklistArchetype` and `LandingArchetype`; `{% block title %}`, archetype-
  specific block overrides, and dynamic `base_template` rendering added to all
  three template renderers (deliverable #2: template package / product-skin
  overrides).
- **`workbook/management/commands/generate_views.py`** — `_resolve_template_source()`
  helper, `--template-package` argument, wiring passed through all three
  archetype handlers (deliverable #2: override mechanism).
- **`workbook/makefile_targets.py`** — `generate_views_block()` target with
  conditional config-file detection, added to phonies and `generate-all`
  dependency list (deliverable #3: generate-all wiring).

Not yet done: tests (deliverable #4), farm real-data test, final gate,
merge and tag. This snapshot was recorded at 19:14 UTC; verify `git diff`
before continuing.
