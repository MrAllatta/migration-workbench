"""Build schema contract dicts from bundle config + profiler JSON artifacts."""

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
    return json.loads(path.read_text(encoding="utf-8"))


def model_name_from_output_path(output_path: str) -> str:
    base = Path(output_path).stem
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", base)
    return s.lower() or "model"


def index_tables_from_doc_profile(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """table name -> { columns: [ {name, format_type, ...} ] }"""
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
    """Returns (table_name, column_name -> profiler summary column dict)."""
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
    """
    bundle_config: live-config / pull_bundle JSON with tabs[].
    doc_profile: optional profile_coda_doc root JSON.
    table_profiles: map worksheet_title -> raw profile_coda_table JSON payload.
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
