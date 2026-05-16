from connectors.google_sheets import _fill_merged_cell_headers


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
