"""Tests for operational model derivation from profiler artifacts."""

from profiler.tools.operational_model_deriver import (
    derive_operational_model,
    _cluster_tabs_into_entities,
    _infer_candidate_events,
    _infer_workflows_from_graph,
    _derive_invariants_from_events,
)
from profiler.tools.operational_model import OperationalModel


class TestDeriveOperationalModel:
    def test_derive_from_minimal_artifacts(self):
        """Derivation produces a valid model from minimal profiler output."""
        discovery = {
            "workbook_index": [
                {"tab_title": "Crop Planner", "row_count": 100, "column_count": 12},
                {"tab_title": "Inventory", "row_count": 200, "column_count": 8},
            ],
            "broad_inventory": [],
        }
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Crop Planner",
                    "columns": [
                        {"header_label": "Crop", "is_formula": False},
                        {
                            "header_label": "Plant Date",
                            "is_formula": False,
                            "null_rate": 0.05,
                            "distinct_values": ["2025-03-01", "2025-04-01"],
                        },
                        {
                            "header_label": "Status",
                            "is_formula": False,
                            "data_validation_type": "dropdown",
                        },
                    ],
                    "fk_candidates": [],
                },
                {
                    "tab_title": "Inventory",
                    "columns": [
                        {"header_label": "Item", "is_formula": False},
                        {"header_label": "Quantity", "is_formula": False},
                        {
                            "header_label": "Adjustment Date",
                            "is_formula": False,
                            "null_rate": 0.10,
                            "distinct_values": ["2025-01-15", "2025-02-15"],
                        },
                    ],
                    "fk_candidates": [],
                },
            ]
        }
        domain_knowledge = {
            "domain": "farm",
            "vocabulary": {"operational": ["crop", "harvest"]},
        }

        model = derive_operational_model(
            discovery=discovery,
            deep_profile_index=deep_profile_index,
            domain_knowledge=domain_knowledge,
        )
        assert isinstance(model, OperationalModel)
        assert model.source_id == "farm"
        assert len(model.capabilities) >= 1
        assert len(model.events) >= 1
        # Events should preserve tab context, not use "unknown"
        for event in model.events:
            for source in event.sourced_from:
                assert source["tab"] != "unknown"

    def test_entity_clustering_jaccard_threshold(self):
        """Tabs with >0.50 Jaccard similarity cluster into same entity."""
        tabs = [
            {"tab_title": "Crop Planner 2025", "columns": ["Crop", "Date", "Status"]},
            {"tab_title": "Crop Planner 2026", "columns": ["Crop", "Date", "Status"]},
            {"tab_title": "Inventory", "columns": ["Item", "Quantity"]},
        ]
        clusters = _cluster_tabs_into_entities(tabs)
        crop_clusters = [c for c in clusters if "Crop" in c["entity_name"]]
        assert len(crop_clusters) >= 1
        assert len(crop_clusters[0]["tabs"]) == 2

    def test_infer_candidate_events(self):
        """Columns with temporal keywords and low null rates become event candidates."""
        columns = [
            {
                "header_label": "Adjustment Date",
                "null_rate": 0.05,
                "distinct_values": ["2025-01-01", "2025-01-02"],
            },
            {
                "header_label": "Quantity",
                "null_rate": 0.10,
                "distinct_values": ["10", "20"],
            },
            {"header_label": "Notes", "null_rate": 0.60, "distinct_values": []},
        ]
        events = _infer_candidate_events(columns)
        assert len(events) >= 1
        assert events[0]["suggested_event_id"] == "adjustment_date_logged"

    def test_workflow_inference_from_formula_graph(self):
        """Formula graph edges produce workflow candidates."""
        formula_graph = {
            "edges": [
                {"from": "Crop Planner", "to": "Harvest Record", "ref_type": "VLOOKUP"},
                {
                    "from": "Harvest Record",
                    "to": "Weekly Sales",
                    "ref_type": "SUM_range",
                },
            ]
        }
        workflows = _infer_workflows_from_graph(formula_graph)
        assert len(workflows) >= 1
        assert any(w["id"] == "crop_planner_to_harvest_record" for w in workflows)

    def test_events_preserve_tab_context(self):
        """Events sourced_from reflects the actual tab, not 'unknown'."""
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Inventory",
                    "columns": [
                        {
                            "header_label": "Adjustment Date",
                            "null_rate": 0.05,
                            "distinct_values": ["2025-01-01"],
                        },
                    ],
                }
            ]
        }
        model = derive_operational_model(
            discovery={"workbook_index": [{"tab_title": "Inventory"}]},
            deep_profile_index=deep_profile_index,
            domain_knowledge={"domain": "test"},
        )
        assert len(model.events) == 1
        assert model.events[0].sourced_from[0]["tab"] == "Inventory"

    def test_derive_invariants_from_events(self):
        """Quantity fields in event payloads suggest non-negative invariants."""
        events = [
            {
                "id": "inventory_adjusted",
                "payload": ["item", "quantity_before", "quantity_after"],
            },
        ]
        invariants = _derive_invariants_from_events(events)
        assert len(invariants) >= 1
        assert any("quantity" in inv["expression"] for inv in invariants)
