"""Google Sheets API helpers for spreadsheet row fetching, ID extraction, and Drive folder traversal.

Provides service-account credential helpers, spreadsheet/tab resolution, and
``SheetsThrottle`` for API rate limiting.
"""

import logging
import os
import time
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


def _fill_merged_cell_headers(headers: list[str]) -> list[str]:
    """Fill ``None`` entries in a header row by carrying forward the last non-None value. Handles merged cells in Sheets header rows."""
    result = list(headers)
    last = None
    for i, h in enumerate(result):
        if h.strip():
            last = h
        elif last is not None:
            result[i] = last
    next_non_empty = None
    for i in range(len(result) - 1, -1, -1):
        if headers[i].strip():
            next_non_empty = headers[i]
        elif next_non_empty is None:
            result[i] = headers[i]
    return result


DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
SPREADSHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


def _extract_id_from_url(url, marker):
    """Extract the segment after *marker* from a URL path component."""
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if marker in parts:
        index = parts.index(marker)
        if index + 1 < len(parts):
            return parts[index + 1]
    return None


def extract_drive_folder_id(value):
    """Extract a Drive folder ID from a URL or return the value unchanged if already an ID."""
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        folder_id = _extract_id_from_url(value, "folders")
        if folder_id:
            return folder_id
        parsed = urlparse(value)
        query_id = parse_qs(parsed.query).get("id", [])
        if query_id:
            return query_id[0]
    return value


def extract_spreadsheet_id(value):
    """Extract a spreadsheet ID from a URL or return the value unchanged if already an ID."""
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        spreadsheet_id = _extract_id_from_url(value, "d")
        if spreadsheet_id:
            return spreadsheet_id
        parsed = urlparse(value)
        query_id = parse_qs(parsed.query).get("id", [])
        if query_id:
            return query_id[0]
    return value


def get_service_account_credentials(scopes=None):
    """Build Google service-account credentials from ``GOOGLE_SA_JSON`` or ``GOOGLE_APPLICATION_CREDENTIALS`` env vars. Optionally restrict to *scopes* (defaults to Sheets and Drive scopes)."""
    import google.auth
    from google.auth import impersonated_credentials
    from google.oauth2 import service_account

    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    impersonate_service_account = os.environ.get("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")
    requested_scopes = scopes or [SHEETS_READONLY_SCOPE]

    # Cloud runtimes can use Application Default Credentials from the attached
    # service account without mounting a JSON key file.
    if not credentials_path:
        if impersonate_service_account:
            # Keep user ADC on cloud-platform only, then mint scoped tokens via SA impersonation.
            source_credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            return impersonated_credentials.Credentials(
                source_credentials=source_credentials,
                target_principal=impersonate_service_account,
                target_scopes=requested_scopes,
                lifetime=3600,
            )
        credentials, _ = google.auth.default(scopes=requested_scopes)
        return credentials

    credentials_file = Path(credentials_path).expanduser()
    if not credentials_file.exists():
        raise ValueError(f"GOOGLE_APPLICATION_CREDENTIALS does not exist: {credentials_file}")

    return service_account.Credentials.from_service_account_file(
        credentials_file,
        scopes=requested_scopes,
    )


def build_google_service(service_name, version, scopes):
    """Build an authenticated Google API service object for the given *service_name* and *version* using service-account credentials with *scopes*."""
    from googleapiclient.discovery import build

    credentials = get_service_account_credentials(scopes=scopes)
    return build(service_name, version, credentials=credentials, cache_discovery=False)


def list_spreadsheets_in_folder(folder_id, drive_service):
    """List spreadsheet file resources in a Drive folder. Returns a list of file dicts with ``id`` and ``name``."""
    files = []
    page_token = None
    query = f"'{folder_id}' in parents and mimeType='{SPREADSHEET_MIME_TYPE}' and trashed=false"

    while True:
        response = (
            drive_service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, modifiedTime)",
                orderBy="name",
                pageToken=page_token,
            )
            .execute()
        )
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return files


def list_child_folder_ids(folder_id, drive_service):
    """List child folder IDs immediately under *folder_id* in Drive."""
    ids = []
    page_token = None
    query = f"'{folder_id}' in parents and mimeType='{FOLDER_MIME_TYPE}' and trashed=false"

    while True:
        response = (
            drive_service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id)",
                orderBy="name",
                pageToken=page_token,
            )
            .execute()
        )
        for item in response.get("files", []):
            ids.append(item["id"])
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return ids


def find_spreadsheet_by_name_in_folder_tree(drive_service, root_folder_id, spreadsheet_name):
    """Breadth-first search for a spreadsheet with exact *spreadsheet_name* under *root_folder_id*."""
    queue = deque([root_folder_id])
    seen_folders = set()
    matches = []

    while queue:
        fid = queue.popleft()
        if fid in seen_folders:
            continue
        seen_folders.add(fid)

        for item in list_spreadsheets_in_folder(fid, drive_service):
            if item.get("name") == spreadsheet_name:
                if not any(m.get("id") == item.get("id") for m in matches):
                    matches.append(item)

        for child_id in list_child_folder_ids(fid, drive_service):
            if child_id not in seen_folders:
                queue.append(child_id)

    if len(matches) > 1:
        ids_preview = ", ".join(m["id"] for m in matches[:5])
        raise ValueError(
            f"multiple spreadsheets named {spreadsheet_name!r} under folder {root_folder_id} "
            f"(recursive search); ids: {ids_preview}"
        )
    return matches[0] if matches else None


def resolve_spreadsheet(tab, drive_service=None, folder_id=None, search_descendants=False):
    """Resolve a spreadsheet ID from a tab config dict. Tries ``tab.spreadsheet_id`` first, then ``tab.spreadsheet_url``, then folder+name search (optionally recursive)."""
    spreadsheet_id = extract_spreadsheet_id(tab.get("spreadsheet_id") or tab.get("spreadsheet_url"))
    if spreadsheet_id:
        return {
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_name": tab.get("spreadsheet_name") or spreadsheet_id,
            "modified_time": None,
        }

    spreadsheet_name = tab.get("spreadsheet_name")
    if not spreadsheet_name or not folder_id or drive_service is None:
        raise ValueError(
            "tab entry must provide spreadsheet_id/spreadsheet_url or spreadsheet_name with drive folder access"
        )

    if search_descendants:
        match = find_spreadsheet_by_name_in_folder_tree(drive_service, folder_id, spreadsheet_name)
        if match is None:
            raise ValueError(
                f"spreadsheet named '{spreadsheet_name}' not found under folder {folder_id} (recursive search)"
            )
    else:
        matches = [
            item
            for item in list_spreadsheets_in_folder(folder_id, drive_service)
            if item.get("name") == spreadsheet_name
        ]
        if not matches:
            raise ValueError(f"spreadsheet named '{spreadsheet_name}' not found in folder {folder_id}")
        if len(matches) > 1:
            raise ValueError(f"multiple spreadsheets named '{spreadsheet_name}' found in folder {folder_id}")

        match = matches[0]
    return {
        "spreadsheet_id": match["id"],
        "spreadsheet_name": match["name"],
        "modified_time": match.get("modifiedTime"),
    }


class SheetsThrottle:
    """Rate limiter for Google Sheets API calls.

    Enforces a minimum interval between consecutive API calls to stay
    under the Sheets API quota (default 60 requests/min per user).

    The interval is configurable via the ``GOOGLE_SHEETS_THROTTLE_INTERVAL``
    environment variable (parsed as a float in seconds).
    """

    def __init__(self, min_interval: float | None = None):
        """Initialize throttle with an optional *min_interval* in seconds between requests."""
        if min_interval is None:
            env_val = os.environ.get("GOOGLE_SHEETS_THROTTLE_INTERVAL")
            if env_val is not None:
                try:
                    min_interval = float(env_val)
                except (ValueError, TypeError):
                    min_interval = 1.0
            else:
                min_interval = 1.0
        self._min_interval = min_interval
        self._last = 0.0

    def wait(self):
        """Block until at least *min_interval* seconds have elapsed since the last call to ``wait``."""
        elapsed = time.monotonic() - self._last
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last = time.monotonic()


default_throttle = SheetsThrottle()

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0


def _execute_with_retry(execute_fn, max_retries=_MAX_RETRIES, base_delay=_RETRY_BASE_DELAY):
    """Execute a Sheets API request with exponential backoff retry on transient failures."""
    from googleapiclient.errors import HttpError

    for attempt in range(max_retries + 1):
        try:
            return execute_fn()
        except HttpError as exc:
            if exc.resp.status != 429 or attempt >= max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "429 rate limit hit, retrying in %.1fs (attempt %d/%d)",
                delay, attempt + 1, max_retries,
            )
            time.sleep(delay)


def fetch_tab_rows(spreadsheet_id, worksheet_title, sheets_service, *, throttle=None):
    """Fetch all rows from a specific worksheet tab as a list of dicts keyed by header names. Uses *sheets_service* for the API call and optional *throttle* for rate limiting."""
    if throttle is None:
        throttle = default_throttle
    throttle.wait()
    escaped_title = worksheet_title.replace("'", "''")

    def _execute():
        return (
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"'{escaped_title}'")
            .execute()
        )

    response = _execute_with_retry(_execute)
    values = response.get("values", [])
    if values:
        values[0] = _fill_merged_cell_headers(values[0])
    return values


def fetch_sheet_structure_data(sheets_service, spreadsheet_id, worksheet_title, *, throttle=None):
    """Fetch raw structural metadata for one worksheet tab.

    Issues a single ``spreadsheets().get()`` call scoped to rows 1-2 of the
    target tab so we recover header labels, a sample data row (used to flag
    formula columns), tab properties, filter views, and named ranges in one
    round trip.

    Args:
        sheets_service: An authenticated Google Sheets v4 service client.
        spreadsheet_id: Resolved spreadsheet id.
        worksheet_title: Tab title to scope the grid data fetch to.
        throttle: Optional SheetsThrottle instance.

    Returns:
        dict: Raw Sheets API response.
    """
    if throttle is None:
        throttle = default_throttle
    throttle.wait()
    quoted_title = worksheet_title.replace("'", "''")
    range_ = f"'{quoted_title}'!1:2"
    fields = (
        "properties(title),"
        "namedRanges,"
        "sheets("
        "properties(sheetId,title,index,hidden,gridProperties),"
        "filterViews,"
        "data(startRow,startColumn,rowData(values("
        "formattedValue,userEnteredValue,dataValidation"
        ")))"
        ")"
    )
    def _execute():
        return (
            sheets_service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                ranges=[range_],
                includeGridData=True,
                fields=fields,
            )
            .execute()
        )

    return _execute_with_retry(_execute)
