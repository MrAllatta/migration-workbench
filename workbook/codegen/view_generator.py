"""Render Django ListView + template + URL patterns for UI archetypes.

The first archetype is the **weekly checklist** — proven in farm_ui's
``checklists.py`` (TaskChecklistView, PlantingChecklistView, NurseryChecklistView).
It is the most common pattern in operator-facing tabular apps: a year/week
filterable list of records, each with an HTMX toggle button.

A checklist config is a plain dict passed to ``render_checklist_view_py()``,
``render_checklist_template_html()``, ``render_checklist_url_pattern()``,
and ``render_toggle_handler_py()``.  The contract and view manifest feed
into those configs via the higher-level :class:`ChecklistArchetype` builder.

Usage::

    from workbook.codegen.view_generator import (
        ChecklistArchetype,
        render_checklist_view_py,
        render_checklist_template_html,
        render_checklist_url_pattern,
        render_toggle_handler_py,
        render_views_auto_py,
        render_urls_auto_py,
    )

    archetype = ChecklistArchetype(
        model="PlantingPlan",
        app_label="core",
        year_field="planned_year",
        week_field="planned_week",
        columns=[
            ("crop", "Crop"),
            ("field_block", "Block"),
        ],
        toggle_field="status",
        ...
    )
    view_source = render_checklist_view_py(archetype)
    template_html = render_checklist_template_html(archetype)
    url_lines = render_checklist_url_pattern(archetype)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from workbook.codegen.python_render import to_python_identifier


# -- archetype config -------------------------------------------------------


@dataclass
class ChecklistColumn:
    """One column in the rendered checklist table."""

    field: str
    label: str
    format: str = "value"  # "value" | "fk_display" | "choice_display"

    def as_template_cell(self) -> str:
        """Render the Django template snippet for one cell in a row."""
        if self.format == "fk_display":
            return f"{{{{ row.{self.field} }}}}"
        if self.format == "choice_display":
            return f"{{{{ row.get_{self.field}_display }}}}"
        return f"{{{{ row.{self.field} }}}}"


@dataclass
class ChecklistArchetype:
    """Configuration for a generated weekly checklist view.

    Attributes:
        model: PascalCase model name (e.g. ``"PlantingPlan"``).
        app_label: Django app label (e.g. ``"core"``).
        year_field: Field name on the model that stores the ISO year.
        week_field: Field name on the model that stores the ISO week.
        columns: Columns to display in the table, in order.
        select_related: FK field names to ``select_related()`` for query
            optimization (e.g. ``["crop", "field_block"]``).
        ordering: Field names to ``order_by()`` in the queryset.
        status_field: Optional model field that holds a status value.
            When set, status badges are rendered and the toggle button
            updates this field.
        status_values: Optional list of valid status values. When omitted,
            derived from the model's ``choices`` if available.
        status_open_value: Status value considered "open" (the value that
            allows the toggle button to be shown). Default ``"open"``.
        status_done_value: Status value considered "done" (the value
            toggled to on click). Default ``"done"``.
        status_badges: Mapping of status value to CSS class, e.g.
            ``{"done": "badge-success", "skipped": "badge-pending"}``.
        toggle_field: Model field that the HTMX toggle button updates.
            Defaults to ``status_field`` when set.
        toggle_url_name: URL name for the HTMX handler (e.g.
            ``"farm_ui_toggle_task_done"``). Required when toggle is set.
        toggle_button_label: Label for the toggle button (default
            ``"Mark Done"``).
        toggle_field_label: Display label for the status column
            (default ``"Status"``).
        title: Page heading (e.g. ``"Task Checklist"``). When the template
            renders, it shows ``{title} — Week {week}, {year}``.
        context_object_name: Variable name in the template's context
            (default ``"rows"``).
        url_path: URL pattern path (e.g. ``"field/tasks/"``).
        url_name: URL pattern name (e.g. ``"farm_ui_task_checklist"``).
        toggle_url_path: URL pattern path for the HTMX toggle handler
            (e.g. ``"field/tasks/<int:pk>/toggle-done/"``).
        toggle_url_name: URL pattern name for the HTMX handler.
        template_path: Output template path relative to the templates
            root (e.g. ``"farm_ui/checklist_tasks.html"``). When omitted,
            derived from ``url_name`` with slashes replaced by underscores.
        back_url_name: Optional URL name to link back to (default None).
        back_url_label: Optional label for the back link (default "Back").
        print_url_name: Optional URL name to link to a print view (default None).
    """

    model: str
    app_label: str
    year_field: str
    week_field: str
    columns: list[ChecklistColumn] = field(default_factory=list)
    select_related: list[str] = field(default_factory=list)
    ordering: list[str] = field(default_factory=list)
    status_field: str | None = None
    status_values: list[str] | None = None
    status_open_value: str = "open"
    status_done_value: str = "done"
    status_badges: dict[str, str] = field(default_factory=dict)
    toggle_field: str | None = None
    toggle_url_name: str | None = None
    toggle_button_label: str = "Mark Done"
    toggle_field_label: str = "Status"
    title: str = "Checklist"
    context_object_name: str = "rows"
    url_path: str = ""
    url_name: str = ""
    toggle_url_path: str = ""
    toggle_url_name: str | None = None
    template_path: str = ""
    back_url_name: str | None = None
    back_url_label: str = "Back"
    print_url_name: str | None = None

    def __post_init__(self) -> None:
        # Default the toggle field to the status field if unset.
        if self.toggle_field is None and self.status_field is not None:
            self.toggle_field = self.status_field
        # Default toggle URL name to "{url_name}_toggle".
        if self.toggle_url_name is None and self.url_name:
            self.toggle_url_name = f"{self.url_name}_toggle"
        # Default toggle URL path to "{url_path}<int:pk>/toggle/".
        if not self.toggle_url_path and self.url_path:
            self.toggle_url_path = f"{self.url_path}<int:pk>/toggle/"
        # Default status badges if status field is set.
        if self.status_field and not self.status_badges:
            self.status_badges = {
                self.status_done_value: "badge-success",
                "skipped": "badge-pending",
            }
            for value in self.status_values or []:
                if value not in self.status_badges:
                    self.status_badges[value] = "badge-pending"
        # Default template path if unset.
        if not self.template_path and self.url_name:
            self.template_path = self.url_name.replace("_", "/") + ".html"


# -- helpers ----------------------------------------------------------------


def _to_snake_case(pascal: str) -> str:
    """Convert PascalCase to snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", pascal).lower()


def _resolve_status_value_expression(archetype: ChecklistArchetype) -> str:
    """Render the Python expression that toggles the status value.

    When the toggle is bound to a status field, we map between
    ``status_open_value`` and ``status_done_value``.  When it is a
    plain boolean, the expression is ``not obj.<field>``.
    """
    field_name = archetype.toggle_field
    if not field_name:
        return "None"
    if field_name == archetype.status_field and archetype.status_field:
        return (
            f'"{archetype.status_done_value}" '
            f'if obj.{field_name} == "{archetype.status_open_value}" '
            f'else "{archetype.status_open_value}"'
        )
    return f"not obj.{field_name}"


def _resolve_status_setter(archetype: ChecklistArchetype) -> str:
    """Render the Python statement that sets the new toggle value on obj."""
    field_name = archetype.toggle_field
    if not field_name:
        return "pass"
    new_value = _resolve_status_value_expression(archetype)
    return f"obj.{field_name} = {new_value}"


# -- view source ------------------------------------------------------------


def render_checklist_view_py(archetype: ChecklistArchetype) -> str:
    """Render the Python source for a checklist ListView subclass.

    The output includes:
    - The ListView subclass with ``model``, ``template_name``,
      ``context_object_name`` set
    - ``get_queryset()`` that filters by year/week from the request
      (falling back to the current ISO week) and applies
      ``select_related``/``order_by``
    - ``get_context_data()`` that adds ``current_year``, ``current_week``,
      and the prev/next year/week pair for navigation
    """
    select_related = ""
    if archetype.select_related:
        sr = ", ".join(repr(f) for f in archetype.select_related)
        select_related = f".select_related({sr})"
    ordering = ""
    if archetype.ordering:
        ob = ", ".join(repr(f) for f in archetype.ordering)
        ordering = f".order_by({ob})"
    model_name = archetype.model
    template = archetype.template_path
    ctx_name = archetype.context_object_name

    lines = [
        "",
        "",
        f"class {model_name}ChecklistView(LoginRequiredMixin, ListView):",
        f"    model = {model_name}",
        f'    template_name = "{template}"',
        f'    context_object_name = "{ctx_name}"',
        "",
        "    def get_queryset(self):",
        "        year, week = _resolve_week_year(self.request)",
        f"        return {model_name}.objects.filter(",
        f"            {archetype.year_field}=year,",
        f"            {archetype.week_field}=week,",
        f"        ){select_related}{ordering}",
        "",
        "    def get_context_data(self, **kwargs):",
        "        context = super().get_context_data(**kwargs)",
        "        year, week = _resolve_week_year(self.request)",
        '        context["current_year"] = year',
        '        context["current_week"] = week',
        "        if week <= 1:",
        '            context["prev_year"] = year - 1',
        '            context["prev_week"] = 52',
        "        else:",
        '            context["prev_year"] = year',
        '            context["prev_week"] = week - 1',
        "        if week >= 52:",
        '            context["next_year"] = year + 1',
        '            context["next_week"] = 1',
        "        else:",
        '            context["next_year"] = year',
        '            context["next_week"] = week + 1',
        "        return context",
        "",
    ]
    return "\n".join(lines)


def render_toggle_handler_py(archetype: ChecklistArchetype) -> str:
    """Render the Python source for the HTMX toggle handler view.

    The handler is a function-based view decorated with
    ``@require_POST`` and ``@login_required`` that:
    1. Fetches the object by ``pk``
    2. Toggles the configured field
    3. Saves the change with ``update_fields=[field]``
    4. Returns a single ``<td>`` HTML response for HTMX to swap
    """
    if not archetype.toggle_field or not archetype.toggle_url_name:
        return ""
    model_name = archetype.model
    setter = _resolve_status_setter(archetype)
    field_name = archetype.toggle_field
    title = archetype.title
    display_attr = (
        f"obj.get_{field_name}_display()"
        if field_name == archetype.status_field
        else f"str(obj.{field_name})"
    )
    lines = [
        "",
        "",
        "@require_POST",
        "@login_required",
        f"def toggle_{to_python_identifier(_to_snake_case(model_name))}_{to_python_identifier(field_name)}("
        "request, pk):",
        f'    """HTMX handler: toggle ``{field_name}`` on {model_name}."""',
        f"    obj = get_object_or_404({model_name}, pk=pk)",
        f"    {setter}",
        f"    obj.save(update_fields=[{field_name!r}])",
        f'    return HttpResponse('
        f'f\'<td colspan="4">Updated {{ {display_attr} }}</td>\'',
        "    )",
        "",
    ]
    return "\n".join(lines)


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
            f"toggle_{to_python_identifier(_to_snake_case(archetype.model))}_"
            f"{to_python_identifier(archetype.toggle_field)}"
        )
        lines.append(
            f'    path("{archetype.toggle_url_path}", {toggle_handler}, name="{archetype.toggle_url_name}"),'
        )
    return lines


# -- template ---------------------------------------------------------------


def render_checklist_template_html(archetype: ChecklistArchetype) -> str:
    """Render the Django template HTML for the checklist archetype.

    The template:
    - Extends ``base.html`` (project default)
    - Renders an ``<h1>`` with the title + current week + year
    - Renders a year/week navigation bar (Prev / This Week / Next)
    - Renders a ``<table>`` with the configured columns
    - When ``status_field`` is set, renders a status badge cell and an
      HTMX toggle button (only when status is not done)
    - Renders a "Back" link at the bottom
    """
    title = archetype.title
    ctx_name = archetype.context_object_name
    status_field = archetype.status_field
    toggle_field = archetype.toggle_field
    toggle_url_name = archetype.toggle_url_name
    toggle_button_label = archetype.toggle_button_label
    toggle_field_label = archetype.toggle_field_label

    # Header row.
    headers = [col.label for col in archetype.columns]
    if status_field:
        headers.append(toggle_field_label)
    if toggle_field:
        headers.append("Action")

    # Body row cells.
    body_cells = []
    for col in archetype.columns:
        cell = col.as_template_cell()
        if col.format == "value":
            cell = f"      <td>{{{{ row.{col.field}|default:\"—\" }}}}</td>"
        else:
            cell = f"      <td>{cell.replace('{{', '{{ ').replace('}}', ' }}').strip()}</td>"
        body_cells.append(cell)

    # Status badge cell.
    status_cell = ""
    if status_field:
        status_cell_lines = [
            "      <td>",
        ]
        for value, css_class in archetype.status_badges.items():
            status_cell_lines.append(
                f"        {{{{% if row.{status_field} == {value!r} }}}}"
            )
            status_cell_lines.append(
                f'          <span class="badge {css_class}">{value.title()}</span>'
            )
            status_cell_lines.append("        {{% endif %}}")
        status_cell_lines.append("      </td>")
        status_cell = "\n".join(status_cell_lines)

    # Toggle button cell.
    toggle_cell = ""
    if toggle_field and toggle_url_name:
        toggle_cell_lines = [
            "      <td>",
            f"        {{{{% if row.{status_field or toggle_field} != {archetype.status_done_value!r} }}}}",
            '        <button class="btn-toggle"',
            f'                hx-post="{{% url {toggle_url_name!r} row.pk %}}"',
            f'                hx-target="#row-{{{{ row.pk }}}}"',
            f'                hx-swap="outerHTML">',
            f"          {toggle_button_label}",
            "        </button>",
            "        {{% endif %}}",
            "      </td>",
        ]
        toggle_cell = "\n".join(toggle_cell_lines)

    # Empty-row fallback.
    colspan = len(headers)

    # Bottom links.
    bottom_links = []
    if archetype.print_url_name:
        bottom_links.append(
            f'    <a href="{{% url {archetype.print_url_name!r} %}}" class="btn">Print List</a>'
        )
    if archetype.back_url_name:
        bottom_links.append(
            f'    <a href="{{% url {archetype.back_url_name!r} %}}" class="btn">{archetype.back_url_label}</a>'
        )
    bottom_links_block = "\n".join(bottom_links)

    rows = "\n".join(f"        <th>{h}</th>" for h in headers)
    body = "\n".join(body_cells)
    if status_cell:
        body += "\n" + status_cell
    if toggle_cell:
        body += "\n" + toggle_cell

    template = f"""{{% extends "base.html" %}}

{{% block content %}}
<h1>{title} &mdash; Week {{{{ current_week }}}}, {{{{ current_year }}}}</h1>

<div class="week-nav">
  <a href="?year={{{{ prev_year }}}}&amp;week={{{{ prev_week }}}}" class="btn btn-small">&larr; Prev Week</a>
  <a href="?year={{{{ next_year }}}}&amp;week={{{{ next_week }}}}" class="btn btn-small">Next Week &rarr;</a>
  <a href="." class="btn btn-small">This Week</a>
</div>

<table class="data-table">
  <thead>
    <tr>
{rows}
    </tr>
  </thead>
  <tbody>
    {{% for row in {ctx_name} %}}
    <tr id="row-{{{{ row.pk }}}}">
{body}
    </tr>
    {{% empty %}}
    <tr><td colspan="{colspan}">No records for this week.</td></tr>
    {{% endfor %}}
  </tbody>
</table>

<div style="margin-top: 1rem;">
{bottom_links_block}
</div>
{{% endblock %}}
"""
    return template


# -- factory ----------------------------------------------------------------


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
        url_path=url_path or _to_snake_case(model).replace("_", "") + "/",
        url_name=url_name or f"{app_label}_{_to_snake_case(model)}_checklist",
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


# -- top-level bundle -------------------------------------------------------


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
                f"toggle_{to_python_identifier(_to_snake_case(arch.model))}_"
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
