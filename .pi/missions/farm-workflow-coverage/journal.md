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
