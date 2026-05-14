from connectors.google_provider import shape_sheet_structure


def test_shape_sheet_structure_sanitizes_tab_name():
    response = {
        "sheets": [
            {
                "properties": {
                    "title": "i|Markets",
                    "sheetId": 101,
                    "index": 0,
                    "gridProperties": {"rowCount": 100, "columnCount": 10},
                },
                "data": [
                    {
                        "rowData": [
                            {"values": [{"formattedValue": "Name"}]},
                            {"values": [{"formattedValue": "Acme"}]},
                        ]
                    }
                ],
                "filterViews": [],
            }
        ],
        "namedRanges": [],
    }
    result = shape_sheet_structure(response, "i|Markets")
    assert result is not None
    assert result["worksheet_title"] == "i_Markets"
