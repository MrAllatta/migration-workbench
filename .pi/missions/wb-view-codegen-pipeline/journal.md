# journal: wb-view-codegen-pipeline

Track B mission to wire `wb generate views` into the CLI and `generate-all`,
and add template package / product-skin override blocks for all archetypes.

## Status
Booted.

## Branch
`feat/wb-view-codegen-pipeline`

## Log

### 2026-07-12 — Boot
- Chosen from portfolio Next table (priority order: 0.7.3).
- `wb-dashboard-archetype` (0.7.2) already merged to master and tagged.
- Portfolio updated: extraction backlog dashboard item marked done,
  `wb-view-codegen-pipeline` marked Active on master.
- Feature branch created from master.
- Brief written and committed.

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
