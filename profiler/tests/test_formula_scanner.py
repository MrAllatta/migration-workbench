"""Tests for formula scanner library."""

import re
from unittest.mock import MagicMock

from profiler.tools.formula_scanner import scan_workbook_patterns


def test_scan_workbook_patterns():
    """Test scan_workbook_patterns with a mocked sheets_service."""
    # Mock sheets_service
    mock_service = MagicMock()

    # Mock the spreadsheets() method
    mock_spreadsheets = MagicMock()
    mock_service.spreadsheets.return_value = mock_spreadsheets

    # Mock the spreadsheets().get() response
    mock_sheets_get = MagicMock()
    mock_sheets_get.execute.return_value = {
        "sheets": [
            {"properties": {"title": "Sheet1"}},
            {"properties": {"title": "Sheet2"}},
        ]
    }
    mock_spreadsheets.get.return_value = mock_sheets_get

    # Mock the spreadsheets().values() method
    mock_values = MagicMock()
    mock_spreadsheets.values.return_value = mock_values

    # Mock the spreadsheets().values().get() response
    mock_values_get = MagicMock()
    mock_values_get.execute.return_value = {
        "values": [
            ["=SUM(A1:A10)", "=VLOOKUP(B1, C1:D10, 2, FALSE)"],
            ["=IF(C1>0, D1, E1)", "=AVERAGE(F1:F5)"],
        ]
    }
    mock_values.get.return_value = mock_values_get

    # Define patterns to match
    patterns = [
        ("sum", re.compile(r"SUM\(", re.I)),
        ("vlookup", re.compile(r"VLOOKUP\(", re.I)),
        ("if", re.compile(r"IF\(", re.I)),
        ("average", re.compile(r"AVERAGE\(", re.I)),
    ]

    # Call the function
    result = scan_workbook_patterns(mock_service, "test_spreadsheet_id", patterns)

    # Verify the result structure
    assert isinstance(result, list)
    # 2 sheets, each mock returns 4 formula cells (2 rows × 2 cols) = 8 total
    assert len(result) == 8

    # Check first 4 matches (Sheet1)
    assert result[0]["sheet"] == "Sheet1"
    assert result[0]["row"] == 1
    assert result[0]["col"] == 1
    assert result[0]["pattern"] == "sum"
    assert result[0]["formula"] == "=SUM(A1:A10)"

    assert result[1]["sheet"] == "Sheet1"
    assert result[1]["row"] == 1
    assert result[1]["col"] == 2
    assert result[1]["pattern"] == "vlookup"
    assert result[1]["formula"] == "=VLOOKUP(B1, C1:D10, 2, FALSE)"

    assert result[2]["sheet"] == "Sheet1"
    assert result[2]["row"] == 2
    assert result[2]["col"] == 1
    assert result[2]["pattern"] == "if"
    assert result[2]["formula"] == "=IF(C1>0, D1, E1)"

    assert result[3]["sheet"] == "Sheet1"
    assert result[3]["row"] == 2
    assert result[3]["col"] == 2
    assert result[3]["pattern"] == "average"
    assert result[3]["formula"] == "=AVERAGE(F1:F5)"

    # Check last 4 matches (Sheet2 - same mock data)
    assert result[4]["sheet"] == "Sheet2"
    assert result[4]["pattern"] == "sum"
    assert result[4]["formula"] == "=SUM(A1:A10)"

    # Verify that the mock was called correctly
    mock_spreadsheets.get.assert_called_once_with(
        spreadsheetId="test_spreadsheet_id", fields="sheets(properties(title))"
    )

    # Verify that values.get was called for each sheet
    assert mock_values.get.call_count == 2
