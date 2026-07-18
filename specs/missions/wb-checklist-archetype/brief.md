# brief: wb-checklist-archetype

## Context
Track B (UI codegen extraction). The farm engagement built a hand-written
`farm_ui` app with 15 templates, 5 view modules, role-based landings, weekly
checklists, dashboards, and print views. Every new engagement without UI
codegen pays the same human cost.

The MWBS behavioral spec (`profiler/tools/behavioral_spec.py`) already ships
the semantic input for UI generation: `Actor`, `BehavioralWorkflow`,
`WorkflowStep`, `JobStory`, `BehavioralEvent`, `Report`,
`AcceptanceCriterion`. But `workbook/codegen/` has only `model_generator.py`,
`admin_generator.py`, `import_generator.py` — no `view_generator` or
`template_generator`.

This mission extracts the **weekly checklist** pattern proven in farm_ui as
the first workbench view archetype. The farm test target exercises the
generated view against real planting-plan data for the current ISO week. The
test must pass in farm's environment, not just workbench unit tests — this is
what earns the 0.6.1 patch.

## Goal
Create a new `workbook/codegen/view_generator.py` module that reads a
behavioral spec + schema contract + view manifest and produces a Django
`ListView` + template + HTMX toggle handler for the weekly checklist
archetype. Prove it works by generating the view for farm's `TaskPlan` or
`PlantingPlan` model, installing it in the farm repo, and passing a
real-data test.

## Repo
migration-workbench (primary) + farm (test target)

## Starting State
- `workbook/codegen/` has: `admin_generator.py`, `model_generator.py`,
  `import_generator.py`, `contract.py`, `manifest.py`, `python_render.py`,
  `stub_writer.py`, `designed_model_detection.py`, `validation_pipeline.py`
- `profiler/tools/behavioral_spec.py` ships: `BehavioralWorkflow` (with
  `steps`, `job_story`, `actor`, `emits`, `acceptance_tests`, `operational`,
  `data_entry`), `Actor` (with `responsibilities`, `access_level`),
  `WorkflowStep` (with `actor_action`, `system_provides`,
  `contains_decision`), `Report`, `AcceptanceCriterion`
- `workbook/view_manifest.py` ships: `build_view_manifest()` that identifies
  status fields, editable fields, time scope, workflow hints
- `workbook/management/commands/scaffold_view_manifest.py` generates a
  first-draft view manifest from profiler structure
- farm's `farm_ui/views/checklists.py` has `TaskChecklistView`,
  `PlantingChecklistView`, `NurseryChecklistView` with year/week navigation,
  HTMX toggles, and selective_related loading
- farm's `farm_ui/templates/farm_ui/checklist_tasks.html` has a
  year+week-navigable data table with HTMX toggle button
- farm's `farm_ui/urls.py` has 22 URL patterns (landings, checklists, HTMX
  handlers, dashboards, prints, data lists)
- 1620 tests pass; `make chassis-gate` green

## Scope
### In-scope
1. Define a `ChecklistArchetype` in a new `workbook/archetypes/` module (or
   within a new `view_generator.py`) that describes the checklist pattern:
   - `model`: the Django model to list
   - `year_field`: field name for the year filter
   - `week_field`: field name for the week filter
   - `fields`: columns to display (field name → header label)
   - `htmx_toggle`: optional field name + handler for toggling a boolean
   - `template_name`: generated template path
2. Create `workbook/codegen/view_generator.py` with:
   - `generate_checklist_view(contract, view_manifest, archetype_config)`
     → returns view Python source, template HTML source, URL patterns
   - The generated view must include year/week navigation, prev/next links,
     and HTMX toggle support
   - The generated template must render a data table with status badges,
     year/week navigation, and an HTMX toggle button per row
   - Wire into `generate_all` Makefile target
3. Create `workbook/management/commands/generate_views.py` command:
   - Reads a schema contract YAML and view manifest YAML
   - Accepts `--archetype-checklist` flag
   - Uses `view_generator` to produce `views_auto.py`, `urls_fragment.py`,
     and template file under a `templates/generated/` directory
   - Follows the existing `*_auto.py` + stub `views.py` re-export convention
4. Test the generator against farm's `TaskPlan` model:
   - Write a workbench unit test in `workbook/tests/` that generates a
     checklist view from a synthetic contract + view manifest and asserts the
     output is valid Python and Django-renderable
5. **Real-data test in farm repo (earns the patch):**
   - Create a farm test that installs the generated view (via editable
     workbench install), exercises it against real `PlantingPlan` records
     for the current ISO week, and asserts the response has the right
     HTML structure (year+week in heading, one row per PlantingPlan record,
     toggle button present)
   - Commit this test to the farm repo on a `feat/test-wb-checklist-archetype`
     branch
   - Run the test against the real farm database; it must pass

### Out-of-scope
- This mission extracts ONLY the checklist archetype. Role-based landing
  pages, dashboards, print views are later missions (0.6.3, 0.7.2).
- Multi-model checklists (the nursery checklist shows two models on one page)
  — that's a future enhancement.
- Product-skin override blocks and template inheritance hierarchy — that's
  `wb-view-codegen-pipeline` (0.7.3).
- Integrating with a behavioral spec `BehavioralWorkflow` — for this first
  checkpoint, the archetype config is provided as an explicit CSV/dict
  parameter. Behavioral spec integration comes after the archetype is proven.

## Success Criteria
- [ ] `generate_views --archetype-checklist` produces valid Python + Django
      template for a given model, contract, and view manifest
- [ ] The generated view has year/week navigation (prev/next links + "this
      week" link) and an HTMX toggle button per row
- [ ] The generated template renders a `<table>` with header row matching the
      `fields` config, and status badges
- [ ] A workbench unit test asserts the generated code is valid Python and
      imports/renders without error
- [ ] **A farm repo test exercises the generated view against real
      `PlantingPlan` records for the current ISO week and passes**
- [ ] The generated `views_auto.py` follows the existing `*_auto.py` + stub
      convention (stub not written if it exists, auto file overwritten)
- [ ] `make chassis-gate` passes in workbench
- [ ] Feature branch is squash-merged to master and deleted

## Constraints
- Do NOT modify farm's existing hand-written `farm_ui`. The generated view
  lives alongside it in a separate `generated/` namespace.
- Do NOT modify the MWBS behavioral spec schema. The archetype config is
  explicit CSV/dict for this first checkpoint.
- Do NOT commit to master. Work in `feat/wb-checklist-archetype`.
- The farm test must pass against REAL data in the farm repo's CI-equivalent
  environment (local `db.sqlite3` with actual records).

## Reference
- Farm checklist views: `farm/backend/apps/farm_ui/views/checklists.py`
- Farm checklist template: `farm/backend/apps/farm_ui/templates/farm_ui/checklist_tasks.html`
- Farm URL patterns: `farm/backend/apps/farm_ui/urls.py`
- MWBS schema: `profiler/tools/behavioral_spec.py`
- MWBS design spec: `docs/superpowers/specs/2026-06-26-mwbs-behavioral-spec-design.md`
- Admin generator pattern (follow same conventions):
  `workbook/codegen/admin_generator.py`
- Import generator pattern: `workbook/codegen/import_generator.py`
- Python render utilities: `workbook/codegen/python_render.py`

## Earns
0.6.1 — Weekly checklist archetype proven against real farm data.
