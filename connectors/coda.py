from connectors.base import ProviderAdapter
from connectors.coda_source import (
    build_coda_session,
    list_columns,
    list_rows,
    list_tables,
    resolve_doc_id,
    rows_to_grid,
)


class CodaAdapter(ProviderAdapter):
    def __init__(self, config: dict):
        self.config = config
        self.session = build_coda_session(config.get("api_token"))
        raw = config.get("doc_url") or config.get("doc_id")
        self.doc_id = resolve_doc_id(self.session, raw) if raw else None
        if not self.doc_id:
            raise ValueError("CodaAdapter requires doc_url or doc_id")
        self._tables_by_name: dict[str, dict] | None = None

    def _resolve_table(self, tab_config: dict):
        if tab_config.get("table_id"):
            tid = tab_config["table_id"]
            return tid, tab_config.get("table_name") or tab_config.get("worksheet_title") or tid
        name = tab_config.get("table_name") or tab_config.get("worksheet_title")
        if not name:
            raise ValueError("Coda tab entry needs table_id, table_name, or worksheet_title")
        if self._tables_by_name is None:
            tables = list_tables(self.session, self.doc_id)
            self._tables_by_name = {t["name"]: t for t in tables if t.get("name")}
        if name not in self._tables_by_name:
            raise ValueError(f"Coda table {name!r} not found in doc {self.doc_id}")
        meta = self._tables_by_name[name]
        return meta["id"], meta["name"]

    def fetch_tab_rows(self, tab_config: dict) -> dict:
        table_id, table_name = self._resolve_table(tab_config)
        columns = list_columns(self.session, self.doc_id, table_id)
        rows = list_rows(self.session, self.doc_id, table_id)
        grid = rows_to_grid(columns, rows)
        return {
            "rows": grid,
            "spreadsheet_id": self.doc_id,
            "spreadsheet_name": self.config.get("doc_name") or self.doc_id,
            "modified_time": None,
            "worksheet_title": table_name,
            "drive_folder_id": None,
        }
