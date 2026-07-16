"""Formula scanner library for profiler pipeline reuse.

This module provides core scanning logic extracted from the scan_formula_patterns
management command, enabling reuse in the profiler pipeline.
"""

from __future__ import annotations

import time
from typing import Pattern


def execute_with_retry(request, max_retries: int = 8):
    """Execute a Google API request with exponential backoff retry on transient failures.

    Args:
        request: Google API request object to execute
        max_retries: Maximum number of retry attempts (default: 8)

    Returns:
        dict: API response data

    Raises:
        HttpError: If the request fails after all retries
        TimeoutError: If the request times out after all retries
    """
    delay = 5.0
    for attempt in range(max_retries):
        try:
            return request.execute()
        except TimeoutError:
            if attempt + 1 >= max_retries:
                raise
            time.sleep(delay)
            delay = min(delay * 1.6, 120.0)
        except Exception as err:
            if (
                not hasattr(err, "resp")
                or err.resp.status != 429
                or attempt + 1 >= max_retries
            ):
                raise
            time.sleep(delay)
            delay = min(delay * 1.6, 120.0)


def scan_workbook_patterns(
    sheets_service, spreadsheet_id: str, patterns: list[tuple[str, Pattern[str]]]
) -> list[dict]:
    """Scan a single workbook for cells matching the given regex patterns.

    Args:
        sheets_service: Authenticated Google Sheets API service object
        spreadsheet_id: ID of the spreadsheet to scan
        patterns: List of (name, compiled_pattern) tuples to match against formulas

    Returns:
        list[dict]: List of match dictionaries with keys:
            - sheet: Worksheet title
            - row: Row number (1-indexed)
            - col: Column number (1-indexed)
            - pattern: Name of the pattern that matched
            - formula: The formula text that matched
    """
    sheets_resp = execute_with_retry(
        sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id, fields="sheets(properties(title))"
        )
    )
    sheet_titles = [s["properties"]["title"] for s in sheets_resp.get("sheets", [])]
    matches = []
    for title in sheet_titles:
        escaped_title = title.replace("'", "''")
        values_resp = execute_with_retry(
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"'{escaped_title}'")
        )
        for row_idx, row in enumerate(values_resp.get("values", []), start=1):
            for col_idx, value in enumerate(row, start=1):
                if not isinstance(value, str) or not value.startswith("="):
                    continue
                for name, pattern in patterns:
                    if pattern.search(value):
                        matches.append(
                            {
                                "sheet": title,
                                "row": row_idx,
                                "col": col_idx,
                                "pattern": name,
                                "formula": value,
                            }
                        )
    return matches
