"""Build schema contract dicts from bundle config and profiler JSON artifacts.

A *schema contract* is a YAML/JSON document that maps every worksheet tab
in a bundle config to:

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

from profiler.tools.enrichment_utils import _to_pascal_case
from workbook.field_mapping import (
    map_profiler_column_to_django_field,
    merge_bundle_headers,
    suggested_field_name,
)


def _filter_section_headers(columns: list[dict]) -> list[dict]:
    """Remove section-header columns from a column list.

    A section header is identified by:
    - ``is_section_header`` flag set to True (from ColumnProfile), or
    - Header is ALL CAPS and the column has very few unique values.
    """
    filtered = []
    for col in columns:
        if col.get("is_section_header"):
            continue
        source = col.get("source_column") or col.get("suggested_field_name") or ""
        if source == source.upper() and len(source) > 2 and source.strip():
            unique_count = col.get("unique_count") or 0
            total_count = col.get("total_count") or col.get("non_empty_cells") or 0
            if total_count > 0 and unique_count <= 2:
                continue
        filtered.append(col)
    return filtered


def _compute_fk_resolutions(tables: list[dict]) -> list[dict]:
    """Suggest FK resolutions from column overlap and cross-sheet refs."""
    fk_candidates = []
    for i, table in enumerate(tables):
        source_cols = {}
        for c in table.get("columns", []):
            key = c.get("source_column") or c.get("suggested_field_name") or ""
            if key:
                source_cols[key] = c
        for j, other_table in enumerate(tables):
            if i == j:
                continue
            other_cols = {}
            for c in other_table.get("columns", []):
                key = c.get("source_column") or c.get("suggested_field_name") or ""
                if key:
                    other_cols[key] = c
            other_model = other_table.get("suggested_model_name", "")
            for col_name, col_def in source_cols.items():
                if col_name in other_cols:
                    other_col = other_cols[col_name]
                    unique_count = (
                        other_col.get("unique_count")
                        or other_col.get("non_empty_cells")
                        or 0
                    )
                    total = (
                        other_col.get("total_count")
                        or other_col.get("non_empty_cells")
                        or 0
                    )
                    if total > 0 and unique_count / total >= 0.8:
                        field_name = col_def.get(
                            "suggested_field_name"
                        ) or col_name.lower().replace(" ", "_")
                        target_field = other_col.get(
                            "suggested_field_name"
                        ) or col_name.lower().replace(" ", "_")
                        fk_candidates.append(
                            {
                                "field": field_name,
                                "target_model": other_model,
                                "target_field": target_field,
                                "confidence": (
                                    "high" if unique_count == total else "medium"
                                ),
                                "source": "column_overlap",
                            }
                        )
    for table in tables:
        for col in table.get("columns", []):
            for ref in col.get("cross_sheet_refs") or []:
                ref_name = (
                    ref[0] if isinstance(ref, list) else ref.get("sheet_name", "")
                )
                for other_table in tables:
                    other_model_slug = (
                        other_table.get("suggested_model_name", "")
                        .lower()
                        .replace(" ", "")
                    )
                    ref_slug = ref_name.lower().replace(" ", "")
                    if other_model_slug == ref_slug:
                        field_name = col.get("suggested_field_name") or (
                            col.get("source_column") or ""
                        ).lower().replace(" ", "_")
                        fk_candidates.append(
                            {
                                "field": field_name,
                                "target_model": other_table["suggested_model_name"],
                                "target_field": field_name,
                                "confidence": "medium",
                                "source": "cross_sheet_formula",
                            }
                        )
    seen = set()
    unique_fks = []
    for fk in fk_candidates:
        key = (fk["field"], fk["target_model"])
        if key not in seen:
            seen.add(key)
            unique_fks.append(fk)
    return unique_fks


_KEY_NAME_PATTERNS = {"sku", "code", "id", "name", "key", "number"}


def _slugify_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_") if header else ""


def _suggest_import_keys(columns: list[dict]) -> dict:
    """Suggest import_key fields based on uniqueness analysis."""
    candidates = []
    for col in columns:
        slug = (col.get("suggested_field_name") or "").lower()
        source = (col.get("source_column") or "").lower()
        unique_count = col.get("unique_count") or col.get("non_empty_cells") or 0
        total_count = col.get("total_count") or col.get("non_empty_cells") or 0
        if total_count == 0:
            continue
        ratio = unique_count / total_count
        is_key_name = any(p in slug for p in _KEY_NAME_PATTERNS) or any(
            p in source for p in _KEY_NAME_PATTERNS
        )
        if ratio >= 0.9 or (ratio >= 0.5 and is_key_name):
            candidates.append((slug, ratio, is_key_name))

    candidates.sort(key=lambda c: (-c[2], -c[1]))
    fields = [c[0] for c in candidates[:4]]
    if not fields:
        return {}
    high_conf = all(c[1] >= 0.9 for c in candidates[: len(fields)])
    return {
        "fields": fields,
        "confidence": "high" if high_conf else "medium",
        "note": "Autogenerated from uniqueness analysis \u2014 review recommended",
    }


def _add_source_bundle_year(tables: list[dict], year: int | None = None) -> list[dict]:
    """Add source_bundle_year field and default to each table if year is known."""
    if year is None:
        return tables
    for table in tables:
        if not any(
            c.get("suggested_field_name") == "source_bundle_year"
            for c in table.get("columns", [])
        ):
            table["columns"].append(
                {
                    "suggested_field_name": "source_bundle_year",
                    "source_column": "source_bundle_year",
                    "django_field_class": "models.IntegerField",
                    "django_field_kwargs": {"null": True, "blank": True},
                }
            )
        import_cfg = table.setdefault("import_config", {})
        defaults = import_cfg.setdefault("defaults", {})
        if "source_bundle_year" not in defaults:
            defaults["source_bundle_year"] = year
    return tables


def _compute_bundle_paths(tables: list[dict], year: int | None = None) -> list[dict]:
    """Generate import_config.bundle_path from bundle_worksheet_title."""
    for table in tables:
        title = table.get("bundle_worksheet_title") or table.get(
            "suggested_model_name", ""
        )
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        import_cfg = table.setdefault("import_config", {})
        if not import_cfg.get("bundle_path"):
            if year:
                import_cfg["bundle_path"] = f"{year}/{slug}.csv"
            else:
                import_cfg["bundle_path"] = f"{slug}.csv"
    return tables


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


def index_table_profile(
    payload: dict[str, Any],
) -> tuple[str, dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract the table name, column index, relation columns, and formula classifications from a ``profile_coda_table`` artifact.

    Args:
        payload: Root dict from a ``profile_coda_table`` JSON artifact.
            Expected to contain a ``"summary"`` sub-dict with ``"table_name"``
            and ``"columns"`` keys.

    Returns:
        tuple: ``(table_name, {col_name: col_dict}, relation_columns, formula_classifications)``
        where *col_dict* is the raw profiler column summary,
        *relation_columns* is the list from ``summary["relation_columns"]``,
        and *formula_classifications* is the list from ``summary["formula_classifications"]``.
    """
    summary = payload.get("summary") or {}
    table_name = str(summary.get("table_name") or "")
    col_meta: dict[str, dict[str, Any]] = {}
    for c in summary.get("columns") or []:
        n = str(c.get("name") or "")
        if n:
            col_meta[n] = c
    relation_columns = summary.get("relation_columns") or []
    formula_classifications = summary.get("formula_classifications") or []
    return table_name, col_meta, relation_columns, formula_classifications


def _resolve_coda_relation_target(
    relation: dict[str, Any],
    table_name_to_model: dict[str, str],
) -> str:
    """Resolve a Coda relation target to a Django model name.

    Uses the target table name from the Coda API when available,
    falling back to a TODO placeholder.  The *table_name_to_model*
    mapping is built from all bundle tabs so that lookups to tables
    in the same doc resolve cleanly.
    """
    target_table_name = relation.get("target_table_name")
    if target_table_name:
        # Coda table names may have spaces; normalise to PascalCase.
        model = _to_pascal_case(
            re.sub(r"[^a-zA-Z0-9_]+", "_", target_table_name.lower()).strip("_")
        )
        # If the resolved name matches another bundle tab, use it directly.
        if model in table_name_to_model.values():
            return model
        return model
    # No target table name exposed by the API.
    col_name = str(relation.get("column_name") or "")
    return f"TODO_{_to_pascal_case(re.sub(r'[^a-zA-Z0-9_]+', '_', col_name.lower()).strip('_'))}"


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
        dict: Schema contract dict::

            {
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

    # Build a mapping from normalised table name to model name for
    # cross-table relation resolution inside the same doc.
    table_name_to_model: dict[str, str] = {}
    for tab in tabs:
        title = str(tab.get("worksheet_title") or "")
        output_path = str(tab.get("output_path") or "")
        snake = model_name_from_output_path(output_path)
        table_name_to_model[_to_pascal_case(snake)] = _to_pascal_case(snake)

    for tab in tabs:
        title = str(tab.get("worksheet_title") or "")
        output_path = str(tab.get("output_path") or "")
        required = list(tab.get("required_headers") or [])

        tp = (table_profiles or {}).get(title)
        col_meta: dict[str, dict[str, Any]] = {}
        relation_columns: list[dict[str, Any]] = []
        formula_classifications: list[dict[str, Any]] = []

        if tp:
            _, col_meta, relation_columns, formula_classifications = index_table_profile(tp)
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
                    "formula_pattern": col.get("formula_pattern"),
                    "django_field_class": hint["django_field_class"],
                    "django_field_kwargs": hint["django_field_kwargs"],
                    "notes": hint.get("notes") or [],
                    "suggested_entity": col.get("suggested_entity"),
                    "suggested_fk_target": col.get("suggested_fk_target"),
                    "is_computed": col.get("is_computed", False),
                    "is_import_key_candidate": col.get(
                        "is_import_key_candidate", False
                    ),
                    "cross_tab_group": col.get("cross_tab_group"),
                }
            )

        django_columns = _filter_section_headers(django_columns)

        # Apply formula classification enrichment: mark expansion formulas as computed.
        if formula_classifications:
            col_by_source = {c["source_column"]: c for c in django_columns}
            for fc in formula_classifications:
                col_name = fc.get("column_name")
                if not col_name:
                    continue
                col_def = col_by_source.get(col_name)
                if col_def is None:
                    continue
                classification = fc.get("classification")
                confidence = fc.get("confidence")
                if classification == "expansion_formula":
                    col_def["is_computed"] = True
                    col_def["notes"].append(
                        f"coda_formula:{classification} (confidence:{confidence})"
                    )
                elif classification in ("row_formula", "hybrid"):
                    col_def["notes"].append(
                        f"coda_formula:{classification} (confidence:{confidence})"
                    )

        # Apply Coda relation column enrichment: upgrade lookup columns
        # to ForeignKey and build fk_resolutions.
        fk_resolutions: list[dict[str, Any]] = []
        if relation_columns:
            col_by_source: dict[str, dict[str, Any]] = {
                c["source_column"]: c for c in django_columns
            }
            for rel in relation_columns:
                col_name = rel.get("column_name")
                if not col_name:
                    continue
                col_type = rel.get("column_type")
                if col_type not in ("lookup", "linked_relation"):
                    continue
                col_def = col_by_source.get(col_name)
                if col_def is None:
                    # The relation column may not be in required_headers;
                    # still record the FK resolution so the human sees it.
                    target = _resolve_coda_relation_target(rel, table_name_to_model)
                    field_name = suggested_field_name(col_name)
                    fk_resolutions.append(
                        {
                            "field": field_name,
                            "target_model": target,
                            "target_field": "id",
                            "confidence": "high" if rel.get("target_table_name") else "medium",
                            "source": "coda_relation_column",
                        }
                    )
                    continue
                target = _resolve_coda_relation_target(rel, table_name_to_model)
                col_def["django_field_class"] = "models.ForeignKey"
                col_def["django_field_kwargs"] = {
                    "to": target,
                    "on_delete": "models.PROTECT",
                    "null": True,
                    "blank": True,
                }
                if "relation_target_todo" in str(col_def.get("notes", [])):
                    col_def["notes"] = [
                        n
                        for n in col_def.get("notes", [])
                        if not n.startswith("relation_target_todo")
                    ]
                col_def["notes"].append(f"coda_relation:{rel.get('column_type')}")
                field_name = col_def.get("suggested_field_name") or suggested_field_name(col_name)
                fk_resolutions.append(
                    {
                        "field": field_name,
                        "target_model": target,
                        "target_field": "id",
                        "confidence": "high" if rel.get("target_table_name") else "medium",
                        "source": "coda_relation_column",
                    }
                )

        snake_model = model_name_from_output_path(output_path)
        entry: dict[str, Any] = {
            "bundle_worksheet_title": title,
            "suggested_model_name": snake_model,
            "model_name": _to_pascal_case(snake_model),
            "bundle_output_path": output_path,
            "columns": django_columns,
        }
        if fk_resolutions:
            entry["fk_resolutions"] = fk_resolutions

        # Seed import_config for bundle-backed tables.
        if required:
            field_names = [
                c["suggested_field_name"]
                for c in django_columns
                if c.get("suggested_field_name")
            ]
            cmap = {
                c["suggested_field_name"]: c["source_column"]
                for c in django_columns
                if c.get("suggested_field_name")
            }
            first_col = field_names[0] if field_names else None
            entry["import_config"] = {
                "bundle_path": output_path,
                "required_headers": list(required),
                "unique_on": [first_col] if first_col else [],
                "column_map": cmap,
            }

        contract_tables.append(entry)

    return {
        "source": {
            "provider": bundle_config.get("provider"),
            "doc_url": bundle_config.get("doc_url"),
            "doc_id": bundle_config.get("doc_id"),
            "source_id": bundle_config.get("source_id"),
        },
        "tables": contract_tables,
    }
