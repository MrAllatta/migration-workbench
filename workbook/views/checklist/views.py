"""Checklist view and toggle handler rendering.

Produces Python source for ``ListView`` subclasses and HTMX toggle-handler
function views for the weekly checklist archetype.
"""

from __future__ import annotations

from workbook.codegen.python_render import to_python_identifier
from workbook.views.checklist.archetype import ChecklistArchetype
from workbook.views.utils import to_snake_case


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
        f"def toggle_{to_python_identifier(to_snake_case(model_name))}_{to_python_identifier(field_name)}("
        "request, pk):",
        f'    """HTMX handler: toggle ``{field_name}`` on {model_name}."""',
        f"    obj = get_object_or_404({model_name}, pk=pk)",
        f"    {setter}",
        f"    obj.save(update_fields=[{field_name!r}])",
        f"    return HttpResponse("
        f"f'<td colspan=\"4\">Updated {{ {display_attr} }}</td>'",
        "    )",
        "",
    ]
    return "\n".join(lines)
