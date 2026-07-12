# Portfolio — migration-workbench

> Roadmap: [docs/roadmap.md](../../docs/roadmap.md). 1.0.0 = tabular system
> replaced in the wild. Two tracks converge on it: Track A (Coda engagement
> validation on Vizcarra) and Track B (UI codegen extraction from farm).
> Minors are earned by validation, not by adding code. Patches are
> unit-tested only. Local line is in PyPI-block remediation until 1.0.0.

## Active

- `wb-view-codegen-pipeline` (Track B, 0.7.3) — `wb generate views` CLI command, template package/product-skin overrides, wired into `generate-all`

## Next

| Mission | Track | Earns | Test target |
|---------|-------|-------|-------------|
| `wb-view-codegen-pipeline` | B | 0.7.3 | farm |
| `vizcarra-generated-ui` | B | 0.8.1 | vizcarra-guitars |
| `vizcarra-cutover` | — | 1.0.0 | vizcarra-guitars |

## Extraction Backlog

Track B sources — patterns proven in `farm_ui`, waiting to become codegen:

- [x] ~~Weekly checklist view with HTMX toggles~~ → `wb-checklist-archetype` (0.6.1)
- [x] ~~Role-based landing with summary cards~~ → `wb-landing-archetype` (0.6.3)
- [x] ~~Dashboard archetype with alert counts~~ → `wb-dashboard-archetype` (0.7.2)
- [ ] `wb generate views` command + template package (product-skin overrides) → `wb-view-codegen-pipeline` (0.7.3)
- [ ] Coverage/drift report command
- [ ] Print-friendly weekly summary view

## Cross-Cutting Notes

- Coda People type: needs workbench enrichment. Queue after relation columns (done in 0.5.3 unit-tested; awaits Vizcarra validation).
- MWBS behavioral spec (`profiler/tools/behavioral_spec.py`) ships the semantic input for UI generation: `Actor`, `JobStory`, `WorkflowStep`, `BehavioralEvent`, `BusinessRule`, `Report`, `AcceptanceCriterion`. `workbook/codegen/view_generator.py` now ships the checklist and landing archetypes (0.6.1/0.6.3) — Track B continues with dashboard, pipeline, and farm-skin override archetypes.
- `wb-view-codegen-pipeline` (0.7.3) must wire a `wb generate views` command into `generate-all`. Vizcarra-generated-ui (0.8.1) consumes it; without it, Vizcarra would hand-write UI like farm did.
- **Track A gap:** After `vizcarra-views-deploy` (0.7.1), no Track A mission is planned until `vizcarra-cutover` (1.0.0). If 0.8.1 surfaces Coda-side issues, handle as patches or a new Track A mission — they do not block the UI codegen track.

## Semver policy

- **Patch** — code written, unit-tested, `make chassis-gate` green. Not validated against real data.
- **Minor** — capability proven end-to-end against real data in a product repo.
- **1.0.0** — a real spreadsheet/Coda doc that a team relies on is now a generated Django app they use day-to-day.

Local releases are tag-only until 1.0.0 (PyPI blocks uploads `≤ 0.9.3`). See
[docs/roadmap.md → Semver Recovery](../../docs/roadmap.md#semver-recovery-pypi-block).

## Done

- `wb-dashboard-archetype` — Dashboard archetype with alert cards and detail tables, generated from YAML config. 27 workbench unit tests + 7 farm real-data tests pass. (0.7.2, local)
- `vizcarra-views-deploy` — Profiled Work Orders/Instruments/ArchivedWorkOrders FK target tables, generated certified contracts + models/admin/import, deployed landing view. 25 tests pass in vizcarra-guitars. (0.7.1, local)
- `vizcarra-profile-clients` — Coda profiler + page composition + schema contract against real Vizcarra Guitars Coda doc. (0.6.0, released)
- `wb-checklist-archetype` — Checklist archetype view generator with HTMX toggle, proven against real farm PlantingPlan data. (0.6.1, released)
- `vizcarra-generate-import` — Codegen pipeline (models/admin/import) executed against validated Vizcarra Clients contract. Fixed comment-only computed-field expression bug. (0.6.2, released)
- `wb-landing-archetype` — Role-based landing page archetype with summary cards, proven against real farm data. Auto-detects model imports from count expressions. (0.6.3, released)
- `coda-formula-classification` — Classify Coda formulas into row/expansion/hybrid taxonomy. (0.5.3, local, unit-tested only)
- `coda-relation-column-profiler` — Detect Coda relation columns and scaffold ForeignKey fields. (0.5.3, local, unit-tested only)