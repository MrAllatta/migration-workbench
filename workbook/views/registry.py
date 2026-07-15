"""Archetype registry — maps archetype labels to their implementing modules.

The registry lets ``generate_views`` dispatch by archetype label instead of
importing each archetype directly.  Each archetype module under
``workbook/views/`` self-registers on import by calling
:func:`register`.  The built-ins are also seeded lazily.

Example usage::

    from workbook.views import registry

    checklist = registry.load("checklist")
    source = checklist.render_checklist_view_py(archetype)

    registry.labels()  # -> ["checklist", "dashboard", "landing", "list"]

The registry intentionally has a tiny interface: register, resolve, load,
labels, has.  Archetype modules are duck-typed; they must export the
renderer functions their callers expect (typically ``render_*_view_py``,
``render_*_template_html``, ``render_*_url_pattern``, and the combined-module
functions ``render_*_views_auto_py`` / ``render_*_urls_auto_py``).
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ArchetypeModule(Protocol):
    """Duck-typed interface for a registered archetype module.

    A module registered as an archetype should export:

    - Config dataclass(es) (e.g. ``ChecklistArchetype``)
    - ``render_<label>_view_py(config) -> str``
    - ``render_<label>_template_html(config) -> str``
    - ``render_<label>_url_pattern(config) -> list[str]``
    - ``render_<label>_views_auto_py(archetypes, *, extra_imports=(), app_label='core') -> str``
    - ``render_<label>_urls_auto_py(archetypes) -> str``

    The exact function names vary by archetype; callers use the label to
    know which module they loaded.  This protocol is structural: it does
    not enforce names at runtime.
    """


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# label -> dotted module path
_registry: dict[str, str] = {}

# Built-in archetypes.  These are registered lazily so the registry can be
# imported without triggering imports of every archetype module.
_BUILTINS: dict[str, str] = {
    "checklist": "workbook.views.checklist",
    "dashboard": "workbook.views.dashboard",
    "landing": "workbook.views.landing",
    "list": "workbook.views.list",
}


def register(label: str, module_path: str) -> None:
    """Register *module_path* as the implementation for *label*.

    Args:
        label: Archetype label (e.g. ``"checklist"``).  Must be unique.
        module_path: Dotted Python module path (e.g.
            ``"workbook.views.checklist"``).

    Raises:
        ValueError: If *label* is already registered to a different path.
    """
    if label in _registry and _registry[label] != module_path:
        raise ValueError(
            f"archetype {label!r} already registered to {_registry[label]!r}"
        )
    _registry[label] = module_path


def resolve(label: str) -> str:
    """Return the module path registered for *label*.

    Args:
        label: Archetype label.

    Returns:
        Dotted module path.

    Raises:
        KeyError: If *label* is not registered.
    """
    if label in _registry:
        return _registry[label]
    if label in _BUILTINS:
        return _BUILTINS[label]
    raise KeyError(
        f"Unknown archetype: {label!r}. "
        f"Registered: {', '.join(sorted(labels()))}"
    )


def load(label: str) -> Any:
    """Lazy-import and return the archetype module for *label*.

    Python's import machinery caches the module, so repeated calls are cheap.

    Args:
        label: Archetype label.

    Returns:
        The imported module (duck-typed as :class:`ArchetypeModule`).

    Raises:
        KeyError: If *label* is not registered.
        ImportError: If the registered module cannot be imported.
    """
    module_path = resolve(label)
    return importlib.import_module(module_path)


def labels() -> list[str]:
    """Return sorted list of all registered archetype labels."""
    return sorted(set(_registry) | set(_BUILTINS))


def has(label: str) -> bool:
    """Return True if *label* is registered."""
    return label in _registry or label in _BUILTINS


def unregister(label: str) -> None:
    """Remove *label* from the explicit registry.

    Built-ins cannot be unregistered; this only removes overrides.
    """
    _registry.pop(label, None)


def clear() -> None:
    """Remove all explicit registrations.  Built-ins remain."""
    _registry.clear()
