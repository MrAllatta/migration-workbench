"""Coda.io REST API helpers (v1) shared by CodaAdapter and profiler commands."""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.parse import urlparse

import requests

CODA_API_BASE = "https://coda.io/apis/v1"


def extract_coda_doc_id(value: str | None) -> str | None:
    """Resolve a Coda doc id from a share URL or return a raw id string.

    Share links look like ``https://coda.io/d/<slug>_<docId>``; the API doc id
    is the segment after the last underscore in the path component after ``/d/``.
    """
    if not value:
        return None
    text = str(value).strip()
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        parts = [p for p in parsed.path.split("/") if p]
        if "d" in parts:
            idx = parts.index("d")
            if idx + 1 < len(parts):
                slug = parts[idx + 1]
                if "_" in slug:
                    return slug.rsplit("_", 1)[-1]
                return slug
        return None
    return text


def build_coda_session(api_token: str | None = None) -> requests.Session:
    token = api_token or os.environ.get("CODA_API_TOKEN")
    if not token:
        raise ValueError("Coda API token required: set CODA_API_TOKEN or pass api_token=")
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


def list_columns(session: requests.Session, doc_id: str, table_id: str) -> list[dict[str, Any]]:
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


def rows_to_grid(table_columns: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[list[str]]:
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
