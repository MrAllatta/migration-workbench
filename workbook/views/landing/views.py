"""Landing view rendering.

Produces Python source for ``TemplateView`` subclasses used in role-based
landing pages with summary cards.
"""

from __future__ import annotations

from workbook.views.landing.archetype import LandingArchetype
from workbook.views.utils import to_pascal_case


def render_landing_view_py(archetype: LandingArchetype) -> str:
    """Render a ``TemplateView`` subclass for a role-based landing page.

    The generated view has ``get_context_data()`` that:
    1. Evaluates each :attr:`LandingArchetype.cards` count_expression
    2. Resolves ``link_url_name`` to concrete URLs via ``reverse()``
    3. Builds a ``summary_cards`` list of dicts (label, value, url, css_class)
    4. Passes it to the template context
    """
    class_name = f"{to_pascal_case(archetype.role)}LandingView"
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
                f"{css}}},"
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
