"""Deprecated re-export module — import from ``workbook.views.*`` directly.

This module re-exports all public symbols from the archetype packages
in ``workbook/views/{checklist,landing,dashboard}/`` for backward
compatibility.

New code should import directly from the archetype package:

    from workbook.views.checklist import ChecklistArchetype, render_checklist_view_py
    from workbook.views.landing import LandingArchetype, SummaryCard
    from workbook.views.dashboard import DashboardArchetype, AlertCard
"""

from workbook.views.checklist import (  # noqa: F401
    ChecklistColumn,
    ChecklistArchetype,
    render_checklist_view_py,
    render_toggle_handler_py,
    render_checklist_url_pattern,
    render_checklist_template_html,
    build_archetype_from_contract,
    render_checklist_bundle,
    render_views_auto_py,
    render_urls_auto_py,
)
from workbook.views.landing import (  # noqa: F401
    SummaryCard,
    LandingArchetype,
    render_landing_view_py,
    render_landing_template_html,
    render_landing_url_pattern,
    render_landing_views_auto_py,
    render_landing_urls_auto_py,
)
from workbook.views.dashboard import (  # noqa: F401
    AlertCard,
    DetailColumn,
    DetailSection,
    DashboardArchetype,
    render_dashboard_view_py,
    render_dashboard_template_html,
    render_dashboard_url_pattern,
    render_dashboard_views_auto_py,
    render_dashboard_urls_auto_py,
)

__all__ = [
    # checklist
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
    # landing
    "SummaryCard",
    "LandingArchetype",
    "render_landing_view_py",
    "render_landing_template_html",
    "render_landing_url_pattern",
    "render_landing_views_auto_py",
    "render_landing_urls_auto_py",
    # dashboard
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
