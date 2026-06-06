"""Package-embedded vertical template discovery and loading.

Re-exports from ``workbook.tools.vertical_registry`` for convenience.
"""

from workbook.tools.vertical_registry import (
    VerticalTemplate,
    discover_verticals,
    load_vertical,
)

__all__ = [
    "VerticalTemplate",
    "discover_verticals",
    "load_vertical",
]
