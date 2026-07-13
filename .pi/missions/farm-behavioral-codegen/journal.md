# journal: farm-behavioral-codegen

Track B 0.8.5 — Build a MWBS-to-archetype adapter so views can be
generated directly from behavioral specs, applied to farm.

## Status
Planned.

## Branch
Workbench: `feat/farm-behavioral-codegen`
Farm: direct commits to `main` (per `farm/AGENTS.md`)

## Log

### 2026-07-12 — Designed
- Brief written: MWBS dataclasses exist; view codegen exists; no
  adapter connects them.  Add a `mwbs_to_archetype` module, derive
  farm MWBS, parity-test against `PlannerLandingView` and
  `CropListView`.

### 2026-07-13 — Booted
- `master` chassis-gate: green.
- Worktree `../migration-workbench-farm-behavioral-codegen` on
  branch `feat/farm-behavioral-codegen`.
- Portfolio marked Active: `farm-behavioral-codegen` (Track B, 0.8.5).
- Preconditions: `vizcarra-import-pipeline` (0.8.4) shipped;
  `vizcarra-generated-ui` (0.8.1) established the view codegen pipeline.
