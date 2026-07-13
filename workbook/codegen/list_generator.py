"""Render Django ListView subclasses and their templates for list archetypes.

The list archetype produces a ``ListView`` subclass that:
1. Defines a model, paginate_by, and context_object_name
2. Has a ``get_queryset()`` that applies filters from the request
3. Has a ``get_context_data()`` that exposes filter options and
   selected filter values for the template to render a filter sidebar

Usage::

    from workbook.codegen.list_generator import (
        ListArchetype,
        render_list_view_py,
    )

    archetype = ListArchetype(
        model="Crop",
        title="View Crops",
        columns=["name", "botanical_family", "product_type"],
        filters=["botanical_family", "product_type"],
        ordering=["name"],
        paginate_by=50,
        context_object_name="crops",
    )
    view_source = render_list_view_py(archetype)
"""

from __future__ import annotations

from dataclasses import dataclass, field


# -- list archetype config --------------------------------------------------


@dataclass
class ListArchetype:
    """Configuration for a generated ``ListView`` subclass.

    The list archetype produces a ``ListView`` that paginates a model
    and exposes filter options for a sidebar (e.g. ``families`` and
    ``product_types`` for the Crop list view).

    Attributes:
        model: Django model name (e.g. ``"Crop"``).
        title: Page heading (e.g. "Crops").
        columns: List of model field names to display in the table.
        filters: List of model field names that can be used as filters.
        ordering: List of field names to order the queryset by.
        paginate_by: Pagination size (default 50).
        context_object_name: Template context key for the object list
            (default: model's snake_case name + ``"s"``).
        filter_options: Optional dict mapping filter field name to a
            Python expression that evaluates to a list of distinct values
            for the filter sidebar.  If None, the renderer generates
            default expressions of the form ``Model.objects.values_list(
            "field", flat=True).exclude(field="").distinct().order_by(
            "field")``.
        template_path: Output template path (default ``"generated/list_{model_snake}.html"``).
        app_label: Django app label for model imports (default ``"core"``).
    """

    model: str
    title: str
    columns: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    ordering: list[str] = field(default_factory=list)
    paginate_by: int = 50
    context_object_name: str = ""
    filter_options: dict[str, str] = field(default_factory=dict)
    template_path: str = ""
    app_label: str = "core"

    def __post_init__(self) -> None:
        if not self.columns:
            self.columns = ["name"]
        if not self.ordering:
            self.ordering = ["id"]
        if not self.context_object_name:
            self.context_object_name = self._default_context_name()
        if not self.template_path:
            self.template_path = f"generated/list_{self._model_snake()}.html"

    def _model_snake(self) -> str:
        """Convert CamelCase model name to snake_case."""
        out = []
        for idx, char in enumerate(self.model):
            if char.isupper() and idx > 0:
                out.append("_")
            out.append(char.lower())
        return "".join(out)

    def _default_context_name(self) -> str:
        """Default context_object_name: model name in snake_case pluralised."""
        snake = self._model_snake()
        if snake.endswith("y"):
            return f"{snake[:-1]}ies"
        if snake.endswith("s"):
            return snake
        return f"{snake}s"


# -- list view rendering ----------------------------------------------------


def _default_filter_option_expression(model: str, field: str) -> str:
    """Return the default Python expression for a filter sidebar list.

    Mirrors farm's CropListView pattern:
    ``Crop.objects.values_list("botanical_family", flat=True)
    .exclude(botanical_family="").distinct().order_by("botanical_family")``
    """
    return (
        f'{model}.objects.values_list("{field}", flat=True)'
        f'.exclude({field}="").distinct()'
        f'.order_by("{field}")'
    )


def _build_filter_expressions(archetype: ListArchetype) -> list[str]:
    """Build the lines that compute filter option lists.

    Each filter gets:
    - A distinct values queryset (context variable named from the field)
    - A selected value (context variable prefixed with ``selected_``)
    """
    lines: list[str] = []
    for filter_field in archetype.filters:
        options_key = f"{filter_field}_options"
        selected_key = f"selected_{filter_field}"

        if filter_field in archetype.filter_options:
            expr = archetype.filter_options[filter_field]
        else:
            expr = (
                f'{archetype.model}.objects.values_list("{filter_field}", flat=True)'
                f'.exclude({filter_field}="").distinct()'
                f'.order_by("{filter_field}")'
            )

        lines.append(f'        context["{options_key}"] = {expr}')
        lines.append(
            f'        context["{selected_key}"] = self.request.GET.get("{filter_field}", "")'
        )
    return lines


def render_list_view_py(archetype: ListArchetype) -> str:
    """Render the Python source for a ``ListView`` subclass.

    The generated view has:
    - ``model``, ``paginate_by``, ``context_object_name``, ``template_name``
    - ``get_queryset()`` applying filters from request GET params
    - ``get_context_data()`` exposing filter option lists and selected
      filter values for the template sidebar
    """
    class_name = f"{archetype.model}ListView"

    lines: list[str] = [
        "",
        "",
        f"class {class_name}(LoginRequiredMixin, ListView):",
        f"    model = {archetype.model}",
        f"    template_name = {archetype.template_path!r}",
        f"    context_object_name = {archetype.context_object_name!r}",
        f"    paginate_by = {archetype.paginate_by}",
        "",
        "    def get_queryset(self):",
        f"        qs = {archetype.model}.objects.all()",
    ]

    # Add filter lines to get_queryset
    for filter_field in archetype.filters:
        var_name = f"_{filter_field}_filter"
        lines.append(
            f"        {var_name} = self.request.GET.get({filter_field!r}, '')"
        )
        lines.append(f"        if {var_name}:")
        lines.append(
            f"            qs = qs.filter({filter_field}={var_name})"
        )

    # Ordering
    if archetype.ordering:
        ordering_str = ", ".join(f"{f}" for f in archetype.ordering)
        lines.append(f"        return qs.order_by({ordering_str!r})")
    else:
        lines.append("        return qs")

    # get_context_data
    lines.extend([
        "",
        "    def get_context_data(self, **kwargs):",
        "        context = super().get_context_data(**kwargs)",
    ])

    # Filter option expressions
    filter_lines = _build_filter_expressions(archetype)
    lines.extend(filter_lines)
    lines.append("        return context")
    lines.append("")
    return "\n".join(lines)


# -- list URL pattern rendering --------------------------------------------


def render_list_url_pattern(archetype: ListArchetype) -> str:
    """Render a Django path() line for the list view URL pattern."""
    class_name = f"{archetype.model}ListView"
    url_name = f"list_{archetype._model_snake()}"
    url_path = f"{archetype._model_snake()}/"
    return f'    path("{url_path}", {class_name}.as_view(), name="{url_name}"),'
