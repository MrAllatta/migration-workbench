"""Checklist archetype config dataclasses.

The checklist archetype is a weekly year/week-filterable ListView with
HTMX toggle — the dominant pattern in operator-facing tabular apps.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
