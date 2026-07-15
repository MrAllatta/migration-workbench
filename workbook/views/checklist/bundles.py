"""Checklist bundle rendering and factory functions.

Includes the top-level ``render_checklist_bundle()``, the combined-module
renderers (``render_views_auto_py``, ``render_urls_auto_py``), and the
``build_archetype_from_contract()`` factory with auto-derivation helpers.
"""

from __future__ import annotations

from typing import Any, Sequence

from workbook.codegen.python_render import to_python_identifier
from workbook.views.checklist.archetype import ChecklistArchetype, ChecklistColumn
from workbook.views.checklist.urls import render_checklist_url_pattern
from workbook.views.checklist.views import render_checklist_view_py, render_toggle_handler_py
from workbook.views.utils import to_snake_case


def build_archetype_from_contract(
    model: str,
    app_label: str,
    contract_table: dict[str, Any],
    *,
    title: str | None = None,
    columns: list[ChecklistColumn] | None = None,
    select_related: list[str] | None = None,
    ordering: list[str] | None = None,
    year_field: str = "planned_year",
    week_field: str = "planned_week",
    url_path: str = "",
    url_name: str = "",
) -> ChecklistArchetype:
    """Build a :class:`ChecklistArchetype` from a contract table entry.

    The contract's table is the canonical source for field names and
    year/week semantics.  ``columns``, ``select_related``, and ``ordering``
    can be supplied explicitly; otherwise they are auto-derived from the
    contract's field list.

    Auto-derivation rules:
    - ``columns`` — first 4 non-PK, non-year/week text-like and FK fields
    - ``select_related`` — all FK field names
    - ``ordering`` — first FK field, or empty
    """
    if columns is None:
        columns = _auto_columns(contract_table)
    if select_related is None:
        select_related = _auto_select_related(contract_table)
    if ordering is None:
        ordering = _auto_ordering(contract_table, select_related)
    return ChecklistArchetype(
        model=model,
        app_label=app_label,
        year_field=year_field,
        week_field=week_field,
        columns=columns,
        select_related=select_related,
        ordering=ordering,
        title=title or f"{model.replace('_', ' ')} Checklist",
        url_path=url_path or to_snake_case(model).replace("_", "") + "/",
        url_name=url_name or f"{app_label}_{to_snake_case(model)}_checklist",
    )


def _auto_columns(contract_table: dict[str, Any]) -> list[ChecklistColumn]:
    """Auto-derive a column list from a contract table."""
    columns: list[ChecklistColumn] = []
    seen: set[str] = set()
    columns_data = contract_table.get("columns") or []
    for col in columns_data:
        if not isinstance(col, dict):
            continue
        field_name = col.get("name") or col.get("suggested_field_name")
        if not field_name or field_name in seen:
            continue
        seen.add(field_name)
        # Skip year/week fields (handled by nav, not table)
        if field_name in ("planned_year", "planned_week", "seeding_year", "seeding_week"):
            continue
        # Skip the PK (auto-numbered, not user-meaningful)
        if field_name in ("id", "pk"):
            continue
        if len(columns) >= 4:
            break
        label = col.get("header") or field_name.replace("_", " ").title()
        # Heuristic: FK field shows __str__ of related object
        is_fk = (col.get("class") or "").endswith("ForeignKey")
        if is_fk:
            columns.append(ChecklistColumn(field=field_name, label=label, format="fk_display"))
        else:
            columns.append(ChecklistColumn(field=field_name, label=label, format="value"))
    return columns


def _auto_select_related(contract_table: dict[str, Any]) -> list[str]:
    """Auto-derive ``select_related`` from a contract table's FK fields."""
    result: list[str] = []
    for col in contract_table.get("columns") or []:
        if not isinstance(col, dict):
            continue
        if (col.get("class") or "").endswith("ForeignKey"):
            name = col.get("name") or col.get("suggested_field_name")
            if name and name not in result:
                result.append(name)
    return result


def _auto_ordering(contract_table: dict[str, Any], select_related: Sequence[str]) -> list[str]:
    """Auto-derive ordering: prefer the first FK field."""
    if select_related:
        return [select_related[0]]
    return []


def render_checklist_bundle(
    archetype: ChecklistArchetype,
) -> dict[str, str]:
    """Render the full checklist bundle as a dict of named source strings.

    Keys:
    - ``view_py``: ListView + toggle handler Python source
    - ``template_html``: rendered Django template
    - ``url_patterns``: list of URL pattern lines (joined with newlines)
    """
    view_parts = [
        render_checklist_view_py(archetype),
        render_toggle_handler_py(archetype),
    ]
    return {
        "view_py": "\n".join(p for p in view_parts if p),
        "template_html": render_checklist_template_html(archetype),
        "url_patterns": "\n".join(render_checklist_url_pattern(archetype)),
    }


# Import here to break circular dependency: bundles.py imports templates.py
# for render_checklist_bundle, but render_checklist_template_html is
# defined in templates.py.  The import is at function call time so it's fine.
def render_checklist_template_html(archetype: ChecklistArchetype) -> str:
    """Re-export of template rendering for bundle use."""
    from workbook.views.checklist.templates import render_checklist_template_html as _render
    return _render(archetype)


def render_views_auto_py(
    archetypes: Sequence[ChecklistArchetype],
    *,
    extra_imports: Sequence[str] = (),
) -> str:
    """Render a complete ``views_auto.py`` module containing all archetypes.

    The output includes a shared ``_resolve_week_year()`` helper, all
    ListView subclasses, and all toggle handler functions.  Stays under
    the ``*_auto.py`` + stub convention by writing the auto file only.
    """
    imports = [
        "from django.contrib.auth.decorators import login_required",
        "from django.contrib.auth.mixins import LoginRequiredMixin",
        "from django.http import HttpResponse",
        "from django.shortcuts import get_object_or_404",
        "from django.utils import timezone",
        "from django.views.decorators.http import require_POST",
        "from django.views.generic import ListView",
        "",
    ]
    imports.extend(extra_imports)
    imports.append("")

    # Resolve unique model imports.
    model_imports: list[str] = []
    seen_apps: dict[str, set[str]] = {}
    for arch in archetypes:
        app = arch.app_label
        seen_apps.setdefault(app, set()).add(arch.model)
    for app, models in sorted(seen_apps.items()):
        model_imports.append(
            f"from {app}.models import {', '.join(sorted(models))}"
        )

    # Shared helper.
    helper = '''
def _resolve_week_year(request):
    """Get year/week from GET params (or fall back to current ISO week)."""
    today = timezone.now().date()
    current_iso = today.isocalendar()
    year = request.GET.get("year")
    week = request.GET.get("week")
    return (
        int(year) if year else current_iso[0],
        int(week) if week else current_iso[1],
    )


'''

    body_parts: list[str] = []
    for arch in archetypes:
        body_parts.append(render_checklist_view_py(arch))
        toggle = render_toggle_handler_py(arch)
        if toggle:
            body_parts.append(toggle)

    return "\n".join(imports) + "\n".join(model_imports) + helper + "\n".join(body_parts)


def render_urls_auto_py(
    archetypes: Sequence[ChecklistArchetype],
) -> str:
    """Render a complete ``urls_auto.py`` module containing all archetypes."""
    view_names: list[str] = []
    for arch in archetypes:
        view_names.append(f"{arch.model}ChecklistView")
        if arch.toggle_field and arch.toggle_url_name:
            handler_name = (
                f"toggle_{to_python_identifier(to_snake_case(arch.model))}_"
                f"{to_python_identifier(arch.toggle_field)}"
            )
            view_names.append(handler_name)
    imports = [
        "from django.urls import include, path",
        "",
        f"from .views_auto import {', '.join(view_names)}",
        "",
        "",
    ]
    patterns: list[str] = []
    for arch in archetypes:
        patterns.extend(render_checklist_url_pattern(arch))
    body = "\n".join(patterns)
    return (
        "\n".join(imports)
        + "urlpatterns = [\n"
        + body
        + "\n]\n"
    )
