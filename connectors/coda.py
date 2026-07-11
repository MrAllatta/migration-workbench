"""Coda provider adapter implementing the ``ProviderAdapter`` interface.

``CodaAdapter`` fetches tab rows and structure from Coda documents via the
Coda API, normalizing them into the row/structure format expected by the
profiler and importer pipeline.
"""

from connectors.base import ProviderAdapter
from connectors.tab_name_utils import sanitize_tab_name
from connectors.coda_source import (
    build_coda_session,
    classify_formula_columns,
    column_has_formula,
    extract_relation_columns,
    list_columns,
    list_rows,
    list_tables,
    resolve_doc_id,
    rows_to_grid,
)


def shape_coda_table_structure(
    table_meta: dict | None,
    columns: list[dict],
    *,
    table_id: str,
    table_name: str,
    table_position: int | None = None,
) -> dict:
    """Shape Coda table + column metadata into a ``structure-draft-1`` tab dict.

    Mirrors :func:`connectors.google_provider.shape_sheet_structure` so
    downstream consumers see a uniform per-tab shape regardless of provider.
    Coda has no concept of frozen panes or filter views at the API level we
    consume, so those keys are present but defaulted/empty.

    Args:
        table_meta: Optional table metadata dict from
            :func:`connectors.coda_source.list_tables` (provides ``rowCount``,
            ``columnCount``, ``type``).
        columns: Column list from :func:`connectors.coda_source.list_columns`.
        table_id: Resolved table id.
        table_name: Resolved table or view name.
        table_position: Position of the table within ``list_tables`` order, if
            known.

    Returns:
        dict: Per-tab structure entry conforming to ``structure-draft-1``.
    """
    meta = table_meta or {}
    shaped_columns = []
    for idx, col in enumerate(columns):
        format_block = col.get("format") or {}
        shaped_columns.append(
            {
                "index": idx,
                "header_label": col.get("name") or "",
                "is_formula": column_has_formula(col),
                "data_validation_type": format_block.get("type"),
                "coda_column_id": col.get("id"),
            }
        )
    relation_columns = extract_relation_columns(columns)
    formula_classifications = classify_formula_columns(columns)
    return {
        "worksheet_title": sanitize_tab_name(table_name),
        "tab_position": table_position,
        "hidden": False,
        "frozen_rows": 0,
        "frozen_cols": 0,
        "total_rows": meta.get("rowCount"),
        "total_cols": meta.get("columnCount") or (len(columns) or None),
        "columns": shaped_columns,
        "relation_columns": relation_columns,
        "formula_classifications": formula_classifications,
        "named_ranges": [],
        "filter_views": [],
        "coda_table_id": table_id,
        "coda_table_type": meta.get("type"),
        "coda_parent_table_id": (meta.get("parentTable") or {}).get("id"),
    }


class CodaAdapter(ProviderAdapter):
    """Coda provider adapter for the profiler/importer pipeline."""

    def __init__(self, config: dict):
        """Initialize the adapter from a source config dict. Validates API token and resolves the document."""
        self.config = config
        self.session = build_coda_session(config.get("api_token"))
        raw = config.get("doc_url") or config.get("doc_id")
        self.doc_id = resolve_doc_id(self.session, raw) if raw else None
        if not self.doc_id:
            raise ValueError("CodaAdapter requires doc_url or doc_id")
        self._tables_by_name: dict[str, dict] | None = None
        self._tables_by_id: dict[str, dict] | None = None
        self._tables_order: list[str] | None = None

    def _ensure_table_index(self):
        """Build an internal lookup index mapping table names to table metadata dicts."""
        if self._tables_by_name is None:
            tables = list_tables(self.session, self.doc_id)
            self._tables_by_name = {t["name"]: t for t in tables if t.get("name")}
            self._tables_by_id = {t["id"]: t for t in tables if t.get("id")}
            self._tables_order = [t.get("id") for t in tables if t.get("id")]

    def _resolve_table(self, tab_config: dict):
        """Resolve a tab config entry to a Coda table, returning the table metadata dict."""
        if tab_config.get("table_id"):
            tid = tab_config["table_id"]
            return (
                tid,
                tab_config.get("table_name")
                or tab_config.get("worksheet_title")
                or tid,
            )
        name = tab_config.get("table_name") or tab_config.get("worksheet_title")
        if not name:
            raise ValueError(
                "Coda tab entry needs table_id, table_name, or worksheet_title"
            )
        self._ensure_table_index()
        if name not in self._tables_by_name:
            raise ValueError(f"Coda table {name!r} not found in doc {self.doc_id}")
        meta = self._tables_by_name[name]
        return meta["id"], meta["name"]

    def fetch_tab_rows(self, tab_config: dict) -> dict:
        """Fetch rows from a Coda table identified by *tab_config*. Returns a dict with ``rows`` and ``headers`` keys."""
        table_id, table_name = self._resolve_table(tab_config)
        columns = list_columns(self.session, self.doc_id, table_id)
        max_rows = tab_config.get("max_rows")
        if max_rows is None:
            max_rows = self.config.get("max_rows")
        max_rows_i = int(max_rows) if max_rows is not None else None
        vf = tab_config.get("value_format") or self.config.get("value_format") or "rich"
        rows = list_rows(
            self.session,
            self.doc_id,
            table_id,
            max_rows=max_rows_i,
            value_format=str(vf),
        )
        grid = rows_to_grid(columns, rows)
        return {
            "rows": grid,
            "spreadsheet_id": self.doc_id,
            "spreadsheet_name": self.config.get("doc_name") or self.doc_id,
            "modified_time": None,
            "worksheet_title": table_name,
            "drive_folder_id": None,
        }

    def fetch_tab_structure(self, tab_config: dict) -> dict | None:
        """Fetch and shape Coda table metadata into a ``structure-draft-1`` entry."""
        table_id, table_name = self._resolve_table(tab_config)
        self._ensure_table_index()
        table_meta = (self._tables_by_id or {}).get(table_id)
        position: int | None = None
        if self._tables_order is not None and table_id in self._tables_order:
            position = self._tables_order.index(table_id)
        columns = list_columns(self.session, self.doc_id, table_id)
        return shape_coda_table_structure(
            table_meta,
            columns,
            table_id=table_id,
            table_name=table_name,
            table_position=position,
        )
