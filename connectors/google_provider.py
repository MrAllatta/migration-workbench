from connectors.base import ProviderAdapter
from connectors.google_sheets import (
    DRIVE_READONLY_SCOPE,
    SHEETS_READONLY_SCOPE,
    build_google_service,
    extract_drive_folder_id,
    fetch_tab_rows,
    resolve_spreadsheet,
)


class GoogleSheetsAdapter(ProviderAdapter):
    def __init__(self, config: dict):
        self.folder_id = extract_drive_folder_id(
            config.get("drive_folder_id") or config.get("drive_folder_url")
        )
        self.drive_service = None
        if self.folder_id:
            self.drive_service = build_google_service("drive", "v3", [DRIVE_READONLY_SCOPE])
        self.sheets_service = build_google_service("sheets", "v4", [SHEETS_READONLY_SCOPE])

    def fetch_tab_rows(self, tab_config: dict) -> dict:
        worksheet_title = tab_config.get("worksheet_title")
        resolved = resolve_spreadsheet(
            tab_config,
            drive_service=self.drive_service,
            folder_id=self.folder_id,
        )
        rows = fetch_tab_rows(
            spreadsheet_id=resolved["spreadsheet_id"],
            worksheet_title=worksheet_title,
            sheets_service=self.sheets_service,
        )
        return {
            "rows": rows,
            "spreadsheet_id": resolved["spreadsheet_id"],
            "spreadsheet_name": resolved["spreadsheet_name"],
            "modified_time": resolved.get("modified_time"),
            "worksheet_title": worksheet_title,
            "drive_folder_id": self.folder_id,
        }
