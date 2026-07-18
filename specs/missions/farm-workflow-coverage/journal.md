# journal: farm-workflow-coverage

Track B 0.8.6 — Wire view manifest into ``wb generate views`` so every
farm spreadsheet workflow has a generated list view.

## Status
Planned.

## Branch
Workbench: `feat/farm-workflow-coverage`
Farm: direct commits to `main` (per `farm/AGENTS.md`)

## Log

### 2026-07-12 — Designed
- Brief written: 72 view-manifest entries vs 19 hand-written farm_ui
  views; integrate ``ListArchetype`` into ``generate_views`` command;
  generate coverage report; validate in farm repo.

### 2026-07-13 — Booted
- `master` chassis-gate: green.
- Worktree `../migration-workbench-farm-workflow-coverage` on
  branch `feat/farm-workflow-coverage`.
- Portfolio marked Active: `farm-workflow-coverage` (Track B, 0.8.6).
- Preconditions: `farm-behavioral-codegen` (0.8.5) shipped; ListArchetype
  and MWBS adapter established.

### 2026-07-13 — Vertical Slice 1: Manifest loader + adapter

- `workbook/codegen/manifest_loader.py` with `load_view_manifest` and
  `manifest_to_list_archetype`.
- 9 unit tests: loading, normalisation, entity derivation, filter config,
  time_scope, renderable output, unknown entity fallback, coverage.

### 2026-07-13 — Vertical Slice 2: Command integration

- `--archetype-list-from-manifest` flag on `wb generate views`.
- `_handle_list_from_manifest` reads manifest, creates ListArchetypes,
  writes views_auto.py, urls_auto.py, templates.
- 4 integration tests: file creation, all entries present, valid Python,
  filter logic.

### 2026-07-13 — Vertical Slice 3: Farm validation

- Run against farm 72-entry manifest → 14 unique list views (1 per entity).
- Deduplication by entity prevents class name collisions.
- `build/_out/workflow-coverage.md` coverage report.
- Real-data tests validate all hand-written views have generated counterparts.
- Farm test suite: 107 passed.
- Workbench: 1811 passed; chassis-gate green.

**All success criteria met. Ready for release.**
