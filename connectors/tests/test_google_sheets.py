import time
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from connectors.google_sheets import (
    SheetsThrottle,
    fetch_tab_rows,
    fetch_sheet_structure_data,
    _fill_merged_cell_headers,
)


def test_fill_merged_cell_headers_no_gaps():
    headers = ["CROP & VARIETY", "Block", "Bed #"]
    result = _fill_merged_cell_headers(headers)
    assert result == ["CROP & VARIETY", "Block", "Bed #"]


def test_fill_merged_cell_headers_fills_gaps():
    headers = ["CROP & VARIETY", "", "Block", "Bed #", ""]
    result = _fill_merged_cell_headers(headers)
    assert result == ["CROP & VARIETY", "CROP & VARIETY", "Block", "Bed #", ""]


def test_fill_merged_cell_headers_first_cell_empty():
    headers = ["", "Block", "Bed #"]
    result = _fill_merged_cell_headers(headers)
    assert result == ["", "Block", "Bed #"]


def test_fill_merged_cell_headers_all_empty():
    headers = ["", "", ""]
    result = _fill_merged_cell_headers(headers)
    assert result == ["", "", ""]


def test_fill_merged_cell_headers_single_empty():
    headers = [""]
    result = _fill_merged_cell_headers(headers)
    assert result == [""]


class TestSheetsThrottle:
    def test_default_min_interval(self):
        t = SheetsThrottle()
        assert t._min_interval == 1.0

    def test_custom_min_interval(self):
        t = SheetsThrottle(min_interval=0.5)
        assert t._min_interval == 0.5

    def test_wait_enforces_minimum_interval(self):
        t = SheetsThrottle(min_interval=0.05)
        t._last = time.monotonic()
        start = time.monotonic()
        t.wait()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.04

    def test_wait_updates_last_timestamp(self):
        t = SheetsThrottle(min_interval=0.01)
        t._last = 0.0
        t.wait()
        assert t._last > 0.0

    def test_no_sleep_when_enough_time_elapsed(self):
        t = SheetsThrottle(min_interval=0.01)
        t._last = time.monotonic() - 10
        start = time.monotonic()
        t.wait()
        elapsed = time.monotonic() - start
        assert elapsed < 0.05


class TestFetchWithThrottle:
    def test_fetch_tab_rows_uses_throttle(self):
        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.execute.return_value = {"values": [["A", "B"]]}
        mock_service.spreadsheets().values().get.return_value = mock_result
        throttle = SheetsThrottle(min_interval=0.001)
        rows = fetch_tab_rows("sid", "Sheet1", mock_service, throttle=throttle)
        assert rows == [["A", "B"]]
        mock_service.spreadsheets().values().get.assert_called_once_with(
            spreadsheetId="sid", range="'Sheet1'"
        )

    def test_fetch_tab_rows_uses_default_throttle(self):
        mock_service = MagicMock()
        mock_service.spreadsheets().values().get().execute.return_value = {
            "values": [["A", "B"]]
        }
        from connectors.google_sheets import default_throttle

        original = default_throttle._min_interval
        default_throttle._min_interval = 0.001
        try:
            rows = fetch_tab_rows("sid", "Sheet1", mock_service)
            assert rows == [["A", "B"]]
        finally:
            default_throttle._min_interval = original

    def test_fetch_sheet_structure_uses_throttle(self):
        mock_service = MagicMock()
        mock_response = {"sheets": [], "namedRanges": [], "properties": {}}
        mock_service.spreadsheets().get().execute.return_value = mock_response
        throttle = SheetsThrottle(min_interval=0.001)
        result = fetch_sheet_structure_data(
            mock_service, "sid", "Sheet1", throttle=throttle
        )
        assert result == mock_response

    def test_fetch_sheet_structure_default_throttle(self):
        mock_service = MagicMock()
        mock_response = {"sheets": [], "namedRanges": [], "properties": {}}
        mock_service.spreadsheets().get().execute.return_value = mock_response
        from connectors.google_sheets import default_throttle

        original = default_throttle._min_interval
        default_throttle._min_interval = 0.001
        try:
            result = fetch_sheet_structure_data(mock_service, "sid", "Sheet1")
            assert result == mock_response
        finally:
            default_throttle._min_interval = original


class TestRetryOn429:
    def _make_429_error(self):
        resp = MagicMock()
        resp.status = 429
        resp.reason = "Rate limit exceeded"
        return HttpError(resp, b'{"error": {"message": "Quota exceeded"}}')

    def test_fetch_tab_rows_retries_on_429(self):
        mock_service = MagicMock()
        error = self._make_429_error()
        mock_service.spreadsheets().values().get().execute.side_effect = [
            error,
            {"values": [["A", "B"]]},
        ]
        throttle = SheetsThrottle(min_interval=0.001)
        rows = fetch_tab_rows("sid", "Sheet1", mock_service, throttle=throttle)
        assert rows == [["A", "B"]]
        assert mock_service.spreadsheets().values().get().execute.call_count == 2

    def test_fetch_tab_rows_raises_after_max_retries(self):
        mock_service = MagicMock()
        error = self._make_429_error()
        mock_service.spreadsheets().values().get().execute.side_effect = error
        throttle = SheetsThrottle(min_interval=0.001)
        with pytest.raises(HttpError):
            fetch_tab_rows("sid", "Sheet1", mock_service, throttle=throttle)
        assert mock_service.spreadsheets().values().get().execute.call_count == 4

    def test_fetch_sheet_structure_retries_on_429(self):
        mock_service = MagicMock()
        error = self._make_429_error()
        mock_response = {"sheets": [], "namedRanges": [], "properties": {}}
        mock_service.spreadsheets().get().execute.side_effect = [error, mock_response]
        throttle = SheetsThrottle(min_interval=0.001)
        result = fetch_sheet_structure_data(
            mock_service, "sid", "Sheet1", throttle=throttle
        )
        assert result == mock_response
