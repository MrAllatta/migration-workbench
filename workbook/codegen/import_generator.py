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
    assign_import_tiers,
    get_fields,
    get_import_config,
    get_model_name,
)


# -- helpers ----------------------------------------------------------------


def _derive_column_map(table: dict[str, Any]) -> dict[str, str]:
    """Derive a column_map from ``columns[].source_column`` -> ``suggested_field_name``."""
    cmap: dict[str, str] = {}
    for col in table.get("columns") or []:
        src = col.get("source_column")
        fname = col.get("suggested_field_name")
        if src and fname:
            cmap[fname] = src
    return cmap


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
    return lookup.get(parser_name, '""') if parser_name else '""'


def _contract_has_year_bundle_path(contract: dict[str, Any]) -> bool:
    """Return True if any table's bundle_path contains {year}."""
    for table in contract.get("tables") or []:
        cfg = table.get("import_config")
        if cfg and "{year}" in (cfg.get("bundle_path") or ""):
            return True
    return False


def _render_resolve_years(indent: int = 4) -> str:
    """Render the _resolve_years method for year-loop imports."""
    pad = " " * indent
    lines = [
        "",
        f"{pad}def _resolve_years(self) -> list[int]:",
        f'{pad}    """Return years to import, from --year flag or filesystem discovery."""',
        f"{pad}    if self.years:",
        f"{pad}        return sorted(self.years)",
        f"{pad}    discovered = []",
        f"{pad}    for entry in Path(self.data_dir).iterdir():",
        f'{pad}        match = re.match(r"^year_(\\d{{4}})$", entry.name)',
        f"{pad}        if match and entry.is_dir():",
        f"{pad}            discovered.append(int(match.group(1)))",
        f"{pad}    if not discovered:",
        f"{pad}        from django.core.management.base import CommandError",
        f"{pad}        raise CommandError(",
        f'{pad}            f"No year_YYYY/ directories found in {{self.data_dir}}. "',
        f'{pad}            "Pass --year explicitly or run pull_bundle first."',
        f"{pad}        )",
        f"{pad}    return sorted(discovered)",
    ]
    return "\n".join(lines)


def _render_resolve_path(indent: int = 4) -> str:
    """Render the _resolve_path method for {year} placeholder substitution."""
    pad = " " * indent
    lines = [
        "",
        f"{pad}def _resolve_path(self, path_template: str, year: int):",
        f'{pad}    """Substitute {{year}} in a path template."""',
        f'{pad}    return path_template.format_map({{"year": year}})',
    ]
    return "\n".join(lines)


def _render_year_argument(indent: int = 8) -> str:
    """Render the --year argument for add_arguments."""
    pad = " " * indent
    lines = [
        f'{pad}parser.add_argument("--year", type=int, nargs="*", dest="years",',
        f'{pad}                    help="Years to import (default: auto-detect from data_dir)")',
    ]
    return "\n".join(lines)


def _render_run_import_pipeline_year_loop(
    tier_calls: list[str], indent: int = 4
) -> str:
    """Render _run_import_pipeline with year loop for multi-year imports."""
    pad = " " * indent
    inner_pad = " " * (indent + 4)
    lines = [
        "",
        f"{pad}def _run_import_pipeline(self):",
        f"{pad}    for year in self._resolve_years():",
        f"{pad}        self._run_year(year)",
        "",
        f"{pad}def _run_year(self, year: int):",
        f'{pad}    self.stdout.write(f"--- Importing year {{year}} ---")',
    ]
    for call in tier_calls:
        lines.append(f"{inner_pad}{call}")
    return "\n".join(lines)


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
            # Multi-source entries (list of headers) are handled in field
            # assignments, not passed to read_bundle_tab.
            if isinstance(source_header, list):
                continue
            map_lines.append(f"{inner}{inner}{field_name!r}: {source_header!r}")
        if map_lines:
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
            f"{pad * 2}self.record_missing_required("
            f"{model_name!r}, row_number, {req_field!r}, {human_label!r})\n"
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
        f"{pad * 2}self.record_missing_required("
        f"{model_name!r}, row_number, {field_name!r}, {human_label!r})\n"
        f"{pad * 2}continue"
    )
    resolve = (
        f"{pad}{field_name} = self._resolve_fk_by_text("
        f"{target_model}, {target_field!r}, {field_name}_val, {human_label!r})"
    )
    stale = (
        f"{pad}if {field_name} is None:\n"
        f"{pad * 2}self.record_stale_fk("
        f"{model_name!r}, row_number, {field_name!r}, {human_label!r}, {field_name}_val)\n"
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
            f"{_parser_method(parser)}(raw) if raw.strip() else None"
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
            f'{pad}{field_name} = {_parser_method(parser)}(row.get({field_name!r}, ""))'
        )
    else:
        return f'{pad}{field_name} = row.get({field_name!r}, "").strip()'


def _render_value_expression(
    field_name: str,
    field: dict[str, Any],
    import_cfg: dict[str, Any],
    indent: int = 10,
) -> tuple[str, str]:
    """Render a field value expression and optional pre-statements.

    For single-source fields the pre-statements string is empty and the
    value expression is a ``row.get(...)`` call (optionally wrapped in a
    parser like ``self._dec(...)``).

    For multi-source fields (``column_map`` entry is a list) the
    pre-statements assign ``parts_<field>`` and ``<field>`` variables
    before the ``defaults`` dict; the value expression is just the
    variable name.

    Returns:
        ``(pre_statements, value_expr)``. *pre_statements* is ``""``
        when no preparatory statements are needed.
    """
    column_map = import_cfg.get("column_map") or {}
    field_transforms = import_cfg.get("field_transforms") or {}
    field_parsers = import_cfg.get("field_parsers") or {}
    source_entry = column_map.get(field_name, field_name)

    # Multi-source: column_map value is a list of source headers.
    if isinstance(source_entry, list):
        pad = " " * indent
        parts_expr = ", ".join(f'row.get({h!r}, "").strip()' for h in source_entry)
        parts_var = f"{field_name}_parts"
        transform = field_transforms.get(field_name)
        if transform:
            code = (
                f"{pad}{parts_var} = [{parts_expr}]\n"
                f"{pad}{field_name} = "
                f"(lambda parts: {transform})({parts_var})"
            )
        else:
            code = (
                f"{pad}{parts_var} = [{parts_expr}]\n"
                f"{pad}{field_name} = "
                f'" ".join(p for p in {parts_var} if p)'
            )
        return (code, field_name)

    # Single source: read_bundle_tab remaps source headers to field names,
    # so use field_name (not source_header) as the row key.
    pad = " " * indent
    parser = field_parsers.get(field_name) or _infer_parser(field)

    if parser == "parse_date":
        pre = (
            f'{pad}raw_{field_name} = row.get({field_name!r}, "")\n'
            f"{pad}{field_name} = "
            f"self._parse_date(raw_{field_name}) "
            f"if raw_{field_name}.strip() else None"
        )
        return (pre, field_name)
    elif parser in ("dec", "int"):
        default = _default_value(parser)
        return (
            "",
            f'{_parser_method(parser)}(row.get({field_name!r}, ""), {default})',
        )
    elif parser == "bool":
        return (
            "",
            f'{_parser_method(parser)}(row.get({field_name!r}, ""))',
        )
    else:
        return (
            "",
            f'row.get({field_name!r}, "").strip()',
        )


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
    unique_on = set(import_cfg.get("unique_on") or [])

    pad = " " * indent
    inner = " " * (indent + 4)

    pre_statements: list[str] = []
    dict_entries: list[str] = []

    for field in contract_fields:
        fname = field["name"]
        if fname in fk_lookup or fname in unique_on:
            continue

        pre, val = _render_value_expression(fname, field, import_cfg, indent=indent)
        if pre:
            pre_statements.append(pre)
        dict_entries.append(f"{inner}{fname!r}: self._prepare_{fname}({val}, row),")

    parts: list[str] = []
    if pre_statements:
        parts.append("\n".join(pre_statements))
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
    unique_on = import_cfg.get("unique_on") or []

    pad = " " * indent
    parts: list[str] = []

    for fname in unique_on:
        if fname in fk_lookup:
            continue
        field = next((f for f in contract_fields if f["name"] == fname), None)
        if not field:
            continue

        pre, val = _render_value_expression(fname, field, import_cfg, indent=indent)
        if pre:
            parts.append(pre)
        else:
            parts.append(f"{pad}{fname} = {val}")

    return "\n".join(parts)


def _render_import_method(
    model_name: str,
    contract_fields: list[dict[str, Any]],
    import_cfg: dict[str, Any],
    indent: int = 4,
    year_aware: bool = False,
) -> str:
    """Render a single import tier method."""
    method_name = f"_import_{model_name.lower()}"
    bundle_path = import_cfg.get("bundle_path")
    if not bundle_path:
        raise ValueError(
            f"import_config.bundle_path is missing for table '{model_name}'. "
            f"Run scaffold_workbook_schema --hardened to auto-generate it, "
            f"or add bundle_path to each table's import_config."
        )
    unique_on = import_cfg.get("unique_on") or []
    required = import_cfg.get("required_source_columns") or []
    fk_lookup = import_cfg.get("fk_lookup") or {}
    _field_parsers = import_cfg.get("field_parsers") or {}  # noqa: F841

    # Build source_header mapping: column_map values, else field name.
    cmap = import_cfg.get("column_map") or {}
    source_headers: dict[str, str] = {}
    for fname in [f["name"] for f in contract_fields]:
        source_headers[fname] = cmap.get(fname, fname)

    tab_config = _render_tab_config(import_cfg, indent=0)

    if year_aware:
        method_sig = f"def {method_name}(self, year: int):"
    else:
        method_sig = f"def {method_name}(self):"

    lines = [
        "",
        method_sig,
        f"    tab_config = {tab_config}",
        "",
    ]

    # read_bundle_tab loop header.
    if year_aware:
        lines.append(
            f"    for row_number, row in self.read_bundle_tab(self._resolve_path({bundle_path!r}, year), tab_config):"
        )
    else:
        lines.append(
            f"    for row_number, row in self.read_bundle_tab({bundle_path!r}, tab_config):"
        )

    # Required field checks (skip FK fields — they get richer checks below).
    if required:
        lines.append("")
        lines.append("        # Required source column checks.")
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
                f"            self.record_missing_required("
                f"{model_name!r}, row_number, {req_field!r}, {human_label!r})"
            )
            lines.append("            continue")
            lines.append("")

    # FK resolutions.
    for fname, fk_cfg in sorted(fk_lookup.items()):
        target_model = fk_cfg.get("model", "TODO_Model")
        target_field = fk_cfg.get("on", "name")
        source_label = source_headers.get(fname, fname)
        human_label = source_label.replace("_", " ").title()
        lines.append(f'        {fname}_val = row.get({fname!r}, "").strip()')
        lines.append(f"        if not {fname}_val:")
        lines.append(
            f"            self.record_missing_required("
            f"{model_name!r}, row_number, {fname!r}, {human_label!r})"
        )
        lines.append("            continue")
        lines.append(
            f"        {fname} = self._resolve_fk_by_text("
            f"{target_model}, {target_field!r}, {fname}_val, {human_label!r})"
        )
        lines.append(f"        if {fname} is None:")
        lines.append(
            f"            self.record_stale_fk("
            f"{model_name!r}, row_number, {fname!r}, {human_label!r}, {fname}_val)"
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
    lines.append(f'            self.stats[{model_name!r}]["processed"] += 1')
    lines.append("            continue")

    # Override hook: _prepare_row.
    lines.append("        data = self._prepare_row(defaults)")
    lines.append("")

    # Per-row exception catching with IntegrityError discrimination.
    unique_kwargs = ", ".join(f"{f}={f}" for f in unique_on)
    lines.append("        try:")
    lines.append(
        f"            obj, created = {model_name}.objects.update_or_create("
        f"{unique_kwargs}, defaults=data)"
    )
    lines.append(
        f"            self.stats[{model_name!r}]["
        f'"created" if created else "updated"] += 1'
    )
    lines.append("            self._before_save(obj, data)")
    lines.append("        except IntegrityError:")
    lines.append(f'            self.stats[{model_name!r}]["error"] += 1')
    lines.append(
        f"            self.record_row_error({model_name!r}, row_number, "
        f'"unique_violation", "", "IntegrityError: unique constraint violation")'
    )
    lines.append("            continue")
    lines.append("        except Exception as exc:")
    lines.append(f'            self.stats[{model_name!r}]["error"] += 1')
    lines.append(
        f"            self.record_row_error({model_name!r}, row_number, "
        f'"row_exception", "", str(exc))'
    )

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
    # Tiers are auto-detected from FK dependency chains (explicit tiers
    # in the contract override auto-detection).
    tier_map = assign_import_tiers(contract)
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    skipped: list[str] = []
    for table in tables:
        name = get_model_name(table)
        cfg = get_import_config(table)
        if cfg is None:
            ws = table.get("bundle_worksheet_title") or "(no source tab)"
            skipped.append(f"# Skipped {name}: no import_config (worksheet: {ws})")
            continue
        cfg.setdefault("column_map", _derive_column_map(table))
        if not cfg.get("unique_on"):
            import_key = table.get("import_key") or {}
            key_fields = import_key.get("fields") or []
            if key_fields:
                cfg["unique_on"] = key_fields
        if not cfg.get("required_headers"):
            cmap = cfg.get("column_map") or {}
            unique_on = cfg.get("unique_on") or []
            derived = [cmap.get(f, f) for f in unique_on]
            if derived:
                cfg["required_headers"] = derived
        tier = tier_map.get(name, 99)
        candidates.append((tier, name, table))

    candidates.sort(key=lambda x: (x[0], x[1]))

    year_aware = _contract_has_year_bundle_path(contract)

    base_class_name = f"GeneratedImport{app_label.capitalize()}"

    if not candidates:
        # Render a valid (empty) command stub with no import methods.
        return (
            "# Generated by migration-workbench codegen \u2014 hand-editable\n"
            f"# App label: {app_label}\n"
            "# Last generated: see git history\n"
            "\n"
            "from typing import Any\n"
            "from django.db import IntegrityError\n"
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
    ]
    if skipped:
        parts.extend(skipped)
        parts.append("")
    import_lines = [
        "from typing import Any",
        "from django.db import IntegrityError",
        "from importer.base import BaseImportCommand",
        f"from {app_label}.models import {', '.join(model_names)}",
    ]
    if year_aware:
        import_lines.insert(0, "import re")
        import_lines.insert(1, "from pathlib import Path")
    import_lines.append("")
    parts.extend(import_lines)

    parts.extend(
        [
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
    )

    # Add _prepare_<field> stubs for each model.
    seen_prepare_stubs: set[str] = set()
    for _, name, table in candidates:
        for f in get_fields(table):
            fname = f["name"]
            if fname not in seen_prepare_stubs:
                parts.append(f"    def _prepare_{fname}(self, raw_value, row) -> Any:")
                parts.append(
                    '        """Hook: transform a single raw value before assignment."""'
                )
                parts.append("        return raw_value")
                parts.append("")
                seen_prepare_stubs.add(fname)

    # Conditionally add add_arguments for --year.
    if year_aware:
        parts.append("    def add_arguments(self, parser):")
        parts.append("        super().add_arguments(parser)")
        parts.append(_render_year_argument(indent=8))
        parts.append("")

    # Build tier calls.
    tier_calls: list[str] = []
    for tier, name, _ in candidates:
        if year_aware:
            tier_calls.append(
                f'self.tier("TIER {tier}: {name}s", lambda: self._import_{name.lower()}(year))'
            )
        else:
            tier_calls.append(
                f'self.tier("TIER {tier}: {name}s", self._import_{name.lower()})'
            )

    # _run_import_pipeline (year-loop or standard).
    if year_aware:
        parts.append(_render_run_import_pipeline_year_loop(tier_calls))
        parts.append(_render_resolve_years(indent=4))
        parts.append(_render_resolve_path(indent=4))
    else:
        parts.append("    def _run_import_pipeline(self):")
        for call in tier_calls:
            parts.append(f"        {call}")
    parts.append("")

    # Per-model import methods.
    for _, name, table in candidates:
        fields = get_fields(table)
        cfg = get_import_config(table) or {}
        parts.append(_render_import_method(name, fields, cfg, year_aware=year_aware))

    parts.append("")
    parts.append("")
    parts.append(f"class Command({base_class_name}):")
    parts.append(f'    """Concrete import command for {app_label}.  Hand-editable."""')
    parts.append("    pass")
    parts.append("")
    return "\n".join(parts)
