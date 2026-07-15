"""Landing template rendering.

Produces Django template HTML for role-based landing pages with summary
card grids.
"""

from __future__ import annotations

from workbook.views.landing.archetype import LandingArchetype


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
