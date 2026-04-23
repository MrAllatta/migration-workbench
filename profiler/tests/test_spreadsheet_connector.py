from connectors.spreadsheet import normalize_rows


def test_normalizer_detects_header_after_preamble():
    rows = [
        ["export 2026"],
        ["notes", "draft only"],
        [" block name ", "block type", "number of beds", "bed width feet", "bedfeet per bed"],
        ["Field 1", "Field", "10", "3", "100"],
    ]
    normalized = normalize_rows(
        rows,
        required_headers=["Block", "Block Type", "# of Beds", "Bed Width (feet)", "Bedfeet per Bed"],
        aliases={
            "block name": "Block",
            "block type": "Block Type",
            "number of beds": "# of Beds",
            "bed width feet": "Bed Width (feet)",
            "bedfeet per bed": "Bedfeet per Bed",
        },
    )
    assert normalized["header_row_index"] == 2
    assert normalized["rows"][1] == ["Field 1", "Field", "10", "3", "100"]
