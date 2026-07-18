"""Contract accessors: model, field, admin, and import-config lookups.

Extracted from ``workbook/codegen/contract.py`` as part of e04
(contract-layer-split).

Every function in this module accesses a slice of a normalised contract
dict and returns either a derived value or a sensible default.

No function in this module depends on any other module in
``workbook.contract`` — they are pure data lookups that can be tested
in isolation.
"""

from __future__ import annotations

from typing import Any


def get_model_name(table: dict[str, Any]) -> str:
    """Return the PascalCase Django model class name from *table*.

    Reads the required ``model_name`` field.  Raises KeyError if absent.
    """
    return str(table["model_name"])


def get_db_table_name(table: dict[str, Any], app_label: str) -> str:
    """Return the ``db_table`` value for *table*.

    Uses the v1.1 ``model_meta.db_table`` when available, otherwise falls
    back to ``{table_app_label}_{suggested_model_name}``.  The *app_label*
    parameter is used as the default; individual tables can override it via
    ``model_meta.app_label``.
    """
    meta = table.get("model_meta") or {}
    explicit = meta.get("db_table")
    if explicit:
        return str(explicit)
    table_app_label = meta.get("app_label") or app_label
    raw = str(table.get("suggested_model_name") or "model")
    return f"{table_app_label}_{raw}"


def get_model_meta(table: dict[str, Any]) -> dict[str, Any]:
    """Return ``class Meta`` options for *table*.

    Keys like ``verbose_name``, ``ordering``, and ``db_table`` are pulled
    from the v1.1 ``model_meta`` block.  ``db_table`` is **always** set via
    :func:`get_db_table_name` so the generated model always has an explicit
    table name.
    """
    meta = dict(table.get("model_meta") or {})
    return meta


def get_str_template(table: dict[str, Any]) -> str | None:
    """Return the ``__str__`` f-string template, or ``None``.

    The template is stored without braces inside ``str_template``, e.g.
    ``"{self.name}"``.  Returns ``None`` when absent or empty.
    """
    raw = table.get("str_template")
    if raw and isinstance(raw, str):
        return raw
    return None


def _resolve_fk_target(
    field_name: str, kwargs: dict[str, Any], resolutions: dict[str, str]
) -> dict[str, Any]:
    """Return updated kwargs with the ``to`` resolved when possible."""
    if kwargs.get("to") == "TODO_TargetModel" and field_name in resolutions:
        out = dict(kwargs)
        out["to"] = resolutions[field_name]
        return out
    return kwargs


def _apply_field_override(
    field_name: str,
    field_class: str,
    kwargs: dict[str, Any],
    overrides: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Return (overridden_class, merged_kwargs) or the originals."""
    override = overrides.get(field_name)
    if not override:
        return field_class, kwargs

    cls = override.get("class") or field_class
    merged = dict(kwargs)
    user_kwargs = override.get("kwargs") or {}
    merged.update(user_kwargs)
    return cls, merged


def _normalise_field_class(raw: str) -> str:
    """Ensure a field class value starts with ``models.``."""
    s = raw.strip()
    if s.startswith("models."):
        return s
    return f"models.{s}"


def get_enums(contract: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    """Return top-level enum definitions as ``{name: [(value, label), ...]}``.

    The contract ``enums`` block is formatted as::

        enums:
          EventType:
            - [seeded, "Seeded"]
            - [harvested, "Harvested"]

    Returns:
        Empty dict when absent.
    """
    raw = contract.get("enums") or {}
    result: dict[str, list[tuple[str, str]]] = {}
    for name, pairs in raw.items():
        result[name] = [(str(p[0]), str(p[1])) for p in pairs]
    return result


def get_admin_config(table: dict[str, Any]) -> dict[str, Any]:
    """Return the ``admin`` configuration block for *table*, or ``{}``.

    The admin block may contain ``list_display``, ``list_filter``,
    ``search_fields``, ``readonly_fields``, ``inlines``, etc.
    """
    cfg = table.get("admin")
    if cfg and isinstance(cfg, dict):
        return cfg
    return {}


def get_auth_config(table: dict[str, Any]) -> dict[str, Any]:
    """Return the ``codegen.auth`` configuration block for *table*, or ``{}``.

    The v1.4+ auth block is stored under ``codegen.auth``::

        codegen:
          auth:
            mechanism: django_groups
            default_owner_role: field_manager

    Returns:
        Dict with ``mechanism``, ``default_owner_role``, and optional
        ``permissions`` keys.  Empty dict ``{}`` when absent.
    """
    codegen = table.get("codegen")
    if codegen and isinstance(codegen, dict):
        auth = codegen.get("auth")
        if auth and isinstance(auth, dict):
            return auth
    return {}


def get_model_base(table: dict[str, Any]) -> str:
    """Return the model base class for *table*.

    Defaults to ``"models.Model"``.  Override via ``model_base`` key::

        model_base: "AbstractUser"
    """
    explicit = table.get("model_base")
    if explicit:
        return str(explicit)
    return "models.Model"


def get_extra_imports(table: dict[str, Any]) -> list[str]:
    """Return extra import lines for *table*, or ``[]``.

    Extra imports are needed when ``model_base`` is not ``models.Model``
    (e.g. ``from django.contrib.auth.models import AbstractUser``).
    """
    imports = table.get("extra_imports")
    if imports and isinstance(imports, list):
        return [str(i) for i in imports]
    return []


def get_computed_fields(table: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ``computed_fields`` for *table*, or ``[]``.

    Computed fields are fields that exist in the model but are excluded
    from import (rendered as ``@property`` methods instead of model fields).
    Each entry has ``"name"``, ``"return_type"`` (optional), and
    ``"expression"`` (Python source for the property body)::

        computed_fields:
          signed_quantity:
            return_type: int
            expression: "self.quantity * -1 if self.direction == 'out' else self.quantity"
    """
    raw = table.get("computed_fields") or {}
    if not raw:
        return []
    result: list[dict[str, Any]] = []
    for name, spec in sorted(raw.items()):
        entry: dict[str, Any] = {"name": name}
        if isinstance(spec, dict):
            if "return_type" in spec:
                entry["return_type"] = spec["return_type"]
            if "expression" in spec:
                entry["expression"] = spec["expression"]
        result.append(entry)
    return result


def get_is_abstract(table: dict[str, Any]) -> bool:
    """Return ``True`` if *table* is an abstract base model.

    When ``is_abstract: true`` is set on a table, the generator emits
    ``class Meta: abstract = True`` instead of ``db_table``, and skips
    migration creation.
    """
    return bool(table.get("is_abstract"))


def has_source_tab(table: dict[str, Any]) -> bool:
    """Return ``True`` if *table* has an associated source tab.

    A table with ``source_tab: null`` or without ``bundle_worksheet_title``
    is a designed model with no source tab.  Codegen skips
    ``import_config`` scaffolding for these.
    """
    if "source_tab" in table and table["source_tab"] is None:
        return False
    ws = table.get("bundle_worksheet_title")
    if ws is None or (isinstance(ws, str) and not ws.strip()):
        return False
    return True


def get_hooks(table: dict[str, Any]) -> dict[str, str]:
    """Return the ``hooks`` block for *table*, or ``{}``.

    Hooks are Python source fragments injected at well-defined points in the
    generated model class::

        hooks:
          after_model: |
              # injected right after ``class <Name>(<Base>):``
          after_meta: |
              # injected after the ``class Meta`` block
          before_return: |
              # injected at the end of the class body, before closing

    See ``docs/roadmap.md`` for the full specification.
    """
    raw = table.get("hooks")
    if raw and isinstance(raw, dict):
        return {k: str(v) for k, v in raw.items()}
    return {}


def get_import_config(table: dict[str, Any]) -> dict[str, Any] | None:
    """Return the ``import_config`` block for *table*, or ``None``.

    The import config is a v1.1 extension that tells the import generator
    how to turn bundle CSV rows into model instances.  Expected keys::

        tier               int   — import ordering (lower = first)
        bundle_path        str   — CSV path relative to bundle root
        required_headers   list  — column headers the CSV must contain
        aliases            dict  — canonical → [alias, …] (optional)
        column_map         dict  — field_name → source_header (optional)
        default_values     dict  — field_name → fallback (optional)
        unique_on          list  — field names for update_or_create
        required_source_columns  list — must be non-empty (optional)
        fk_lookup          dict  — field → {model, on} (optional)
        field_parsers      dict  — field → parser_name (optional)

    Returns ``None`` when the block is absent so generators can skip
    models that are not importable from bundles.
    """
    cfg = table.get("import_config")
    if cfg and isinstance(cfg, dict):
        return cfg
    return None


def resolve_field_mapping(table: dict[str, Any]) -> dict[str, str]:
    """Return the effective field-name to source-column mapping for *table*.

    Merges two sources, with ``import_config.column_map`` taking priority:

    1. **columns[] baseline** — ``source_column`` → ``suggested_field_name``
       pairs auto-generated by the scaffold (populated when profiler data is
       available, e.g. via ``--table-profile``).

    2. **import_config.column_map override** — hand-authored overrides for
       fields whose source column does not match the scaffold's inference.

    Multi-source mappings (list-valued ``column_map`` entries) are excluded
    from the return value because they involve value-level transforms rather
    than a single source header.

    Audit, verification, and drift-detection tools call this function to
    determine which source column feeds each model field without re-deriving
    the mapping from generated code.

    Args:
        table: A single table entry from a schema-contract YAML.

    Returns:
        Dict mapping each model field name to its source CSV column header.
        Only fields with an explicit mapping are included.  Fields whose
        value is assembled from multiple columns (list-valued entries) are
        omitted — they require value-level inspection.
    """
    mapping: dict[str, str] = {}

    for col in table.get("columns") or []:
        src = col.get("source_column")
        field_name = col.get("suggested_field_name")
        if src and field_name:
            mapping[field_name] = src

    import_cfg = table.get("import_config") or {}
    for field_name, source in (import_cfg.get("column_map") or {}).items():
        if isinstance(source, list):
            continue  # multi-source — handled at value-expression level
        if isinstance(source, str):
            mapping[field_name] = source

    return mapping


def get_fields(table: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the resolved, overridden field list for *table*.

    Processing order:
    1. Auto-generated ``columns[]``.
    2. ``field_overrides`` applied per-column.
    3. ``fk_resolutions`` applied to FK targets.
    4. ``extra_fields`` appended.

    Each returned dict has ``"name"``, ``"class"``, and ``"kwargs"`` keys.
    """
    columns = table.get("columns") or []
    overrides = table.get("field_overrides") or {}
    resolutions = table.get("fk_resolutions") or {}
    extra = table.get("extra_fields") or {}

    fields: list[dict[str, Any]] = []

    for col in columns:
        fname = str(col.get("suggested_field_name") or "field")
        fclass = _normalise_field_class(
            str(col.get("django_field_class") or "models.TextField")
        )
        fkwargs = dict(col.get("django_field_kwargs") or {})

        fkwargs = _resolve_fk_target(fname, fkwargs, resolutions)
        fclass, fkwargs = _apply_field_override(fname, fclass, fkwargs, overrides)

        fields.append({"name": fname, "class": fclass, "kwargs": fkwargs})

    for fname, spec in extra.items():
        fclass = _normalise_field_class(str(spec.get("class") or "models.TextField"))
        fkwargs = dict(spec.get("kwargs") or {})
        fields.append({"name": fname, "class": fclass, "kwargs": fkwargs})

    return fields
