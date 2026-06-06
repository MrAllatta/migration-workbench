"""Load, normalise, and query a schema-contract YAML for code generation.

Provides a uniform access layer so generators don't need to branch on
contract features — accessor functions return sensible defaults for
absent keys.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from workbook.codegen.validation_pipeline import ValidationResult


def _make_contract_loader(base_path: str | Path) -> type:
    """Return a ``SafeLoader`` subclass supporting ``!include`` and ``!include_list``.

    Both tags load YAML from another file and inline it at the point of use.
    Include paths are resolved relative to the directory of the including
    file, not the root contract file.

    Cyclic includes are detected and rejected.
    """
    import yaml

    contract_path = Path(base_path).resolve()

    class ContractLoader(yaml.SafeLoader):
        """YAML loader that supports ``!include`` for contract composition."""

        _include_stack: list[Path] = []
        _contract_path: Path = contract_path

    def _resolve_include_target(loader: ContractLoader, path_str: str) -> Path:
        including_file = (
            loader._include_stack[-1]
            if loader._include_stack
            else loader._contract_path
        )
        return (including_file.parent / path_str).resolve()

    def _load_included_yaml(loader: ContractLoader, target: Path) -> Any:
        if target == loader._contract_path or target in loader._include_stack:
            cycle = " -> ".join(str(p) for p in loader._include_stack + [target])
            from workbench.exceptions import UserFacingError

            raise UserFacingError(
                f"cyclic include detected: {cycle}",
                action="Remove the circular !include reference in the contract YAML.",
                check_id="WORKBOOK-CONTRACT-001",
            )
        if not target.is_file():
            from workbench.exceptions import UserFacingError

            raise UserFacingError(
                f"include file not found: {target}",
                action="Create the missing file or correct the !include path in the contract YAML.",
                check_id="WORKBOOK-CONTRACT-002",
            )
        loader._include_stack.append(target)
        try:
            text = target.read_text(encoding="utf-8")
            return yaml.load(text, Loader=type(loader))
        finally:
            loader._include_stack.pop()

    def _include_constructor(loader: ContractLoader, node: yaml.ScalarNode) -> Any:
        path_str: str = str(loader.construct_scalar(node))
        target = _resolve_include_target(loader, path_str)
        return _load_included_yaml(loader, target)

    def _include_list_constructor(loader: ContractLoader, node: yaml.ScalarNode) -> Any:
        path_str: str = str(loader.construct_scalar(node))
        target = _resolve_include_target(loader, path_str)
        included = _load_included_yaml(loader, target)
        if not isinstance(included, list):
            from workbench.exceptions import UserFacingError

            included_type_name = type(included).__name__
            raise UserFacingError(
                f"!include_list target must be a YAML list (got {included_type_name}) in {target}",
                action="Ensure the included file contains a YAML list (a sequence starting with '-').",
                check_id="WORKBOOK-CONTRACT-003",
            )
        return included

    ContractLoader.add_constructor("!include", _include_constructor)
    ContractLoader.add_constructor("!include_list", _include_list_constructor)
    return ContractLoader


def load_contract_unvalidated(path: str | Path) -> dict[str, Any]:
    """Load a schema-contract YAML and return a normalised dict without validation.

    Handles YAML loading with ``!include``/``!include_list`` support,
    default key injection, table-list validation, and recursive flattening
    of nested table entries.

    Args:
        path: Filesystem path to a ``.yaml`` / ``.yml`` file.

    Returns:
        Normalised contract dict with ``"version"``, ``"source"``, and
        ``"tables"`` keys guaranteed present.
    """
    import yaml

    src = Path(path).read_text(encoding="utf-8")
    loader_cls = _make_contract_loader(path)
    raw: dict[str, Any] = yaml.load(src, Loader=loader_cls)
    if not isinstance(raw, dict):
        from workbench.exceptions import UserFacingError

        raise UserFacingError(
            "Schema contract must be a YAML mapping",
            action="Check that the contract file is valid YAML with a top-level mapping (not a list).",
            check_id="WORKBOOK-CONTRACT-004",
        )

    raw.setdefault("version", "")
    raw.setdefault("source", {})
    raw.setdefault("tables", [])

    tables = raw.get("tables")
    if not isinstance(tables, list):
        from workbench.exceptions import UserFacingError

        raise UserFacingError(
            "Schema contract 'tables' must be a YAML list",
            action="Ensure the 'tables' key in your contract contains a list of table mappings.",
            check_id="WORKBOOK-CONTRACT-005",
        )

    def _walk_table_entries(table_entries: list[Any]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for entry in table_entries:
            if isinstance(entry, list):
                flattened.extend(_walk_table_entries(entry))
                continue
            if not isinstance(entry, dict):
                from workbench.exceptions import UserFacingError

                entry_type_name = type(entry).__name__
                raise UserFacingError(
                    f"Schema contract table entries must be mappings (got {entry_type_name})",
                    action="Each entry in the 'tables' list must be a mapping (key-value pairs). Check for stray scalar or list entries.",
                    check_id="WORKBOOK-CONTRACT-006",
                )
            flattened.append(entry)
        return flattened

    raw["tables"] = _walk_table_entries(tables)

    return raw


def load_contract(path: str | Path) -> dict[str, Any]:
    """Load and strictly validate a contract YAML.

    Loads the contract via :func:`load_contract_unvalidated` and then runs
    :func:`strict_validate_contract`.  Raises ``UserFacingError`` if
    validation fails.

    Args:
        path: Filesystem path to a ``.yaml`` / ``.yml`` file.

    Returns:
        Normalised contract dict with ``"version"``, ``"source"``, and
        ``"tables"`` keys guaranteed present.
    """
    contract = load_contract_unvalidated(path)
    from workbench.exceptions import UserFacingError

    results = strict_validate_contract(contract)
    if results:
        lines = [f"  {r.check_id}: {r.message}" for r in results]
        if any(r.action for r in results):
            lines.append("Suggested actions:")
            for r in results:
                if r.action:
                    lines.append(f"  - {r.action}")
        raise UserFacingError(
            "Contract validation failed:\n" + "\n".join(lines),
            action="Fix the reported issues in the contract and re-run.",
            check_id="WORKBOOK-CONTRACT-007",
        )
    return contract


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


def validate_contract_tables(
    contract: dict[str, Any],
) -> list[str]:
    """Run validation checks on a schema contract and return warning messages.

    Checks:
    - ``model_name`` is present on every table
    - FK target models exist in the contract table list
    - ``import_config.fk_lookup`` field references resolve to actual fields
    - ``import_config.unique_on`` fields have no duplicates

    Returns:
        List of human-readable warning strings (empty when no issues).
    """
    warnings: list[str] = []
    tables = list(contract.get("tables") or [])

    for table in tables:
        if "model_name" not in table:
            warnings.append(
                f"Table '{table.get('suggested_model_name', '?')}' "
                f"missing required 'model_name'"
            )
            continue

    table_names = {get_model_name(t) for t in tables if "model_name" in t}

    for table in tables:
        if "model_name" not in table:
            continue
        name = get_model_name(table)
        fields = get_fields(table)
        field_names = {f["name"] for f in fields}

        for field in fields:
            if field["class"] != "models.ForeignKey":
                continue
            fk_to = field["kwargs"].get("to")
            if fk_to and fk_to not in table_names and fk_to != "self":
                warnings.append(
                    f'{name}.{field["name"]}: FK target "{fk_to}" '
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
                        f'FK target "{target}" is not a table in the contract'
                    )

            unique_on = import_cfg.get("unique_on") or []
            seen: set[str] = set()
            for f in unique_on:
                if f in seen:
                    warnings.append(
                        f'{name}.import_config.unique_on: "{f}" appears more than once'
                    )
                seen.add(f)

    return warnings


def review_contract(contract: dict[str, Any]) -> list[dict[str, str]]:
    """Run a design-review checklist on a schema contract.

    Checks intended for schema designers before codegen — catches common
    pitfalls like nullable FKs without ``on_delete``, CharFields without
    ``max_length``, and missing ``unique_together`` on multi-FK tables.

    Returns:
        List of issue dicts. Each issue includes stable ``rule_id`` plus
        ``table``, ``field``, and ``message`` keys.
    """
    issues: list[dict[str, str]] = []
    tables = list(contract.get("tables") or [])
    table_names = {get_model_name(t) for t in tables}

    for table in tables:
        name = get_model_name(table)
        fields = get_fields(table)
        meta = table.get("model_meta") or {}

        suppressed_rule_ids = set(table.get("suppress_review_warnings") or [])

        def add_issue(rule_id: str, field: str, message: str) -> None:
            if rule_id in suppressed_rule_ids:
                return
            issues.append(
                {
                    "rule_id": rule_id,
                    "table": name,
                    "field": field,
                    "message": message,
                }
            )

        # Check: CharField without max_length.
        for field in fields:
            fclass = _field_class_short(field["class"])
            kwargs = field["kwargs"]
            if fclass == "CharField" and "max_length" not in kwargs:
                add_issue(
                    "charfield_missing_max_length",
                    field["name"],
                    "CharField without max_length — default will be used",
                )
            # Check: nullable FK without explicit on_delete.
            if fclass == "ForeignKey":
                on_delete = kwargs.get("on_delete")
                null_ok = kwargs.get("null", kwargs.get("blank", False))
                if null_ok and not on_delete:
                    add_issue(
                        "nullable_fk_missing_on_delete",
                        field["name"],
                        "nullable FK without explicit on_delete — Django will warn at runtime",
                    )
                elif null_ok and str(on_delete) == "PROTECT":
                    add_issue(
                        "nullable_fk_with_protect",
                        field["name"],
                        "nullable FK with PROTECT — import failures leave orphaned rows",
                    )

        # Check: multiple FK fields but no unique_together or constraints.
        fk_fields = [f for f in fields if f["class"] == "models.ForeignKey"]
        if len(fk_fields) >= 2:
            has_unique = bool(meta.get("unique_together") or meta.get("constraints"))
            if not has_unique:
                add_issue(
                    "multiple_fk_without_unique",
                    ", ".join(f["name"] for f in fk_fields),
                    "multiple FK fields but no unique_together or constraints — possible duplicate rows",
                )

        # Check: model has no __str__ template for admin usability.
        str_tmpl = table.get("str_template")
        if not str_tmpl:
            add_issue(
                "missing_str_template",
                "",
                "no str_template — admin lists show unhelpful object labels",
            )

        # Check: fk_lookup targets a model not in the contract.
        import_config = table.get("import_config") or {}
        fk_lookup = import_config.get("fk_lookup") or {}
        for field_name, lookup_def in fk_lookup.items():
            target_model = lookup_def.get("model", "")
            if target_model and target_model not in table_names:
                add_issue(
                    "fk_lookup_missing_target_model",
                    field_name,
                    f"fk_lookup references '{target_model}' which is not a table in the contract",
                )

        # Check: admin.inlines target a model not in the contract.
        admin_config = table.get("admin") or {}
        for inline_name in admin_config.get("inlines") or []:
            if inline_name not in table_names:
                add_issue(
                    "admin_inline_missing_target_model",
                    inline_name,
                    f"admin.inlines references '{inline_name}' which is not a table in the contract",
                )

        # Check: computed_fields use snake_case names.
        computed = table.get("computed_fields") or {}
        for cf_name in computed:
            if not re.match(r"^[a-z][a-z0-9_]*$", cf_name):
                add_issue(
                    "computed_field_not_snake_case",
                    cf_name,
                    f"computed_field '{cf_name}' is not snake_case — use lowercase_with_underscores",
                )

    return issues


def _field_class_short(raw: str) -> str:
    """Strip the ``models.`` prefix from a field class string."""
    return raw.removeprefix("models.")


def assign_import_tiers(
    contract: dict[str, Any],
) -> dict[str, int]:
    """Auto-assign import tiers by topological sort of FK dependency chains.

    Tables with no FK dependencies get tier 1.  Each subsequent tier adds
    one.  If a table already has an explicit ``import_config.tier``, that
    value is preserved.

    Returns:
        ``{model_name: tier}`` for every table with ``import_config``.
    """
    tables = list(contract.get("tables") or [])
    table_names: dict[str, dict[str, Any]] = {}
    for t in tables:
        name = get_model_name(t)
        if get_import_config(t) is not None:
            table_names[name] = t

    # Build adjacency: model → set of FK target model names.
    deps: dict[str, set[str]] = {}
    for name, t in table_names.items():
        cfg = get_import_config(t)
        fk_lookup = (cfg or {}).get("fk_lookup") or {}
        targets: set[str] = set()
        for fk_cfg in fk_lookup.values():
            target = fk_cfg.get("model")
            if target and target in table_names:
                targets.add(target)
        deps[name] = targets

    # Topological sort via Kahn's algorithm.
    in_degree: dict[str, int] = {n: 0 for n in table_names}
    for name in table_names:
        for dep in deps[name]:
            in_degree[dep] = in_degree.get(dep, 0) + 1

    queue: list[str] = [n for n, d in in_degree.items() if d == 0]
    tier_map: dict[str, int] = {}
    current_tier = 1

    while queue:
        next_queue: list[str] = []
        for name in queue:
            tier_map[name] = current_tier
            for dep_name, dep_set in deps.items():
                if name in dep_set:
                    in_degree[dep_name] -= 1
                    if in_degree[dep_name] == 0:
                        next_queue.append(dep_name)
        queue = next_queue
        current_tier += 1

    # Apply explicit tiers as overrides.
    result: dict[str, int] = {}
    for name, t in table_names.items():
        cfg = get_import_config(t)
        explicit = cfg.get("tier") if cfg else None
        if explicit is not None:
            result[name] = int(explicit)
        else:
            result[name] = tier_map.get(name, 99)

    return result


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


def diff_contracts(
    old: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, Any]:
    """Compare two normalised schema contracts and return a structured diff.

    Compares tables (matched by ``suggested_model_name``), resolved fields
    per table, and ``model_meta`` options.  No fuzzy rename detection —
    models present in only one contract are reported as added/removed.

    Args:
        old: First (older) normalised contract dict.
        new: Second (newer) normalised contract dict.

    Returns:
        Dict keyed by diff category, or ``{}`` when contracts are identical.
    """
    old_tables = {get_model_name(t): t for t in (old.get("tables") or [])}
    new_tables = {get_model_name(t): t for t in (new.get("tables") or [])}

    old_names = set(old_tables)
    new_names = set(new_tables)

    added_models = sorted(new_names - old_names)
    removed_models = sorted(old_names - new_names)
    common_models = sorted(old_names & new_names)

    if not added_models and not removed_models and not common_models:
        return {}

    result: dict[str, Any] = {}
    if added_models:
        result["models_added"] = added_models
    if removed_models:
        result["models_removed"] = removed_models

    model_diffs: dict[str, Any] = {}
    for name in common_models:
        diff = _diff_tables(old_tables[name], new_tables[name])
        if diff:
            model_diffs[name] = diff

    if model_diffs:
        result["model_diffs"] = model_diffs

    return result


def _diff_tables(
    old_table: dict[str, Any],
    new_table: dict[str, Any],
) -> dict[str, Any] | None:
    """Compare two tables with the same model name.

    Returns a diff dict or ``None`` when no differences are found.
    """
    old_fields = _field_map(get_fields(old_table))
    new_fields = _field_map(get_fields(new_table))

    old_names = set(old_fields)
    new_names = set(new_fields)

    result: dict[str, Any] = {}

    # Field additions / removals.
    added = sorted(new_names - old_names)
    if added:
        result["fields_added"] = [_field_summary(new_fields[f]) for f in added]

    removed = sorted(old_names - new_names)
    if removed:
        result["fields_removed"] = [_field_summary(old_fields[f]) for f in removed]

    # Field changes.
    changed: list[dict[str, Any]] = []
    for fname in sorted(old_names & new_names):
        of = old_fields[fname]
        nf = new_fields[fname]
        fc = _diff_fields(of, nf)
        if fc:
            changed.append(fc)
    if changed:
        result["fields_changed"] = changed

    # Meta changes.
    meta_diff = _diff_meta(
        old_table.get("model_meta") or {},
        new_table.get("model_meta") or {},
    )
    if meta_diff:
        result["meta_changed"] = meta_diff

    return result if result else None


def _field_map(fields: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index a field list by ``name``."""
    return {f["name"]: f for f in fields}


def _field_summary(field: dict[str, Any]) -> dict[str, Any]:
    """Return a clean, comparable field dict."""
    return {
        "name": field["name"],
        "class": field["class"],
        "kwargs": dict(field.get("kwargs") or {}),
    }


def _diff_fields(
    old: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, Any] | None:
    """Compare two fields with the same name.

    Returns a change dict or ``None`` when fields are identical.
    """
    cls_old = old.get("class", "")
    cls_new = new.get("class", "")
    kwargs_old = dict(old.get("kwargs") or {})
    kwargs_new = dict(new.get("kwargs") or {})

    # YAML parses null: as a Python None key — normalise to "null".
    kwargs_old = {("null" if k is None else k): v for k, v in kwargs_old.items()}
    kwargs_new = {("null" if k is None else k): v for k, v in kwargs_new.items()}

    class_changed = cls_old != cls_new

    all_kwargs_keys = sorted(set(kwargs_old) | set(kwargs_new))
    kwarg_diffs: dict[str, dict[str, Any]] = {}
    for k in all_kwargs_keys:
        v_old = kwargs_old.get(k)
        v_new = kwargs_new.get(k)
        if v_old != v_new:
            kwarg_diffs[k] = {"old": v_old, "new": v_new}

    if not class_changed and not kwarg_diffs:
        return None

    entry: dict[str, Any] = {
        "name": old["name"],
        "class": {"old": cls_old, "new": cls_new},
    }

    if kwarg_diffs:
        entry["kwargs"] = kwarg_diffs

    return entry


MIGRATION_SEVERITY_DANGER = "DANGER"
MIGRATION_SEVERITY_WARNING = "WARNING"


def migration_safety_checks(diffs: dict[str, Any]) -> list[dict[str, Any]]:
    """Inspect ``diff_contracts()`` output for migration safety risks.

    Checks for field removals, nullable→non-nullable changes, field type
    changes, ``max_length`` reductions, ``unique=True`` additions, and
    non-nullable fields added without defaults.

    Args:
        diffs: Output from :func:`diff_contracts`.

    Returns:
        List of risk items, each with ``severity`` (DANGER or WARNING),
        ``model``, ``field``, ``message``, and optional ``detail``.
        Empty list when no risks are found.
    """
    results: list[dict[str, Any]] = []

    for model_name, model_diff in (diffs.get("model_diffs") or {}).items():
        # Field removals.
        for f in model_diff.get("fields_removed") or []:
            results.append(
                {
                    "severity": MIGRATION_SEVERITY_DANGER,
                    "model": model_name,
                    "field": f["name"],
                    "message": "Field removed — existing data in source will be lost",
                    "detail": {"old_class": f.get("class", "")},
                }
            )

        # Field changes.
        for fc in model_diff.get("fields_changed") or []:
            fname = fc["name"]
            kwargs_diff = fc.get("kwargs") or {}

            # nullable → non-nullable
            null_old = kwargs_diff.get("null", {}).get("old")
            null_new = kwargs_diff.get("null", {}).get("new")
            if null_old is True and null_new is not True:
                results.append(
                    {
                        "severity": MIGRATION_SEVERITY_DANGER,
                        "model": model_name,
                        "field": fname,
                        "message": "Field changed from nullable to non-nullable — "
                        "migration will fail if null rows exist",
                        "detail": {"null": {"old": True, "new": null_new}},
                    }
                )

            # Field class changed
            class_change = fc.get("class")
            if class_change and class_change["old"] != class_change["new"]:
                results.append(
                    {
                        "severity": MIGRATION_SEVERITY_WARNING,
                        "model": model_name,
                        "field": fname,
                        "message": (
                            f"Field class changed: "
                            f"{_field_class_short(class_change['old'])} -> "
                            f"{_field_class_short(class_change['new'])}"
                            " — existing data may not cast cleanly"
                        ),
                        "detail": {
                            "old_class": class_change["old"],
                            "new_class": class_change["new"],
                        },
                    }
                )

            # max_length decreased
            max_old = kwargs_diff.get("max_length", {}).get("old")
            max_new = kwargs_diff.get("max_length", {}).get("new")
            if max_old is not None and max_new is not None and max_old > max_new:
                results.append(
                    {
                        "severity": MIGRATION_SEVERITY_WARNING,
                        "model": model_name,
                        "field": fname,
                        "message": (
                            f"max_length decreased: {max_old} -> {max_new}"
                            " — existing data may be truncated"
                        ),
                        "detail": {
                            "old_max_length": max_old,
                            "new_max_length": max_new,
                        },
                    }
                )

            # unique=True added
            unique_old = kwargs_diff.get("unique", {}).get("old")
            unique_new = kwargs_diff.get("unique", {}).get("new")
            if unique_new is True and unique_old is not True:
                results.append(
                    {
                        "severity": MIGRATION_SEVERITY_WARNING,
                        "model": model_name,
                        "field": fname,
                        "message": (
                            "unique=True added — "
                            "migration will fail if duplicate values exist"
                        ),
                        "detail": {"unique": {"old": unique_old, "new": True}},
                    }
                )

        # Field additions — check non-nullable without default.
        for f in model_diff.get("fields_added") or []:
            kwargs = f.get("kwargs") or {}
            null = kwargs.get("null")
            has_default = "default" in kwargs or null is True
            if not has_default:
                results.append(
                    {
                        "severity": MIGRATION_SEVERITY_WARNING,
                        "model": model_name,
                        "field": f["name"],
                        "message": (
                            "Non-nullable field added without default — "
                            "existing rows will need a backfill value"
                        ),
                        "detail": {"class": f.get("class", "")},
                    }
                )

    return results


def _diff_meta(
    old_meta: dict[str, Any],
    new_meta: dict[str, Any],
) -> dict[str, Any] | None:
    """Compare two ``model_meta`` dicts.

    Only keys present in ``DIFF_META_KEYS`` are compared.
    """
    DIFF_META_KEYS = {
        "unique_together",
        "indexes",
        "constraints",
        "ordering",
        "verbose_name",
        "db_table",
        "app_label",
    }
    result: dict[str, Any] = {}
    for key in DIFF_META_KEYS:
        v_old = old_meta.get(key)
        v_new = new_meta.get(key)
        if v_old != v_new:
            result[key] = {"old": v_old, "new": v_new}
    return result if result else None


def strict_validate_contract(contract: dict[str, Any]) -> list[ValidationResult]:
    """Run strict validation checks and return structured results.

    Checks:
    - No model_name is null or empty.
    - Every suggested_field_name is a valid Python identifier and not a keyword.
    - No duplicate model_name values exist across tables.
    - No suggested_field_name starts with a digit.
    """
    import keyword

    results: list[ValidationResult] = []
    tables = list(contract.get("tables") or [])
    model_names: list[str] = []

    for table in tables:
        model_name = str(table.get("model_name", "")).strip()
        if not model_name:
            label = table.get("suggested_model_name") or table.get(
                "bundle_worksheet_title", "?"
            )
            results.append(
                ValidationResult(
                    model_name=model_name or "_UNNAMED",
                    check_id="WORKBOOK-CONTRACT-NULL-MODEL",
                    message=f"Table '{label}' has empty model_name",
                    action="Set a unique model_name or add suggested_model_name to the contract",
                )
            )
            continue
        model_names.append(model_name)

    seen_model_names: set[str] = set()
    for mn in model_names:
        if mn in seen_model_names:
            results.append(
                ValidationResult(
                    model_name=mn,
                    check_id="WORKBOOK-CONTRACT-DUPLICATE-MODEL",
                    message=f'Duplicate model_name "{mn}" (2+ tables)',
                    action="Rename one of the duplicate tables or merge them",
                )
            )
        seen_model_names.add(mn)

    for table in tables:
        model_name = str(table.get("model_name", "")).strip()
        for col in table.get("columns", []):
            field_name = col.get("suggested_field_name", "")
            if not field_name:
                continue
            if not str(field_name).isidentifier() or keyword.iskeyword(str(field_name)):
                results.append(
                    ValidationResult(
                        model_name=model_name or None,
                        check_id="WORKBOOK-CONTRACT-INVALID-FIELD-NAME",
                        message=f'Field "{field_name}" in model "{model_name}" is not a valid Python identifier',
                        action="Rename the source column in the contract",
                    )
                )
            elif str(field_name)[0].isdigit():
                results.append(
                    ValidationResult(
                        model_name=model_name or None,
                        check_id="WORKBOOK-CONTRACT-INVALID-FIELD-NAME",
                        message=f'Field "{field_name}" in model "{model_name}" starts with a digit',
                        action="Rename the source column in the contract",
                    )
                )

    return results
