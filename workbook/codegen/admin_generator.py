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

from typing import Any

from workbook.codegen.contract import (
    get_admin_config,
    get_fields,
    get_model_base,
    get_model_meta,
    get_model_name,
)
from workbook.codegen.manifest import find_view_for_entity


# -- helpers ----------------------------------------------------------------

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

    Preference order:
    1. ``admin.list_display`` from the contract.
    2. ``editable_fields`` from the view manifest (up to *max_count*).
    3. First non-id field from the contract if no match.
    """
    valid = {f["name"] for f in contract_fields}
    if admin_cfg:
        raw = admin_cfg.get("list_display")
        if raw and isinstance(raw, list):
            return raw[:max_count] if authoritative else [f for f in raw if f in valid][:max_count]
    if view:
        editable = view.get("editable_fields") or []
        if authoritative:
            return editable[:max_count]
        return [f for f in editable if f in valid][:max_count]
    if contract_fields:
        return [contract_fields[0]["name"]]
    return []


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
    *,
    authoritative: bool = False,
    status_field: str | None = None,
) -> list[str]:
    """Pick ``list_filter`` fields.

    Preference order:
    1. ``admin.list_filter`` from the contract.
    2. ``filterable_by`` from the view manifest.
    3. Date fields from the contract.

    When *status_field* is set and present in the result, it is promoted
    to the front of the list so status-based filtering is immediately
    accessible in the admin changelist.
    """
    valid = {f["name"] for f in contract_fields}
    if admin_cfg:
        raw = admin_cfg.get("list_filter")
        if raw and isinstance(raw, list):
            result = raw if authoritative else [f for f in raw if f in valid]
            return _promote_status(result, status_field, valid_fields=valid)
    if view:
        fb = view.get("filterable_by") or []
        if authoritative:
            result = fb
        else:
            result = [f for f in fb if f in valid]
        return _promote_status(result, status_field, valid_fields=valid)
    result = [f["name"] for f in contract_fields if _is_date_field(f)]
    return _promote_status(result, status_field, valid_fields=valid)


def _pick_search_fields(
    contract_fields: list[dict[str, Any]],
    fk_index_entry: list[dict[str, Any]] | None = None,
    admin_cfg: dict[str, Any] | None = None,
    *,
    authoritative: bool = False,
) -> list[str]:
    """Pick ``search_fields``.

    Preference order:
    1. ``admin.search_fields`` from the contract.
    2. Text-type fields and FK names.
    """
    valid = {f["name"] for f in contract_fields}
    if admin_cfg:
        raw = admin_cfg.get("search_fields")
        if raw and isinstance(raw, list):
            return raw if authoritative else [f for f in raw if f in valid]
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

    Preference order:
    1. ``admin.readonly_fields`` from the contract.
    2. ``computed_fields`` from the view manifest.
    """
    valid = {f["name"] for f in contract_fields}
    if admin_cfg:
        raw = admin_cfg.get("readonly_fields")
        if raw and isinstance(raw, list):
            return raw if authoritative else [f for f in raw if f in valid]
    if not view:
        return []
    computed = view.get("computed_fields") or []
    if authoritative:
        return computed
    return [f for f in computed if f in valid]


def _inline_field_names(
    source_fields: list[dict[str, Any]],
    fk_field_name: str,
) -> list[str]:
    """Return field names for an inline, excluding the FK itself."""
    return [f["name"] for f in source_fields if f["name"] != fk_field_name]


# -- rendering --------------------------------------------------------------


def _render_inline_class(
    source_name: str,
    source_fields: list[dict[str, Any]],
    fk_field_name: str,
    override_fields: list[str] | None = None,
) -> str:
    """Render a ``TabularInline`` class for a reverse FK relationship.

    Args:
        source_name: Model name of the inline model.
        source_fields: Fields of the inline model.
        fk_field_name: FK field linking back to the parent model.
        override_fields: Optional explicit field list from ``admin.inlines``
            in the contract.  When set, use these instead of auto-picking.
    """
    inline_name = f"{source_name}Inline"
    if override_fields:
        display = override_fields
    else:
        display = _inline_field_names(source_fields, fk_field_name)
    field_list = ", ".join(repr(f) for f in display[:6])

    lines = [
        "",
        f"class {inline_name}(admin.TabularInline):",
        f"    model = {source_name}",
        "    extra = 0",
    ]
    if display:
        lines.append(f"    fields = [{field_list}]")
    lines.append("")
    return "\n".join(lines)


def _render_admin_class(
    model_name: str,
    display_fields: list[str],
    filter_fields: list[str],
    search_fields: list[str],
    readonly_fields: list[str],
    list_editable_fields: list[str],
    autocomplete_fields_list: list[str],
    inline_classes: list[str],
    verbose_name: str | None,
    admin_base_class: str = "admin.ModelAdmin",
    status_field: str | None = None,
) -> str:
    """Render a ``ModelAdmin`` class with ``@admin.register``."""
    lines: list[str] = []

    if status_field:
        lines.append(f"# status_field: {status_field}")

    lines.extend([
        "",
        f"@admin.register({model_name})",
        f"class {model_name}Admin({admin_base_class}):",
    ])

    if display_fields:
        items = ", ".join(repr(f) for f in display_fields)
        lines.append(f"    list_display = [{items}]")

    if filter_fields:
        items = ", ".join(repr(f) for f in filter_fields)
        lines.append(f"    list_filter = [{items}]")

    if search_fields:
        items = ", ".join(repr(f) for f in search_fields)
        lines.append(f"    search_fields = [{items}]")

    if list_editable_fields:
        items = ", ".join(repr(f) for f in list_editable_fields)
        lines.append(f"    list_editable = [{items}]")

    if readonly_fields:
        items = ", ".join(repr(f) for f in readonly_fields)
        lines.append(f"    readonly_fields = [{items}]")

    if autocomplete_fields_list:
        items = ", ".join(repr(f) for f in autocomplete_fields_list)
        lines.append(f"    autocomplete_fields = [{items}]")

    if inline_classes:
        items = ", ".join(inline_classes)
        lines.append(f"    inlines = [{items}]")

    if all(
        not x
        for x in [display_fields, filter_fields, search_fields, readonly_fields, list_editable_fields, autocomplete_fields_list, inline_classes]
    ):
        lines.append("    pass")

    lines.append("")
    return "\n".join(lines)


def _render_header(app_label: str) -> str:
    """Render the file-level header comment."""
    return (
        "# Generated by migration-workbench codegen \u2014 hand-editable\n"
        f"# App label: {app_label}\n"
        "# Last generated: see git history\n"
    )


def _render_imports(tables: list[dict[str, Any]], *, needs_user_admin: bool) -> str:
    """Render the ``import`` block."""
    model_names = sorted({get_model_name(t) for t in tables})
    imports = ", ".join(model_names)
    lines = ["from django.contrib import admin"]
    if needs_user_admin:
        lines.append("from django.contrib.auth.admin import UserAdmin as BaseUserAdmin")
    lines.append(f"from .models import {imports}")
    return "\n".join(lines) + "\n"


def render_admin_py(
    contract: dict[str, Any],
    manifest: dict[str, Any] | None,
    app_label: str = "core",
) -> str:
    """Render a complete ``admin.py`` file from a contract and optional manifest.

    Args:
        contract: Normalised schema-contract dict (v1.0 or v1.1).
        manifest: Optional normalised view-manifest dict.  When ``None``,
            admin classes are generated from contract data alone (no
            ``list_display``, ``list_filter``, etc. inference from the
            manifest).
        app_label: Django app label for header comments.

    Returns:
        Complete ``admin.py`` source text.
    """
    tables = list(contract.get("tables") or [])

    # Pass 1: build FK reverse index for inline detection.
    fk_index = _build_fk_index(tables)

    if not tables:
        return _render_header(app_label) + "from django.contrib import admin\n" + "\n"

    needs_user_admin = any(_is_abstract_user_model(t) for t in tables)

    parts: list[str] = [
        _render_header(app_label),
        _render_imports(tables, needs_user_admin=needs_user_admin),
    ]

    # Collect all inline classes (must be defined before admin classes).
    inline_class_defs: list[str] = []
    admin_class_parts: list[str] = []

    for table in tables:
        model_name = get_model_name(table)
        contract_fields = get_fields(table)
        # View manifest entities are stored as suggested_model_name (lowercase).
        raw_entity = str(table.get("suggested_model_name") or "").lower()
        view = find_view_for_entity(manifest, raw_entity) if manifest else None
        meta = get_model_meta(table)
        verbose_name = meta.get("verbose_name")
        admin_cfg = get_admin_config(table)

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
            ref_entity = str(ref_table.get("suggested_model_name") or "").lower()
            override_fields = inline_overrides.get(ref_entity)
            inline_class_defs.append(
                _render_inline_class(
                    ref["source_name"],
                    source_fields,
                    ref["field_name"],
                    override_fields=override_fields,
                )
            )
            inline_names.append(f"{ref['source_name']}Inline")

        # Admin class for this model.
        is_user = _is_abstract_user_model(table)
        status_field = (view.get("status_field") or None) if view else None
        display = _pick_display_fields(view, contract_fields, admin_cfg, authoritative=is_user)
        filters = _pick_filter_fields(view, contract_fields, admin_cfg, authoritative=is_user, status_field=status_field)
        search = _pick_search_fields(contract_fields, rev_fks, admin_cfg, authoritative=is_user)
        readonly = _pick_readonly_fields(view, contract_fields, admin_cfg, authoritative=is_user)

        list_editable = admin_cfg.get("list_editable") or []
        if list_editable:
            valid = {f["name"] for f in contract_fields}
            list_editable = [f for f in list_editable if f in valid]

        autocomplete = admin_cfg.get("autocomplete_fields") or []
        if autocomplete:
            valid = {f["name"] for f in contract_fields if _is_fk_field(f)}
            autocomplete = [f for f in autocomplete if f in valid]

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
            )
        )

    parts.extend(inline_class_defs)
    parts.extend(admin_class_parts)
    parts.append("")
    return "\n".join(parts)
