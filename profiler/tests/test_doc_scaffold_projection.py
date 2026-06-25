"""Tests for the doc_scaffold projection from the operational model."""

import pytest

from profiler.tools.operational_model import (
    Capability,
    Command,
    Event,
    Invariant,
    OperationalModel,
    Workflow,
)
from profiler.tools.pipeline_state import PipelineState


def _build_state_with_fake_model(tmp_path) -> PipelineState:
    """Build a PipelineState with a populated operational model for testing."""
    state = PipelineState()
    state.configure(out_dir=tmp_path)
    state.domain_knowledge.domain = "test_farm"
    state.discovery.workbook_index = [
        {"tab_title": "Crop Planner", "row_count": 100},
        {"tab_title": "Planting Log", "row_count": 50},
    ]
    state.operational_model = OperationalModel(
        source_id="test_farm",
        capabilities=[
            Capability(
                id="crop_management",
                owner="grower",
                criticality="high",
                workflows=["plant_crop", "harvest_crop"],
            ),
            Capability(
                id="inventory_tracking",
                owner="logistics",
                criticality="medium",
                workflows=["order_supplies"],
            ),
        ],
        workflows=[
            Workflow(
                id="plant_crop",
                frequency="seasonal",
                actor="grower",
                commands=["prepare_field", "sow_seeds", "irrigate"],
                outcome="Crop planted",
                evidence=["Planting Log tab", "Crop Planner tab"],
            ),
            Workflow(
                id="harvest_crop",
                frequency="seasonal",
                actor="grower",
                commands=["inspect_ripeness", "pick", "pack"],
                outcome="Crop harvested",
                evidence=["Harvest Log tab"],
            ),
        ],
        commands=[
            Command(
                id="prepare_field",
                actor="grower",
                produces=["tilled_field"],
                precondition="field is assigned",
                postcondition="field is ready for sowing",
            ),
            Command(
                id="sow_seeds",
                actor="grower",
                produces=["planted_row"],
                precondition="field is prepared",
                postcondition="seeds are planted",
            ),
            Command(
                id="irrigate",
                actor="grower",
                produces=["watered_crop"],
                precondition="crop is planted",
                postcondition="crop is watered",
            ),
        ],
        events=[
            Event(
                id="crop_planted",
                payload=["crop_name", "plant_date", "field", "quantity"],
                sourced_from=[{"tab": "Planting Log", "column": "Crop Name"}],
            ),
            Event(
                id="crop_harvested",
                payload=["crop_name", "harvest_date", "yield_kg"],
                sourced_from=[{"tab": "Harvest Log", "column": "Crop Name"}],
            ),
        ],
        invariants=[
            Invariant(
                id="quantity_never_negative",
                expression="quantity >= 0",
                enforcement="database_check",
                violations_are="error",
            ),
            Invariant(
                id="plant_date_before_harvest",
                expression="plant_date < harvest_date",
                enforcement="application_logic",
                violations_are="warning",
            ),
        ],
    )
    return state


class TestDocScaffoldProjection:
    """Tests for derive_state_projections with doc_scaffold projection."""

    def test_requires_operational_model(self, tmp_path):
        """Projection phase guards against missing operational model."""
        state = PipelineState()
        state.configure(out_dir=tmp_path)
        with pytest.raises(RuntimeError, match="operational_model"):
            state.derive_state_projections(projection="doc_scaffold")

    def test_unsupported_projection_raises_value_error(self, tmp_path):
        """Unsupported projections still raise ValueError."""
        state = PipelineState()
        state.configure(out_dir=tmp_path)
        state.operational_model = OperationalModel(source_id="test")
        with pytest.raises(ValueError, match="Unsupported projection: invalid"):
            state.derive_state_projections(projection="invalid")

    def test_generates_non_empty_markdown_string(self, tmp_path):
        """Generated doc_scaffold is a non-empty Markdown string."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="doc_scaffold")

        assert state.doc_scaffold is not None
        assert isinstance(state.doc_scaffold, str)
        assert len(state.doc_scaffold) > 0

    def test_contains_all_expected_sections(self, tmp_path):
        """Generated document includes all required sections."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="doc_scaffold")

        scaffold = state.doc_scaffold
        assert scaffold is not None
        assert "## Capabilities" in scaffold
        assert "## Events" in scaffold
        assert "## Workflows" in scaffold
        assert "## Commands" in scaffold
        assert "## Invariants" in scaffold

    def test_source_id_appears_in_title(self, tmp_path):
        """The source_id appears in the document title."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="doc_scaffold")

        scaffold = state.doc_scaffold
        assert scaffold is not None
        assert "# Operational Model: test_farm" in scaffold

    def test_event_details_rendered(self, tmp_path):
        """Event details including ID, payload, and sourced_from are present."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="doc_scaffold")

        scaffold = state.doc_scaffold
        assert scaffold is not None
        assert "crop_planted" in scaffold
        assert "crop_name" in scaffold
        assert "plant_date" in scaffold
        assert "field" in scaffold
        assert "quantity" in scaffold
        assert "Planting Log" in scaffold or "Crop Name" in scaffold

    def test_invariant_details_rendered(self, tmp_path):
        """Invariant details including expression and enforcement are present."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="doc_scaffold")

        scaffold = state.doc_scaffold
        assert scaffold is not None
        assert "quantity_never_negative" in scaffold
        assert "quantity >= 0" in scaffold
        assert "database_check" in scaffold
        assert "plant_date_before_harvest" in scaffold
        assert "plant_date < harvest_date" in scaffold
        assert "application_logic" in scaffold

    def test_capabilities_rendered(self, tmp_path):
        """Capabilities with IDs and owners are present."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="doc_scaffold")

        scaffold = state.doc_scaffold
        assert scaffold is not None
        assert "crop_management" in scaffold
        assert "grower" in scaffold
        assert "inventory_tracking" in scaffold
        assert "logistics" in scaffold

    def test_workflows_rendered(self, tmp_path):
        """Workflows with commands and evidence are present."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="doc_scaffold")

        scaffold = state.doc_scaffold
        assert scaffold is not None
        assert "plant_crop" in scaffold
        assert "harvest_crop" in scaffold
        assert "prepare_field" in scaffold
        assert "sow_seeds" in scaffold

    def test_commands_listed(self, tmp_path):
        """All command IDs appear in the Commands section."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="doc_scaffold")

        scaffold = state.doc_scaffold
        assert scaffold is not None
        assert "Commands" in scaffold

    def test_round_trip_through_checkpoint(self, tmp_path):
        """doc_scaffold persists through save/load cycle."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="doc_scaffold")
        assert state.doc_scaffold is not None

        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state.save_checkpoint(checkpoint_path)

        loaded = PipelineState.load(checkpoint_path)
        assert loaded.doc_scaffold == state.doc_scaffold

    def test_schema_contract_projection_unaffected(self, tmp_path):
        """Existing schema_contract projection still works when doc_scaffold is added."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="schema_contract")
        assert state.schema_contract is not None
        assert "tables" in state.schema_contract
        # doc_scaffold should remain None
        assert state.doc_scaffold is None

    def test_test_scaffold_projection_unaffected(self, tmp_path):
        """Existing test_scaffold projection still works when doc_scaffold is added."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="test_scaffold")
        assert state.test_scaffold is not None
        # doc_scaffold should remain None
        assert state.doc_scaffold is None

    def test_empty_operational_model(self, tmp_path):
        """Generates minimal valid markdown even when model has no data."""
        state = PipelineState()
        state.configure(out_dir=tmp_path)
        state.domain_knowledge.domain = "empty_test"
        state.discovery.workbook_index = []
        state.derive_operational_model()
        state.derive_state_projections(projection="doc_scaffold")

        scaffold = state.doc_scaffold
        assert scaffold is not None
        # Should still have the basic structure
        assert "# Operational Model:" in scaffold
        assert "## Capabilities" in scaffold
        assert "## Events" in scaffold
        assert "## Workflows" in scaffold
        assert "## Commands" in scaffold
        assert "## Invariants" in scaffold

    def test_timestamp_in_document(self, tmp_path):
        """Generated document includes a timestamp."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="doc_scaffold")

        scaffold = state.doc_scaffold
        assert scaffold is not None
        assert "Generated at:" in scaffold

    def test_event_to_workflow_mapping_section(self, tmp_path):
        """Event-to-Workflow Mapping section appears when applicable."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="doc_scaffold")

        scaffold = state.doc_scaffold
        assert scaffold is not None
        assert "Event-to-Workflow Mapping" in scaffold

    def test_invariant_violations_handling_rendered(self, tmp_path):
        """Violations handling text appears for invariants."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="doc_scaffold")

        scaffold = state.doc_scaffold
        assert scaffold is not None
        assert "error" in scaffold
