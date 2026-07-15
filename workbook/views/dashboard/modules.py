"""Dashboard combined-module rendering.

Produces ``views_auto.py`` and ``urls_auto.py`` modules for one or more
dashboard archetypes.
"""

from __future__ import annotations

from typing import Sequence

from workbook.views.dashboard.archetype import DashboardArchetype
from workbook.views.dashboard.views import render_dashboard_view_py
from workbook.views.dashboard.urls import render_dashboard_url_pattern
from workbook.views.utils import to_pascal_case, extract_model_names


def render_dashboard_views_auto_py(
    archetypes: Sequence[DashboardArchetype],
    *,
    extra_imports: Sequence[str] = (),
    app_label: str = "core",
) -> str:
    """Render a complete ``views_auto.py`` with multiple dashboard archetypes.

    Includes ``TemplateView``/``LoginRequiredMixin`` imports, auto-detected
    model imports from count and queryset expressions, and all generated
    view classes.
    """
    all_model_names: set[str] = set()
    for arch in archetypes:
        for alert in arch.alerts:
            all_model_names.update(extract_model_names(alert.count_expression))
        for section in arch.sections:
            all_model_names.update(extract_model_names(section.queryset_expression))

    imports: list[str] = [
        "from django.contrib.auth.mixins import LoginRequiredMixin",
        "from django.views.generic import TemplateView",
        "",
    ]
    if all_model_names:
        sorted_names = sorted(all_model_names)
        imports.append(f"from {app_label}.models import {', '.join(sorted_names)}")
        imports.append("")
    imports.extend(extra_imports)
    imports.append("")

    body_parts: list[str] = []
    for arch in archetypes:
        body_parts.append(render_dashboard_view_py(arch))
    return "\n".join(imports) + "\n".join(body_parts)


def render_dashboard_urls_auto_py(
    archetypes: Sequence[DashboardArchetype],
) -> str:
    """Render a complete ``urls_auto.py`` with multiple dashboard archetypes."""
    view_names: list[str] = []
    for arch in archetypes:
        view_names.append(f"{to_pascal_case(arch.name)}DashboardView")
    imports = [
        "from django.urls import include, path",
        "",
        f"from .views_auto import {', '.join(view_names)}",
        "",
        "",
    ]
    patterns: list[str] = []
    for arch in archetypes:
        patterns.extend(render_dashboard_url_pattern(arch))
    body = "\n".join(patterns)
    return (
        "\n".join(imports)
        + "urlpatterns = [\n"
        + body
        + "\n]\n"
    )
