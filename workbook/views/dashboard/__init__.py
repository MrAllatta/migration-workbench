"""Dashboard view archetype — alert cards with detail section tables.

Produces ``TemplateView`` subclasses that evaluate alert count expressions
and section queryset expressions in ``get_context_data()``.
"""

from workbook.views import registry
from workbook.views.dashboard.archetype import (
    AlertCard,
    DashboardArchetype,
    DetailColumn,
    DetailSection,
)
from workbook.views.dashboard.modules import (
    render_dashboard_urls_auto_py,
    render_dashboard_views_auto_py,
)
from workbook.views.dashboard.templates import render_dashboard_template_html
from workbook.views.dashboard.urls import render_dashboard_url_pattern
from workbook.views.dashboard.views import render_dashboard_view_py

__all__ = [
    "AlertCard",
    "DetailColumn",
    "DetailSection",
    "DashboardArchetype",
    "render_dashboard_view_py",
    "render_dashboard_template_html",
    "render_dashboard_url_pattern",
    "render_dashboard_views_auto_py",
    "render_dashboard_urls_auto_py",
]

# Register this archetype with the registry.
registry.register("dashboard", "workbook.views.dashboard")
