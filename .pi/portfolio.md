# Portfolio — migration-workbench

> Roadmap: [docs/roadmap.md](../../docs/roadmap.md). 1.0.0 = both the farm
> spreadsheet and the Vizcarra Coda doc replaced in the wild. Two tracks
> converge on it: Track A (Coda engagement validation + cut-over on
> Vizcarra) and Track B (UI codegen extraction from farm + farm cut-over).
> Minors are earned by validation, not by adding code. Patches are
> unit-tested only. Local line is in PyPI-block remediation until 1.0.0.

## Active

| Mission | Track | Earns | Test target |
|---------|-------|-------|-------------|
| `farm-data-migration` | B | 0.8.7 | farm |

## Next

| Mission | Track | Earns | Test target |
|---------|-------|-------|-------------|
| `cutover-prep` | — | 0.9.4 | farm + vizcarra |
| `cutover` | — | 1.0.0 | farm + vizcarra |

## Extraction Backlog

Track B sources — patterns proven in `farm_ui`, waiting to become codegen:

- [x] ~~Weekly checklist view with HTMX toggles~~ → `wb-checklist-archetype` (0.6.1)
- [x] ~~Role-based landing with summary cards~~ → `wb-landing-archetype` (0.6.3)
- [x] ~~Dashboard archetype with alert counts~~ → `wb-dashboard-archetype` (0.7.2)
- [x] ~~`wb generate views` command + template package (product-skin overrides)~~ → `wb-view-codegen-pipeline` (0.7.3)
- [ ] Coverage/drift report command
- [ ] Print-friendly weekly summary view

## Cross-Cutting Notes

- MWBS behavioral spec (`profiler/tools/behavioral_spec.py`) ships the semantic input for UI generation: `Actor`, `JobStory`, `WorkflowStep`, `BehavioralEvent`, `BusinessRule`, `Report`, `AcceptanceCriterion`. `workbook/codegen/view_generator.py` now ships checklist, landing, dashboard archetypes plus the full `wb generate views` pipeline (0.6.1/0.6.3/0.7.2/0.7.3). `vizcarra-generated-ui` (0.8.1) consumes the pipeline on Vizcarra; Track B then applies the same pipeline back to farm (0.8.5–0.8.7) to retire the farm spreadsheet.
- **Track A sequence to 1.0.0:** After `vizcarra-views-deploy` (0.7.1), three Coda-side validation missions harden Vizcarra for cutover:
  1. `vizcarra-people-type` (0.8.2) — map Coda People columns to Django users.
  2. `vizcarra-formula-parity` (0.8.3) — validate business-critical Coda formulas against generated computed fields.
  3. `vizcarra-import-pipeline` (0.8.4) — repeatable, reconciled Coda→Django import.
- **Track B sequence to 1.0.0:** After `wb-view-codegen-pipeline` (0.7.3), three farm missions close the cut-over gap:
  1. `farm-behavioral-codegen` (0.8.5) — generate views directly from the MWBS behavioral spec.
  2. `farm-workflow-coverage` (0.8.6) — map every farm spreadsheet workflow to a generated view.
  3. `farm-data-migration` (0.8.7) — import and reconcile real farm spreadsheet data.
- **Joint 1.0.0 gate:** `cutover-prep` (0.9.4) — dry-run, readiness checklist, runbook, go/no-go for both engagements. Then `cutover` (1.0.0) retires both the farm spreadsheet and the Vizcarra Coda doc.

## Semver policy

- **Patch** — code written, unit-tested, `make chassis-gate` green. Not validated against real data.
- **Minor** — capability proven end-to-end against real data in a product repo.
- **1.0.0** — both the farm spreadsheet and the Vizcarra Coda doc that teams rely on are now generated Django apps they use day-to-day.

Local releases are tag-only until 1.0.0 (PyPI blocks uploads `≤ 0.9.3`). See
[docs/roadmap.md → Semver Recovery](../../docs/roadmap.md#semver-recovery-pypi-block).

## Done

- `vizcarra-generated-ui` — Vizcarra-guitars consumes the `wb generate views` pipeline: template package with Vizcarra brand base template, regenerated landing view, dashboard archetype for Instruments (alert cards + detail table). 5 new real-data tests in vizcarra-guitars (30 total pass). Proves the view codegen pipeline generalises beyond farm. (0.8.1, local)
- `wb-view-codegen-pipeline` — `wb generate views` CLI command with `--template-package` support, `base_template` on all archetypes, `{% block %}` override points in generated templates, `generate-views` wired into `generate-all`. 23 workbench unit tests + 2 farm real-data tests pass. (0.7.3, local)
- `wb-dashboard-archetype` — Dashboard archetype with alert cards and detail tables, generated from YAML config. 27 workbench unit tests + 7 farm real-data tests pass. (0.7.2, local)
- `vizcarra-views-deploy` — Profiled Work Orders/Instruments/ArchivedWorkOrders FK target tables, generated certified contracts + models/admin/import, deployed landing view. 25 tests pass in vizcarra-guitars. (0.7.1, local)
- `vizcarra-profile-clients` — Coda profiler + page composition + schema contract against real Vizcarra Guitars Coda doc. (0.6.0, released)
- `wb-checklist-archetype` — Checklist archetype view generator with HTMX toggle, proven against real farm PlantingPlan data. (0.6.1, released)
- `vizcarra-generate-import` — Codegen pipeline (models/admin/import) executed against validated Vizcarra Clients contract. Fixed comment-only computed-field expression bug. (0.6.2, released)
- `wb-landing-archetype` — Role-based landing page archetype with summary cards, proven against real farm data. Auto-detects model imports from count expressions. (0.6.3, released)
- `coda-formula-classification` — Classify Coda formulas into row/expansion/hybrid taxonomy. (0.5.3, local, unit-tested only)
- `coda-relation-column-profiler` — Detect Coda relation columns and scaffold ForeignKey fields. (0.5.3, local, unit-tested only)
- `vizcarra-people-type` — Coda People columns mapped to Django users. Profiler detects person columns (is_user_reference=True), contract upgrades to ForeignKey(auth.User), product repo resolves Coda JSON-LD to User records during import. 6 new workbench tests + 25 new product-repo tests. (0.8.2, local)
- `vizcarra-formula-parity` — Business-critical Work Orders formulas validated against 552 real Coda rows. Five compute_* methods on WorkOrders model with real-data parity tests. Taxable?, Total, Top 5, Tax at 100% agreement; Paid? at 83% (94 rows have manual Coda overrides). 17 unit tests + 6 real-data tests. (0.8.3, local)
- `vizcarra-import-pipeline` — Full Coda→Django import pipeline for 4 tables (Clients, WorkOrders, Instruments, ArchivedWorkOrders). Compound unique key, FK nullification, date tolerance, reconciliation post-check. 2232 records imported with 0 errors. (0.8.4, local)
- `farm-behavioral-codegen` — MWBS-to-archetype adapter bridges behavioral spec to view codegen. Derives farm MWBS YAML from existing artifacts. 14 real-data parity tests validate generated views against 5 hand-written farm_ui views. (0.8.5, local)
- `farm-workflow-coverage` — View-manifest-driven list view generation for all 72 farm spreadsheet workflows. ``manifest_loader.py`` + ``generate_views --archetype-list-from-manifest``. 14 unique entity-based views emitted; coverage report + real-data validation tests. (0.8.6, local)