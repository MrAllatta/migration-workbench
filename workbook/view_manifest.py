"""Build view-manifest dicts from a profiler ``structure.json`` artifact.

A *view manifest* is a sibling to the schema contract: it captures **UI and
workflow** concerns (which tab is read by whom, which fields are editable,
which column drives the status state machine) that the schema contract does
not own. The builder in this module produces a first-draft manifest from
structural inference; operators annotate the YAML during discovery and
downstream consumers (the admin scaffold generator) read the annotated artifact.

The schema-contract YAML is an optional secondary input. When provided, each
view's ``entity`` field binds to the contract's ``suggested_model_name`` and
``editable_fields`` reuse the contract's ``suggested_field_name`` so model
fields and form fields stay in sync.
"""

from __future__ import annotations

import re
from typing import Any

from workbook.field_mapping import suggested_field_name

VIEW_MANIFEST_VERSION = "view-manifest-draft-1"

# Headers that look like state machines: 'Status', 'state', 'Stage', etc.
# Whole-word match (case-insensitive) keeps obviously-unrelated headers out.
_STATUS_HEADER_RE = re.compile(r"^(status|state|stage)$", re.IGNORECASE)
_WEEK_FIELD_RE = re.compile(r".*_week$", re.IGNORECASE)
_DATE_FIELD_RE = re.compile(r".*_date$", re.IGNORECASE)


def _index_schema_contract_tables(
    contract: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Index a schema-contract dict by ``bundle_worksheet_title``.

    Args:
        contract: Schema-contract dict as produced by
            :func:`workbook.schema_contract.build_contract`, or ``None``.

    Returns:
        dict[str, dict]: Mapping from worksheet title to ``{"model": str,
        "field_by_source": {source_column: suggested_field_name}}``.  Empty
        when *contract* is ``None`` or has no ``tables`` list.
    """
    out: dict[str, dict[str, Any]] = {}
    if not contract:
        return out
    for table in contract.get("tables") or []:
        title = str(table.get("bundle_worksheet_title") or "")
        if not title:
            continue
        field_by_source: dict[str, str] = {}
        for col in table.get("columns") or []:
            src = str(col.get("source_column") or "")
            field = str(col.get("suggested_field_name") or "")
            if src and field:
                field_by_source[src] = field
        out[title] = {
            "model": str(table.get("suggested_model_name") or ""),
            "field_by_source": field_by_source,
            "columns": table.get("columns") or [],
        }
    return out


def _infer_status_field(columns: list[dict[str, Any]]) -> str | None:
    """Pick the first dropdown-validated column whose header looks state-y.

    Conservative on purpose: requires both a header name match (``status`` /
    ``state`` / ``stage``) and a non-null ``data_validation_type``. Tabs with
    ambiguous status conventions return ``None`` so the operator decides
    during discovery.

    Args:
        columns: ``columns`` list from a structure-tab entry.

    Returns:
        str | None: Slugified field name of the matched column, or ``None``.
    """
    for col in columns:
        header = str(col.get("header_label") or "").strip()
        dv_type = col.get("data_validation_type")
        if not header or dv_type is None:
            continue
        if _STATUS_HEADER_RE.match(header):
            return suggested_field_name(header)
    return None


def _resolve_field_name(
    source_column: str, field_by_source: dict[str, str] | None
) -> str:
    """Use the schema-contract slug when available, else compute one."""
    if field_by_source:
        mapped = field_by_source.get(source_column)
        if mapped:
            return mapped
    return suggested_field_name(source_column)


def _field_class_short(raw: str) -> str:
    """Strip the ``models.`` prefix from a Django field class string."""
    return raw.removeprefix("models.")


def _infer_time_scope(entity: str | None, contract_index: dict) -> dict | None:
    """Scan the matching contract table for temporal fields.

    Returns a dict with keys ``year_field``, ``week_field``, and/or
    ``date_field`` plus ``default_scope``, or ``None`` if no temporal
    columns are found for *entity*.
    """
    if not entity:
        return None
    for info in contract_index.values():
        if info.get("model") == entity:
            ts: dict[str, Any] = {}
            for col in info.get("columns") or []:
                name = col.get("suggested_field_name") or ""
                klass = _field_class_short(str(col.get("django_field_class") or ""))
                if name == "source_bundle_year":
                    ts["year_field"] = name
                elif _WEEK_FIELD_RE.match(name) and klass in ("IntegerField",):
                    ts["week_field"] = name
                elif _DATE_FIELD_RE.match(name) and klass in ("DateField", "DateTimeField"):
                    ts["date_field"] = name
            if ts:
                ts["default_scope"] = "current_season"
                return ts
    return None


def _build_view_entry(
    tab: dict[str, Any],
    contract_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Shape one structure-tab dict into a view-manifest ``views[]`` entry."""
    title = str(tab.get("worksheet_title") or "")
    columns = tab.get("columns") or []

    contract_match = contract_index.get(title)
    entity = (contract_match or {}).get("model") or None
    field_by_source = (contract_match or {}).get("field_by_source") or {}

    editable_fields: list[str] = []
    computed_fields: list[str] = []
    filterable_by: list[str] = []

    for col in columns:
        header = str(col.get("header_label") or "").strip()
        if not header:
            continue
        field = _resolve_field_name(header, field_by_source)
        if col.get("is_formula"):
            computed_fields.append(field)
        else:
            editable_fields.append(field)
        if col.get("data_validation_type") is not None:
            filterable_by.append(field)

    return {
        "name": suggested_field_name(title) if title else "view",
        "entity": entity,
        "source_tab": title,
        # ``list`` is the safe default; operator picks form/detail/dashboard
        # during discovery once they describe the view's role.
        "type": "list",
        "editable_fields": editable_fields,
        "computed_fields": computed_fields,
        "filterable_by": filterable_by,
        "status_field": _infer_status_field(columns),
        "notes": None,
    }


def _build_workflow_hints(tabs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute ``workflow_hints``: tab sequence + empty operator placeholders."""
    visible = [t for t in tabs if not t.get("hidden")]
    visible.sort(key=lambda t: (t.get("tab_position") if t.get("tab_position") is not None else 1_000_000))
    sequence = [str(t.get("worksheet_title") or "") for t in visible if t.get("worksheet_title")]
    return {
        "tab_sequence": sequence,
        "role_hints": [],
        "weekly_actions": [],
    }


def build_view_manifest(
    structure: dict[str, Any],
    *,
    schema_contract: dict[str, Any] | None = None,
    column_profiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``view-manifest-draft-1`` dict from a profiler structure artifact.

    The resulting manifest is a sibling artifact to the schema contract: the
    schema contract owns model/field definitions, this manifest owns UI and
    workflow concerns. Both are intended to be human-edited after generation.

    Args:
        structure: Parsed ``structure.json`` from
            ``pull_bundle --include-structure``.  Must include a ``"tabs"``
            list; ``source_id`` and ``provider`` are propagated when present.
        schema_contract: Optional parsed schema-contract dict.  When
            provided, ``entity`` binds per worksheet title
            and ``editable_fields`` reuse the contract's
            ``suggested_field_name`` slugs.
        column_profiles: Optional dict keyed by tab title then field name,
            each containing ``distinct_values`` for the status state machine.

    Returns:
        dict: View-manifest dict conforming to ``view-manifest-draft-1``::

            {
                "version": "...",
                "source": {"source_id": ..., "provider": ...},
                "views": [
                    {
                        "name": "...",
                        "entity": "..." | None,
                        "source_tab": "...",
                        "type": "list",
                        "editable_fields": [...],
                        "computed_fields": [...],
                        "filterable_by": [...],
                        "status_field": "..." | None,
                        "status_values": [...] | None,
                        "time_scope": {...} | None,
                        "notes": None,
                    },
                    ...
                ],
                "workflow_hints": {
                    "tab_sequence": [...],
                    "role_hints": [],
                    "weekly_actions": [],
                },
            }
    """
    tabs = list(structure.get("tabs") or [])
    contract_index = _index_schema_contract_tables(schema_contract)

    views = [_build_view_entry(tab, contract_index) for tab in tabs]

    for view in views:
        entity = view.get("entity")
        ts = _infer_time_scope(entity, contract_index)
        if ts is not None:
            view["time_scope"] = ts

    if column_profiles:
        for view in views:
            status_field = view.get("status_field")
            source_tab = view.get("source_tab")
            if status_field and source_tab:
                tab_profiles = column_profiles.get(source_tab) or {}
                col_profile = tab_profiles.get(status_field) or {}
                distinct = col_profile.get("distinct_values")
                if distinct:
                    view["status_values"] = list(distinct)

    workflow_hints = _build_workflow_hints(tabs)

    return {
        "version": VIEW_MANIFEST_VERSION,
        "source": {
            "source_id": structure.get("source_id"),
            "provider": structure.get("provider"),
        },
        "views": views,
        "workflow_hints": workflow_hints,
    }
