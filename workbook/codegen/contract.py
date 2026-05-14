"""Load, normalise, and query a schema-contract YAML for code generation.

A schema contract may be version ``"1.0"`` (auto-generated hints) or ``"1.1"``
(human-hardened with model metadata, FK resolutions, field overrides, and
extra fields).  This module provides a uniform access layer so generators
don't need to branch on the version.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def load_contract(path: str | Path) -> dict[str, Any]:
    """Load a schema-contract YAML, validate, and return a normalised dict.

    Args:
        path: Filesystem path to a ``.yaml`` / ``.yml`` file.

    Returns:
        Normalised contract dict with ``"version"``, ``"source"``, and
        ``"tables"`` keys guaranteed present.

    Raises:
        CommandError (via caller) or ``ValueError`` if the file is missing,
        unparseable, or has an unsupported version.
    """
    import yaml

    src = Path(path).read_text(encoding="utf-8")
    raw: dict[str, Any] = yaml.safe_load(src)
    if not isinstance(raw, dict):
        raise ValueError("schema contract must be a YAML mapping")

    version = str(raw.get("version") or "1.0")
    if version not in ("1.0", "1.1", "1.2", "1.3"):
        raise ValueError(f"unsupported schema contract version: {version}")

    raw.setdefault("source", {})
    raw.setdefault("tables", [])
    raw["version"] = version
    return raw


def get_model_name(table: dict[str, Any]) -> str:
    """Return the PascalCase Django model class name for *table*."""
    raw = str(table.get("suggested_model_name") or "model")
    parts = raw.replace("-", "_").split("_")
    name = "".join(p.capitalize() for p in parts if p)
    return name or "Model"


def get_db_table_name(table: dict[str, Any], app_label: str) -> str:
    """Return the ``db_table`` value for *table*.

    Uses the v1.1 ``model_meta.db_table`` when available, otherwise falls
    back to ``{app_label}_{suggested_model_name}``.
    """
    meta = table.get("model_meta") or {}
    explicit = meta.get("db_table")
    if explicit:
        return str(explicit)
    raw = str(table.get("suggested_model_name") or "model")
    return f"{app_label}_{raw}"


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


def validate_contract_tables(
    contract: dict[str, Any],
) -> list[str]:
    """Run validation checks on a schema contract and return warning messages.

    Checks:
    - FK target models exist in the contract table list
    - ``import_config.fk_lookup`` field references resolve to actual fields
    - ``import_config.unique_on`` fields have no duplicates

    Returns:
        List of human-readable warning strings (empty when no issues).
    """
    warnings: list[str] = []
    tables = list(contract.get("tables") or [])
    table_names = {get_model_name(t) for t in tables}

    for table in tables:
        name = get_model_name(table)
        field_names = {f["name"] for f in get_fields(table)}

        for col in table.get("columns") or []:
            fname = col.get("suggested_field_name", "?")
            fk_to = (col.get("django_field_kwargs") or {}).get("to")
            if fk_to and fk_to not in table_names and fk_to != "self":
                warnings.append(
                    f"{name}.{fname}: FK target \"{fk_to}\" "
                    f"is not a table in the contract"
                )

        import_cfg = get_import_config(table)
        if import_cfg:
            fk_lookup = import_cfg.get("fk_lookup") or {}
            for fk_field, fk_cfg in fk_lookup.items():
                if fk_field not in field_names:
                    warnings.append(
                        f"{name}.import_config.fk_lookup.{fk_field}: "
                        f"references a field not in the model"
                    )
                target = fk_cfg.get("model")
                if target and target not in table_names:
                    warnings.append(
                        f"{name}.import_config.fk_lookup.{fk_field}: "
                        f"FK target \"{target}\" is not a table in the contract"
                    )

            unique_on = import_cfg.get("unique_on") or []
            seen: set[str] = set()
            for f in unique_on:
                if f in seen:
                    warnings.append(
                        f"{name}.import_config.unique_on: \"{f}\" appears more than once"
                    )
                seen.add(f)

    return warnings


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
        fclass = _normalise_field_class(str(col.get("django_field_class") or "models.TextField"))
        fkwargs = dict(col.get("django_field_kwargs") or {})

        fkwargs = _resolve_fk_target(fname, fkwargs, resolutions)
        fclass, fkwargs = _apply_field_override(fname, fclass, fkwargs, overrides)

        fields.append({"name": fname, "class": fclass, "kwargs": fkwargs})

    for fname, spec in sorted(extra.items()):
        fclass = _normalise_field_class(str(spec.get("class") or "models.TextField"))
        fkwargs = dict(spec.get("kwargs") or {})
        fields.append({"name": fname, "class": fclass, "kwargs": fkwargs})

    return fields
