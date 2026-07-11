# Portfolio — migration-workbench

> Roadmap: [docs/roadmap.md](../../docs/roadmap.md). 1.0.0 = tabular system
> replaced in the wild. Two tracks converge on it: Track A (Coda engagement
> validation on Vizcarra) and Track B (UI codegen extraction from farm).
> Minors are earned by validation, not by adding code. Patches are
> unit-tested only. Local line is in PyPI-block remediation until 1.0.0.

## Active

| Mission | Track | Earns | Test target | What it proves |
|---------|-------|-------|-------------|----------------|
| `vizcarra-profile-clients` | A | 0.6.0 | vizcarra-guitars | Coda profiler produces a valid contract against real data |
| `wb-checklist-archetype` | B | 0.6.1 | farm | Weekly checklist + HTMX toggle extractable from contract + view manifest |

## Next

| Mission | Track | Earns | Test target |
|---------|-------|-------|-------------|
| `vizcarra-generate-import` | A | 0.6.2 | vizcarra-guitars |
| `wb-landing-archetype` | B | 0.6.3 | farm |
| `vizcarra-views-deploy` | A | 0.7.1 | vizcarra-guitars |
| `wb-dashboard-archetype` | B | 0.7.2 | farm |
| `wb-view-codegen-pipeline` | B | 0.7.3 | farm |
| `vizcarra-generated-ui` | B | 0.8.1 | vizcarra-guitars |
| `vizcarra-cutover` | — | 1.0.0 | vizcarra-guitars |

## Extraction Backlog

Track B sources — patterns proven in `farm_ui`, waiting to become codegen:

- [x] ~~Weekly checklist view with HTMX toggles~~ → `wb-checklist-archetype` (0.6.1)
- [ ] Role-based landing with summary cards → `wb-landing-archetype` (0.6.3)
- [ ] Dashboard archetype with alert counts → `wb-dashboard-archetype` (0.7.2)
- [ ] `wb generate views` command + template package (product-skin overrides) → `wb-view-codegen-pipeline` (0.7.3)
- [ ] Coverage/drift report command
- [ ] Print-friendly weekly summary view

## Cross-Cutting Notes

- Coda People type: needs workbench enrichment. Queue after relation columns (done in 0.5.3 unit-tested; awaits Vizcarra validation).
- MWBS behavioral spec (`profiler/tools/behavioral_spec.py`) ships the semantic input for UI generation: `Actor`, `JobStory`, `WorkflowStep`, `BehavioralEvent`, `BusinessRule`, `Report`, `AcceptanceCriterion`. `workbook/codegen/` has no `view_generator` yet — Track B closes that gap.
- `wb-view-codegen-pipeline` (0.7.3) must wire a `wb generate views` command into `generate-all`. Vizcarra-generated-ui (0.8.1) consumes it; without it, Vizcarra would hand-write UI like farm did.

## Semver policy

- **Patch** — code written, unit-tested, `make chassis-gate` green. Not validated against real data.
- **Minor** — capability proven end-to-end against real data in a product repo.
- **1.0.0** — a real spreadsheet/Coda doc that a team relies on is now a generated Django app they use day-to-day.

Local releases are tag-only until 1.0.0 (PyPI blocks uploads `≤ 0.9.3`). See
[docs/roadmap.md → Semver Recovery](../../docs/roadmap.md#semver-recovery-pypi-block).

## Done

- `coda-formula-classification` — Classify Coda formulas into row/expansion/hybrid taxonomy. (0.5.3, local, unit-tested only)
- `coda-relation-column-profiler` — Detect Coda relation columns and scaffold ForeignKey fields. (0.5.3, local, unit-tested only)