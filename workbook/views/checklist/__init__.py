"""Checklist view archetype — weekly year/week-filterable ListView with HTMX toggle.

This is the dominant pattern in operator-facing tabular apps, proven in
farm_ui's ``checklists.py`` (TaskChecklistView, PlantingChecklistView,
NurseryChecklistView).
"""

from workbook.views import registry
from workbook.views.checklist.archetype import ChecklistArchetype, ChecklistColumn
from workbook.views.checklist.bundles import (
    build_archetype_from_contract,
    render_checklist_bundle,
    render_urls_auto_py,
    render_views_auto_py,
)
from workbook.views.checklist.templates import render_checklist_template_html
from workbook.views.checklist.urls import render_checklist_url_pattern
from workbook.views.checklist.views import (
    render_checklist_view_py,
    render_toggle_handler_py,
)

__all__ = [
    "ChecklistColumn",
    "ChecklistArchetype",
    "render_checklist_view_py",
    "render_toggle_handler_py",
    "render_checklist_url_pattern",
    "render_checklist_template_html",
    "build_archetype_from_contract",
    "render_checklist_bundle",
    "render_views_auto_py",
    "render_urls_auto_py",
]

# Register this archetype with the registry.
registry.register("checklist", "workbook.views.checklist")
