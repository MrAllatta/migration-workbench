"""Coda.io REST API helpers (v1) shared by CodaAdapter and profiler commands."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import requests

CODA_API_BASE = "https://coda.io/apis/v1"
# Coda doc URLs embed the API doc id after "_d" in the /d/<segment> path (see coda.io/api doc ID help).
_DOC_ID_AFTER_D = re.compile(r"_d([\w-]+)$")


def _doc_segment_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if "d" not in parts:
        return None
    idx = parts.index("d")
    if idx + 1 >= len(parts):
        return None
    return parts[idx + 1]


def extract_coda_doc_id(value: str | None) -> str | None:
    """Resolve a Coda API doc id from a share URL or return a raw id string.

    Official pattern (Coda doc ID extractor): the id is the substring after ``_d``
    in the ``/d/<segment>`` path (e.g. ``..._dCMrB5f1AZE`` → ``CMrB5f1AZE``).

    If that pattern is missing, fall back to the segment after ``/d/``, then to
    the substring after the last underscore (legacy URLs).
    """
    if not value:
        return None
    text = str(value).strip()
    if text.startswith("http://") or text.startswith("https://"):
        segment = _doc_segment_from_url(text)
        if not segment:
            return None
        match = _DOC_ID_AFTER_D.search(segment)
        if match:
            return match.group(1)
        if "_" in segment:
            return segment.rsplit("_", 1)[-1]
        return segment
    return text


def resolve_doc_id_via_browser_link(
    session: requests.Session, share_url: str
) -> str | None:
    """Use ``GET /resolveBrowserLink`` to obtain a doc id when URL parsing is ambiguous."""
    params = {"url": share_url}
    data = _request_with_retry(
        session,
        "GET",
        f"{CODA_API_BASE}/resolveBrowserLink",
        params=params,
    )
    resource = data.get("resource") or {}
    if resource.get("type") == "doc":
        return resource.get("id")
    doc = resource.get("doc")
    if isinstance(doc, dict) and doc.get("id"):
        return doc.get("id")
    href = resource.get("href") or ""
    if "/docs/" in href:
        tail = href.split("/docs/", 1)[-1].strip("/").split("/", 1)[0]
        if tail:
            return tail
    return None


def resolve_doc_id(session: requests.Session, url_or_id: str) -> str | None:
    """Prefer ``resolveBrowserLink`` for HTTP URLs; otherwise parse or pass through raw id."""
    text = str(url_or_id).strip()
    if not text:
        return None
    if text.startswith("http://") or text.startswith("https://"):
        try:
            rid = resolve_doc_id_via_browser_link(session, text)
            if rid:
                return rid
        except requests.HTTPError:
            pass
    return extract_coda_doc_id(text)


def build_coda_session(api_token: str | None = None) -> requests.Session:
    token = api_token or os.environ.get("CODA_API_TOKEN")
    if not token:
        raise ValueError(
            "Coda API token required: set CODA_API_TOKEN or pass api_token="
        )
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    )
    return session


def _request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    max_retries: int = 8,
) -> dict[str, Any]:
    delay = 2.0
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = session.request(method, url, params=params, timeout=120)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 >= max_retries:
                    response.raise_for_status()
                time.sleep(delay)
                delay = min(delay * 1.6, 120.0)
                continue
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt + 1 >= max_retries:
                raise
            time.sleep(delay)
            delay = min(delay * 1.6, 120.0)
    if last_exc:
        raise last_exc
    return {}


def coda_list_paginated_items(
    session: requests.Session,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    max_retries: int = 8,
) -> list[dict[str, Any]]:
    """GET a Coda list endpoint and concatenate all ``items`` across pages."""
    base_params = dict(params or {})
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        page_params = dict(base_params)
        if page_token:
            page_params["pageToken"] = page_token
        data = _request_with_retry(
            session,
            "GET",
            f"{CODA_API_BASE}{path}",
            params=page_params,
            max_retries=max_retries,
        )
        items.extend(data.get("items") or [])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return items


def list_tables(session: requests.Session, doc_id: str) -> list[dict[str, Any]]:
    """List tables and views in a doc (Coda API returns both; no filter for compatibility)."""
    return coda_list_paginated_items(session, f"/docs/{doc_id}/tables", params=None)


def list_columns(
    session: requests.Session, doc_id: str, table_id: str
) -> list[dict[str, Any]]:
    return coda_list_paginated_items(
        session,
        f"/docs/{doc_id}/tables/{table_id}/columns",
        params={"format": "full"},
    )


def list_rows(
    session: requests.Session,
    doc_id: str,
    table_id: str,
    *,
    value_format: str = "rich",
    use_column_names: bool = True,
    max_rows: int | None = None,
) -> list[dict[str, Any]]:
    """List table rows with pagination. If *max_rows* is set, stop after that many rows."""
    rows: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        limit = 500
        if max_rows is not None:
            remaining = max_rows - len(rows)
            if remaining <= 0:
                break
            limit = min(500, remaining)
        params: dict[str, Any] = {
            "limit": str(limit),
            "useColumnNames": "true" if use_column_names else "false",
            "valueFormat": value_format,
        }
        if page_token:
            params["pageToken"] = page_token
        data = _request_with_retry(
            session,
            "GET",
            f"{CODA_API_BASE}/docs/{doc_id}/tables/{table_id}/rows",
            params=params,
        )
        batch = data.get("items") or []
        rows.extend(batch)
        if max_rows is not None and len(rows) >= max_rows:
            return rows[:max_rows]
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return rows


def get_doc(session: requests.Session, doc_id: str) -> dict[str, Any]:
    return _request_with_retry(session, "GET", f"{CODA_API_BASE}/docs/{doc_id}")


def get_whoami(session: requests.Session) -> dict[str, Any]:
    """Return the authenticated user/workspace identity (``GET /whoami``)."""
    return _request_with_retry(session, "GET", f"{CODA_API_BASE}/whoami")


def _extract_ref_table_from_cell(cell: Any) -> dict[str, str | None] | None:
    """If *cell* is a row reference, return ``{"tableId": ..., "tableName": ...}`` (names may be None)."""
    if not isinstance(cell, dict):
        return None
    inner = cell.get("value")
    if isinstance(inner, dict):
        add_type = str(inner.get("additionalType") or "").lower()
        if inner.get("tableId") and add_type in ("row", ""):
            return {
                "tableId": str(inner.get("tableId") or ""),
                "tableName": str(inner.get("table") or inner.get("tableName") or "")
                or None,
            }
        if inner.get("tableId"):
            return {
                "tableId": str(inner.get("tableId") or ""),
                "tableName": str(inner.get("table") or inner.get("tableName") or "")
                or None,
            }
    if cell.get("type") == "ref":
        tid = cell.get("tableId") or cell.get("table")
        if tid:
            return {
                "tableId": str(tid),
                "tableName": str(cell.get("tableName") or cell.get("name") or "")
                or None,
            }
    return None


def _classify_cell_for_analysis(cell: Any) -> tuple[str, dict[str, str | None] | None]:
    """Return (kind, optional_ref) where kind is plain | ref | empty | other."""
    if cell is None:
        return ("empty", None)
    if isinstance(cell, str):
        s = cell.strip()
        return ("empty", None) if not s else ("plain", None)
    if isinstance(cell, (int, float, bool)):
        return ("plain", None)
    if isinstance(cell, dict):
        ref = _extract_ref_table_from_cell(cell)
        if ref and ref.get("tableId"):
            return ("ref", ref)
        if "displayValue" in cell:
            dv = cell.get("displayValue")
            if dv is None or (isinstance(dv, str) and not str(dv).strip()):
                return ("empty", None)
            return ("plain", None)
        if cell.get("type") == "ref":
            return ("ref", ref)
        return ("other", None)
    return ("other", None)


def analyze_column_values(
    col_name: str,
    rows: list[dict[str, Any]],
    *,
    column_format_type: str | None = None,
) -> dict[str, Any]:
    """Aggregate null rate, cardinality sample, and cross-table refs for one column from row payloads."""
    total = len(rows)
    null_count = 0
    type_counts: dict[str, int] = {"plain": 0, "ref": 0, "empty": 0, "other": 0}
    ref_tables: dict[str, dict[str, str | None]] = {}
    fingerprints: set[str] = set()

    for row in rows:
        vals = row.get("values") or {}
        cell = vals.get(col_name)
        kind, ref = _classify_cell_for_analysis(cell)
        type_counts[kind] = type_counts.get(kind, 0) + 1
        if kind == "empty":
            null_count += 1
        if ref and ref.get("tableId"):
            tid = str(ref["tableId"])
            if tid not in ref_tables:
                ref_tables[tid] = {"tableId": tid, "tableName": ref.get("tableName")}
        fp = ""
        if cell is not None:
            if isinstance(cell, dict) and ref and ref.get("tableId"):
                rid = cell.get("value", {})
                row_id = ""
                if isinstance(rid, dict):
                    row_id = str(rid.get("rowId") or rid.get("id") or "")
                fp = f"ref:{ref['tableId']}:{row_id}"
            else:
                fp = _cell_to_str(cell).strip()
        fingerprints.add(fp if fp else "__EMPTY__")

    unique_count_sample = len(fingerprints)

    null_rate = float(null_count) / float(total) if total else 0.0
    is_relation_type = bool(
        column_format_type
        and str(column_format_type).lower() in ("lookup", "reference")
    )

    return {
        "null_count": null_count,
        "total": total,
        "null_rate": null_rate,
        "unique_count_sample": unique_count_sample,
        "value_type_counts": type_counts,
        "ref_tables_seen": sorted(
            ref_tables.values(), key=lambda x: x.get("tableId") or ""
        ),
        "is_relation_type": is_relation_type,
    }


def _cell_to_str(cell: Any) -> str:
    if cell is None:
        return ""
    if isinstance(cell, str):
        return cell
    if isinstance(cell, (int, float, bool)):
        return str(cell)
    if isinstance(cell, dict):
        if "displayValue" in cell and cell["displayValue"] is not None:
            return str(cell["displayValue"])
        if "value" in cell:
            v = cell["value"]
            if isinstance(v, dict):
                return json.dumps(v, sort_keys=True, default=str)
            return str(v)
        if cell.get("type") == "ref" and "name" in cell:
            return str(cell["name"])
        if cell.get("type") == "ref" and "id" in cell:
            return str(cell["id"])
        return json.dumps(cell, sort_keys=True, default=str)
    return str(cell)


def rows_to_grid(
    table_columns: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> list[list[str]]:
    """Flatten Coda rows into a rectangular grid (header row + data rows)."""
    if not table_columns:
        if not rows:
            return []
        first_values = (rows[0].get("values") or {}) if rows else {}
        header = list(first_values.keys())
        grid: list[list[str]] = [header]
        for row in rows:
            vals = row.get("values") or {}
            grid.append([_cell_to_str(vals.get(h)) for h in header])
        return grid

    header = [c.get("name") or c.get("id") or "" for c in table_columns]
    grid = [header]
    for row in rows:
        vals = row.get("values") or {}
        grid.append([_cell_to_str(vals.get(h)) for h in header])
    return grid


def column_has_formula(column: dict[str, Any]) -> bool:
    return bool(column.get("formula") or column.get("formulaText"))


def formula_text(column: dict[str, Any]) -> str:
    return str(column.get("formulaText") or column.get("formula") or "")
