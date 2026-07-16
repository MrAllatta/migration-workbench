"""Checklist template rendering.

Produces the Django template HTML for the weekly checklist archetype:
week navigation bar, data table with status badges, HTMX toggle button, bottom links.
"""

from __future__ import annotations

from workbook.views.checklist.archetype import ChecklistArchetype


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
            cell = f'      <td>{{{{ row.{col.field}|default:"—" }}}}</td>'
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
            '                hx-target="#row-{{ row.pk }}"',
            '                hx-swap="outerHTML">',
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
