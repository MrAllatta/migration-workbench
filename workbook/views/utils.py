"""Shared utility functions for view archetype rendering.

These helpers are used by multiple archetype packages.  Import from here
instead of duplicating across checklist, landing, and dashboard modules.
"""

from __future__ import annotations

import builtins
import keyword
import re


def to_snake_case(pascal: str) -> str:
    """Convert PascalCase to snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", pascal).lower()


def to_pascal_case(snake: str) -> str:
    """Convert snake_case to PascalCase."""
    if not snake:
        return snake
    return "".join(word.capitalize() for word in snake.split("_"))


def extract_model_names(expression: str) -> list[str]:
    """Extract capitalized identifiers from *expression* that look like
    Django model class names (not Python builtins, keywords, or common
    Django identifiers).

    Used by landing and dashboard combined-module functions to generate
    the correct ``from core.models import ...`` line for card count
    expressions.
    """
    words = set(re.findall(r"[A-Z][a-zA-Z0-9_]+", expression))
    blacklist = set(dir(builtins)) | set(keyword.kwlist)
    blacklist |= {
        "True", "False", "None",
        "HttpResponse", "HttpRequest", "self", "request",
        "Q", "F", "Count", "Sum", "Avg", "Min", "Max",
        "Value", "Case", "When", "Subquery", "OuterRef",
        "Exists", "ExpressionWrapper", "DurationExpression",
        "LoginRequiredMixin", "TemplateView", "ListView",
        "UserPassesTestMixin", "AccessMixin", "RedirectView",
    }
    return sorted(w for w in words if w not in blacklist)
