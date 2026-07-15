"""List view archetype.

This package re-exports the existing list archetype implementation from
:mod:`workbook.codegen.list_generator` so that all view archetypes live
under ``workbook.views/`` and can be registered through the archetype
registry.

Direct callers should import from here in new code; existing imports from
``workbook.codegen.list_generator`` continue to work.
"""

from __future__ import annotations

from workbook.codegen.list_generator import (
    ListArchetype,
    render_list_url_pattern,
    render_list_view_py,
)
from workbook.views import registry

__all__ = [
    "ListArchetype",
    "render_list_view_py",
    "render_list_url_pattern",
]

# Register this archetype with the registry.
registry.register("list", "workbook.views.list")
