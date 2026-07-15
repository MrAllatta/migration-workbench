"""Checklist URL pattern rendering.

Produces Django ``path()`` lines for the checklist ListView and its
HTMX toggle handler.
"""

from __future__ import annotations

from workbook.codegen.python_render import to_python_identifier
from workbook.views.checklist.archetype import ChecklistArchetype
from workbook.views.utils import to_snake_case


def render_checklist_url_pattern(archetype: ChecklistArchetype) -> list[str]:
    """Render URL pattern lines for the checklist view and its toggle handler.

    Returns a list of string lines (not joined) suitable for inclusion in a
    Django ``urlpatterns`` list.
    """
    if not archetype.url_path or not archetype.url_name:
        return []
    class_name = f"{archetype.model}ChecklistView"
    lines = [
        f'    path("{archetype.url_path}", {class_name}.as_view(), name="{archetype.url_name}"),',
    ]
    if archetype.toggle_field and archetype.toggle_url_name:
        toggle_handler = (
            f"toggle_{to_python_identifier(to_snake_case(archetype.model))}_"
            f"{to_python_identifier(archetype.toggle_field)}"
        )
        lines.append(
            f'    path("{archetype.toggle_url_path}", {toggle_handler}, name="{archetype.toggle_url_name}"),'
        )
    return lines
