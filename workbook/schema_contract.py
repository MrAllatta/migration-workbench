"""Build schema contract dicts from bundle config and profiler JSON artifacts.

A *schema contract* is a JSON document (schema version ``"1.0"``) that maps
every worksheet tab in a bundle config to:

* A suggested Django model name.
* An ordered list of columns, each annotated with a suggested Django field
  class, kwargs, and advisory notes produced by
  :func:`~workbook.field_mapping.map_profiler_column_to_django_field`.

The contract is consumed by ``scaffold_workbook_schema`` to generate a model
skeleton that a developer then reviews and adjusts before writing migrations.

**Typical call sequence**::

    bundle   = load_json(Path("configs/my_bundle.json"))
    doc_prof = load_json(Path("build/_out/profile_doc.json"))
    contract = build_contract(bundle, doc_profile=doc_prof)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from workbook.field_mapping import (
    map_profiler_column_to_django_field,
    merge_bundle_headers,
    suggested_field_name,
)


def load_json(path: Path) -> Any:
    """Read and parse a UTF-8 JSON file.

    Args:
        path: Filesystem path to the JSON file.

    Returns:
        Any: Parsed Python object (typically ``dict`` or ``list``).
    """
    return json.loads(path.read_text(encoding="utf-8"))


def model_name_from_output_path(output_path: str) -> str:
    """Derive a snake_case model name from a bundle ``output_path`` value.

    Strips the file extension, replaces non-alphanumeric characters with
    underscores, and lowercases the result.

    Args:
        output_path: Bundle tab ``output_path`` string (e.g.
            ``"data/crops.csv"``).

    Returns:
        str: Suggested Django model name (e.g. ``"crops"``), or ``"model"``
        if the stem is empty after sanitising.

    Example::

        >>> model_name_from_output_path("data/crop_blocks.csv")
        'crop_blocks'
    """
    base = Path(output_path).stem
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", base)
    return s.lower() or "model"


def index_tables_from_doc_profile(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index a ``profile_coda_doc`` payload by table name.

    Args:
        doc: Root dict from a ``profile_coda_doc`` JSON artifact.  Expected to
            contain a ``"tables"`` list, each entry with ``"name"``/``"id"``
            and ``"columns"`` keys.

    Returns:
        dict[str, dict]: Mapping from table name to
        ``{"columns": [...], "by_name": {col_name: col_dict}}``.
    """
    out: dict[str, dict[str, Any]] = {}
    for t in doc.get("tables") or []:
        name = str(t.get("name") or t.get("id") or "")
        cols = t.get("columns") or []
        col_meta = {}
        for c in cols:
            cn = str(c.get("name") or "")
            if cn:
                col_meta[cn] = c
        out[name] = {"columns": cols, "by_name": col_meta}
    return out


def index_table_profile(payload: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    """Extract the table name and column index from a ``profile_coda_table`` artifact.

    Args:
        payload: Root dict from a ``profile_coda_table`` JSON artifact.
            Expected to contain a ``"summary"`` sub-dict with ``"table_name"``
            and ``"columns"`` keys.

    Returns:
        tuple[str, dict[str, dict]]: ``(table_name, {col_name: col_dict})``
        where *col_dict* is the raw profiler column summary.
    """
    summary = payload.get("summary") or {}
    table_name = str(summary.get("table_name") or "")
    col_meta: dict[str, dict[str, Any]] = {}
    for c in summary.get("columns") or []:
        n = str(c.get("name") or "")
        if n:
            col_meta[n] = c
    return table_name, col_meta


def build_contract(
    bundle_config: dict[str, Any],
    *,
    doc_profile: dict[str, Any] | None = None,
    table_profiles: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a schema contract dict from a bundle config and optional profiler data.

    Column metadata is resolved in this order of preference:

    1. Per-table profiler artifact in *table_profiles* (most specific).
    2. Doc-level profiler artifact in *doc_profile*.
    3. Required-headers stub (if neither profiler source has data for a tab).

    Args:
        bundle_config: Live-config or ``pull_bundle`` JSON with a ``"tabs"``
            list.  Each tab entry should include at minimum
            ``"worksheet_title"``, ``"output_path"``, and
            ``"required_headers"``.
        doc_profile: Optional root dict from a ``profile_coda_doc`` artifact.
            Provides document-level column metadata for all tables.
        table_profiles: Optional ``{worksheet_title: profile_coda_table_payload}``
            mapping.  Takes precedence over *doc_profile* for the matched table.

    Returns:
        dict: Schema contract conforming to version ``"1.0"``::

            {
                "version": "1.0",
                "source": {"provider": ..., "doc_url": ..., ...},
                "tables": [
                    {
                        "bundle_worksheet_title": "...",
                        "suggested_model_name": "...",
                        "bundle_output_path": "...",
                        "columns": [
                            {
                                "source_column": "...",
                                "suggested_field_name": "...",
                                "profiler_format_type": ...,
                                "has_formula": ...,
                                "django_field_class": "...",
                                "django_field_kwargs": {...},
                                "notes": [...],
                            },
                            ...
                        ],
                    },
                    ...
                ],
            }
    """
    doc_tables = index_tables_from_doc_profile(doc_profile) if doc_profile else {}

    contract_tables: list[dict[str, Any]] = []
    tabs = bundle_config.get("tabs") or []

    for tab in tabs:
        title = str(tab.get("worksheet_title") or "")
        output_path = str(tab.get("output_path") or "")
        required = list(tab.get("required_headers") or [])

        tp = (table_profiles or {}).get(title)
        col_meta: dict[str, dict[str, Any]] = {}

        if tp:
            _, col_meta = index_table_profile(tp)
        elif title in doc_tables:
            col_meta = dict(doc_tables[title]["by_name"])
        else:
            col_meta = {}

        # Fall back to stubs from required_headers when no profiler data exists.
        if not col_meta and required:
            for rh in required:
                col_meta[rh] = {"name": rh, "format_type": None}

        merged_cols = merge_bundle_headers(col_meta, required)
        django_columns: list[dict[str, Any]] = []
        for col in merged_cols:
            src = str(col.get("name") or "")
            hint = map_profiler_column_to_django_field(col)
            django_columns.append(
                {
                    "source_column": src,
                    "suggested_field_name": suggested_field_name(src),
                    "profiler_format_type": col.get("format_type"),
                    "has_formula": col.get("has_formula"),
                    "django_field_class": hint["django_field_class"],
                    "django_field_kwargs": hint["django_field_kwargs"],
                    "notes": hint.get("notes") or [],
                }
            )

        contract_tables.append(
            {
                "bundle_worksheet_title": title,
                "suggested_model_name": model_name_from_output_path(output_path),
                "bundle_output_path": output_path,
                "columns": django_columns,
            }
        )

    return {
        "version": "1.0",
        "source": {
            "provider": bundle_config.get("provider"),
            "doc_url": bundle_config.get("doc_url"),
            "doc_id": bundle_config.get("doc_id"),
            "source_id": bundle_config.get("source_id"),
        },
        "tables": contract_tables,
    }
