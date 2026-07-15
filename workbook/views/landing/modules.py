"""Landing combined-module rendering.

Produces ``views_auto.py`` and ``urls_auto.py`` modules for one or more
landing archetypes.
"""

from __future__ import annotations

from typing import Sequence

from workbook.views.landing.archetype import LandingArchetype
from workbook.views.landing.views import render_landing_view_py
from workbook.views.landing.urls import render_landing_url_pattern
from workbook.views.utils import to_pascal_case, extract_model_names


def render_landing_views_auto_py(
    archetypes: Sequence[LandingArchetype],
    *,
    extra_imports: Sequence[str] = (),
    app_label: str = "core",
) -> str:
    """Render a complete ``views_auto.py`` module with multiple landing archetypes.

    Includes ``TemplateView``/``LoginRequiredMixin`` imports, auto-detected
    model imports based on capitalized identifiers in card count expressions,
    and all generated view classes.

    Args:
        archetypes: Landing archetypes to render.
        extra_imports: Additional import lines to include.
        app_label: Django app label for the model import module
            (default ``"core"``).
    """
    all_model_names: set[str] = set()
    for arch in archetypes:
        for card in arch.cards:
            all_model_names.update(extract_model_names(card.count_expression))

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
        body_parts.append(render_landing_view_py(arch))
    return "\n".join(imports) + "\n".join(body_parts)


def render_landing_urls_auto_py(
    archetypes: Sequence[LandingArchetype],
) -> str:
    """Render a complete ``urls_auto.py`` module with multiple landing archetypes."""
    view_names: list[str] = []
    for arch in archetypes:
        view_names.append(f"{to_pascal_case(arch.role)}LandingView")
    imports = [
        "from django.urls import include, path",
        "",
        f"from .views_auto import {', '.join(view_names)}",
        "",
        "",
    ]
    patterns: list[str] = []
    for arch in archetypes:
        patterns.extend(render_landing_url_pattern(arch))
    body = "\n".join(patterns)
    return (
        "\n".join(imports)
        + "urlpatterns = [\n"
        + body
        + "\n]\n"
    )
