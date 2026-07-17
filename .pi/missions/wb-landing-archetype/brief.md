# brief: wb-landing-archetype

## Context
Track B (UI codegen extraction). The checklist archetype (0.6.1) proved the
view generator pattern works against real farm data. The next most common
pattern in ``farm_ui`` is the role-based landing page — a ``TemplateView``
that shows summary cards (counts, recent items, alerts) and routes users to
their role-appropriate dashboard.

Three hand-written landing views exist in farm_ui:
- ``PlannerLandingView`` — open tasks, current plantings, counts for nursery
  seeding, low inventory, recent events
- ``FieldWorkerLandingView`` — open tasks, today's plantings
- ``NurseryWorkerLandingView`` — seeding schedule, pot-up schedule

This mission extracts the landing archetype as a codegen target: a
configurable ``TemplateView`` that accepts a list of summary cards and
optional recent-items queries, generates the Python view + template, and
proves it works against real farm data.

## Goal
Extend ``workbook/codegen/view_generator.py`` with a landing archetype
that generates Django ``TemplateView`` + template with role-based summary
cards. Prove it works by generating a field-worker landing for the farm
repo and passing a real-data test.

## Repo
migration-workbench (primary) + farm (test target)

## Starting State
- ``workbook/codegen/view_generator.py`` has ``ChecklistArchetype``
- ``workbook/management/commands/generate_views.py`` has ``--archetype-checklist``
- farm_ui has ``PlannerLandingView``, ``FieldWorkerLandingView``,
  ``NurseryWorkerLandingView`` in ``views/landing.py``
- 1671 tests pass; ``make chassis-gate`` green

## Scope
### In-scope
1. Add ``LandingArchetype`` dataclass with:
   - ``role`` and ``title``
   - ``summary_cards`` — list of ``SummaryCard(label, count_expression, icon, link_url_name)``
   - ``recent_lists`` — optional list of ``RecentList(title, queryset_fields, link_url_name)``
   - ``template_path``
2. Add render functions to ``view_generator.py``:
   - ``render_landing_view_py()`` — generates ``TemplateView`` with
     ``get_context_data()`` that evaluates each card's count expression
   - ``render_landing_template_html()`` — renders a card-grid template
3. Add ``--archetype-landing`` flag to ``generate_views`` command
4. Write workbench unit tests (42+ covered: archetype defaults, view source
   ast-validated, template structure, card rendering)
5. Write farm real-data test (generate FieldWorkerLanding, test it shows
   open tasks and current-plantings count)

### Out-of-scope
- Role-based URL routing (the ``role_redirect`` dispatcher is product-specific)
- Print views
- Dashboard archetype with alerts (separate mission, 0.7.2)

## Success Criteria
- [ ] ``generate_views --archetype-landing`` produces valid Python + template
- [ ] Generated view has ``get_context_data()`` with card counts
- [ ] Generated template renders a card grid with label + value per card
- [ ] Workbench unit tests pass (ast-validated, template structure)
- [ ] Farm real-data test exercises generated landing against real records
- [ ] ``make chassis-gate`` passes
- [ ] Squash-merge to master, tag v0.6.3

## Earns
0.6.3 — Role-based landing archetype proven against real farm data.
