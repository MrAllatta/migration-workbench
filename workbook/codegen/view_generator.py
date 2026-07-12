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
        base_template: The Django template the generated template extends
            (default ``"base.html"``).  Product repos should set this to
            their project's base template (e.g. ``"farm_ui/base.html"``).
            The template must define ``{% block content %}`` for the
            generated view to render into.
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
    base_template: str = "base.html"

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

    base_template = archetype.base_template
    template = f"""{{% extends "{base_template}" %}}

{{% block title %}}{title}{{% endblock %}}

{{% block content %}}
{{% block checklist_heading %}}
<h1>{title} &mdash; Week {{{{ current_week }}}}, {{{{ current_year }}}}</h1>
{{% endblock %}}

{{% block checklist_week_nav %}}
<div class="week-nav">
  <a href="?year={{{{ prev_year }}}}&amp;week={{{{ prev_week }}}}" class="btn btn-small">&larr; Prev Week</a>
  <a href="?year={{{{ next_year }}}}&amp;week={{{{ next_week }}}}" class="btn btn-small">Next Week &rarr;</a>
  <a href="." class="btn btn-small">This Week</a>
</div>
{{% endblock %}}

{{% block checklist_table %}}
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
{{% endblock %}}

{{% block checklist_bottom_links %}}
<div style="margin-top: 1rem;">
{bottom_links_block}
</div>
{{% endblock %}}
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


# -- landing archetype ------------------------------------------------------


@dataclass
class SummaryCard:
    """One summary card on a landing page dashboard.

    Attributes:
        label: Display text (e.g. "Open Tasks").
        count_expression: Python expression for the card's value. Evaluated
            at render time in ``get_context_data()``, so it typically
            contains a Django ORM count call or an ``len()``.
        link_url_name: Optional URL name the card links to.
        css_class: Optional extra CSS class for conditional styling
            (e.g. "card-warning", "card-success").
    """

    label: str
    count_expression: str
    link_url_name: str | None = None
    css_class: str = ""


@dataclass
class LandingArchetype:
    """Configuration for a generated role-based landing page.

    The landing archetype produces a ``TemplateView`` subclass whose
    ``get_context_data()`` populates a ``summary_cards`` list of dicts
    (label, value, url_name, css_class) for the template to render in
    a card grid.

    Attributes:
        role: Snake-case role identifier (e.g. ``"field_worker"``).
        title: Page heading (e.g. "Field Ops — Today's Work").
        cards: List of :class:`SummaryCard` instances.
        template_path: Output template path relative to templates root.
            Default: ``"generated/landing_{role}.html"``.
        url_path: URL pattern path. Default: ``"{role}/"``.
        url_name: URL pattern name. Default: ``"landing_{role}"``.
        back_url_name: Optional URL name for a "Back" link.
        back_url_label: Label for the back link (default "Back").
        base_template: The Django template the generated template extends
            (default ``"base.html"``).  Product repos should set this to
            their project's base template (e.g. ``"farm_ui/base.html"``).
            The template must define ``{% block content %}`` for the
            generated view to render into.
    """

    role: str
    title: str
    cards: list[SummaryCard] = field(default_factory=list)
    template_path: str = ""
    url_path: str = ""
    url_name: str = ""
    back_url_name: str | None = None
    back_url_label: str = "Back"
    base_template: str = "base.html"

    def __post_init__(self) -> None:
        if not self.url_name and self.role:
            self.url_name = f"landing_{self.role}"
        if not self.url_path and self.role:
            self.url_path = f"{self.role.replace('_', '-')}/"
        if not self.template_path and self.url_name:
            self.template_path = f"generated/{self.url_name}.html"


# -- landing rendering ------------------------------------------------------


def render_landing_view_py(archetype: LandingArchetype) -> str:
    """Render a ``TemplateView`` subclass for a role-based landing page.

    The generated view has ``get_context_data()`` that:
    1. Evaluates each :attr:`LandingArchetype.cards` count_expression
    2. Resolves ``link_url_name`` to concrete URLs via ``reverse()``
    3. Builds a ``summary_cards`` list of dicts (label, value, url, css_class)
    4. Passes it to the template context
    """
    class_name = f"{_to_pascal_case(archetype.role)}LandingView"
    has_urls = any(card.link_url_name for card in archetype.cards)
    lines: list[str] = [
        "",
        "",
        f"class {class_name}(LoginRequiredMixin, TemplateView):",
        f'    template_name = "{archetype.template_path}"',
        "",
        "    def get_context_data(self, **kwargs):",
        "        context = super().get_context_data(**kwargs)",
    ]
    if has_urls:
        lines.append("        from django.urls import reverse")

    card_vars: list[str] = []
    card_dicts: list[str] = []
    for idx, card in enumerate(archetype.cards):
        var_name = f"_card_{idx}"
        card_vars.append(f"        {var_name} = {card.count_expression}")
        css = f', "css_class": "{card.css_class}"' if card.css_class else ""
        if card.link_url_name:
            card_dicts.append(
                f'            {{"label": "{card.label}", "value": {var_name}'
                f', "url": reverse("{card.link_url_name}")'
                f'{css}}},'
            )
        else:
            card_dicts.append(
                f'            {{"label": "{card.label}", "value": {var_name}{css}}},'
            )

    if card_vars:
        lines.extend(card_vars)
        lines.append("")
    lines.append('        context["summary_cards"] = [')
    lines.extend(card_dicts)
    lines.append("        ]")
    lines.append("        return context")
    lines.append("")
    return "\n".join(lines)


def render_landing_template_html(archetype: LandingArchetype) -> str:
    """Render a Django template for a landing page with summary cards.

    The template renders a heading, a grid of summary cards (each showing
    a value and label, optionally wrapping an ``<a>`` tag), and a back
    link at the bottom.

    Cards with a ``url`` key (pre-resolved by the view's ``get_context_data``
    from ``link_url_name``) wrap each card in an ``<a>`` tag.
    """
    back_link = ""
    if archetype.back_url_name:
        back_link = (
            '<div style="margin-top: 1rem;">'
            f'<a href="{{% url {archetype.back_url_name!r} %}}" class="btn">'
            f"{archetype.back_url_label}</a></div>"
        )

    base_template = archetype.base_template
    return f"""{{% extends "{base_template}" %}}

{{% block title %}}{archetype.title}{{% endblock %}}

{{% block content %}}
{{% block landing_heading %}}
<h1>{archetype.title}</h1>
{{% endblock %}}

{{% block landing_summary_cards %}}
<div class="summary-cards">
  {{% for card in summary_cards %}}
  {{% if card.url %}}
  <a href="{{{{ card.url }}}}" class="card-link">
  {{% endif %}}
    <div class="card {{{{ card.css_class }}}}">
      <div class="card-number">{{{{ card.value }}}}</div>
      <div class="card-label">{{{{ card.label }}}}</div>
    </div>
  {{% if card.url %}}
  </a>
  {{% endif %}}
  {{% empty %}}
  <p>No data available.</p>
  {{% endfor %}}
</div>
{{% endblock %}}
{back_link}
{{% endblock %}}
"""


def render_landing_url_pattern(archetype: LandingArchetype) -> list[str]:
    """Render URL pattern lines for a landing page.

    Returns:
        A list with one ``path()`` line ready for ``urlpatterns = [...]``.
    """
    if not archetype.url_path or not archetype.url_name:
        return []
    class_name = f"{_to_pascal_case(archetype.role)}LandingView"
    return [
        f'    path("{archetype.url_path}", {class_name}.as_view(), name="{archetype.url_name}"),',
    ]


def render_landing_views_auto_py(
    archetypes: Sequence[LandingArchetype],
    *,
    extra_imports: Sequence[str] = (),
    app_label: str = "core",
) -> str:
    """Render a complete ``views_auto.py`` module with multiple landing archetypes.

    Includes ``TemplateView``/``LoginRequiredMixin`` imports, auto-detected
    model imports based on capitalized identifiers in card count expressions,
    and all generated view classes.

    Args:
        archetypes: Landing archetypes to render.
        extra_imports: Additional import lines to include.
        app_label: Django app label for the model import module
            (default ``"core"``).
    """
    # Collect all model names from card expressions.
    all_model_names: set[str] = set()
    for arch in archetypes:
        for card in arch.cards:
            all_model_names.update(_extract_model_names(card.count_expression))

    imports: list[str] = [
        "from django.contrib.auth.mixins import LoginRequiredMixin",
        "from django.views.generic import TemplateView",
        "",
    ]
    if all_model_names:
        sorted_names = sorted(all_model_names)
        imports.append(f"from {app_label}.models import {', '.join(sorted_names)}")
        imports.append("")
    imports.extend(extra_imports)
    imports.append("")

    body_parts: list[str] = []
    for arch in archetypes:
        body_parts.append(render_landing_view_py(arch))
    return "\n".join(imports) + "\n".join(body_parts)


def render_landing_urls_auto_py(
    archetypes: Sequence[LandingArchetype],
) -> str:
    """Render a complete ``urls_auto.py`` module with multiple landing archetypes."""
    view_names: list[str] = []
    for arch in archetypes:
        view_names.append(f"{_to_pascal_case(arch.role)}LandingView")
    imports = [
        "from django.urls import include, path",
        "",
        f"from .views_auto import {', '.join(view_names)}",
        "",
        "",
    ]
    patterns: list[str] = []
    for arch in archetypes:
        patterns.extend(render_landing_url_pattern(arch))
    body = "\n".join(patterns)
    return (
        "\n".join(imports)
        + "urlpatterns = [\n"
        + body
        + "\n]\n"
    )


# -- dashboard archetype ------------------------------------------------------


@dataclass
class AlertCard:
    """One alert card on a dashboard view.

    Attributes:
        label: Display text (e.g. "Zero Stock").
        count_expression: Python expression that evaluates to the card's
            count at render time (typically a Django ORM count call).
        severity: CSS severity class (``info``, ``success``, ``warning``,
            ``danger``).
        link_url_name: Optional URL name the card links to.
    """

    label: str
    count_expression: str
    severity: str = "info"
    link_url_name: str | None = None


@dataclass
class DetailColumn:
    """One column in a dashboard detail section table.

    Attributes:
        field: Model field name (e.g. ``"crop"``).
        label: Column header (e.g. "Crop").
        format: Cell format (``"value"``, ``"fk_display"``,
            ``"choice_display"``).
    """

    field: str
    label: str
    format: str = "value"

    def as_template_cell(self) -> str:
        """Render the Django template expression for one cell."""
        if self.format == "fk_display":
            return f"{{{{ row.{self.field} }}}}"
        if self.format == "choice_display":
            return f"{{{{ row.get_{self.field}_display }}}}"
        return f"{{{{ row.{self.field}|default:\"—\" }}}}"


@dataclass
class DetailSection:
    """One detail section (title + data table) in a dashboard.

    Attributes:
        title: Section heading (e.g. "Inventory Items").
        queryset_expression: Python expression that evaluates to a
            QuerySet or list of model instances at render time.
        columns: Columns to display in the section table.
        limit: Maximum rows to display (default ``None`` = no limit).
        empty_message: Text shown when the queryset is empty.
    """

    title: str
    queryset_expression: str
    columns: list[DetailColumn] = field(default_factory=list)
    limit: int | None = None
    empty_message: str = "No records found."


@dataclass
class DashboardArchetype:
    """Configuration for a generated dashboard ``TemplateView``.

    The dashboard archetype produces a ``TemplateView`` whose
    ``get_context_data()`` evaluates alert count expressions and section
    queryset expressions, then passes them to a generated template with
    an alert card grid and one or more detail data tables.

    Attributes:
        name: Internal identifier (snake_case, used for URL defaults).
        title: Page heading (e.g. "Inventory Dashboard").
        alerts: Alert cards to render at the top of the dashboard.
        sections: Detail sections with tables below the alerts.
        template_path: Output template path relative to templates root.
            Default: ``"generated/dashboard_{name}.html"``.
        url_path: URL pattern path. Default: ``"{name}/"``.
        url_name: URL pattern name. Default: ``"dashboard_{name}"``.
        back_url_name: Optional URL name for a back link.
        back_url_label: Label for the back link (default "Back").
        app_label: Django app label for model imports (default ``"core"``).
        base_template: The Django template the generated template extends
            (default ``"base.html"``).  Product repos should set this to
            their project's base template (e.g. ``"farm_ui/base.html"``).
    """

    name: str
    title: str
    alerts: list[AlertCard] = field(default_factory=list)
    sections: list[DetailSection] = field(default_factory=list)
    template_path: str = ""
    url_path: str = ""
    url_name: str = ""
    back_url_name: str | None = None
    back_url_label: str = "Back"
    app_label: str = "core"
    base_template: str = "base.html"

    def __post_init__(self) -> None:
        if not self.url_name and self.name:
            self.url_name = f"dashboard_{self.name}"
        if not self.url_path and self.name:
            self.url_path = f"{self.name.replace('_', '-')}/"
        if not self.template_path and self.url_name:
            self.template_path = f"generated/{self.url_name}.html"


# -- dashboard view source --------------------------------------------------


def render_dashboard_view_py(archetype: DashboardArchetype) -> str:
    """Render the Python source for a dashboard ``TemplateView`` subclass.

    The generated view has ``get_context_data()`` that:
    1. Evaluates each :attr:`DashboardArchetype.alerts` count expression
    2. Resolves ``link_url_name`` to concrete URLs via ``reverse()``
    3. Builds an ``alerts`` context list of dicts
    4. Evaluates each :attr:`DashboardArchetype.sections` queryset
       expression, applies ``limit``, and builds context variables
       ``section_{idx}_title``, ``section_{idx}_rows``, etc.
    """
    class_name = f"{_to_pascal_case(archetype.name)}DashboardView"

    # Check if any alert has a URL (needs reverse import).
    has_urls = any(alert.link_url_name for alert in archetype.alerts)

    lines: list[str] = [
        "",
        "",
        f"class {class_name}(LoginRequiredMixin, TemplateView):",
        f'    template_name = "{archetype.template_path}"',
        "",
        "    def get_context_data(self, **kwargs):",
        "        context = super().get_context_data(**kwargs)",
    ]
    if has_urls:
        lines.append("        from django.urls import reverse")

    # --- Evaluate alert expressions.
    alert_vars: list[str] = []
    alert_dicts: list[str] = []
    for idx, alert in enumerate(archetype.alerts):
        var_name = f"_alert_{idx}"
        alert_vars.append(f"        {var_name} = {alert.count_expression}")
        css = f'"{alert.severity}"'
        if alert.link_url_name:
            alert_dicts.append(
                f'            {{"label": "{alert.label}", "value": {var_name}'
                f', "severity": {css}'
                f', "url": reverse("{alert.link_url_name}")}}, '
            )
        else:
            alert_dicts.append(
                f'            {{"label": "{alert.label}", "value": {var_name}'
                f', "severity": {css}}}, '
            )

    if alert_vars:
        lines.append("")
        lines.extend(alert_vars)
        lines.append("")
        lines.append('        context["alerts"] = [')
        lines.extend(alert_dicts)
        lines.append("        ]")
    else:
        lines.append('        context["alerts"] = []')

    # --- Evaluate section querysets.
    for idx, section in enumerate(archetype.sections):
        lines.append("")
        lines.append(f'        context["section_{idx}_title"] = {section.title!r}')
        limit_expr = f"[:{section.limit}]" if section.limit else ""
        lines.append(
            f'        context["section_{idx}_rows"] = '
            f'{section.queryset_expression}{limit_expr}'
        )
        lines.append(
            f'        context["section_{idx}_empty_message"] = '
            f'{section.empty_message!r}'
        )
        lines.append(f'        context["section_{idx}_colspan"] = {len(section.columns)}')

    lines.append("        return context")
    lines.append("")
    return "\n".join(lines)


# -- dashboard template -----------------------------------------------------


def render_dashboard_template_html(archetype: DashboardArchetype) -> str:
    """Render the Django template HTML for the dashboard archetype.

    The template:
    - Extends ``base.html`` (project default)
    - Renders an ``<h1>`` with the dashboard title
    - Renders a grid of alert cards with severity CSS classes
    - For each detail section, renders a heading + data table with
      the configured columns
    - Shows a back link at the bottom

    Each section's table is hard-coded at generation time with the
    column field references.  To change columns, re-generate.
    """
    title = archetype.title

    # --- Build section table blocks.
    section_blocks: list[str] = []
    for idx, section in enumerate(archetype.sections):
        cols = len(section.columns)
        # Column headers.
        headers = "\n".join(
            f'        <th>{col.label}</th>'
            for col in section.columns
        )
        # Column body cells.
        body_cells = []
        for col in section.columns:
            if col.format == "fk_display":
                body_cells.append(f'      <td>{{{{ row.{col.field} }}}}</td>')
            elif col.format == "choice_display":
                body_cells.append(f'      <td>{{{{ row.get_{col.field}_display }}}}</td>')
            else:
                body_cells.append(f'      <td>{{{{ row.{col.field}|default:"—" }}}}</td>')
        body = "\n".join(body_cells)

        block_parts = [
            "",
            f"<h2>{{{{ section_{idx}_title }}}}</h2>",
            '<table class="data-table">',
            "  <thead>",
            "    <tr>",
            headers,
            "    </tr>",
            "  </thead>",
            "  <tbody>",
            f"    {{% for row in section_{idx}_rows %}}",
            "    <tr>",
            body,
            "    </tr>",
            f"    {{% empty %}}",
            f'    <tr><td colspan="{cols}">{{{{ section_{idx}_empty_message }}}}</td></tr>',
            f"    {{% endfor %}}",
            "  </tbody>",
            "</table>",
        ]
        section_blocks.append("\n".join(block_parts))

    sections_html = "\n".join(section_blocks)

    base_template = archetype.base_template

    back_link = ""
    if archetype.back_url_name:
        back_link = (
            '\n<div style="margin-top: 1rem;">'
            f'<a href="{{% url {archetype.back_url_name!r} %}}" class="btn">'
            f"{archetype.back_url_label}</a></div>"
        )

    template = f"""{{% extends "{base_template}" %}}

{{% block title %}}{title}{{% endblock %}}

{{% block content %}}
{{% block dashboard_heading %}}
<h1>{title}</h1>
{{% endblock %}}

{{% block dashboard_alert_cards %}}
<div class="summary-cards">
  {{% for alert in alerts %}}
  {{% if alert.url %}}
  <a href="{{{{ alert.url }}}}" class="card-link">
  {{% endif %}}
    <div class="card card-{{{{ alert.severity }}}}">
      <div class="card-number">{{{{ alert.value }}}}</div>
      <div class="card-label">{{{{ alert.label }}}}</div>
    </div>
  {{% if alert.url %}}
  </a>
  {{% endif %}}
  {{% empty %}}
  <p>No alerts configured.</p>
  {{% endfor %}}
</div>
{{% endblock %}}

{{% block dashboard_sections %}}
{sections_html}
{{% endblock %}}
{back_link}
{{% endblock %}}
"""
    return template


# -- dashboard URL patterns -------------------------------------------------


def render_dashboard_url_pattern(archetype: DashboardArchetype) -> list[str]:
    """Render URL pattern lines for a dashboard view.

    Returns:
        A list with one ``path()`` line ready for ``urlpatterns = [...]``.
    """
    if not archetype.url_path or not archetype.url_name:
        return []
    class_name = f"{_to_pascal_case(archetype.name)}DashboardView"
    return [
        f'    path("{archetype.url_path}", {class_name}.as_view(), name="{archetype.url_name}"),',
    ]


# -- dashboard combined modules ---------------------------------------------


def render_dashboard_views_auto_py(
    archetypes: Sequence[DashboardArchetype],
    *,
    extra_imports: Sequence[str] = (),
    app_label: str = "core",
) -> str:
    """Render a complete ``views_auto.py`` with multiple dashboard archetypes.

    Includes ``TemplateView``/``LoginRequiredMixin`` imports, auto-detected
    model imports from count and queryset expressions, and all generated
    view classes.
    """
    # Collect all model names from alert and section expressions.
    all_model_names: set[str] = set()
    for arch in archetypes:
        for alert in arch.alerts:
            all_model_names.update(_extract_model_names(alert.count_expression))
        for section in arch.sections:
            all_model_names.update(_extract_model_names(section.queryset_expression))

    imports: list[str] = [
        "from django.contrib.auth.mixins import LoginRequiredMixin",
        "from django.views.generic import TemplateView",
        "",
    ]
    if all_model_names:
        sorted_names = sorted(all_model_names)
        imports.append(f"from {app_label}.models import {', '.join(sorted_names)}")
        imports.append("")
    imports.extend(extra_imports)
    imports.append("")

    body_parts: list[str] = []
    for arch in archetypes:
        body_parts.append(render_dashboard_view_py(arch))
    return "\n".join(imports) + "\n".join(body_parts)


def render_dashboard_urls_auto_py(
    archetypes: Sequence[DashboardArchetype],
) -> str:
    """Render a complete ``urls_auto.py`` with multiple dashboard archetypes."""
    view_names: list[str] = []
    for arch in archetypes:
        view_names.append(f"{_to_pascal_case(arch.name)}DashboardView")
    imports = [
        "from django.urls import include, path",
        "",
        f"from .views_auto import {', '.join(view_names)}",
        "",
        "",
    ]
    patterns: list[str] = []
    for arch in archetypes:
        patterns.extend(render_dashboard_url_pattern(arch))
    body = "\n".join(patterns)
    return (
        "\n".join(imports)
        + "urlpatterns = [\n"
        + body
        + "\n]\n"
    )


def _extract_model_names(expression: str) -> list[str]:
    """Extract capitalized identifiers from *expression* that look like
    Django model class names (not Python builtins, keywords, or common
    Django identifiers).

    Used by :func:`render_landing_views_auto_py` to generate the correct
    ``from core.models import ...`` line for card count expressions.
    """
    import builtins
    import keyword
    import re
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


def _to_pascal_case(snake: str) -> str:
    """Convert snake_case to PascalCase."""
    if not snake:
        return snake
    return "".join(word.capitalize() for word in snake.split("_"))
