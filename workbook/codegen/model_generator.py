"""Render Django ``models.py`` source from a schema-contract dict.

Usage from a management command::

    from workbook.codegen.contract import load_contract
    from workbook.codegen.model_generator import render_models_py

    contract = load_contract("build/schema-contract.yaml")
    source = render_models_py(contract, app_label="core")
    Path("backend/apps/core/models.py").write_text(source)
"""

from __future__ import annotations

from typing import Any

from workbook.codegen.contract import (
    get_computed_fields,
    get_db_table_name,
    get_enums,
    get_extra_imports,
    get_fields,
    get_hooks,
    get_is_abstract,
    get_model_base,
    get_model_meta,
    get_model_name,
    get_str_template,
)
from workbook.codegen.python_render import (
    get_and_clear_codegen_warnings,
    render_choices_class,
    render_computed_property,
    render_field,
    render_import_block,
    render_meta,
    render_str_method,
)


def render_model(
    table: dict[str, Any],
    app_label: str,
    enum_names: set[str] | None = None,
    rendered_model_names: set[str] | None = None,
) -> tuple[str, list[str]]:
    """Render a single Django model class as source text.

    Args:
        table: A single table entry from the schema contract.
        app_label: Django app label (used for ``db_table`` fallback and imports).
        enum_names: Set of known enum type names for field kwarg rendering.
        rendered_model_names: Set of already-rendered model names (for FK
            forward-reference detection).

    Returns:
        Complete model class source, including the leading blank line.
    """
    class_name = get_model_name(table)
    base_class = get_model_base(table)
    fields = get_fields(table)
    meta_options = dict(get_model_meta(table))
    str_template = get_str_template(table)
    is_abstract = get_is_abstract(table)
    computed_fields = get_computed_fields(table)

    if is_abstract:
        meta_options.pop("db_table", None)
        meta_options["abstract"] = True
    else:
        meta_options["db_table"] = get_db_table_name(table, app_label)

    lines: list[str] = []

    lines.append("")
    lines.append(f"class {class_name}({base_class}):")

    hooks = get_hooks(table)
    after_model = hooks.get("after_model", "").strip()
    if after_model:
        for line in after_model.split("\n"):
            lines.append(f"    {line}")
        lines.append("")

    for f in fields:
        lines.append(
            render_field(
                name=f["name"],
                field_class=f["class"],
                kwargs=f["kwargs"],
                indent=4,
                enum_names=enum_names,
                model_name=class_name,
                rendered_model_names=rendered_model_names,
            )
        )

    if not fields and not computed_fields and not after_model:
        lines.append("    pass")

    for cf in computed_fields:
        lines.append(
            render_computed_property(
                name=cf["name"],
                return_type=cf.get("return_type"),
                expression=cf.get("expression"),
                indent=4,
            )
        )

    rendered_meta = render_meta(meta_options, indent=4)
    if rendered_meta:
        lines.append(rendered_meta)

    after_meta = hooks.get("after_meta", "").strip()
    if after_meta:
        for line in after_meta.split("\n"):
            lines.append(f"    {line}")
        lines.append("")

    rendered_str = render_str_method(str_template, indent=4)
    if rendered_str:
        lines.append(rendered_str)

    extra = hooks.get("extra_methods", "").strip()
    if extra:
        for line in extra.split("\n"):
            lines.append(f"    {line}")
        lines.append("")

    return "\n".join(lines) + "\n", get_and_clear_codegen_warnings()


def render_models_py(
    contract: dict[str, Any], app_label: str = "core"
) -> tuple[str, list[str]]:
    """Render a complete ``models.py`` file from a schema contract.

    Args:
        contract: Normalised schema-contract dict (v1.0–v1.2).
        app_label: Django app label for generated models.

    Returns:
        Complete ``models.py`` source text, including import block, enum
        classes, model classes, and a trailing newline.
    """
    tables = list(contract.get("tables") or [])
    enums = get_enums(contract)

    # Collect all extra imports from all tables.
    all_extra_imports: list[str] = []
    seen_imports: set[str] = set()
    for table in tables:
        for imp in get_extra_imports(table):
            if imp not in seen_imports:
                all_extra_imports.append(imp)
                seen_imports.add(imp)

    parts: list[str] = [
        render_import_block(app_label, extra_imports=all_extra_imports or None),
    ]

    # Render enum choice classes after imports, before model classes.
    if enums:
        parts.append("")
    for enum_name, pairs in sorted(enums.items()):
        parts.append(render_choices_class(enum_name, pairs))

    # Track rendered model names for FK forward-reference detection.
    rendered_model_names: set[str] = set()
    for table in tables:
        rendered_model_names.add(get_model_name(table))

    all_warnings: list[str] = []
    for table in tables:
        part, warnings = render_model(
            table,
            app_label,
            enum_names=set(enums.keys()),
            rendered_model_names=rendered_model_names,
        )
        parts.append(part)
        all_warnings.extend(warnings)

    parts.append("")
    return "\n".join(parts), all_warnings
