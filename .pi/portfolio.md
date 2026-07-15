# Portfolio — migration-workbench

> **Engine roadmap:** [docs/roadmap.md](../../docs/roadmap.md) tracks workbench
> capability releases. **Product roadmaps:** [docs/product-roadmaps.md](../../docs/product-roadmaps.md)
> track what each client engagement (Vizcarra, farm) must reach before its
> tabular system is retired. Minors are earned by product validation, not
> by adding engine code. Patches are unit-tested only. The local line is
> in PyPI-block remediation until 1.0.0. Semver minors are integers:
> `0.10.0`, `0.11.0`, etc. are valid and used for product-validated
> milestones before `1.0.0`.

## Active

The engine is ready (0.9.4). The next work is product-side specification
enrichment and validation in the two engagements. Tracks A and B advance
independently; the first product-validated milestone earns 0.10.0.

| Mission | Track | Earns | Test target |
|---------|-------|-------|-------------|
| `vizcarra-acceptance-validation` | A | 0.10.0 | vizcarra-guitars |
| `farm-behavioral-elicitation` | B | 0.10.0 | farm |

## Next

| Mission | Track | Earns | Test target |
|---------|-------|-------|-------------|
| `vizcarra-parallel-run` | A | 0.11.0 | vizcarra-guitars |
| `farm-interaction-contract` | B | 0.11.0 | farm |

## Extraction Backlog

Track B sources — patterns proven in `farm_ui`, waiting to become codegen:

- [x] ~~Weekly checklist view with HTMX toggles~~ → `wb-checklist-archetype` (0.6.1)
- [x] ~~Role-based landing with summary cards~~ → `wb-landing-archetype` (0.6.3)
- [x] ~~Dashboard archetype with alert counts~~ → `wb-dashboard-archetype` (0.7.2)
- [x] ~~`wb generate views` command + template package (product-skin overrides)~~ → `wb-view-codegen-pipeline` (0.7.3)
- [ ] Coverage/drift report command
- [ ] Print-friendly weekly summary view

## Cross-Cutting Notes

- MWBS behavioral spec (`profiler/tools/behavioral_spec.py`) ships the semantic input for UI generation: `Actor`, `JobStory`, `WorkflowStep`, `BehavioralEvent`, `BusinessRule`, `Report`, `AcceptanceCriterion`. `workbook/codegen/view_generator.py` now ships checklist, landing, dashboard archetypes plus the full `wb generate views` pipeline (0.6.1/0.6.3/0.7.2/0.7.3). The vizcarra session of 2026-07-14 consumed the pipeline and enriched the spec to 1,691 lines of behavioral spec, 998 lines of view manifest, and 545 lines of interaction contract.
- **0.9.4 revision:** `cutover-prep` (0.9.4) proved the engine was capable, not that the engagements were ready to cut over. The recent Vizcarra session (2026-07-14) enriched the behavioral spec, interaction contract, and view manifest, producing 39 view classes and 58 templates *after* 0.9.4. Engagement milestones now live in [docs/product-roadmaps.md](../../docs/product-roadmaps.md).
- **Track A sequence (revised):** Vizcarra now moves through `vizcarra-acceptance-validation` (0.10.0) → `vizcarra-parallel-run` (0.11.0) → `vizcarra-coda-retired` (0.12.0) → `vizcarra-operational-maturity` (0.13.0).
- **Track B sequence (revised):** Farm now moves through `farm-behavioral-elicitation` (0.10.0) → `farm-interaction-contract` (0.11.0) → `farm-generated-views-wired` (0.12.0) → `farm-data-reconciliation` (0.13.0) → `farm-spreadsheet-retired` (0.14.0) → `farm-operational-maturity` (0.15.0).
- **Joint 1.0.0 gate:** Both engagements retired and the consultant playbook proven. See [docs/product-roadmaps.md](../../docs/product-roadmaps.md).

## Semver policy

- **Patch** — code written, unit-tested, `make chassis-gate` green. Not validated against real data.
- **Minor** — product capability proven end-to-end against real data in a product repo. Minors are integers: `0.10.0`, `0.11.0`, etc. follow `0.9.x` naturally.
- **1.0.0** — both engagements retired per their product roadmaps; consultant playbook proven; engine ready for a third engagement.

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
- `farm-data-migration` — Crop alias resolution eliminates 674 stale-FK errors in farm import pipeline. ``config/crop_aliases.csv`` + ``_resolve_crop_name``/``_get_or_create_crop_by_alias``. Real-data reconciliation tests validate full bundle import (27 166 rows, 0 errors). (0.8.7, local)
- `cutover-prep` — Joint readiness gate for both engagements. Readiness report, two runbooks (Vizcarra + farm), go/no-go decision (GO). All pre-cutover sequences complete. (0.9.4, local)