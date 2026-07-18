# Journal: wb-landing-archetype

## 2026-07-11 — Boot

**Decision:**
`vizcarra-generate-import` shipped (0.6.2). Track B's third archetype (landing)
continues the UI codegen extraction pattern from 0.6.1. The landing pattern is
well-understood from farm_ui's three hand-written views: TemplateView + summary
cards in `get_context_data()` + role-based routing.

### Starting state
- Branch: `master` (workbench)
- `make chassis-gate`: 1671 passed, 1 warning

## 2026-07-11 — Session 1 (COMPLETE)

### Delivered
- **LandingArchetype** + **SummaryCard** dataclasses in view_generator.py
- **render_landing_view_py()**: generates TemplateView with get_context_data()
  that evaluates card count expressions, resolves URL names via reverse(),
  and builds summary_cards list
- **render_landing_template_html()**: generates card-grid template with
  pre-resolved URL paths (no {% url %} variable issue)
- **render_landing_views_auto_py()**: combined module with auto-detected
  model imports (scans count expressions for capitalized class names)
- **--archetype-landing <config.yaml>** flag in generate_views command
- **22 new tests** in workbench (archetype defaults, view Python, template,
  URL patterns, combined modules, command end-to-end)
- **6 farm tests** proving generated FieldWorkerLandingView renders summary
  cards with real data counts

### Gate
- Workbench: 1693 passed, 1 warning
- Farm: 6/6 passed

### Ready for merge
- feat/wb-landing-archetype branch in workbench
- feat/test-wb-landing-archetype branch in farm
- Version bump to 0.6.3 pending
