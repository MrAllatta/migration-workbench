"""Render Django ``admin.py`` source from a schema contract + view manifest.

Usage::

    from workbook.codegen.contract import load_contract
    from workbook.codegen.manifest import load_manifest
    from workbook.codegen.admin_generator import render_admin_py

    contract = load_contract("build/schema-contract.yaml")
    manifest = load_manifest("build/view-manifest.yaml")
    source = render_admin_py(contract, manifest, app_label="core")
    Path("backend/apps/core/admin.py").write_text(source)
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from workbook.codegen.contract import (
    get_admin_config,
    get_fields,
    get_model_base,
    get_model_meta,
    get_model_name,
)
from workbook.codegen.manifest import find_view_for_entity
from workbook.codegen.stub_writer import MARKER


class _ClassRef:
    """Wrapper that renders as a bare Python name when repr() is called.

    Used for filter_items that need to be class references (not string
    literals) in the generated ``list_filter`` list.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return self._name

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self._name == other
        if isinstance(other, _ClassRef):
            return self._name == other._name
        return NotImplemented


# -- helpers ----------------------------------------------------------------


def _to_snake_case(pascal: str) -> str:
    """Convert PascalCase to snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", pascal).lower()


def _to_pascal_case(snake: str) -> str:
    """Convert snake_case to PascalCase."""
    if not snake:
        return snake
    return "".join(word.capitalize() for word in snake.split("_"))


_MODEL_CLASSES_WITH_SEARCH = {
    "CharField",
    "TextField",
    "SlugField",
    "URLField",
    "EmailField",
}


def _field_class_short(raw: str) -> str:
    """Strip the ``models.`` prefix from a field class string."""
    return raw.removeprefix("models.")


def _is_text_field(field: dict[str, Any]) -> bool:
    """Return ``True`` if *field* is a text-like searchable type."""
    short = _field_class_short(field["class"])
    return short in _MODEL_CLASSES_WITH_SEARCH


def _is_fk_field(field: dict[str, Any]) -> bool:
    """Return ``True`` if *field* is a ``ForeignKey``."""
    return field["class"] == "models.ForeignKey"


def _is_date_field(field: dict[str, Any]) -> bool:
    """Return ``True`` if *field* is a date/time type."""
    return _field_class_short(field["class"]) in ("DateField", "DateTimeField")


def _is_abstract_user_model(table: dict[str, Any]) -> bool:
    """Return ``True`` if *table* extends ``AbstractUser``."""
    base = str(get_model_base(table))
    return base == "AbstractUser" or base.endswith(".AbstractUser")


def _build_fk_index(
    tables: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Build ``{target_model_name: [{source_table, fk_field_name}, ...]}``.

    Crawls all tables in the contract and indexes every ForeignKey field
    by its target model, so the admin generator can emit ``TabularInline``
    classes for reverse FK relationships.
    """
    index: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        source_name = get_model_name(table)
        for field in get_fields(table):
            if _is_fk_field(field):
                target = field["kwargs"].get("to", "")
                if target and isinstance(target, str) and target != "self":
                    index.setdefault(target, []).append(
                        {"source_name": source_name, "field_name": field["name"]}
                    )
    return index


def _pick_display_fields(
    view: dict[str, Any] | None,
    contract_fields: list[dict[str, Any]],
    admin_cfg: dict[str, Any] | None = None,
    max_count: int = 5,
    *,
    authoritative: bool = False,
) -> list[str]:
    """Pick ``list_display`` field names for a model.

    Priority:
    1. Contract ``admin.list_display`` (if set, authoritative)
    2. Manifest suggested_display_fields (if no explicit admin config)
    3. Auto-detect from field type (name, date, FK fields)
    """
    if admin_cfg:
        explicit = admin_cfg.get("list_display")
        if explicit:
            return list(explicit)

    if view:
        suggested = (
            view.get("suggested_display_fields")
            or view.get("display_fields")
            or view.get("editable_fields")
            or []
        )
        if suggested:
            valid = {f["name"] for f in contract_fields}
            return [f for f in suggested if f in valid][:max_count]

    if admin_cfg and authoritative:
        return []

    # Auto-detect
    ordered = []
    # name/title first
    name_fields = [f for f in contract_fields if f["name"] in ("name", "title")]
    ordered.extend(f["name"] for f in name_fields if f["name"] not in ordered)
    # date fields
    date_fields = [f for f in contract_fields if _is_date_field(f)]
    ordered.extend(f["name"] for f in date_fields if f["name"] not in ordered)
    # FK fields
    fk_fields = [f for f in contract_fields if _is_fk_field(f)]
    ordered.extend(f["name"] for f in fk_fields if f["name"] not in ordered)

    return ordered[:max_count]


def _promote_status(
    fields: list[str], status_field: str | None, valid_fields: set[str] | None = None
) -> list[str]:
    """Promote *status_field* to the front of *fields*, adding it if absent.

    When *valid_fields* is provided, *status_field* is only added or
    promoted if it exists within that set, preventing non-existent
    fields from being injected into generated admin code.
    """
    if not status_field:
        return fields
    if valid_fields is not None and status_field not in valid_fields:
        return fields
    without = [f for f in fields if f != status_field]
    return [status_field] + without


def _pick_filter_fields(
    view: dict[str, Any] | None,
    contract_fields: list[dict[str, Any]],
    admin_cfg: dict[str, Any] | None = None,
    max_count: int = 5,
    *,
    authoritative: bool = False,
    status_field: str | None = None,
) -> list[str]:
    """Pick ``list_filter`` fields.

    Priority:
    1. Contract ``admin.list_filter`` (if set, authoritative)
    2. Manifest suggested_filter_fields / status_field
    3. Auto-detect from status_field
    """
    if admin_cfg:
        explicit = admin_cfg.get("list_filter")
        if explicit:
            result = list(explicit)
            if status_field and status_field not in result:
                result.insert(0, status_field)
            return result

    if view:
        suggested = (
            view.get("suggested_filter_fields")
            or view.get("filterable_by")
            or view.get("status_field")
            and [view["status_field"]]
            or []
        )
        if suggested:
            valid = {f["name"] for f in contract_fields}
            result = [f for f in suggested if f in valid][:max_count]
            return _promote_status(result, status_field, valid_fields=valid)

    if admin_cfg and authoritative:
        return [status_field] if status_field else []

    return [status_field] if status_field else []


def _pick_search_fields(
    contract_fields: list[dict[str, Any]],
    fk_index_entry: list[dict[str, Any]] | None = None,
    admin_cfg: dict[str, Any] | None = None,
    *,
    authoritative: bool = False,
) -> list[str]:
    """Pick ``search_fields``.

    Priority:
    1. Contract ``admin.search_fields`` (if set, authoritative)
    2. Auto-detect from text fields and FK names
    """
    if admin_cfg:
        explicit = admin_cfg.get("search_fields")
        if explicit:
            return list(explicit)

    if admin_cfg and authoritative:
        return []

    fields: list[str] = []
    for f in contract_fields:
        if _is_text_field(f):
            fields.append(f["name"])
        elif _is_fk_field(f):
            fields.append(f"{f['name']}__name")
    return fields


def _pick_readonly_fields(
    view: dict[str, Any] | None,
    contract_fields: list[dict[str, Any]],
    admin_cfg: dict[str, Any] | None = None,
    *,
    authoritative: bool = False,
) -> list[str]:
    """Pick ``readonly_fields``.

    Priority:
    1. Contract ``admin.readonly_fields`` (if set, authoritative)
    2. Manifest readonly_fields / computed_fields
    3. Empty (auto-detect has no readonly defaults)
    """
    if admin_cfg:
        explicit = admin_cfg.get("readonly_fields")
        if explicit:
            return list(explicit)

    if view:
        readonly = view.get("readonly_fields") or view.get("computed_fields") or []
        if readonly:
            # Validate against contract field names: view-manifest slugs may
            # be derived from source column headers, not hardened model fields.
            valid_names = {f["name"] for f in contract_fields}
            filtered = [f for f in readonly if f in valid_names]
            return filtered

    if admin_cfg and authoritative:
        return []

    return []


def _inline_field_names(
    source_fields: list[dict[str, Any]],
    fk_field_name: str,
) -> list[str]:
    """Return field names for an inline, excluding the FK itself and non-editable fields."""

    def _is_editable(field: dict[str, Any]) -> bool:
        kwargs = field.get("kwargs", {})
        return not (kwargs.get("auto_now") or kwargs.get("auto_now_add"))

    return [
        f["name"]
        for f in source_fields
        if f["name"] != fk_field_name and _is_editable(f)
    ]


def _render_fk_link_method(
    field_name: str,
    target_model_name: str,
    app_label: str,
) -> str:
    """Render a ``{field_name}_link`` display method for FK admin columns.

    Generates a method that produces a clickable admin change link for the
    FK's related object, falling back to ``'-'`` when the FK is null.
    """
    target_snake = target_model_name.lower()
    lines = [
        f"    def {field_name}_link(self, obj):",
        f"        if obj.{field_name}_id:",
        f"            url = reverse('admin:{app_label}_{target_snake}_change', args=[obj.{field_name}_id])",
        f"            return format_html('<a href=\"{{}}\">{{}}</a>', url, obj.{field_name})",
        "        return '-'",
        f"    {field_name}_link.short_description = '{field_name.replace('_', ' ').title()}'",
    ]
    return "\n".join(lines)


def _is_integer_field(field: dict[str, Any]) -> bool:
    """Return ``True`` if *field* is an integer type."""
    short = _field_class_short(field["class"])
    return short in (
        "IntegerField",
        "PositiveIntegerField",
        "SmallIntegerField",
        "PositiveSmallIntegerField",
        "BigIntegerField",
        "PositiveBigIntegerField",
        "SmallAutoField",
        "AutoField",
        "BigAutoField",
    )


def _render_year_week_filter(
    year_field: str,
    week_field: str,
    model_name: str = "",
    contract_fields: list[dict[str, Any]] | None = None,
) -> str:
    """Render a SimpleListFilter subclass for year+week filtering.

    Uses a model-specific class name (e.g. ``TaskPlanYearWeekFilter``)
    to avoid collisions when multiple models define year+week filters.

    When *contract_fields* is provided, the year field type is detected
    to generate the correct ``lookups()`` implementation — integer fields
    use ``values_list()`` instead of ``datetimes()``.
    """
    suffix = model_name if model_name else ""
    class_name = f"{suffix}YearWeekFilter" if suffix else "YearWeekFilter"
    param_name = _to_snake_case(class_name) if suffix else "season"

    year_is_integer = False
    if contract_fields:
        for cf in contract_fields:
            if cf["name"] == year_field or cf["name"] == year_field.rstrip("__year"):
                if _is_integer_field(cf):
                    year_is_integer = True
                break

    if year_is_integer:
        lookup_lines = """        years = qs.values_list(base_year_field, flat=True).distinct().order_by(base_year_field)
        items = []
        for y in years:
            items.append((f"{y}", f"{y}"))
            for w in range(1, 54):
                items.append((f"{y}-W{w:02d}", f"Year {y} \u2014 Week {w}"))
        return items"""
    else:
        lookup_lines = """        years = qs.datetimes(base_year_field, 'year') if hasattr(qs, 'datetimes') else []
        items = []
        for y in years:
            items.append((f"{y.year}", f"{y.year}"))
            for w in range(1, 54):
                items.append((f"{y.year}-W{w:02d}", f"Year {y.year} \u2014 Week {w}"))
        return items"""

    return f"""
class {class_name}(admin.SimpleListFilter):
    title = "season"
    parameter_name = "{param_name}"

    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request)
        base_year_field = '{year_field}'.replace('__year', '') if '{year_field}'.endswith('__year') else '{year_field}'
{lookup_lines}

    def queryset(self, request, queryset):
        val = self.value()
        if not val:
            return queryset
        if "-W" in val:
            year_str, week_str = val.split("-W")
            return queryset.filter(**{{'{year_field}': int(year_str), '{week_field}': int(week_str)}})
        return queryset.filter(**{{'{year_field}': int(val)}})
"""


# -- rendering --------------------------------------------------------------


def _render_inline_class(
    source_name: str,
    source_fields: list[dict[str, Any]],
    fk_field_name: str,
    override_fields: list[str] | None = None,
    inline_fields: list[str] | None = None,
    inline_config: dict[str, Any] | None = None,
) -> str:
    """Render a ``TabularInline`` class for a reverse FK relationship.

    Args:
        source_name: Model name of the inline model.
        source_fields: Fields of the inline model.
        fk_field_name: FK field linking back to the parent model.
        override_fields: Optional explicit field list from ``admin.inlines``
            in the contract.  When set, use these instead of auto-picking.
        inline_fields: Optional explicit field list from the codegen manifest's
            ``workflow_hints.inline_fields``.  When set, all specified fields
            are shown (no auto-truncation).
        inline_config: Optional dict from the codegen manifest's
            ``workflow_hints.inline_config``.  Supported keys:
            - ``archetype`` (``"editable_grid"`` or ``"reference"``):
              ``"reference"`` makes all inline fields read-only.
            - ``show_change_link`` (bool): default ``True``.
            - ``can_delete`` (bool): default ``False``.
            - ``extra`` (int): default ``0``.
    """
    inline_name = f"{source_name}Inline"
    if inline_fields:
        display = inline_fields
    elif override_fields:
        display = override_fields
    else:
        display = _inline_field_names(source_fields, fk_field_name)
    if inline_fields:
        field_list = ", ".join(repr(f) for f in display)
    else:
        field_list = ", ".join(repr(f) for f in display[:6])

    icfg = inline_config or {}
    show_change_link = icfg.get("show_change_link", True)
    can_delete = icfg.get("can_delete", False)
    extra_rows = icfg.get("extra", 0)
    archetype = icfg.get("archetype", "editable_grid")

    lines = [
        "",
        f"class {inline_name}(admin.TabularInline):",
        f"    model = {source_name}",
        f"    extra = {extra_rows}",
        f"    show_change_link = {str(show_change_link)}",
    ]
    if can_delete:
        lines.append("    can_delete = True")
    if display:
        lines.append(f"    fields = [{field_list}]")
    if archetype == "reference" and display:
        lines.append(f"    readonly_fields = [{field_list}]")
    lines.append("")
    return "\n".join(lines)


def _render_admin_class(
    model_name: str,
    display_fields: list[str],
    filter_fields: Sequence[str | _ClassRef],
    search_fields: list[str],
    readonly_fields: list[str],
    list_editable_fields: list[str],
    autocomplete_fields_list: list[str],
    inline_classes: list[str],
    verbose_name: str | None,
    admin_base_class: str = "admin.ModelAdmin",
    status_field: str | None = None,
    link_methods: list[str] | None = None,
    time_scope: dict[str, Any] | None = None,
    status_values: list[str] | None = None,
    editable_fields: list[str] | None = None,
    status_transitions: Any = None,
    access_hints: dict[str, Any] | None = None,
    contract_fields: list[dict[str, Any]] | None = None,
    extra_display_fields: list[dict[str, Any]] | None = None,
    css_rules: list[dict[str, Any]] | None = None,
    custom_actions: list[dict[str, str]] | None = None,
    dashboard_config: dict[str, Any] | None = None,
    select_related_fk_fields: list[str] | None = None,
    ordering_fields: list[str] | None = None,
) -> str:
    """Render a ``ModelAdmin`` class with ``@admin.register``."""
    lines: list[str] = []

    if status_field:
        lines.append(f"# status_field: {status_field}")

    # YearWeekFilter class (if needed) must come before the admin class that references it
    year_week_filter_text = ""
    if time_scope and time_scope.get("year_field"):
        year_field = time_scope["year_field"]
        if year_field not in filter_fields:
            filter_fields = list(filter_fields) + [year_field]
        # Generate YearWeekFilter if week_field is also present.
        if time_scope.get("week_field"):
            week_field = time_scope["week_field"]
            year_week_filter_text = _render_year_week_filter(year_field, week_field, model_name, contract_fields)
            ywf_ref = _ClassRef(f"{model_name}YearWeekFilter")
            if ywf_ref not in filter_fields:
                filter_fields = list(filter_fields) + [ywf_ref]

    if year_week_filter_text:
        lines.append(year_week_filter_text)
        lines.append("")

    lines.extend(
        [
            "",
            f"@admin.register({model_name})",
            f"class {model_name}Admin({admin_base_class}):",
            "    save_on_top = True",
        ]
    )

    if display_fields:
        items = ", ".join(repr(f) for f in display_fields)
        lines.append(f"    list_display = [{items}]")

    # list_select_related for FK fields in list_display
    if select_related_fk_fields:
        items = ", ".join(repr(f) for f in select_related_fk_fields)
        lines.append(f"    list_select_related = [{items}]")

    # Explicit ordering from model_meta (avoids implicit model.Meta.ordering)
    if ordering_fields:
        items = ", ".join(repr(f) for f in ordering_fields)
        lines.append(f"    ordering = [{items}]")

    if link_methods:
        lines.append("")
        lines.extend(link_methods)

    if filter_fields:
        items = ", ".join(repr(f) for f in filter_fields)
        lines.append(f"    list_filter = [{items}]")

    if search_fields:
        items = ", ".join(repr(f) for f in search_fields)
        lines.append(f"    search_fields = [{items}]")

    # Extra computed display fields
    if extra_display_fields:
        lines.append("")
        for edf in extra_display_fields:
            name = edf["name"]
            description = edf.get("description", "")
            expression = edf.get("expression", "")
            boolean_flag = edf.get("boolean", False)
            if boolean_flag:
                lines.append(f"    @admin.display(description='{description}', boolean=True)")
            else:
                lines.append(f"    @admin.display(description='{description}')")
            lines.append(f"    def {name}(self, obj):")
            if "\n" in expression:
                # Multi-line expression: use directly (may include import + return)
                for expr_line in expression.split("\n"):
                    lines.append(f"        {expr_line}")
            else:
                lines.append(f"        return {expression}")
            lines.append("")

    if list_editable_fields:
        items = ", ".join(repr(f) for f in list_editable_fields)
        lines.append(f"    list_editable = [{items}]")

    if readonly_fields:
        items = ", ".join(repr(f) for f in readonly_fields)
        lines.append(f"    readonly_fields = [{items}]")

    # Expand '__all__' autocomplete to all FK fields in the contract
    if '__all__' in autocomplete_fields_list and contract_fields:
        fk_fields = [f['name'] for f in contract_fields if _is_fk_field(f)]
        autocomplete_fields_list = [f for f in fk_fields if f not in readonly_fields]

    if autocomplete_fields_list:
        items = ", ".join(repr(f) for f in autocomplete_fields_list)
        lines.append(f"    autocomplete_fields = [{items}]")

    if inline_classes:
        items = ", ".join(inline_classes)
        lines.append(f"    inlines = [{items}]")

    # date_hierarchy — prefer explicit time_scope.date_field, then
    # auto-detect the first DateField/DateTimeField from the contract.
    date_hierarchy_field: str | None = None
    if time_scope and time_scope.get("date_field"):
        date_hierarchy_field = str(time_scope["date_field"])
    elif contract_fields:
        for f in contract_fields:
            fclass = f.get("class", "")
            if fclass in ("models.DateField", "models.DateTimeField"):
                date_hierarchy_field = f["name"]
                break
    if date_hierarchy_field:
        lines.append(f"    date_hierarchy = '{date_hierarchy_field}'")

    # fields (change form) from editable_fields
    if editable_fields:
        items = ", ".join(repr(f) for f in editable_fields)
        lines.append(f"    fields = [{items}]")

    # get_queryset for current-season default filtering
    if time_scope and time_scope.get("year_field"):
        year_field = time_scope["year_field"]
        lines.extend(
            [
                "",
                "    def get_queryset(self, request):",
                "        qs = super().get_queryset(request)",
                f"        year = request.GET.get('{year_field}')",
                "        if not year:",
                f"            qs = qs.filter({year_field}=timezone.now().year)",
                "        return qs",
            ]
        )

    # get_queryset for role-based access restriction
    if access_hints:
        restricted_to = access_hints.get("restricted_to") or []
        if restricted_to:
            if len(restricted_to) == 1:
                role = restricted_to[0]
                lines.extend(
                    [
                        "",
                        "    def get_queryset(self, request):",
                        "        qs = super().get_queryset(request)",
                        f"        if not request.user.groups.filter(name='{role}').exists():",
                        "            return qs.none()",
                        "        return qs",
                    ]
                )
            else:
                roles_repr = ", ".join(repr(r) for r in restricted_to)
                lines.extend(
                    [
                        "",
                        "    def get_queryset(self, request):",
                        "        qs = super().get_queryset(request)",
                        f"        if not request.user.groups.filter(name__in=[{roles_repr}]).exists():",
                        "            return qs.none()",
                        "        return qs",
                    ]
                )

    # Row CSS class injection via get_changelist_instance override
    if css_rules:
        lines.append("")
        lines.append("    def get_changelist_instance(self, request):")
        lines.append("        cl = super().get_changelist_instance(request)")
        for rule in css_rules:
            condition = rule["condition"]  # Python expression
            css_class = rule["css_class"]
            lines.append("        for row in cl.result_list:")
            lines.append(f"            if {condition}:")
            lines.append(f"                row.css_class = '{css_class}'")
        lines.append("        return cl")

    # Admin action methods from status_values
    if status_values and status_field:
        # Build target_to_prior map from status_transitions if provided.
        # Each value is a single string (the next status), not a list.
        target_to_prior: dict[str, str] = {}
        if status_transitions:
            for prior_value, target_value in status_transitions.items():
                targets = target_value if isinstance(target_value, list) else [target_value]
                for tv in targets:
                    target_to_prior[str(tv)] = str(prior_value)

        action_names: list[str] = []
        for value in status_values:
            slugified = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
            method_name = f"mark_as_{slugified}"
            action_names.append(method_name)

            allowed_prior = target_to_prior.get(value)
            if allowed_prior:
                lines.extend(
                    [
                        "",
                        f"    @admin.action(description='Mark as {value}')",
                        f"    def {method_name}(self, request, queryset):",
                        f'        allowed_prior = "{allowed_prior}"',
                        f"        filtered = queryset.filter({status_field}=allowed_prior)",
                        f'        count = filtered.update({status_field}="{value}")',
                        f'        self.message_user(request, f"{{count}} updated to {value}")',
                        "        skipped = queryset.count() - count",
                        "        if skipped:",
                        f'            self.message_user(request, f"{{skipped}} skipped \\u2014 can only transition from \'{allowed_prior}\'", level="WARNING")',
                    ]
                )
            else:
                lines.extend(
                    [
                        "",
                        f"    @admin.action(description='Mark as {value}')",
                        f"    def {method_name}(self, request, queryset):",
                        f'        queryset.update({status_field}="{value}")',
                    ]
                )
        if action_names:
            items = ", ".join(action_names)
            lines.append(f"    actions = [{items}]")

    # Custom bulk actions from codegen manifest workflow_hints.actions
    if custom_actions:
        custom_action_names: list[str] = []
        for action_def in custom_actions:
            action_name = action_def.get("name", "")
            description = action_def.get("description", "")
            expression = action_def.get("expression", "")
            if not action_name:
                continue
            custom_action_names.append(action_name)
            lines.extend(
                [
                    "",
                    f"    @admin.action(description='{description}')",
                    f"    def {action_name}(self, request, queryset):",
                ]
            )
            if "\n" in expression:
                for expr_line in expression.split("\n"):
                    lines.append(f"        {expr_line}")
            else:
                lines.append(f"        {expression}")
        if custom_action_names:
            items = ", ".join(custom_action_names)
            lines.append(f"    actions = [{items}]")

    # Permission override methods from access_hints.permissions.
    _access_permissions: dict[str, Any] | None = None
    if access_hints:
        _access_permissions = access_hints.get("permissions")
    if _access_permissions:
        _owner_role_pascal = _to_pascal_case(
            _access_permissions.get("owner_role", "")
        )
        _reviewer_roles_pascal = [
            _to_pascal_case(r)
            for r in (_access_permissions.get("reviewer_roles") or [])
        ]
        _all_roles = [_owner_role_pascal] + [
            r for r in _reviewer_roles_pascal if r != _owner_role_pascal
        ]

        lines.append("")
        lines.append("    def has_change_permission(self, request, obj=None):")
        lines.append("        if request.user.is_superuser:")
        lines.append("            return True")
        lines.append(
            f"        return request.user.groups.filter(name__in=[{', '.join(repr(r) for r in [_owner_role_pascal])}]).exists()"
        )

        lines.append("")
        lines.append("    def has_view_permission(self, request, obj=None):")
        lines.append("        if request.user.is_superuser:")
        lines.append("            return True")
        lines.append(
            f"        return request.user.groups.filter(name__in=[{', '.join(repr(r) for r in _all_roles)}]).exists()"
        )

        lines.append("")
        lines.append("    def has_add_permission(self, request, obj=None):")
        lines.append("        if request.user.is_superuser:")
        lines.append("            return True")
        lines.append(
            f"        return request.user.groups.filter(name__in=[{', '.join(repr(r) for r in [_owner_role_pascal])}]).exists()"
        )

        lines.append("")
        lines.append("    def has_delete_permission(self, request, obj=None):")
        lines.append("        if request.user.is_superuser:")
        lines.append("            return True")
        lines.append(
            f"        return request.user.groups.filter(name__in=[{', '.join(repr(r) for r in [_owner_role_pascal])}]).exists()"
        )

    # Dashboard summary cards — changelist_view override
    if dashboard_config:
        summary_cards = dashboard_config.get("summary_cards") or []
        if summary_cards:
            lines.append("")
            lines.append("    change_list_template = \"admin/workbench_dashboard/change_list.html\"")
            lines.append("")
            lines.append("    def changelist_view(self, request, extra_context=None):")
            lines.append("        from django.db import models as db_models")
            lines.append("        response = super().changelist_view(request, extra_context)")
            lines.append("        try:")
            lines.append("            qs = response.context_data[\"cl\"].queryset")
            lines.append("        except (AttributeError, KeyError):")
            lines.append("            return response")
            lines.append("        cards = []")
            for card in summary_cards:
                label = card.get("label", "")
                color = card.get("color", "#e0e0e0")
                expression = card.get("expression", "qs.count()")
                lines.append(f"        cards.append({{")
                lines.append(f'            "label": "{label}",')
                lines.append(f'            "color": "{color}",')
                lines.append(f'            "value": {expression},')
                lines.append(f"        }})")
            lines.append('        response.context_data["dashboard_cards"] = cards')
            lines.append("        return response")

    if all(
        not x
        for x in [
            display_fields,
            filter_fields,
            search_fields,
            readonly_fields,
            list_editable_fields,
            autocomplete_fields_list,
            inline_classes,
        ]
    ):
        has_new_content = (
            (time_scope and time_scope.get("date_field"))
            or (time_scope and time_scope.get("year_field"))
            or (status_values and status_field)
            or editable_fields
            or _access_permissions
            or dashboard_config
        )
        if not has_new_content:
            lines.append("    pass")

    lines.append("")
    return "\n".join(lines)


def _render_ensure_groups(
    model_name: str,
    owner_role: str,
    reviewer_roles: list[str],
) -> str:
    """Render a ``_ensure_groups()`` function for a model with permissions.

    Args:
        model_name: PascalCase model name (e.g. ``CropPlan``).
        owner_role: Snake_case owner role name (e.g. ``field_manager``).
        reviewer_roles: List of snake_case reviewer role names.

    Returns:
        Python source for the ``_ensure_groups`` function.
    """
    model_snake = _to_snake_case(model_name)
    owner_group_pascal = _to_pascal_case(owner_role)
    owner_codenames = [
        f"change_{model_snake}",
        f"view_{model_snake}",
        f"add_{model_snake}",
        f"delete_{model_snake}",
    ]
    lines = [
        "",
        "",
        "# Generated — run once via ``_ensure_groups()`` or management command",
        f"def _ensure_{model_snake}_groups():",
        "    from django.contrib.auth.models import Group, Permission",
        "    from django.contrib.contenttypes.models import ContentType",
        f"    content_type = ContentType.objects.get_for_model({model_name})",
        "",
        f'    owner_group, _ = Group.objects.get_or_create(name="{owner_group_pascal}")',
        "    for codename in [",
    ]
    for cn in owner_codenames:
        lines.append(f'            "{cn}",')
    lines.append("        ]:")
    lines.append("        perm, _ = Permission.objects.get_or_create(")
    lines.append("            codename=codename, content_type=content_type,")
    lines.append("        )")
    lines.append("        owner_group.permissions.add(perm)")
    lines.append("")
    for reviewer_role in reviewer_roles:
        reviewer_pascal = _to_pascal_case(reviewer_role)
        lines.append(
            f'    group, _ = Group.objects.get_or_create(name="{reviewer_pascal}")'
        )
        lines.append(
            f'    view_perm = Permission.objects.get('
        )
        lines.append(
            f'        codename="view_{model_snake}", content_type=content_type,'
        )
        lines.append("    )")
        lines.append("    group.permissions.add(view_perm)")
        lines.append("")
    return "\n".join(lines)


def _render_header(app_label: str) -> str:
    """Render the file-level header comment."""
    return (
        "# Generated by migration-workbench codegen \u2014 hand-editable\n"
        f"# App label: {app_label}\n"
        "# Last generated: see git history\n"
    )


def _render_imports(
    tables: list[dict[str, Any]],
    *,
    needs_user_admin: bool,
    needs_fk_links: bool = False,
    needs_timezone: bool = False,
) -> str:
    """Render the ``import`` block."""
    model_names = sorted({get_model_name(t) for t in tables})
    imports = ", ".join(model_names)
    lines = ["from django.contrib import admin"]
    if needs_fk_links:
        lines.append("from django.urls import reverse")
        lines.append("from django.utils.html import format_html")
    if needs_user_admin:
        lines.append("from django.contrib.auth.admin import UserAdmin as BaseUserAdmin")
    if needs_timezone:
        lines.append("from django.utils import timezone")
    lines.append(f"from .models import {imports}")
    return "\n".join(lines) + "\n"


def _index_codegen_manifest(
    codegen_manifest: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Index a codegen manifest by ``model_name`` for quick lookup.

    Args:
        codegen_manifest: Parsed codegen-manifest dict, or ``None``.

    Returns:
        Dict mapping model_name to its table entry. Empty when *codegen_manifest*
        is ``None`` or has no ``tables``.
    """
    index: dict[str, dict[str, Any]] = {}
    if not codegen_manifest:
        return index
    for table in codegen_manifest.get("tables") or []:
        mname = str(table.get("model_name") or "")
        if mname:
            index[mname] = table
    return index


def _pick_computed_display_fields(
    codegen_entry: dict[str, Any] | None,
    contract_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract computed display field definitions from codegen manifest."""
    if not codegen_entry:
        return []
    hints = codegen_entry.get("workflow_hints") or {}
    return hints.get("computed_fields") or []


def extract_custom_sections(source: str) -> list[str]:
    """Extract all lines below the custom-models marker.

    Parses *source* looking for the marker line defined in
    ``workbook.codegen.stub_writer.MARKER`` and returns every line
    that follows it (the hand-written custom section).

    Returns:
        Empty list when the marker is not found.
    """
    lines = source.splitlines(keepends=True)
    marker_found = False
    custom: list[str] = []
    for line in lines:
        if line.strip() == MARKER.strip():
            marker_found = True
            custom.append(line)
        elif marker_found:
            custom.append(line)
    return custom


def render_admin_py(
    contract: dict[str, Any],
    manifest: dict[str, Any] | None,
    app_label: str = "core",
    codegen_manifest: dict[str, Any] | None = None,
    existing_source: str | None = None,
) -> str:
    """Render a complete ``admin.py`` file from a contract and optional manifest.

    Args:
        contract: Normalised schema-contract dict (v1.0 or v1.1).
        manifest: Optional normalised view-manifest dict.  When ``None``,
            admin classes are generated from contract data alone (no
            ``list_display``, ``list_filter``, etc. inference from the
            manifest).
        app_label: Django app label for header comments.
        codegen_manifest: Optional codegen-manifest dict (Layer 3). When
            provided, archetype-based ``list_editable``, status transition
            actions from ``workflow_hints.status_transitions``, role hints,
            and workflow notes enrich the generated admin.
        existing_source: Optional source text from a previously-generated
            ``admin.py``.  When provided, any hand-written custom sections
            below the marker line (``# --- custom models below this line ---``)
            are preserved and appended after the newly generated content.

    Returns:
        Complete ``admin.py`` source text.
    """
    tables = list(contract.get("tables") or [])

    # Build codegen manifest index keyed by model_name.
    codegen_index = _index_codegen_manifest(codegen_manifest)

    # Pass 1: build FK reverse index for inline detection.
    fk_index = _build_fk_index(tables)

    if not tables:
        return _render_header(app_label) + "from django.contrib import admin\n" + "\n"

    needs_user_admin = any(_is_abstract_user_model(t) for t in tables)
    # Pre-scan for FK fields that need link methods (two-pass for imports).
    needs_fk_links = any(
        _is_fk_field(f)
        and f["kwargs"].get("to", "")
        and isinstance(f["kwargs"].get("to", ""), str)
        and f["kwargs"]["to"] != "self"
        for t in tables
        for f in get_fields(t)
    )

    # Determine if any view uses time_scope with year_field (needs timezone import).
    needs_timezone = False
    if manifest:
        for table in tables:
            raw_entity = _to_snake_case(get_model_name(table))
            view = find_view_for_entity(manifest, raw_entity)
            if view:
                ts = view.get("time_scope") or {}
                if ts.get("year_field"):
                    needs_timezone = True
                    break

    parts: list[str] = [
        _render_header(app_label),
        _render_imports(
            tables,
            needs_user_admin=needs_user_admin,
            needs_fk_links=needs_fk_links,
            needs_timezone=needs_timezone,
        ),
    ]

    # Workflow graph comment: tab_sequence from codegen manifest.
    if codegen_manifest:
        workflow_graph = codegen_manifest.get("workflow_graph") or {}
        tab_sequence = workflow_graph.get("tab_sequence") or []
        if tab_sequence:
            seq_comment = (
                "# Workflow dependency graph — tab sequence:\n"
                + "\n".join(
                    f"#   {idx + 1}. {tab_name}"
                    for idx, tab_name in enumerate(tab_sequence)
                )
                + "\n#\n"
            )
            if workflow_graph.get("has_cycles"):
                seq_comment += "#   ⚠ Cycle detected in dependency graph\n"
            parts.append(seq_comment)

    # Collect all inline classes (must be defined before admin classes).
    inline_class_defs: list[str] = []
    inline_class_names: set[str] = set()  # Track which inline classes we've already emitted.
    ensure_groups_defs: list[str] = []  # _ensure_*_groups() functions for permission-based access.
    admin_class_parts: list[str] = []

    for table in tables:
        model_name = get_model_name(table)
        contract_fields = get_fields(table)
        # View manifest entities are stored as snake_case (derived from model_name).
        raw_entity = _to_snake_case(get_model_name(table))
        view = find_view_for_entity(manifest, raw_entity) if manifest else None
        meta = get_model_meta(table)
        verbose_name = meta.get("verbose_name")
        model_ordering: list[str] | None = meta.get("ordering")
        admin_cfg = get_admin_config(table)

        # Codegen manifest entry for this model (may be None).
        # Try contract model_name first, then fall back to source_tab for
        # manifests that haven't been regenerated with entity->PascalCase names.
        codegen_entry = codegen_index.get(model_name)
        if codegen_entry is None and view is not None:
            source_tab: str | None = view.get("source_tab")
            if source_tab:
                codegen_entry = codegen_index.get(source_tab)

        # _ensure_groups() for permission-based access control.
        if codegen_entry:
            cg_access_hints = codegen_entry.get("access_hints") or {}
            cg_permissions = cg_access_hints.get("permissions")
            if cg_permissions:
                ensure_groups_defs.append(
                    _render_ensure_groups(
                        model_name=model_name,
                        owner_role=str(
                            cg_permissions.get("owner_role", "")
                        ),
                        reviewer_roles=list(
                            cg_permissions.get("reviewer_roles") or []
                        ),
                    )
                )

        # Inline classes for *this* model's reverse FK relationships.
        # admin.inlines can override default field lists per inline source.
        inline_overrides = admin_cfg.get("inlines") or {}
        rev_fks = fk_index.get(model_name) or []
        inline_names: list[str] = []
        for ref in rev_fks:
            ref_table = next(
                t for t in tables if get_model_name(t) == ref["source_name"]
            )
            source_fields = get_fields(ref_table)
            ref_entity = _to_snake_case(get_model_name(ref_table))
            override_fields = inline_overrides.get(ref_entity)
            inline_name = f"{ref['source_name']}Inline"
            if inline_name not in inline_class_names:
                inline_class_names.add(inline_name)
                # Check codegen manifest for inline configuration on the child model.
                child_codegen = codegen_index.get(ref["source_name"])
                child_inline_fields: list[str] | None = None
                child_inline_config: dict[str, Any] | None = None
                if child_codegen:
                    child_hints = child_codegen.get("workflow_hints") or {}
                    child_inline_fields = child_hints.get("inline_fields")
                    child_inline_config = child_hints.get("inline_config")
                inline_class_defs.append(
                    _render_inline_class(
                        ref["source_name"],
                        source_fields,
                        ref["field_name"],
                        override_fields=override_fields,
                        inline_fields=child_inline_fields,
                        inline_config=child_inline_config,
                    )
                )
            inline_names.append(inline_name)

        # Auto-generate FK reverse count fields for list_display.
        # For each child model that FK's to this model, add a count
        # method (e.g. "planting_plan_count → obj.planting_plans.count()")
        # unless the codegen manifest already provides it.
        auto_count_fields: list[dict[str, Any]] = []
        existing_computed = {
            f["name"]
            for f in (_pick_computed_display_fields(codegen_entry, contract_fields))
        }
        for ref in rev_fks:
            ref_table = next(
                t for t in tables if get_model_name(t) == ref["source_name"]
            )
            child_fk = next(
                (f for f in get_fields(ref_table) if f["name"] == ref["field_name"]),
                None,
            )
            rel_name = (
                child_fk["kwargs"].get("related_name") if child_fk else None
            )
            if not rel_name:
                rel_name = f"{_to_snake_case(ref['source_name'])}_set"
            count_name = f"{_to_snake_case(ref['source_name'])}_count"
            if count_name not in existing_computed:
                auto_count_fields.append({
                    "name": count_name,
                    "description": " ".join(
                        w.capitalize() for w in _to_snake_case(ref["source_name"]).split("_")
                    ),
                    "expression": f"obj.{rel_name}.count()",
                    "boolean": False,
                })

        # Admin class for this model.
        is_user = _is_abstract_user_model(table)
        is_authoritative = bool(admin_cfg) or is_user
        status_field = (view.get("status_field") or None) if view else None
        time_scope = view.get("time_scope") if view else None
        status_values = view.get("status_values") if view else None
        # If status_values not in view manifest, derive from contract enums.
        # The contract's status field has a "choices" key referencing an enum
        # name in the top-level "enums" section.
        if status_values is None and status_field is not None:
            for field in contract_fields:
                if field["name"] == status_field:
                    choices_ref = field.get("kwargs", {}).get("choices")
                    if choices_ref and isinstance(choices_ref, str):
                        contract_enums = contract.get("enums", {})
                        enum_values = contract_enums.get(choices_ref)
                        if enum_values:
                            status_values = [v[0] for v in enum_values]
                    break
        editable_fields = view.get("editable_fields") if view else None
        # Validate editable_fields against contract field names.
        # View-manifest slugs may be derived from source column headers, not
        # necessarily matching the hardened model's field names.
        if editable_fields:
            valid_names = {f["name"] for f in contract_fields}
            filtered = [f for f in editable_fields if f in valid_names]
            # Only pass filtered editable_fields to _render_admin_class.
            fields_to_pass = filtered if filtered else None
        else:
            fields_to_pass = None
        display = _pick_display_fields(
            view, contract_fields, admin_cfg, authoritative=is_authoritative
        )
        filters = _pick_filter_fields(
            view,
            contract_fields,
            admin_cfg,
            authoritative=is_authoritative,
            status_field=status_field,
        )
        search = _pick_search_fields(
            contract_fields, rev_fks, admin_cfg, authoritative=is_authoritative
        )
        readonly = _pick_readonly_fields(
            view, contract_fields, admin_cfg, authoritative=is_authoritative
        )

        list_editable = list(admin_cfg.get("list_editable") or [])
        if list_editable:
            valid = {f["name"] for f in contract_fields}
            list_editable = [f for f in list_editable if f in valid]

        # Codegen manifest overrides: archetype-based list_editable.
        if codegen_entry and not list_editable:
            cg_hints = codegen_entry.get("workflow_hints") or {}
            archetype = str(codegen_entry.get("ui_archetype") or "list")
            if archetype == "form" and editable_fields:
                # Form archetype: make all editable fields list_editable.
                # Exclude FK fields — list_editable on FK risks silent
                # data corruption via changelist dropdown edits.
                valid_names = {f["name"] for f in contract_fields}
                fk_field_names = {f["name"] for f in contract_fields if _is_fk_field(f)}
                list_editable = [
                    f for f in editable_fields
                    if f in valid_names and f not in fk_field_names
                ]
            elif archetype in ("dashboard", "reference"):
                # Dashboard/reference: all fields become readonly.
                all_field_names = [f["name"] for f in contract_fields]
                for fn in all_field_names:
                    if fn not in readonly:
                        readonly = list(readonly) + [fn]
            elif archetype == "list" and not list_editable:
                # List archetype auto-detection: put boolean fields into
                # list_editable for convenient inline toggling.
                valid_names = {f["name"] for f in contract_fields}
                fk_field_names = {f["name"] for f in contract_fields if _is_fk_field(f)}
                for field in contract_fields:
                    fname = field["name"]
                    fclass = field.get("class", "")
                    if fclass == "models.BooleanField" and fname in valid_names and fname not in fk_field_names:
                        if fname not in list_editable:
                            list_editable = list(list_editable) + [fname]
                if status_field and status_field in valid_names and status_field not in list_editable:
                    list_editable = list(list_editable) + [status_field]

        # Codegen manifest: status transitions → admin actions.
        cg_status_transitions = None
        if codegen_entry:
            cg_hints = codegen_entry.get("workflow_hints") or {}
            cg_status_transitions = cg_hints.get("status_transitions")

        # Codegen manifest: css_rules for conditional row highlighting.
        cg_css_rules = None
        if codegen_entry:
            cg_hints = codegen_entry.get("workflow_hints") or {}
            cg_css_rules = cg_hints.get("css_rules")

        # Use codegen manifest status_field if view manifest doesn't have one.
        if codegen_entry and not status_field:
            cg_hints = codegen_entry.get("workflow_hints") or {}
            cg_sf = cg_hints.get("status_field")
            if cg_sf:
                status_field = str(cg_sf)

        # Generate default status_transitions when status_values exist but
        # the codegen manifest provides no transition rules.  Terminal-like
        # values ('done', 'skipped', 'cancelled') are mapped from a plausible
        # prior like 'open', 'todo', or the first status value.
        # Use a list-valued dict so multiple terminal values (e.g. "done" and
        # "skipped") can share the same prior ("open") without overwriting.
        if cg_status_transitions is None and status_values and status_field:
            _terminal_prefixes = ("done", "skipped", "cancelled", "completed", "finished", "closed", "archived")
            _default_transitions: dict[str, list[str]] = {}
            for sv in status_values:
                sv_lower = sv.lower()
                if any(sv_lower == p or sv_lower.endswith(p) for p in _terminal_prefixes):
                    for candidate in ("open", "todo", str(status_values[0])):
                        if candidate != sv and candidate in status_values:
                            _default_transitions.setdefault(str(candidate), []).append(str(sv))
                            break
            if _default_transitions:
                cg_status_transitions = _default_transitions

        # Build status_values from status_transitions if present.
        codegen_status_values: list[str] | None = None
        if cg_status_transitions:
            codegen_status_values = list(cg_status_transitions.keys())
            # Also include transition targets (value may be str or list[str]).
            for target in cg_status_transitions.values():
                targets = target if isinstance(target, list) else [target]
                for t in targets:
                    if t not in codegen_status_values:
                        codegen_status_values.append(t)
            # If status_values from view manifest is richer, prefer it.
            if status_values:
                codegen_status_values = status_values

        autocomplete = admin_cfg.get("autocomplete_fields") or []
        if autocomplete:
            valid = {f["name"] for f in contract_fields if _is_fk_field(f)}
            # Preserve '__all__' sentinel; it will be expanded later.
            autocomplete = [f for f in autocomplete if f in valid or f == '__all__']

        # Exclude readonly fields from autocomplete to avoid dead config
        # (readonly_fields takes precedence over autocomplete_fields).
        if readonly:
            autocomplete = [f for f in autocomplete if f not in readonly]

        # FK link display methods — generate _link methods and swap into list_display.
        # Also collect FK field names for list_select_related (N+1 prevention).
        link_methods: list[str] = []
        select_related_fk_fields: list[str] = []
        for field in contract_fields:
            if _is_fk_field(field):
                target = field["kwargs"].get("to", "")
                if target and isinstance(target, str) and target != "self":
                    if field["name"] in display:
                        select_related_fk_fields.append(field["name"])
                        link_methods.append(
                            _render_fk_link_method(field["name"], target, app_label)
                        )
                        display = [
                            f"{fn}_link" if fn == field["name"] else fn
                            for fn in display
                        ]
                        needs_fk_links = True

        computed_fields = _pick_computed_display_fields(codegen_entry, contract_fields)
        # Merge auto-generated FK reverse count fields.
        # These are appended AFTER manifest computed_fields so manifest wins
        # for same-named entries (auto generation skips duplicates above).
        extra_display_fields = list(computed_fields) + auto_count_fields
        # Merge computed display field names into list_display so they appear
        # as columns in the changelist view alongside their generated methods.
        if extra_display_fields:
            computed_names = [f["name"] for f in extra_display_fields if "name" in f]
            # De-duplicate while preserving insertion order (Python 3.7+).
            display = list(dict.fromkeys(display + computed_names))

        # Codegen manifest: custom bulk actions → admin action methods.
        cg_custom_actions: list[dict[str, str]] = []
        if codegen_entry:
            cg_hints = codegen_entry.get("workflow_hints") or {}
            cg_custom_actions = cg_hints.get("actions") or []

        # Dashboard config from codegen manifest: summary cards + changelist_view override.
        cg_dashboard_config: dict[str, Any] | None = None
        if codegen_entry:
            cg_hints = codegen_entry.get("workflow_hints") or {}
            archetype = str(codegen_entry.get("ui_archetype") or "list")
            if archetype == "dashboard":
                raw_dashboard = cg_hints.get("dashboard") or {}
                if raw_dashboard.get("summary_cards"):
                    cg_dashboard_config = raw_dashboard

        admin_class_parts.append(
            _render_admin_class(
                model_name=model_name,
                display_fields=display,
                filter_fields=filters,
                search_fields=search,
                readonly_fields=readonly,
                list_editable_fields=list_editable,
                autocomplete_fields_list=autocomplete,
                inline_classes=inline_names,
                verbose_name=verbose_name,
                admin_base_class="BaseUserAdmin" if is_user else "admin.ModelAdmin",
                status_field=status_field,
                link_methods=link_methods,
                time_scope=time_scope,
                status_values=codegen_status_values or status_values,
                editable_fields=fields_to_pass,
                status_transitions=cg_status_transitions,
                access_hints=codegen_entry.get("access_hints")
                if codegen_entry
                else None,
                contract_fields=contract_fields,
                extra_display_fields=extra_display_fields,
                css_rules=cg_css_rules,
                custom_actions=cg_custom_actions,
                dashboard_config=cg_dashboard_config,
                select_related_fk_fields=select_related_fk_fields,
                ordering_fields=model_ordering,
            )
        )

    parts.extend(inline_class_defs)
    parts.extend(ensure_groups_defs)
    parts.extend(admin_class_parts)
    parts.append("")
    result = "\n".join(parts)

    # Preserve hand-written custom sections from the existing file.
    if existing_source is not None:
        custom_sections = extract_custom_sections(existing_source)
        if custom_sections:
            result += "\n" + "".join(custom_sections)

    return result
