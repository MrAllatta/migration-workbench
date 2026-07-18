# brief: wb-dashboard-archetype

## Context
Track B (UI codegen extraction). The checklist (0.6.1) and landing (0.6.3)
archetypes proved that ``workbook/codegen/view_generator.py`` can emit
working Django views + templates from explicit config. The next most common
pattern in ``farm_ui`` is the dashboard: a ``TemplateView`` that shows alert
counts (zero stock, low stock, goals met, completion percentage) plus one or
more detail sections.

Three hand-written dashboards exist in ``farm_ui``:
- ``InventoryDashboardView`` — zero/low/total stock alert cards + inventory
  detail table
- ``GoalsDashboardView`` — achieved/total goal alert card + goals detail table
- ``SeasonOverviewView`` — planned/planted/completion alert cards + this
  week's events detail table

This mission extracts the dashboard archetype as a codegen target: a
configurable ``TemplateView`` that accepts alert cards and detail sections,
generates the Python view + template, and proves it works against real farm
data. It also lays the groundwork for consuming MWBS ``Report`` objects
(provenance, audience, displays) in the later ``wb-view-codegen-pipeline``
mission (0.7.3); for this patch the config is explicit YAML.

## Goal
Extend ``workbook/codegen/view_generator.py`` with a dashboard archetype
that generates Django ``TemplateView`` + template with alert cards and
detail sections. Prove it by generating an inventory-style dashboard for the
farm repo and passing a real-data test.

## Repo
migration-workbench (primary) + farm (test target)

## Starting State
- ``workbook/codegen/view_generator.py`` has ``ChecklistArchetype`` and
  ``LandingArchetype``
- ``workbook/management/commands/generate_views.py`` has
  ``--archetype-checklist`` and ``--archetype-landing``
- farm_ui has ``InventoryDashboardView``, ``GoalsDashboardView``,
  ``SeasonOverviewView`` in ``views/dashboards.py``
- 1693 tests pass; ``make chassis-gate`` green

## Scope
### In-scope
1. Add ``DashboardArchetype`` dataclass with:
   - ``name`` and ``title``
   - ``alerts`` — list of ``AlertCard(label, count_expression, severity,
     link_url_name)`` where ``severity`` is one of ``info``, ``success``,
     ``warning``, ``danger``
   - ``sections`` — list of ``DetailSection(title, queryset_expression,
     columns, limit, empty_message)``
   - ``template_path``, ``url_path``, ``url_name``
2. Add render functions to ``view_generator.py``:
   - ``render_dashboard_view_py()`` — generates ``TemplateView`` with
     ``get_context_data()`` that evaluates each alert count and each section's
     queryset expression
   - ``render_dashboard_template_html()`` — renders alert-card grid + detail
     tables with the configured columns
   - ``render_dashboard_url_pattern()`` — URL pattern for the dashboard view
   - ``render_dashboard_views_auto_py()`` / ``render_dashboard_urls_auto_py()``
     — combined modules (auto-detect model imports from expressions)
3. Add ``--archetype-dashboard`` flag to ``generate_views`` command that reads
   a YAML config with a top-level ``dashboards`` list
4. Write workbench unit tests (ast-validated, template structure, alert/section
   rendering)
5. Write farm real-data test (generate an inventory-style dashboard, test it
   shows zero/low/total counts and a detail table with real ``InventoryLedger``
   records)

### Out-of-scope
- Consuming MWBS ``Report`` objects directly (that's 0.7.3)
- Product-skin override blocks and template inheritance hierarchy (0.7.3)
- Print views (future extraction backlog)
- Drill-down charts or graphs

## Success Criteria
- [ ] ``generate_views --archetype-dashboard`` produces valid Python + template
- [ ] Generated view has ``get_context_data()`` with alert counts and detail
      sections
- [ ] Generated template renders alert cards (label + value + severity class)
      and detail tables
- [ ] Workbench unit tests pass (ast-validated, template structure)
- [ ] Farm real-data test exercises generated dashboard against real records
- [ ] ``make chassis-gate`` passes
- [ ] Squash-merge to master, tag v0.7.2

## Earns
0.7.2 — Dashboard archetype with alert counts proven against real farm data.
