"""Landing URL pattern rendering.

Produces Django ``path()`` lines for the landing page.
"""

from __future__ import annotations

from workbook.views.landing.archetype import LandingArchetype
from workbook.views.utils import to_pascal_case


def render_landing_url_pattern(archetype: LandingArchetype) -> list[str]:
    """Render URL pattern lines for a landing page.

    Returns:
        A list with one ``path()`` line ready for ``urlpatterns = [...]``.
    """
    if not archetype.url_path or not archetype.url_name:
        return []
    class_name = f"{to_pascal_case(archetype.role)}LandingView"
    return [
        f'    path("{archetype.url_path}", {class_name}.as_view(), name="{archetype.url_name}"),',
    ]
