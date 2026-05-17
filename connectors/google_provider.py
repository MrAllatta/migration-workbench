"""Google Sheets provider adapter for the workbench connector pipeline.

Exposes :class:`GoogleSheetsAdapter` plus the :func:`shape_sheet_structure`
shaping helper used by ``pull_bundle --include-structure`` to turn the raw
``spreadsheets().get`` response into the ``structure-draft-1`` envelope.
"""

from connectors.base import ProviderAdapter
from connectors.tab_name_utils import sanitize_tab_name
from connectors.google_sheets import (
    DRIVE_READONLY_SCOPE,
    SHEETS_READONLY_SCOPE,
    SheetsThrottle,
    build_google_service,
    default_throttle,
    extract_drive_folder_id,
    fetch_sheet_structure_data,
    fetch_tab_rows,
    resolve_spreadsheet,
)


def _col_letter(idx0: int) -> str:
    """Convert a 0-based column index to its A1 column letter (e.g. 0 -> 'A')."""
    n = idx0 + 1
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _user_entered_is_formula(user_entered):
    """Return True when a Sheets ``userEnteredValue`` dict represents a formula."""
    return bool(user_entered) and "formulaValue" in user_entered


def _data_validation_type(cell):
    """Pull the ``condition.type`` string from a cell's dataValidation rule, if any."""
    dv = (cell or {}).get("dataValidation") or {}
    condition = dv.get("condition") or {}
    return condition.get("type")


def shape_sheet_structure(response: dict, worksheet_title: str) -> dict | None:
    """Shape a Sheets API ``spreadsheets().get`` response into a structure tab dict.

    The response is expected to scope grid data to the requested ``worksheet_title``
    (header row plus a single sample data row); see
    :func:`connectors.google_sheets.fetch_sheet_structure_data`.

    Args:
        response: Raw Sheets API response dict containing ``sheets`` and
            ``namedRanges`` keys.
        worksheet_title: Tab title used to filter the response payload.

    Returns:
        dict | None: Per-tab structure entry conforming to the
        ``structure-draft-1`` shape, or ``None`` when the requested tab is
        absent from the response (e.g. it was renamed mid-fetch).
    """
    target = None
    for sheet in response.get("sheets", []) or []:
        props = sheet.get("properties") or {}
        if props.get("title") == worksheet_title:
            target = sheet
            break
    if target is None:
        return None

    props = target.get("properties") or {}
    grid = props.get("gridProperties") or {}
    sheet_id = props.get("sheetId")

    header_cells: list[dict] = []
    sample_cells: list[dict] = []
    for block in target.get("data", []) or []:
        rows = block.get("rowData", []) or []
        if rows:
            header_cells = rows[0].get("values", []) or []
        if len(rows) > 1:
            sample_cells = rows[1].get("values", []) or []
        break

    columns = []
    for idx, header_cell in enumerate(header_cells):
        sample_cell = sample_cells[idx] if idx < len(sample_cells) else {}
        header_label = (
            header_cell.get("formattedValue")
            or (header_cell.get("userEnteredValue") or {}).get("stringValue")
            or ""
        )
        is_formula = _user_entered_is_formula(sample_cell.get("userEnteredValue"))
        # Fall back to the header cell's validation when the sample row is empty;
        # validation rules typically apply to the whole column so this still
        # surfaces dropdowns even on otherwise-blank sheets.
        dv_type = _data_validation_type(sample_cell) or _data_validation_type(header_cell)
        columns.append(
            {
                "index": idx,
                "col_letter": _col_letter(idx),
                "header_label": header_label,
                "is_formula": is_formula,
                "data_validation_type": dv_type,
            }
        )

    named_ranges = []
    for nr in response.get("namedRanges", []) or []:
        nr_range = nr.get("range") or {}
        if nr_range.get("sheetId") == sheet_id:
            named_ranges.append(
                {
                    "name": nr.get("name"),
                    "named_range_id": nr.get("namedRangeId"),
                    "range": nr_range,
                }
            )

    filter_views = []
    for fv in target.get("filterViews", []) or []:
        filter_views.append(
            {
                "filter_view_id": fv.get("filterViewId"),
                "title": fv.get("title"),
                "range": fv.get("range"),
            }
        )

    worksheet_title = sanitize_tab_name(worksheet_title)

    return {
        "worksheet_title": worksheet_title,
        "tab_position": props.get("index"),
        "hidden": bool(props.get("hidden", False)),
        "frozen_rows": grid.get("frozenRowCount", 0) or 0,
        "frozen_cols": grid.get("frozenColumnCount", 0) or 0,
        "total_rows": grid.get("rowCount"),
        "total_cols": grid.get("columnCount"),
        "columns": columns,
        "named_ranges": named_ranges,
        "filter_views": filter_views,
    }


class GoogleSheetsAdapter(ProviderAdapter):
    """Google Sheets provider adapter for the profiler/importer pipeline."""
    def __init__(self, config: dict, throttle: SheetsThrottle | None = None):
        """Initialize the adapter from a source config dict. Optionally accepts a ``SheetsThrottle`` instance for API rate limiting."""
        self.throttle = throttle or default_throttle
        self.folder_id = extract_drive_folder_id(
            config.get("drive_folder_id") or config.get("drive_folder_url")
        )
        self.drive_service = None
        if self.folder_id:
            self.drive_service = build_google_service("drive", "v3", [DRIVE_READONLY_SCOPE])
        self.sheets_service = build_google_service("sheets", "v4", [SHEETS_READONLY_SCOPE])

    def fetch_tab_rows(self, tab_config: dict) -> dict:
        """Fetch rows from a Google Sheets tab identified by *tab_config*. Resolves the spreadsheet by ID, URL, or folder search, then fetches and normalizes rows."""
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
            throttle=self.throttle,
        )
        return {
            "rows": rows,
            "spreadsheet_id": resolved["spreadsheet_id"],
            "spreadsheet_name": resolved["spreadsheet_name"],
            "modified_time": resolved.get("modified_time"),
            "worksheet_title": worksheet_title,
            "drive_folder_id": self.folder_id,
        }

    def fetch_tab_structure(self, tab_config: dict) -> dict | None:
        """Fetch and shape a structure entry for a single worksheet tab.

        Expects ``tab_config`` to include either ``spreadsheet_id`` /
        ``spreadsheet_url`` or the same name+folder combination accepted by
        :func:`fetch_tab_rows`; ``pull_bundle`` injects the resolved
        ``spreadsheet_id`` after the rows fetch to avoid a second name lookup.
        """
        worksheet_title = tab_config.get("worksheet_title")
        if not worksheet_title:
            return None
        resolved = resolve_spreadsheet(
            tab_config,
            drive_service=self.drive_service,
            folder_id=self.folder_id,
        )
        response = fetch_sheet_structure_data(
            sheets_service=self.sheets_service,
            spreadsheet_id=resolved["spreadsheet_id"],
            worksheet_title=worksheet_title,
            throttle=self.throttle,
        )
        return shape_sheet_structure(response, worksheet_title)
