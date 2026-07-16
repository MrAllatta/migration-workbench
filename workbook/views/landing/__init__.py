"""Landing view archetype — role-based landing page with summary cards.

Produces ``TemplateView`` subclasses where ``get_context_data()`` evaluates
configured count expressions and resolves URLs for a card-grid template.
"""

from workbook.views import registry
from workbook.views.landing.archetype import LandingArchetype, SummaryCard
from workbook.views.landing.modules import (
    render_landing_urls_auto_py,
    render_landing_views_auto_py,
)
from workbook.views.landing.templates import render_landing_template_html
from workbook.views.landing.urls import render_landing_url_pattern
from workbook.views.landing.views import render_landing_view_py

__all__ = [
    "SummaryCard",
    "LandingArchetype",
    "render_landing_view_py",
    "render_landing_template_html",
    "render_landing_url_pattern",
    "render_landing_views_auto_py",
    "render_landing_urls_auto_py",
]

# Register this archetype with the registry.
registry.register("landing", "workbook.views.landing")
