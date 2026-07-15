"""Dashboard URL pattern rendering.

Produces Django ``path()`` lines for dashboard views.
"""

from __future__ import annotations

from workbook.views.dashboard.archetype import DashboardArchetype
from workbook.views.utils import to_pascal_case


def render_dashboard_url_pattern(archetype: DashboardArchetype) -> list[str]:
    """Render URL pattern lines for a dashboard view.

    Returns:
        A list with one ``path()`` line ready for ``urlpatterns = [...]``.
    """
    if not archetype.url_path or not archetype.url_name:
        return []
    class_name = f"{to_pascal_case(archetype.name)}DashboardView"
    return [
        f'    path("{archetype.url_path}", {class_name}.as_view(), name="{archetype.url_name}"),',
    ]
