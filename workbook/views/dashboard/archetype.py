"""Dashboard archetype config dataclasses.

The dashboard archetype produces a ``TemplateView`` with alert cards at the
top and one or more detail data tables below.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
