"""Tests for the OperationalModel dataclass layer."""

from profiler.tools.operational_model import (
    Capability,
    Workflow,
    Command,
    Event,
    Invariant,
    OperationalModel,
)


class TestOperationalModelDataclasses:
    """Validate construction, defaults, and round-trip serialization."""

    def test_capability_minimal(self):
        """Minimal construction uses default values."""
        capability = Capability(id="plan_production")
        assert capability.id == "plan_production"
        assert capability.owner == ""
        assert capability.criticality == "medium"
        assert capability.workflows == []

    def test_capability_full(self):
        """Full construction sets all fields and workflows list."""
        capability = Capability(
            id="plan_production",
            owner="operations",
            criticality="high",
            workflows=["weekly_harvest_planning"],
        )
        assert capability.workflows == ["weekly_harvest_planning"]

    def test_workflow_evidence_list(self):
        """Workflow stores evidence and command references."""
        workflow = Workflow(
            id="weekly_harvest_planning",
            frequency="weekly",
            actor="field_manager",
            commands=["create_harvest_plan"],
            outcome="harvest_plan_approved",
            evidence=["harvest_orders_sheet"],
        )
        assert workflow.evidence == ["harvest_orders_sheet"]

    def test_event_payload_and_sourced_from(self):
        """Event carries payload schema and source provenance."""
        event = Event(
            id="inventory_adjusted",
            payload=["item", "quantity_before", "quantity_after"],
            sourced_from=[{"tab": "Inventory", "column": "Adjustment Quantity"}],
            immutable=True,
        )
        assert event.immutable is True
        assert event.sourced_from[0]["tab"] == "Inventory"

    def test_invariant_enforcement_levels(self):
        """Invariant supports different enforcement strategies."""
        invariant = Invariant(
            id="inventory_never_negative",
            expression="inventory.quantity >= 0",
            enforcement="database_check",
            violations_are="blocking",
        )
        assert invariant.enforcement == "database_check"

    def test_operational_model_as_dict(self):
        """to_dict produces versioned dict with all sub-collections."""
        model = OperationalModel(
            capabilities=[Capability(id="plan_production")],
            workflows=[Workflow(id="weekly_harvest_planning")],
            commands=[Command(id="record_adjustment")],
            events=[Event(id="inventory_adjusted")],
            invariants=[Invariant(id="inventory_never_negative")],
        )
        data = model.to_dict()
        assert data["version"] == "operational-model-1"
        assert len(data["capabilities"]) == 1
        assert data["capabilities"][0]["id"] == "plan_production"

    def test_operational_model_from_dict(self):
        """from_dict reconstructs OperationalModel from plain dict."""
        data = {
            "version": "operational-model-1",
            "generated_at": "2026-06-25T12:00:00+00:00",
            "source_id": "farm_corpus",
            "capabilities": [{"id": "plan_production", "owner": "operations"}],
            "workflows": [],
            "commands": [],
            "events": [],
            "invariants": [],
        }
        model = OperationalModel.from_dict(data)
        assert model.capabilities[0].id == "plan_production"
        assert model.capabilities[0].owner == "operations"

    def test_operational_model_yaml_round_trip(self, tmp_path):
        """to_yaml then from_yaml preserves all fields."""
        model = OperationalModel(
            source_id="test_corpus",
            capabilities=[Capability(id="c1", owner="ops")],
            workflows=[Workflow(id="w1", actor="admin")],
            commands=[],
            events=[],
            invariants=[],
        )
        yaml_path = tmp_path / "operational-model.yaml"
        model.to_yaml(yaml_path)
        restored = OperationalModel.from_yaml(yaml_path)
        assert restored.source_id == "test_corpus"
        assert restored.capabilities[0].id == "c1"
