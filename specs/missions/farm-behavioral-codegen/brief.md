# brief: farm-behavioral-codegen (Track B, 0.8.5)

## Context

The workbench already ships a rich **Migration Workbench Behavioral
Specification (MWBS)** schema (``profiler/tools/behavioral_spec.py``)
covering ``Actor``, ``JobStory``, ``WorkflowStep``, ``BehavioralEvent``,
``BusinessRule``, ``Report``, and ``AcceptanceCriterion`` — all as
first-class dataclasses with YAML serialization.

The workbench also ships a **view codegen pipeline**
(``workbook/codegen/view_generator.py``) with four archetypes (landing,
checklist, list, dashboard) that generate Django views + templates + URLs
from a schema contract and view manifest.

The gap: **the view codegen pipeline does not consume MWBS data.** It
takes a schema contract and view manifest as input, not ``Actor``,
``Report``, or ``WorkflowStep`` instances.  There is no adapter that
maps MWBS to archetype configs.

Meanwhile, farm's ``backend/apps/farm_ui/`` has 6 hand-written view
modules (landing, lists, checklists, dashboards, prints, auth) and 17
hand-written templates that proved the UI patterns.  The behavioral
spec has never been derived for farm — no MWBS YAML exists in
``config/``.  Closing the gap means both deriving a MWBS for farm and
building the adapter that turns it into generated views.

## Goal

Build a **MWBS-to-archetype adapter** in the workbench codegen layer so
that an MWBS behavioral spec YAML file can be used as input to the view
generator, producing Django views + templates comparable to what farm's
hand-written ``farm_ui/`` provides.

## Starting State

- MWBS dataclasses exist in ``profiler/tools/behavioral_spec.py`` (877
  lines, tested through ``profiler/tests/test_behavioral_spec.py``).
- MWBS elicitor exists in ``profiler/tools/behavioral_spec_elicitor.py``
  (``derive_behavioral_spec``, ``derive_operational_model``).
- View codegen pipeline exists in ``workbook/codegen/view_generator.py``
  (1371 lines, archetypes: landing, checklist, list, dashboard).
- No adapter connects the two.
- Farm has no MWBS YAML; ``farm_ui/`` has hand-written views with
  established test coverage.

## Scope

### In-scope

1. **MWBS-to-landing adapter** — Convert ``Actor`` + list of ``Report``
   entries in MWBS into a landing archetype config.  The generated landing
   page should match the shape of farm's ``PlannerLandingView`` (summary
   cards for open tasks, current plantings, nursery-to-seed, low
   inventory; recent events timeline).  Map MWBS ``Actor.responsibilities``
   → count expression; map MWBS ``Report`` → card display.

2. **MWBS-to-list adapter** — Convert ``WorkflowStep`` entries tagged with
   ``kind: list`` (or equivalent signal) into a list archetype config
   matching farm's ``CropListView`` / ``FieldBlockListView`` patterns
   (filter sidebar, paginated table, ``get_queryset`` overrides).

3. **Derive farm MWBS** — Run the MWBS elicitor against farm's source
   data (Google Sheets structure, schema contract, view manifest) to
   produce a ``config/behavioral-spec.yaml``.  The human reviews and
   adjusts the derived spec before codegen uses it.

4. **Real-data parity tests** — Assert that generated views (from the
   derived farm MWBS) produce the same page-level data as farm's
   hand-written views for at least one actor (e.g. Planner) and one
   list view (e.g. Crop list).  Tests run in the farm product repo.

5. **Documentation** — Add a ``docs/mwbs-codegen.md`` or equivalent
   explaining the adapter and how to add new MWBS→archetype mappings.

### Out-of-scope

- Replacing every ``farm_ui/`` view (that's ``farm-workflow-coverage``,
   0.8.6).
- Modifying the existing view manifest + contract input path (both remain
  supported).
- MWBS editing UI or dashboard for viewing specs.
- Coda-side MWBS elicitation (future work).

## Success Criteria

- [ ] ``mwbs_to_archetype`` module exists in ``workbook/codegen/``
- [ ] MWBS ``Actor`` + ``Report`` produces a landing config comparable
      to ``PlannerLandingView``
- [ ] MWBS ``WorkflowStep`` (``kind: list``) produces a list config
      comparable to ``CropListView``
- [ ] Farm MWBS YAML exists in ``config/behavioral-spec.yaml``
- [ ] Generated landing page passes parity assertion against
      ``PlannerLandingView`` (same summary-card counts, same event list)
- [ ] Generated list page passes parity assertion against
      ``CropListView`` (same filter options, same columns)
- [ ] Workbench ``make chassis-gate`` green
- [ ] Farm test suite green
- [ ] Merge to master, tag v0.8.5

## Earns

0.8.5 — Views generated directly from MWBS behavioral spec; the codegen
pipeline now accepts behavioral input alongside schema contracts.
