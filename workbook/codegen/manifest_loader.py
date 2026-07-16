"""View manifest loader — load, normalise, and convert view-manifest.yaml
entries into ListArchetype configs for the view codegen pipeline.

The view manifest is the authoritative map of spreadsheet tabs to Django
views.  This module bridges the gap between the YAML manifest format
and the :class:`workbook.codegen.list_generator.ListArchetype` dataclass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from workbook.codegen.list_generator import ListArchetype


def load_view_manifest(path: str | Path) -> list[dict[str, Any]]:
    """Load a view-manifest.yaml file and return its view entries.

    Each entry is a dict with keys: ``name``, ``entity``, ``source_tab``,
    ``type``, ``filterable_by``, ``status_field``, ``time_scope``,
    ``editable_fields``, ``workflow_hints``.

    Args:
        path: Path to view-manifest.yaml.

    Returns:
        List of view entry dicts, normalised with defaults for missing
        optional fields.

    Raises:
        FileNotFoundError: If the manifest file does not exist.
        ValueError: If the YAML is malformed or has no ``views`` key.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"View manifest not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    if not data or "views" not in data:
        raise ValueError(f"View manifest at {path} has no 'views' key")

    views = data["views"]
    if not isinstance(views, list):
        raise ValueError(
            f"View manifest 'views' must be a list, got {type(views).__name__}"
        )

    # Normalise each entry: ensure all optional fields exist
    normalized: list[dict[str, Any]] = []
    for entry in views:
        norm = {
            "name": entry.get("name", ""),
            "entity": entry.get("entity", ""),
            "source_tab": entry.get("source_tab", ""),
            "type": entry.get("type", "list"),
            "filterable_by": entry.get("filterable_by", []),
            "status_field": entry.get("status_field"),
            "time_scope": entry.get("time_scope"),
            "editable_fields": entry.get("editable_fields", []),
            "workflow_hints": entry.get("workflow_hints", {}),
        }
        normalized.append(norm)

    return normalized


def _derive_model_name(entity: str) -> str:
    """Convert a snake_case entity key to a CamelCase model name.

    Examples:
        ``"field_block"`` → ``"FieldBlock"``
        ``"crop"`` → ``"Crop"``
        ``"sales_plan"`` → ``"SalesPlan"``
    """
    if not entity:
        return ""
    parts = entity.replace("-", "_").split("_")
    return "".join(p.capitalize() for p in parts if p)


def _derive_columns(entity: str, model_name: str) -> list[str]:
    """Return default display columns for a manifest entry.

    Uses heuristics based on entity type.  The caller should override
    with contract-derived columns for production use.
    """
    return ["name"]


def manifest_to_list_archetype(
    manifest_entry: dict[str, Any],
    model_name: str | None = None,
    contract_tables: dict[str, dict[str, Any]] | None = None,
) -> ListArchetype:
    """Convert a view-manifest entry into a ``ListArchetype``.

    The archetype is configured from the manifest entry's fields:

    * ``entity`` → ``model`` (via ``model_name`` parameter or CamelCase derivation)
    * ``filterable_by`` → ``filters``
    * ``name`` / ``source_tab`` → ``title``
    * ``time_scope`` (year_field, week_field) → included in ``ordering``
    * Contract table columns → ``columns`` (overrides entity-type defaults)

    Args:
        manifest_entry: A single view entry dict from ``load_view_manifest``.
        model_name: Explicit model name override.  If not provided, derived
            from the entry's ``entity`` key.
        contract_tables: Optional dict mapping ``suggested_model_name`` to a
            dict with ``columns`` list.  Used to infer display columns.

    Returns:
        A fully populated ``ListArchetype``.

    Raises:
        ValueError: If ``model_name`` is not provided and cannot be derived
            from the entry's entity.
    """
    entity = manifest_entry.get("entity", "") or ""
    name = manifest_entry.get("name", "")
    source_tab = manifest_entry.get("source_tab", "")
    filterable_by: list[str] = manifest_entry.get("filterable_by", [])
    time_scope: dict | None = manifest_entry.get("time_scope")

    # Resolve model name
    resolved_model = model_name or _derive_model_name(entity)
    if not resolved_model:
        raise ValueError(
            f"Cannot determine model name for manifest entry '{name}': "
            f"entity='{entity}' and no model_name override"
        )

    # Title from source_tab or name
    title = source_tab if source_tab else name.replace("_", " ").title()

    # Columns from contract_tables or entity-type defaults
    columns: list[str] = []
    if contract_tables and resolved_model in contract_tables:
        col_data = contract_tables[resolved_model]
        if isinstance(col_data, dict) and "columns" in col_data:
            columns = [
                c["column_name"] for c in col_data["columns"] if isinstance(c, dict)
            ]
    if not columns:
        columns = _derive_columns(entity, resolved_model)

    # Ordering: add time_scope fields, fallback to id
    ordering: list[str] = []
    if time_scope:
        if "year_field" in time_scope:
            ordering.append(str(time_scope["year_field"]))
        if "week_field" in time_scope:
            ordering.append(str(time_scope["week_field"]))
    if not ordering:
        ordering = ["name"]

    # Pagination
    paginate_by = 50

    # Context object name: snake_case plural
    snake_parts = []
    for char in resolved_model:
        if char.isupper() and snake_parts:
            snake_parts.append("_")
        snake_parts.append(char.lower())
    snake_name = "".join(snake_parts)
    if snake_name.endswith("y"):
        context_object_name = f"{snake_name[:-1]}ies"
    elif snake_name.endswith("s"):
        context_object_name = snake_name
    else:
        context_object_name = f"{snake_name}s"

    return ListArchetype(
        model=resolved_model,
        title=title,
        columns=columns,
        filters=filterable_by,
        ordering=ordering,
        paginate_by=paginate_by,
        context_object_name=context_object_name,
    )
