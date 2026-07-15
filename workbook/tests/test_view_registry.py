"""Tests for the view archetype registry.

The registry maps archetype labels to modules under ``workbook/views/``.
Each archetype package self-registers on import.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest

from workbook.views import registry


class TestBuiltinRegistry:
    """Built-in archetypes are registered lazily."""

    def test_labels_includes_all_builtins(self) -> None:
        labels = registry.labels()
        assert "checklist" in labels
        assert "landing" in labels
        assert "dashboard" in labels
        assert "list" in labels

    def test_has_returns_true_for_builtins(self) -> None:
        assert registry.has("checklist") is True
        assert registry.has("landing") is True
        assert registry.has("dashboard") is True
        assert registry.has("list") is True

    def test_has_returns_false_for_unknown(self) -> None:
        assert registry.has("not_an_archetype") is False

    def test_resolve_returns_module_path(self) -> None:
        assert registry.resolve("checklist") == "workbook.views.checklist"
        assert registry.resolve("landing") == "workbook.views.landing"
        assert registry.resolve("dashboard") == "workbook.views.dashboard"
        assert registry.resolve("list") == "workbook.views.list"

    def test_resolve_raises_for_unknown(self) -> None:
        with pytest.raises(KeyError, match="Unknown archetype"):
            registry.resolve("unknown")

    def test_load_returns_module(self) -> None:
        module = registry.load("checklist")
        assert isinstance(module, ModuleType)
        assert module.__name__ == "workbook.views.checklist"
        assert hasattr(module, "render_checklist_view_py")

    def test_load_returns_list_module(self) -> None:
        module = registry.load("list")
        assert module.__name__ == "workbook.views.list"
        assert hasattr(module, "ListArchetype")
        assert hasattr(module, "render_list_view_py")

    def test_load_caches_module(self) -> None:
        first = registry.load("checklist")
        second = registry.load("checklist")
        assert first is second


class TestExplicitRegistration:
    """Custom archetypes can be registered and unregistered."""

    def test_register_custom_label(self) -> None:
        # Create a fake module path that points to the checklist module.
        custom_path = "workbook.views.checklist"
        registry.register("custom-checklist", custom_path)
        assert registry.has("custom-checklist") is True
        assert registry.resolve("custom-checklist") == custom_path

    def test_register_duplicate_same_path_is_ok(self) -> None:
        registry.register("dup-test", "workbook.views.checklist")
        registry.register("dup-test", "workbook.views.checklist")
        assert registry.resolve("dup-test") == "workbook.views.checklist"

    def test_register_different_path_raises(self) -> None:
        registry.register("conflict-test", "workbook.views.checklist")
        with pytest.raises(ValueError, match="already registered"):
            registry.register("conflict-test", "workbook.views.landing")
        # Clean up.
        registry.unregister("conflict-test")

    def test_unregister_removes_explicit_only(self) -> None:
        registry.register("temp-test", "workbook.views.checklist")
        assert registry.has("temp-test") is True
        registry.unregister("temp-test")
        assert registry.has("temp-test") is False

    def test_clear_removes_explicit_registrations(self) -> None:
        registry.register("clear-test", "workbook.views.checklist")
        assert registry.has("clear-test") is True
        registry.clear()
        assert registry.has("clear-test") is False
        # Built-ins survive clear.
        assert registry.has("checklist") is True


class TestSelfRegistration:
    """Archetype packages register themselves on import."""

    def test_checklist_self_registered(self) -> None:
        # Force re-import to ensure __init__.py registration runs.
        if "workbook.views.checklist" in sys.modules:
            importlib.reload(sys.modules["workbook.views.checklist"])
        assert registry.has("checklist") is True
        module = registry.load("checklist")
        assert hasattr(module, "ChecklistArchetype")

    def test_landing_self_registered(self) -> None:
        if "workbook.views.landing" in sys.modules:
            importlib.reload(sys.modules["workbook.views.landing"])
        assert registry.has("landing") is True
        module = registry.load("landing")
        assert hasattr(module, "LandingArchetype")

    def test_dashboard_self_registered(self) -> None:
        if "workbook.views.dashboard" in sys.modules:
            importlib.reload(sys.modules["workbook.views.dashboard"])
        assert registry.has("dashboard") is True
        module = registry.load("dashboard")
        assert hasattr(module, "DashboardArchetype")

    def test_list_self_registered(self) -> None:
        if "workbook.views.list" in sys.modules:
            importlib.reload(sys.modules["workbook.views.list"])
        assert registry.has("list") is True
        module = registry.load("list")
        assert hasattr(module, "ListArchetype")

    def test_archetype_modules_expose_renderers(self) -> None:
        checklist = registry.load("checklist")
        assert callable(checklist.render_checklist_view_py)
        assert callable(checklist.render_checklist_template_html)
        assert callable(checklist.render_checklist_url_pattern)
        assert callable(checklist.render_views_auto_py)
        assert callable(checklist.render_urls_auto_py)

        landing = registry.load("landing")
        assert callable(landing.render_landing_view_py)
        assert callable(landing.render_landing_template_html)
        assert callable(landing.render_landing_url_pattern)

        dashboard = registry.load("dashboard")
        assert callable(dashboard.render_dashboard_view_py)
        assert callable(dashboard.render_dashboard_template_html)
        assert callable(dashboard.render_dashboard_url_pattern)

        list_module = registry.load("list")
        assert callable(list_module.render_list_view_py)
        assert callable(list_module.render_list_url_pattern)
