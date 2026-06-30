"""Tests for the view-manifest builder and management command."""

from __future__ import annotations

import json

import yaml
from django.core.management import call_command

from workbook.view_manifest import VIEW_MANIFEST_VERSION, build_view_manifest


def _orders_structure(*, hidden_staging: bool = False) -> dict:
    """Build a fixture structure dict mimicking pull_bundle --include-structure output."""
    tabs = [
        {
            "worksheet_title": "Orders",
            "tab_position": 0,
            "hidden": False,
            "frozen_rows": 1,
            "frozen_cols": 0,
            "total_rows": 100,
            "total_cols": 4,
            "columns": [
                {
                    "index": 0,
                    "col_letter": "A",
                    "header_label": "Order ID",
                    "is_formula": False,
                    "data_validation_type": None,
                },
                {
                    "index": 1,
                    "col_letter": "B",
                    "header_label": "Customer",
                    "is_formula": False,
                    "data_validation_type": None,
                },
                {
                    "index": 2,
                    "col_letter": "C",
                    "header_label": "Status",
                    "is_formula": False,
                    "data_validation_type": "ONE_OF_LIST",
                },
                {
                    "index": 3,
                    "col_letter": "D",
                    "header_label": "Total",
                    "is_formula": True,
                    "data_validation_type": None,
                },
            ],
            "named_ranges": [],
            "filter_views": [],
        }
    ]
    if hidden_staging:
        tabs.append(
            {
                "worksheet_title": "Staging",
                "tab_position": 1,
                "hidden": True,
                "frozen_rows": 1,
                "frozen_cols": 0,
                "total_rows": 50,
                "total_cols": 1,
                "columns": [
                    {
                        "index": 0,
                        "col_letter": "A",
                        "header_label": "Note",
                        "is_formula": False,
                        "data_validation_type": None,
                    }
                ],
                "named_ranges": [],
                "filter_views": [],
            }
        )
    return {
        "schema_version": "structure-draft-1",
        "source_id": "demo",
        "provider": "google_sheets",
        "tabs": tabs,
    }


def test_build_view_manifest_minimal_structure_only():
    structure = {
        "schema_version": "structure-draft-1",
        "source_id": "demo",
        "provider": "google_sheets",
        "tabs": [
            {
                "worksheet_title": "Notes",
                "tab_position": 0,
                "hidden": False,
                "columns": [
                    {
                        "header_label": "Title",
                        "is_formula": False,
                        "data_validation_type": None,
                    },
                    {
                        "header_label": "Computed Hash",
                        "is_formula": True,
                        "data_validation_type": None,
                    },
                ],
            }
        ],
    }

    manifest = build_view_manifest(structure)

    assert manifest["version"] == VIEW_MANIFEST_VERSION
    assert manifest["source"] == {"source_id": "demo", "provider": "google_sheets"}
    assert len(manifest["views"]) == 1

    view = manifest["views"][0]
    assert view["entity"] is None
    assert view["source_tab"] == "Notes"
    assert view["type"] == "list"
    assert view["editable_fields"] == ["title"]
    assert view["computed_fields"] == ["computed_hash"]
    assert view["filterable_by"] == []
    assert view["status_field"] is None
    assert view["notes"] is None


def test_build_view_manifest_status_field_heuristic():
    structure = _orders_structure()
    manifest = build_view_manifest(structure)
    view = manifest["views"][0]
    assert view["status_field"] == "status"

    # Without validation, the heuristic must NOT fire even on a 'Status' header.
    structure["tabs"][0]["columns"][2]["data_validation_type"] = None
    manifest_no_dv = build_view_manifest(structure)
    assert manifest_no_dv["views"][0]["status_field"] is None


def test_build_view_manifest_filterable_from_validation():
    structure = _orders_structure()
    manifest = build_view_manifest(structure)
    view = manifest["views"][0]
    assert view["filterable_by"] == ["status"]
    assert "status" not in view["computed_fields"]
    assert "total" in view["computed_fields"]
    assert "order_id" in view["editable_fields"]


def test_build_view_manifest_binds_entity_from_contract():
    structure = _orders_structure()
    schema_contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "bundle_worksheet_title": "Orders",
                "suggested_model_name": "orders",
                "model_name": "Orders",
                "bundle_output_path": "data/orders.csv",
                "columns": [
                    {
                        "source_column": "Order ID",
                        "suggested_field_name": "order_id_pk",
                    },
                    {
                        "source_column": "Customer",
                        "suggested_field_name": "customer_name",
                    },
                    {"source_column": "Status", "suggested_field_name": "status"},
                    {"source_column": "Total", "suggested_field_name": "total_amount"},
                ],
            }
        ],
    }

    manifest = build_view_manifest(structure, schema_contract=schema_contract)
    view = manifest["views"][0]
    assert view["entity"] == "orders"
    assert "order_id_pk" in view["editable_fields"]
    assert "customer_name" in view["editable_fields"]
    assert view["computed_fields"] == ["total_amount"]
    assert view["filterable_by"] == ["status"]


def test_build_view_manifest_excludes_hidden_tabs_from_sequence():
    structure = _orders_structure(hidden_staging=True)
    manifest = build_view_manifest(structure)

    titles = [v["source_tab"] for v in manifest["views"]]
    # Hidden tabs still produce a view entry so the operator can review them.
    assert titles == ["Orders", "Staging"]
    # ...but workflow_hints.tab_sequence is the visible-only ordering.
    assert manifest["workflow_hints"]["tab_sequence"] == ["Orders"]
    assert manifest["workflow_hints"]["role_hints"] == []
    assert manifest["workflow_hints"]["weekly_actions"] == []


def test_build_view_manifest_infers_time_scope_from_year_and_week():
    structure = {
        "schema_version": "structure-draft-1",
        "source_id": "demo",
        "provider": "google_sheets",
        "tabs": [
            {
                "worksheet_title": "Crop Plans",
                "tab_position": 0,
                "hidden": False,
                "columns": [
                    {
                        "header_label": "Block",
                        "is_formula": False,
                        "data_validation_type": None,
                    },
                    {
                        "header_label": "Plan Field Week",
                        "is_formula": False,
                        "data_validation_type": None,
                    },
                    {
                        "header_label": "Source Bundle Year",
                        "is_formula": False,
                        "data_validation_type": None,
                    },
                ],
            }
        ],
    }
    schema_contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "bundle_worksheet_title": "Crop Plans",
                "suggested_model_name": "crop_plan",
                "model_name": "CropPlan",
                "bundle_output_path": "data/crop_plans.csv",
                "columns": [
                    {
                        "source_column": "Block",
                        "suggested_field_name": "block",
                        "django_field_class": "models.ForeignKey",
                        "django_field_kwargs": {"to": "FieldBlock"},
                    },
                    {
                        "source_column": "Plan Field Week",
                        "suggested_field_name": "plan_field_week",
                        "django_field_class": "models.IntegerField",
                        "django_field_kwargs": {"null": True},
                    },
                    {
                        "source_column": "Source Bundle Year",
                        "suggested_field_name": "source_bundle_year",
                        "django_field_class": "models.IntegerField",
                        "django_field_kwargs": {"null": True},
                    },
                ],
            }
        ],
    }
    manifest = build_view_manifest(structure, schema_contract=schema_contract)
    view = manifest["views"][0]
    assert "time_scope" in view
    ts = view["time_scope"]
    assert ts["year_field"] == "source_bundle_year"
    assert ts["week_field"] == "plan_field_week"
    assert ts["default_scope"] == "current_season"


def test_build_view_manifest_time_scope_with_date_field():
    structure = {
        "schema_version": "structure-draft-1",
        "source_id": "demo",
        "provider": "google_sheets",
        "tabs": [
            {
                "worksheet_title": "Market Data",
                "tab_position": 0,
                "hidden": False,
                "columns": [
                    {
                        "header_label": "Outlet",
                        "is_formula": False,
                        "data_validation_type": None,
                    },
                    {
                        "header_label": "Distribution Date",
                        "is_formula": False,
                        "data_validation_type": None,
                    },
                ],
            }
        ],
    }
    schema_contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "bundle_worksheet_title": "Market Data",
                "suggested_model_name": "market_entry",
                "model_name": "MarketEntry",
                "bundle_output_path": "data/market.csv",
                "columns": [
                    {
                        "source_column": "Outlet",
                        "suggested_field_name": "outlet",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "source_column": "Distribution Date",
                        "suggested_field_name": "distribution_date",
                        "django_field_class": "models.DateField",
                        "django_field_kwargs": {"null": True},
                    },
                ],
            }
        ],
    }
    manifest = build_view_manifest(structure, schema_contract=schema_contract)
    view = manifest["views"][0]
    ts = view.get("time_scope")
    assert ts is not None
    assert ts["date_field"] == "distribution_date"


def test_build_view_manifest_no_time_scope_when_no_temporal():
    structure = _orders_structure()
    manifest = build_view_manifest(structure)
    view = manifest["views"][0]
    assert view.get("time_scope") is None


def test_build_view_manifest_status_values_with_column_profiles():
    """When column_profiles provides distinct values, status_values is populated."""
    structure = _orders_structure()
    schema_contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "bundle_worksheet_title": "Orders",
                "suggested_model_name": "orders",
                "model_name": "Orders",
                "bundle_output_path": "data/orders.csv",
                "columns": [
                    {
                        "source_column": "Order ID",
                        "suggested_field_name": "order_id",
                        "django_field_class": "models.IntegerField",
                        "django_field_kwargs": {},
                    },
                    {
                        "source_column": "Customer",
                        "suggested_field_name": "customer",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "source_column": "Status",
                        "suggested_field_name": "status",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 50},
                    },
                    {
                        "source_column": "Total",
                        "suggested_field_name": "total",
                        "django_field_class": "models.DecimalField",
                        "django_field_kwargs": {"max_digits": 10, "decimal_places": 2},
                    },
                ],
            }
        ],
    }
    column_profiles = {
        "Orders": {
            "status": {
                "distinct_values": ["Planted", "Harvested", "Finished"],
                "distinct_count": 3,
            }
        }
    }
    manifest = build_view_manifest(
        structure,
        schema_contract=schema_contract,
        column_profiles=column_profiles,
    )
    view = manifest["views"][0]
    assert view["status_field"] == "status"
    assert view["status_values"] == ["Planted", "Harvested", "Finished"]


def test_build_view_manifest_status_values_none_when_no_profiles():
    """Without column_profiles, status_values is not populated."""
    structure = _orders_structure()
    manifest = build_view_manifest(structure)
    view = manifest["views"][0]
    assert view.get("status_values") is None


def test_scaffold_view_manifest_command_writes_yaml(tmp_path):
    structure_path = tmp_path / "structure.json"
    structure_path.write_text(
        json.dumps(_orders_structure(hidden_staging=True)), encoding="utf-8"
    )

    contract_path = tmp_path / "schema-contract.yaml"
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "bundle_worksheet_title": "Orders",
                "suggested_model_name": "orders",
                "model_name": "Orders",
                "bundle_output_path": "data/orders.csv",
                "columns": [
                    {"source_column": "Order ID", "suggested_field_name": "order_id"},
                    {"source_column": "Customer", "suggested_field_name": "customer"},
                    {"source_column": "Status", "suggested_field_name": "status"},
                    {"source_column": "Total", "suggested_field_name": "total"},
                ],
            }
        ],
    }
    contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")

    out_path = tmp_path / "view-manifest.yaml"
    summary_path = tmp_path / "view-manifest.summary.json"

    call_command(
        "scaffold_view_manifest",
        structure=str(structure_path),
        schema_contract=str(contract_path),
        out=str(out_path),
        summary_json=str(summary_path),
    )

    manifest = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert manifest["version"] == VIEW_MANIFEST_VERSION
    assert [v["source_tab"] for v in manifest["views"]] == ["Orders", "Staging"]
    orders_view = manifest["views"][0]
    assert orders_view["entity"] == "orders"
    assert orders_view["status_field"] == "status"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary == {
        "version": VIEW_MANIFEST_VERSION,
        "view_count": 2,
        "entities_bound": 1,
        "status_fields_inferred": 1,
        "tabs_hidden_skipped": 1,
    }


def test_view_entry_with_acceptance_criteria():
    """View manifest entry can define acceptance criteria."""
    view_entry = {
        "tab": "HarvestOrders",
        "model_name": "HarvestOrder",
        "view_type": "list",
        "acceptance_criteria": [
            {
                "id": "AC-harvest-001",
                "type": "completion",
                "description": "All confirmed orders appear in harvest plan",
                "assertion": "count(harvest_order.line_items) == count(confirmed_orders)",
                "test_type": "automated",
            }
        ],
    }
    assert view_entry["acceptance_criteria"][0]["type"] == "completion"


def test_validate_view_manifest_with_acceptance_criteria():
    """View manifest validation catches bad acceptance criteria."""
    from workbook.view_manifest import validate_view_manifest

    manifest = {
        "version": "view-manifest-draft-1",
        "views": [
            {
                "name": "harvest_orders",
                "acceptance_criteria": [
                    {
                        "id": "AC-001",
                        "type": "completion",
                        "description": "All orders included",
                        "test_type": "automated",
                    },
                    {
                        "id": "AC-002",
                        "type": "invalid_type",
                        "description": "Bad type",
                        "test_type": "automated",
                    },
                    {
                        "id": "AC-003",
                        "type": "completion",
                        "description": "",
                        "test_type": "manual",
                    },
                ],
            }
        ],
    }
    errors = validate_view_manifest(manifest)
    assert any("invalid type" in e for e in errors)
    assert any("missing description" in e for e in errors)
