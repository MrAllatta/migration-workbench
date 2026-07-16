"""Dashboard template rendering.

Produces Django template HTML for dashboards with alert cards and detail
section tables.
"""

from __future__ import annotations

from workbook.views.dashboard.archetype import DashboardArchetype


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

    section_blocks: list[str] = []
    for idx, section in enumerate(archetype.sections):
        cols = len(section.columns)
        headers = "\n".join(
            f'        <th>{col.label}</th>'
            for col in section.columns
        )
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
            "    {% empty %}",
            f'    <tr><td colspan="{cols}">{{{{ section_{idx}_empty_message }}}}</td></tr>',
            "    {% endfor %}",
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
