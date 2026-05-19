"""Tests for the profiler raw-structure pass.

Covers shaping helpers in :mod:`connectors.google_provider` and
:mod:`connectors.coda`, plus end-to-end ``pull_bundle --include-structure``
behaviour through a fake provider adapter (no network).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from django.core.management import call_command

from connectors.base import ProviderAdapter
from connectors.coda import shape_coda_table_structure
from connectors.google_provider import shape_sheet_structure


def _orders_response() -> dict[str, Any]:
    """Sheets API fixture: 'Orders' sheet with a status dropdown column."""
    return {
        "properties": {"title": "Demo Workbook"},
        "namedRanges": [
            {
                "namedRangeId": "nr_orders",
                "name": "OrdersTotalRange",
                "range": {"sheetId": 11, "startRowIndex": 0, "endRowIndex": 5},
            },
            {
                "namedRangeId": "nr_other",
                "name": "OtherSheetRange",
                "range": {"sheetId": 99},
            },
        ],
        "sheets": [
            {
                "properties": {
                    "sheetId": 11,
                    "title": "Orders",
                    "index": 2,
                    "hidden": False,
                    "gridProperties": {
                        "rowCount": 1000,
                        "columnCount": 4,
                        "frozenRowCount": 1,
                        "frozenColumnCount": 0,
                    },
                },
                "filterViews": [
                    {
                        "filterViewId": 501,
                        "title": "Open orders",
                        "range": {"sheetId": 11},
                    }
                ],
                "data": [
                    {
                        "startRow": 0,
                        "startColumn": 0,
                        "rowData": [
                            {
                                "values": [
                                    {
                                        "formattedValue": "Order ID",
                                        "userEnteredValue": {"stringValue": "Order ID"},
                                    },
                                    {
                                        "formattedValue": "Customer",
                                        "userEnteredValue": {"stringValue": "Customer"},
                                    },
                                    {
                                        "formattedValue": "Status",
                                        "userEnteredValue": {"stringValue": "Status"},
                                    },
                                    {
                                        "formattedValue": "Total",
                                        "userEnteredValue": {"stringValue": "Total"},
                                    },
                                ]
                            },
                            {
                                "values": [
                                    {
                                        "formattedValue": "1001",
                                        "userEnteredValue": {"numberValue": 1001},
                                    },
                                    {
                                        "formattedValue": "Acme",
                                        "userEnteredValue": {"stringValue": "Acme"},
                                    },
                                    {
                                        "formattedValue": "open",
                                        "userEnteredValue": {"stringValue": "open"},
                                        "dataValidation": {
                                            "condition": {
                                                "type": "ONE_OF_LIST",
                                                "values": [
                                                    {"userEnteredValue": "open"},
                                                    {"userEnteredValue": "shipped"},
                                                ],
                                            }
                                        },
                                    },
                                    {
                                        "formattedValue": "=B2*1.1",
                                        "userEnteredValue": {"formulaValue": "=B2*1.1"},
                                    },
                                ]
                            },
                        ],
                    }
                ],
            }
        ],
    }


def _two_sheet_response() -> dict[str, Any]:
    """Fixture with two sheets to verify tab filtering."""
    return {
        "namedRanges": [],
        "sheets": [
            {
                "properties": {
                    "sheetId": 1,
                    "title": "Customers",
                    "index": 0,
                    "gridProperties": {"rowCount": 50, "columnCount": 2},
                },
                "data": [
                    {
                        "rowData": [
                            {
                                "values": [
                                    {"formattedValue": "Name"},
                                    {"formattedValue": "Email"},
                                ]
                            }
                        ]
                    }
                ],
            },
            {
                "properties": {
                    "sheetId": 2,
                    "title": "Inventory",
                    "index": 1,
                    "gridProperties": {"rowCount": 200, "columnCount": 3},
                },
                "data": [
                    {
                        "rowData": [
                            {
                                "values": [
                                    {"formattedValue": "SKU"},
                                    {"formattedValue": "Qty"},
                                    {"formattedValue": "Price"},
                                ]
                            }
                        ]
                    }
                ],
            },
        ],
    }


def test_google_structure_shapes_columns():
    structure = shape_sheet_structure(_orders_response(), worksheet_title="Orders")
    assert structure is not None
    assert structure["worksheet_title"] == "Orders"
    assert structure["tab_position"] == 2
    assert structure["hidden"] is False
    assert structure["frozen_rows"] == 1
    assert structure["frozen_cols"] == 0
    assert structure["total_rows"] == 1000
    assert structure["total_cols"] == 4

    headers = [c["header_label"] for c in structure["columns"]]
    assert headers == ["Order ID", "Customer", "Status", "Total"]

    by_label = {c["header_label"]: c for c in structure["columns"]}
    assert by_label["Status"]["data_validation_type"] == "ONE_OF_LIST"
    assert by_label["Total"]["is_formula"] is True
    assert by_label["Order ID"]["is_formula"] is False
    assert by_label["Order ID"]["col_letter"] == "A"
    assert by_label["Total"]["col_letter"] == "D"

    assert len(structure["named_ranges"]) == 1
    assert structure["named_ranges"][0]["name"] == "OrdersTotalRange"

    assert len(structure["filter_views"]) == 1
    assert structure["filter_views"][0]["title"] == "Open orders"


def test_google_structure_skips_non_target_tabs():
    response = _two_sheet_response()
    inventory = shape_sheet_structure(response, worksheet_title="Inventory")
    assert inventory is not None
    assert inventory["worksheet_title"] == "Inventory"
    assert [c["header_label"] for c in inventory["columns"]] == ["SKU", "Qty", "Price"]

    missing = shape_sheet_structure(response, worksheet_title="Nope")
    assert missing is None


def test_coda_structure_from_list_columns():
    table_meta = {
        "id": "tbl-orders",
        "name": "Orders",
        "type": "table",
        "rowCount": 42,
        "columnCount": 3,
    }
    columns = [
        {"id": "c-1", "name": "Customer", "format": {"type": "text"}},
        {
            "id": "c-2",
            "name": "Status",
            "format": {
                "type": "select",
                "options": ["open", "shipped"],
            },
        },
        {
            "id": "c-3",
            "name": "Total",
            "format": {"type": "number"},
            "formulaText": "[Subtotal] * 1.1",
        },
    ]

    shaped = shape_coda_table_structure(
        table_meta,
        columns,
        table_id="tbl-orders",
        table_name="Orders",
        table_position=0,
    )

    assert shaped["worksheet_title"] == "Orders"
    assert shaped["tab_position"] == 0
    assert shaped["total_rows"] == 42
    assert shaped["total_cols"] == 3
    assert shaped["coda_table_id"] == "tbl-orders"
    assert shaped["coda_table_type"] == "table"
    assert shaped["named_ranges"] == []
    assert shaped["filter_views"] == []

    by_label = {c["header_label"]: c for c in shaped["columns"]}
    assert by_label["Customer"]["is_formula"] is False
    assert by_label["Customer"]["data_validation_type"] == "text"
    assert by_label["Status"]["data_validation_type"] == "select"
    assert by_label["Total"]["is_formula"] is True


class _StubAdapter(ProviderAdapter):
    """Fake provider that returns pre-canned rows + structure (no network)."""

    def __init__(self, config: dict):
        self.config = config
        self.calls: list[str] = []

    def fetch_tab_rows(self, tab_config: dict) -> dict:
        self.calls.append(f"rows:{tab_config['worksheet_title']}")
        return {
            "rows": [
                [
                    "Block",
                    "Block Type",
                    "# of Beds",
                    "Bed Width (feet)",
                    "Bedfeet per Bed",
                ],
                ["Field 1", "Field", "1", "3", "100"],
            ],
            "spreadsheet_id": "stub-doc",
            "spreadsheet_name": "Stub Doc",
            "modified_time": None,
            "worksheet_title": tab_config["worksheet_title"],
            "drive_folder_id": None,
        }

    def fetch_tab_structure(self, tab_config: dict) -> dict:
        self.calls.append(f"struct:{tab_config['worksheet_title']}")
        return {
            "worksheet_title": tab_config["worksheet_title"],
            "tab_position": 0,
            "hidden": False,
            "frozen_rows": 1,
            "frozen_cols": 0,
            "total_rows": 1,
            "total_cols": 5,
            "columns": [
                {
                    "index": 0,
                    "col_letter": "A",
                    "header_label": "Block",
                    "is_formula": False,
                    "data_validation_type": None,
                }
            ],
            "named_ranges": [],
            "filter_views": [],
        }


def _stub_config(tmp_path):
    config = {
        "provider": "stub",
        "source_id": "stub-bundle",
        "tabs": [
            {
                "worksheet_title": "Blocks",
                "output_path": "reference/blocks.csv",
                "required_headers": [
                    "Block",
                    "Block Type",
                    "# of Beds",
                    "Bed Width (feet)",
                    "Bedfeet per Bed",
                ],
            }
        ],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def test_pull_bundle_writes_structure_json(tmp_path):
    config_path = _stub_config(tmp_path)
    out_dir = tmp_path / "bundle"
    stub = _StubAdapter({})

    with patch(
        "profiler.management.commands.pull_bundle.build_provider_adapter",
        return_value=stub,
    ):
        call_command(
            "pull_bundle",
            config=str(config_path),
            output_dir=str(out_dir),
            include_structure=True,
        )

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "bundle-draft-1"

    structure_path = out_dir / "structure.json"
    assert structure_path.exists()
    structure = json.loads(structure_path.read_text(encoding="utf-8"))
    assert structure["schema_version"] == "structure-draft-1"
    assert structure["source_id"] == "stub-bundle"
    assert structure["provider"] == "stub"
    assert len(structure["tabs"]) == 1
    assert structure["tabs"][0]["worksheet_title"] == "Blocks"

    assert "rows:Blocks" in stub.calls
    assert "struct:Blocks" in stub.calls


def test_pull_bundle_no_structure_flag(tmp_path):
    config_path = _stub_config(tmp_path)
    out_dir = tmp_path / "bundle"
    stub = _StubAdapter({})

    with patch(
        "profiler.management.commands.pull_bundle.build_provider_adapter",
        return_value=stub,
    ):
        call_command(
            "pull_bundle",
            config=str(config_path),
            output_dir=str(out_dir),
        )

    assert (out_dir / "manifest.json").exists()
    assert not (out_dir / "structure.json").exists()
    # Adapter must not have been asked for structure when the flag is absent.
    assert "struct:Blocks" not in stub.calls
