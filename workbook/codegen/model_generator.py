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
    get_db_table_name,
    get_fields,
    get_model_meta,
    get_model_name,
    get_str_template,
)
from workbook.codegen.python_render import (
    render_field,
    render_import_block,
    render_meta,
    render_str_method,
)


def render_model(table: dict[str, Any], app_label: str) -> str:
    """Render a single Django model class as source text.

    Args:
        table: A single table entry from the schema contract.
        app_label: Django app label (used for ``db_table`` fallback and imports).

    Returns:
        Complete model class source, including the leading blank line.
    """
    class_name = get_model_name(table)
    fields = get_fields(table)
    meta_options = dict(get_model_meta(table))
    str_template = get_str_template(table)

    # Always set db_table so every generated model has an explicit table name.
    meta_options["db_table"] = get_db_table_name(table, app_label)

    lines: list[str] = []

    lines.append("")
    lines.append(f"class {class_name}(models.Model):")

    for f in fields:
        lines.append(
            render_field(
                name=f["name"],
                field_class=f["class"],
                kwargs=f["kwargs"],
                indent=4,
            )
        )

    if not fields:
        lines.append("    pass")

    rendered_meta = render_meta(meta_options, indent=4)
    if rendered_meta:
        lines.append(rendered_meta)

    rendered_str = render_str_method(str_template, indent=4)
    if rendered_str:
        lines.append(rendered_str)

    return "\n".join(lines) + "\n"


def render_models_py(contract: dict[str, Any], app_label: str = "core") -> str:
    """Render a complete ``models.py`` file from a schema contract.

    Args:
        contract: Normalised schema-contract dict (v1.0 or v1.1).
        app_label: Django app label for generated models.

    Returns:
        Complete ``models.py`` source text, including import block, one
        ``class`` per contract table, and a trailing newline.
    """
    parts: list[str] = [
        render_import_block(app_label, extra_imports=None),
    ]

    for table in contract.get("tables") or []:
        parts.append(render_model(table, app_label))

    parts.append("")
    return "\n".join(parts)
