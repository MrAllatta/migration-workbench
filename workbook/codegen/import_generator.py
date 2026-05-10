"""Render a Django management command for importing data from bundle CSVs.

Usage::

    from workbook.codegen.contract import load_contract
    from workbook.codegen.import_generator import render_import_py

    contract = load_contract("build/schema-contract.yaml")
    source = render_import_py(contract, app_label="core")
    Path("backend/apps/core/management/commands/import_core_data.py").write_text(source)
"""

from __future__ import annotations

from typing import Any

from workbook.codegen.contract import (
    get_fields,
    get_import_config,
    get_model_name,
)


# -- helpers ----------------------------------------------------------------

def _field_class_short(raw: str) -> str:
    """Strip ``models.`` prefix from a field class string."""
    return raw.removeprefix("models.")


def _infer_parser(field: dict[str, Any]) -> str | None:
    """Infer a parser method name from the Django field class.

    Returns ``None`` for plain string/text fields (no parser needed).
    """
    short = _field_class_short(field["class"])
    parser_map = {
        "DateField": "parse_date",
        "DateTimeField": "parse_date",
        "DecimalField": "dec",
        "IntegerField": "int",
        "PositiveIntegerField": "int",
        "PositiveSmallIntegerField": "int",
        "SmallIntegerField": "int",
        "BigIntegerField": "int",
        "BooleanField": "bool",
        "FloatField": "dec",
        "DurationField": "int",
    }
    return parser_map.get(short)


def _parser_method(parser_name: str) -> str:
    """Map a short parser name to the ``BaseImportCommand`` method."""
    lookup = {
        "parse_date": "self._parse_date",
        "dec": "self._dec",
        "int": "self._int",
        "bool": "self._bool",
    }
    return lookup.get(parser_name, parser_name)


def _default_value(parser_name: str | None) -> str:
    """Return the default fallback for a parser."""
    lookup = {
        "parse_date": "None",
        "dec": '"0"',
        "int": "0",
        "bool": "False",
    }
    return lookup.get(parser_name) if parser_name else '""'


# -- rendering --------------------------------------------------------------


def _render_tab_config(import_cfg: dict[str, Any], indent: int = 8) -> str:
    """Render the ``tab_config`` dict literal for ``read_bundle_tab``."""
    pad = " " * indent
    inner = " " * (indent + 4)

    required = import_cfg.get("required_headers") or []
    rh_list = ", ".join(repr(h) for h in required)

    lines = [f"{pad}{{", f'{inner}"required_headers": [{rh_list}],']

    aliases = import_cfg.get("aliases")
    if aliases:
        alias_lines = []
        for canonical, alias_list in sorted(aliases.items()):
            items = ", ".join(repr(a) for a in alias_list)
            alias_lines.append(f"{inner}{inner}{canonical!r}: [{items}]")
        alias_body = ",\n".join(alias_lines)
        lines.append(f'{inner}"aliases": {{\n{alias_body}\n{inner}}},')

    cmap = import_cfg.get("column_map")
    if cmap:
        map_lines = []
        for field_name, source_header in sorted(cmap.items()):
            map_lines.append(f"{inner}{inner}{field_name!r}: {source_header!r}")
        map_body = ",\n".join(map_lines)
        lines.append(f'{inner}"column_map": {{\n{map_body}\n{inner}}},')

    defaults = import_cfg.get("default_values")
    if defaults:
        dv_lines = []
        for k, v in sorted(defaults.items()):
            dv_lines.append(f"{inner}{inner}{k!r}: {v!r}")
        dv_body = ",\n".join(dv_lines)
        lines.append(f'{inner}"default_values": {{\n{dv_body}\n{inner}}},')

    lines.append(f"{pad}}}")
    return "\n".join(lines)


def _render_required_check(
    model_name: str,
    field_name: str,
    source_headers: dict[str, str],
    required: list[str],
    indent: int = 12,
) -> str:
    """Render the required-field check + ``record_missing_required``."""
    pad = " " * indent
    parts: list[str] = []
    for req_field in required:
        source_label = source_headers.get(req_field, req_field)
        human_label = source_label.replace("_", " ").title()
        parts.append(
            f"{pad}{req_field}_val = row.get({req_field!r}, '').strip()\n"
            f"{pad}if not {req_field}_val:\n"
            f'{pad * 2}self.record_missing_required('
            f'{model_name!r}, row_number, {req_field!r}, {human_label!r})\n'
            f"{pad * 2}continue"
        )
    return "\n".join(parts)


def _render_fk_resolution(
    model_name: str,
    field_name: str,
    fk_cfg: dict[str, Any],
    source_headers: dict[str, str],
    indent: int = 12,
) -> str:
    """Render a FK resolution call via ``_resolve_fk_by_text``."""
    pad = " " * indent
    target_model = fk_cfg.get("model", "TODO_Model")
    target_field = fk_cfg.get("on", "name")
    source_label = source_headers.get(field_name, field_name)
    human_label = source_label.replace("_", " ").title()

    src = f'{pad}{field_name}_val = row.get({field_name!r}, "").strip()'
    check = (
        f"{pad}if not {field_name}_val:\n"
        f'{pad * 2}self.record_missing_required('
        f'{model_name!r}, row_number, {field_name!r}, {human_label!r})\n'
        f"{pad * 2}continue"
    )
    resolve = (
        f"{pad}{field_name} = self._resolve_fk_by_text("
        f"{target_model}, {target_field!r}, {field_name}_val, {human_label!r})"
    )
    stale = (
        f"{pad}if {field_name} is None:\n"
        f'{pad * 2}self.record_stale_fk('
        f'{model_name!r}, row_number, {field_name!r}, {human_label!r}, {field_name}_val)\n'
        f"{pad * 2}continue"
    )
    return f"{src}\n{check}\n{resolve}\n{stale}"


def _render_field_assignment(
    field_name: str,
    field: dict[str, Any],
    parser_override: str | None,
    indent: int = 12,
) -> str:
    """Render a single field assignment in the defaults dict.

    Returns ``(line, parser_used)``.
    """
    pad = " " * indent
    parser = parser_override or _infer_parser(field)

    if parser == "parse_date":
        src = f'raw = row.get({field_name!r}, "")'
        assign = (
            f"{pad}{field_name} = "
            f'{_parser_method(parser)}(raw) if raw.strip() else None'
        )
        return f"{src}\n{assign}"
    elif parser in ("dec", "int"):
        default = _default_value(parser)
        return (
            f"{pad}{field_name} = "
            f'{_parser_method(parser)}(row.get({field_name!r}, ""), {default})'
        )
    elif parser == "bool":
        return (
            f"{pad}{field_name} = "
            f'{_parser_method(parser)}(row.get({field_name!r}, ""))'
        )
    else:
        return f'{pad}{field_name} = row.get({field_name!r}, "").strip()'


def _render_defaults_dict(
    contract_fields: list[dict[str, Any]],
    import_cfg: dict[str, Any],
    indent: int = 8,
) -> str:
    """Render the ``defaults`` dict for ``update_or_create``.

    Each field gets a value expression (not a full assignment statement).
    Date/DateTime fields emit a ``raw_<name>`` statement before the dict
    and reference it inside.
    """
    fk_lookup = import_cfg.get("fk_lookup") or {}
    field_parsers = import_cfg.get("field_parsers") or {}
    unique_on = set(import_cfg.get("unique_on") or [])

    pad = " " * indent
    inner = " " * (indent + 4)

    raw_statements: list[str] = []
    dict_entries: list[str] = []

    for field in contract_fields:
        fname = field["name"]
        # Skip FK fields (resolved separately) and unique fields.
        if fname in fk_lookup or fname in unique_on:
            continue
        parser = field_parsers.get(fname) or _infer_parser(field)

        if parser == "parse_date":
            raw_statements.append(f'{inner}raw_{fname} = row.get({fname!r}, "")')
            val = f"self._parse_date(raw_{fname}) if raw_{fname}.strip() else None"
            dict_entries.append(
                f"{inner}{fname!r}: self._prepare_{fname}({val}, row),"
            )
        elif parser in ("dec", "int"):
            default = _default_value(parser)
            val = f'{_parser_method(parser)}(row.get({fname!r}, ""), {default})'
            dict_entries.append(
                f"{inner}{fname!r}: self._prepare_{fname}({val}, row),"
            )
        elif parser == "bool":
            val = f'{_parser_method(parser)}(row.get({fname!r}, ""))'
            dict_entries.append(
                f"{inner}{fname!r}: self._prepare_{fname}({val}, row),"
            )
        else:
            val = f'row.get({fname!r}, "").strip()'
            dict_entries.append(
                f"{inner}{fname!r}: self._prepare_{fname}({val}, row),"
            )

    parts: list[str] = []
    if raw_statements:
        parts.append("\n".join(raw_statements))
    parts.append(f"{pad}defaults = {{")
    if dict_entries:
        parts.append("\n".join(dict_entries))
    parts.append(f"{pad}}}")
    return "\n".join(parts)


def _render_unique_assignments(
    contract_fields: list[dict[str, Any]],
    import_cfg: dict[str, Any],
    indent: int = 8,
) -> str:
    """Render variable assignments for ``unique_on`` fields not in ``fk_lookup``.

    These assignments go *before* the ``defaults`` dict so the variables
    exist for the ``update_or_create`` unique kwargs.
    """
    fk_lookup = import_cfg.get("fk_lookup") or {}
    field_parsers = import_cfg.get("field_parsers") or {}
    unique_on = import_cfg.get("unique_on") or []

    pad = " " * indent
    parts: list[str] = []

    for fname in unique_on:
        if fname in fk_lookup:
            continue
        field = next((f for f in contract_fields if f["name"] == fname), None)
        if not field:
            continue
        parser = field_parsers.get(fname) or _infer_parser(field)

        if parser == "parse_date":
            parts.append(f'{pad}raw_{fname} = row.get({fname!r}, "")')
            parts.append(
                f"{pad}{fname} = "
                f"self._parse_date(raw_{fname}) if raw_{fname}.strip() else None"
            )
        elif parser in ("dec", "int"):
            default = _default_value(parser)
            parts.append(
                f"{pad}{fname} = "
                f'{_parser_method(parser)}(row.get({fname!r}, ""), {default})'
            )
        elif parser == "bool":
            parts.append(
                f"{pad}{fname} = "
                f'{_parser_method(parser)}(row.get({fname!r}, ""))'
            )
        else:
            parts.append(
                f'{pad}{fname} = row.get({fname!r}, "").strip()'
            )

    return "\n".join(parts)


def _render_import_method(
    model_name: str,
    contract_fields: list[dict[str, Any]],
    import_cfg: dict[str, Any],
    indent: int = 4,
) -> str:
    """Render a single import tier method."""
    method_name = f"_import_{model_name.lower()}"
    bundle_path = import_cfg.get("bundle_path", "TODO_bundle_path.csv")
    unique_on = import_cfg.get("unique_on") or []
    required = import_cfg.get("required_source_columns") or []
    fk_lookup = import_cfg.get("fk_lookup") or {}
    field_parsers = import_cfg.get("field_parsers") or {}

    # Build source_header mapping: column_map values, else field name.
    cmap = import_cfg.get("column_map") or {}
    source_headers: dict[str, str] = {}
    for fname in [f["name"] for f in contract_fields]:
        source_headers[fname] = cmap.get(fname, fname)

    tab_config = _render_tab_config(import_cfg, indent=0)

    lines = [
        "",
        f"def {method_name}(self):",
        f"    tab_config = {tab_config}",
        "",
    ]

    # read_bundle_tab loop header.
    lines.append(
        '    for row_number, row in self.read_bundle_tab('
        f'{bundle_path!r}, tab_config):'
    )

    # Required field checks (skip FK fields — they get richer checks below).
    if required:
        lines.append("")
        lines.append(
            f"        # Required source column checks."
        )
        for req_field in required:
            if req_field in fk_lookup:
                continue
            source_label = source_headers.get(req_field, req_field)
            human_label = source_label.replace("_", " ").title()
            lines.append(
                f'        {req_field}_val = row.get({req_field!r}, "").strip()'
            )
            lines.append(f"        if not {req_field}_val:")
            lines.append(
                f'            self.record_missing_required('
                f'{model_name!r}, row_number, {req_field!r}, {human_label!r})'
            )
            lines.append("            continue")
            lines.append("")

    # FK resolutions.
    for fname, fk_cfg in sorted(fk_lookup.items()):
        target_model = fk_cfg.get("model", "TODO_Model")
        target_field = fk_cfg.get("on", "name")
        source_label = source_headers.get(fname, fname)
        human_label = source_label.replace("_", " ").title()
        lines.append(
            f'        {fname}_val = row.get({fname!r}, "").strip()'
        )
        lines.append(f"        if not {fname}_val:")
        lines.append(
            f'            self.record_missing_required('
            f'{model_name!r}, row_number, {fname!r}, {human_label!r})'
        )
        lines.append("            continue")
        lines.append(
            f"        {fname} = self._resolve_fk_by_text("
            f"{target_model}, {target_field!r}, {fname}_val, {human_label!r})"
        )
        lines.append(f"        if {fname} is None:")
        lines.append(
            f'            self.record_stale_fk('
            f'{model_name!r}, row_number, {fname!r}, {human_label!r}, {fname}_val)'
        )
        lines.append("            continue")

    # Unique-on variable assignments (non-FK fields used in update_or_create).
    unique_assignments = _render_unique_assignments(
        contract_fields, import_cfg, indent=8
    )
    if unique_assignments:
        lines.append("")
        lines.append("        # Unique field value resolution.")
        lines.append(unique_assignments)

    # Defaults dict construction.
    lines.append("")
    defaults_dict = _render_defaults_dict(contract_fields, import_cfg, indent=8)
    lines.append(defaults_dict)

    # write_disabled guard.
    lines.append("")
    lines.append("        if self.write_disabled:")
    lines.append(
        f'            self.stats[{model_name!r}]["processed"] += 1'
    )
    lines.append("            continue")

    # Override hook: _prepare_row.
    lines.append("        data = self._prepare_row(defaults)")
    lines.append("")

    # update_or_create call.
    unique_kwargs = ", ".join(
        f"{f}={f}" for f in unique_on
    )
    lines.append(
        f"        obj, created = {model_name}.objects.update_or_create("
        f"{unique_kwargs}, defaults=data)"
    )
    lines.append(
        f'        self.stats[{model_name!r}]['
        f'"created" if created else "updated"] += 1'
    )
    lines.append("        self._before_save(obj, data)")

    result = "\n".join(lines)
    if indent:
        pad = " " * indent
        result = pad + result.replace("\n", "\n" + pad)
    return result


def render_import_py(
    contract: dict[str, Any],
    app_label: str = "core",
) -> str:
    """Render a complete import management command source file.

    The output is a ``BaseImportCommand`` subclass with one ``_import_*``
    method per table that has an ``import_config`` block in the contract.

    Args:
        contract: Normalised schema-contract dict (v1.0 or v1.1).  Only
            tables with a non-empty ``import_config`` block are emitted.
        app_label: Django app label for model imports and header comment.

    Returns:
        Complete ``import_{app_label}.py`` source text.
    """
    tables = list(contract.get("tables") or [])

    # Collect models with import config, sorted by tier then name.
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for table in tables:
        cfg = get_import_config(table)
        if cfg is None:
            continue
        name = get_model_name(table)
        tier = int(cfg.get("tier", 99))
        candidates.append((tier, name, table))

    candidates.sort(key=lambda x: (x[0], x[1]))

    base_class_name = f"GeneratedImport{app_label.capitalize()}"

    if not candidates:
        # Render a valid (empty) command stub with no import methods.
        return (
            "# Generated by migration-workbench codegen \u2014 hand-editable\n"
            f"# App label: {app_label}\n"
            "# Last generated: see git history\n"
            "\n"
            "from typing import Any\n"
        "from importer.base import BaseImportCommand\n"
            "\n"
            "\n"
            f"class {base_class_name}(BaseImportCommand):\n"
            f'    help = "Import {app_label} data from normalized bundles."\n'
            "\n"
            "    def _run_import_pipeline(self):\n"
            "        pass\n"
            "\n"
            "\n"
            f"class Command({base_class_name}):\n"
            "    pass\n"
        )

    model_names = sorted({name for _, name, _ in candidates})

    # File header.
    parts = [
        "# Generated by migration-workbench codegen \u2014 hand-editable",
        f"# App label: {app_label}",
        "# Last generated: see git history",
        "",
        "from typing import Any",
        "from importer.base import BaseImportCommand",
        f"from {app_label}.models import {', '.join(model_names)}",
        "",
        "",
        f"class {base_class_name}(BaseImportCommand):",
        f'    help = "Import {app_label} data from normalized bundles."',
        "",
        "    # -- Override hooks ---------------------------------------------------",
        "",
        "    def _prepare_row(self, data: dict) -> dict:",
        '        """Hook: transform the defaults dict before update_or_create."""',
        "        return data",
        "",
        "    def _before_save(self, obj, data: dict) -> None:",
        '        """Hook: called after each update_or_create."""',
        "        pass",
        "",
    ]

    # Add _prepare_<field> stubs for each model.
    seen_prepare_stubs: set[str] = set()
    for _, name, table in candidates:
        for f in get_fields(table):
            fname = f["name"]
            if fname not in seen_prepare_stubs:
                parts.append(
                    f"    def _prepare_{fname}(self, raw_value, row) -> Any:"
                )
                parts.append(
                    f'        """Hook: transform a single raw value before assignment."""'
                )
                parts.append("        return raw_value")
                parts.append("")
                seen_prepare_stubs.add(fname)

    # _run_import_pipeline with tier calls.
    parts.append("    def _run_import_pipeline(self):")
    seen_tiers: set[int] = set()
    for tier, name, _ in candidates:
        if tier not in seen_tiers:
            parts.append(f'        self.tier("TIER {tier}: {name}s", self._import_{name.lower()})')
            seen_tiers.add(tier)
        # If same tier as previous, add without tier heading.
    parts.append("")

    # Per-model import methods.
    for _, name, table in candidates:
        fields = get_fields(table)
        cfg = get_import_config(table)
        parts.append(_render_import_method(name, fields, cfg))

    parts.append("")
    parts.append("")
    parts.append(f"class Command({base_class_name}):")
    parts.append(f'    """Concrete import command for {app_label}.  Hand-editable."""')
    parts.append("    pass")
    parts.append("")
    return "\n".join(parts)
