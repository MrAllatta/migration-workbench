"""Landing archetype config dataclasses.

The landing archetype produces a role-based landing page with summary cards.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
