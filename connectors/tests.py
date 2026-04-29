from unittest.mock import patch

from connectors.coda import CodaAdapter
from connectors.coda_source import extract_coda_doc_id, rows_to_grid
from connectors.google_sheets import extract_drive_folder_id, resolve_spreadsheet
from connectors.router import build_provider_adapter
from connectors.spreadsheet import normalize_rows, summarize_header_detection_failure


class _FakeDriveFiles:
    def __init__(self, file_map):
        self.file_map = file_map
        self._parent = None

    def list(self, q, fields=None, orderBy=None, pageToken=None):
        parent = q.split("'")[1]
        self._parent = parent
        return self

    def execute(self):
        return {"files": self.file_map.get(self._parent, []), "nextPageToken": None}


class _FakeDriveService:
    def __init__(self, file_map):
        self._files = _FakeDriveFiles(file_map)

    def files(self):
        return self._files


def test_extract_drive_folder_id_from_url():
    url = "https://drive.google.com/drive/folders/abc123?usp=sharing"
    assert extract_drive_folder_id(url) == "abc123"


def test_resolve_spreadsheet_search_descendants():
    drive = _FakeDriveService(
        {
            "root": [{"id": "child", "name": "Nested", "mimeType": "application/vnd.google-apps.folder"}],
            "child": [{"id": "sheet1", "name": "Workbook 601", "modifiedTime": "2026-04-28T10:00:00Z"}],
        }
    )
    result = resolve_spreadsheet(
        {"spreadsheet_name": "Workbook 601"},
        drive_service=drive,
        folder_id="root",
        search_descendants=True,
    )
    assert result["spreadsheet_id"] == "sheet1"


def test_normalize_rows_supports_constant_columns_and_skip_rows_missing():
    rows = [
        ["Crop", "Format", "Notes Source"],
        [" Lettuce ", "Bunch", "Cool weather"],
        ["", "Case", "skip me"],
    ]
    normalized = normalize_rows(
        rows,
        required_headers=["Crop", "Format"],
        output_headers=["Crop Name", "Product Name", "Source Tier"],
        column_map={"Crop Name": "Crop", "Product Name": "Format"},
        constant_columns={"Source Tier": "reference"},
        skip_rows_missing=["Crop Name"],
    )
    assert normalized["rows"][1] == [" Lettuce ", "Bunch", "reference"]
    assert len(normalized["rows"]) == 2


def test_normalize_rows_supports_fold_into_notes():
    rows = [
        ["Crop", "Variety", "Notes"],
        ["Carrot", "Napoli", "sweet"],
    ]
    normalized = normalize_rows(
        rows,
        required_headers=["Crop", "Variety", "Notes"],
        output_headers=["Crop", "Notes"],
        column_map={"Crop": "Crop", "Notes": "Notes"},
        fold_into_notes=[{"into": "Notes", "from": "Variety", "prefix": "Variety"}],
    )
    assert normalized["rows"][1][1] == "sweet\nVariety: Napoli"


def test_summarize_header_detection_failure_reports_candidates():
    rows = [
        ["junk", ""],
        ["Crop", "Format"],
        ["Carrot", "Bunch"],
    ]
    summary = summarize_header_detection_failure(rows, required_headers=["Crop", "Channel"])
    assert summary["required_header_count"] == 2
    assert summary["top_candidates"]


def test_extract_coda_doc_id_from_url():
    url = "https://coda.io/d/VG-2025_dCMrB5f1AZE"
    assert extract_coda_doc_id(url) == "CMrB5f1AZE"
    assert extract_coda_doc_id("dRawId123") == "dRawId123"


def test_rows_to_grid_orders_by_columns():
    cols = [{"id": "a", "name": "B"}, {"id": "b", "name": "A"}]
    rows = [{"values": {"A": "1", "B": "2"}}]
    grid = rows_to_grid(cols, rows)
    assert grid[0] == ["B", "A"]
    assert grid[1] == ["2", "1"]


def test_coda_adapter_routes_via_router_with_doc_url(monkeypatch):
    monkeypatch.setenv("CODA_API_TOKEN", "test-token-for-router")
    adapter = build_provider_adapter({"provider": "coda", "doc_url": "https://coda.io/d/VG-2025_dCMrB5f1AZE"})
    assert isinstance(adapter, CodaAdapter)
    assert adapter.doc_id == "CMrB5f1AZE"


def test_coda_adapter_fetch_tab_rows_with_patched_helpers(monkeypatch):
    monkeypatch.setenv("CODA_API_TOKEN", "t")

    def fake_list_tables(session, doc_id):
        return [{"id": "tbl-1", "name": "Clients", "type": "table"}]

    def fake_list_columns(session, doc_id, table_id):
        return [{"id": "c1", "name": "Name", "format": {"type": "text"}}]

    def fake_list_rows(session, doc_id, table_id, **kwargs):
        return [{"id": "r1", "values": {"Name": "Alice"}}]

    def fake_to_grid(columns, rows):
        return [["Name"], ["Alice"]]

    with (
        patch("connectors.coda.list_tables", fake_list_tables),
        patch("connectors.coda.list_columns", fake_list_columns),
        patch("connectors.coda.list_rows", fake_list_rows),
        patch("connectors.coda.rows_to_grid", fake_to_grid),
    ):
        adapter = CodaAdapter({"doc_url": "https://coda.io/d/X_doc1"})
        out = adapter.fetch_tab_rows({"worksheet_title": "Clients"})
    assert out["rows"] == [["Name"], ["Alice"]]
    assert out["worksheet_title"] == "Clients"
