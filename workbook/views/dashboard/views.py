"""Dashboard view rendering.

Produces Python source for ``TemplateView`` subclasses with alert cards
and detail section tables.
"""

from __future__ import annotations

from workbook.views.dashboard.archetype import DashboardArchetype
from workbook.views.utils import to_pascal_case


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
    class_name = f"{to_pascal_case(archetype.name)}DashboardView"

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

    for idx, section in enumerate(archetype.sections):
        lines.append("")
        lines.append(f'        context["section_{idx}_title"] = {section.title!r}')
        limit_expr = f"[:{section.limit}]" if section.limit else ""
        lines.append(
            f'        context["section_{idx}_rows"] = '
            f"{section.queryset_expression}{limit_expr}"
        )
        lines.append(
            f'        context["section_{idx}_empty_message"] = '
            f"{section.empty_message!r}"
        )
        lines.append(
            f'        context["section_{idx}_colspan"] = {len(section.columns)}'
        )

    lines.append("        return context")
    lines.append("")
    return "\n".join(lines)
