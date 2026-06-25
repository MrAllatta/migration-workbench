"""Tests for the test_scaffold projection from the operational model."""

import pytest

from profiler.tools.operational_model import (
    Event,
    Invariant,
    OperationalModel,
    Workflow,
)
from profiler.tools.pipeline_state import PipelineState


class TestTestScaffoldProjection:
    """Tests for derive_state_projections with test_scaffold projection."""

    def test_requires_operational_model(self, tmp_path):
        """Projection phase guards against missing operational model."""
        state = PipelineState()
        state.configure(out_dir=tmp_path)
        with pytest.raises(RuntimeError, match="operational_model"):
            state.derive_state_projections(projection="test_scaffold")

    def test_unsupported_projection_raises_value_error(self, tmp_path):
        """Unsupported projections still raise ValueError."""
        state = PipelineState()
        state.configure(out_dir=tmp_path)
        state.operational_model = OperationalModel(source_id="test")
        with pytest.raises(ValueError, match="Unsupported projection: invalid"):
            state.derive_state_projections(projection="invalid")

    def test_generates_valid_python_string(self, tmp_path):
        """Generated test_scaffold is a non-empty Python source string."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="test_scaffold")

        assert state.test_scaffold is not None
        assert isinstance(state.test_scaffold, str)
        assert len(state.test_scaffold) > 0
        # Verify it compiles as valid Python
        compile(state.test_scaffold, "<test>", "exec")

    def test_contains_test_classes_and_methods(self, tmp_path):
        """Generated scaffold includes test classes for invariants, workflows, events."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="test_scaffold")

        scaffold = state.test_scaffold
        assert scaffold is not None
        assert "class TestOperationalInvariants" in scaffold
        assert "class TestOperationalWorkflows" in scaffold
        assert "class TestOperationalEvents" in scaffold
        assert "import pytest" in scaffold

    def test_invariant_tests_for_database_check(self, tmp_path):
        """Database_check invariants produce test methods."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="test_scaffold")

        scaffold = state.test_scaffold
        assert scaffold is not None
        assert "test_quantity_never_negative" in scaffold

    def test_workflow_tests_generated(self, tmp_path):
        """Workflows produce test methods for commands."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="test_scaffold")

        scaffold = state.test_scaffold
        assert scaffold is not None
        assert "test_plant_crop_has_commands" in scaffold
        assert "assert len(commands_list) >= 1" in scaffold

    def test_event_tests_generated(self, tmp_path):
        """Events produce test methods for payload."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="test_scaffold")

        scaffold = state.test_scaffold
        assert scaffold is not None
        assert "test_crop_planted_has_payload" in scaffold
        assert "assert len(payload_list) >= 1" in scaffold

    def test_source_id_and_timestamp_in_header(self, tmp_path):
        """Generated scaffold includes source_id and timestamp in header."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="test_scaffold")

        scaffold = state.test_scaffold
        assert scaffold is not None
        assert "Generated from operational model: test_farm" in scaffold
        assert "Generated at:" in scaffold

    def test_round_trip_through_checkpoint(self, tmp_path):
        """test_scaffold persists through save/load cycle."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="test_scaffold")
        assert state.test_scaffold is not None

        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state.save_checkpoint(checkpoint_path)

        loaded = PipelineState.load(checkpoint_path)
        assert loaded.test_scaffold == state.test_scaffold

    def test_schema_contract_projection_unaffected(self, tmp_path):
        """Existing schema_contract projection still works."""
        state = _build_state_with_fake_model(tmp_path)
        state.derive_state_projections(projection="schema_contract")
        assert state.schema_contract is not None
        assert "tables" in state.schema_contract
        # test_scaffold should remain None
        assert state.test_scaffold is None

    def test_empty_operational_model(self, tmp_path):
        """Generates valid scaffold even when model has no invariants/workflows/events."""
        state = PipelineState()
        state.configure(out_dir=tmp_path)
        state.domain_knowledge.domain = "empty_test"
        state.discovery.workbook_index = []
        state.derive_operational_model()
        state.derive_state_projections(projection="test_scaffold")

        scaffold = state.test_scaffold
        assert scaffold is not None
        # Should still compile
        compile(scaffold, "<test>", "exec")
        # Should contain the class definitions (with placeholder comments)
        assert "class TestOperationalInvariants" in scaffold
        assert "class TestOperationalWorkflows" in scaffold
        assert "class TestOperationalEvents" in scaffold

    def test_app_scaffold_projection_not_yet_implemented(self, tmp_path):
        """Unsupported projection still raises ValueError."""
        state = PipelineState()
        state.configure(out_dir=tmp_path)
        state.operational_model = OperationalModel(source_id="test")
        with pytest.raises(ValueError, match="Unsupported projection: app_scaffold"):
            state.derive_state_projections(projection="app_scaffold")

    def test_unknown_projection_raises_value_error(self, tmp_path):
        """Unsupported projection still raises ValueError."""
        state = PipelineState()
        state.configure(out_dir=tmp_path)
        state.operational_model = OperationalModel(source_id="test")
        with pytest.raises(ValueError, match="Unsupported projection: unknown_thing"):
            state.derive_state_projections(projection="unknown_thing")


def _build_state_with_fake_model(tmp_path) -> PipelineState:
    """Build a PipelineState with a populated operational model for testing."""
    state = PipelineState()
    state.configure(out_dir=tmp_path)
    state.domain_knowledge.domain = "test_farm"
    state.discovery.workbook_index = [
        {"tab_title": "Crop Planner", "row_count": 100},
        {"tab_title": "Planting Log", "row_count": 50},
    ]
    state.deep_profile_index.entries = [
        {
            "tab_title": "Crop Planner",
            "columns": [
                {"header_label": "Crop Name", "null_rate": 0.0},
                {"header_label": "Quantity", "null_rate": 0.05},
            ],
        },
        {
            "tab_title": "Planting Log",
            "columns": [
                {"header_label": "Plant Date", "null_rate": 0.0},
                {"header_label": "Field", "null_rate": 0.0},
            ],
        },
    ]
    state.operational_model = OperationalModel(
        source_id="test_farm",
        workflows=[
            Workflow(
                id="plant_crop",
                frequency="seasonal",
                actor="grower",
                commands=["prepare_field", "sow_seeds", "irrigate"],
                outcome="Crop planted",
            ),
            Workflow(
                id="harvest_crop",
                frequency="seasonal",
                actor="grower",
                commands=["inspect_ripeness", "pick", "pack"],
                outcome="Crop harvested",
            ),
        ],
        events=[
            Event(
                id="crop_planted",
                payload=["crop_name", "plant_date", "field", "quantity"],
                sourced_from=[{"tab": "Planting Log"}],
            ),
            Event(
                id="crop_harvested",
                payload=["crop_name", "harvest_date", "yield_kg"],
                sourced_from=[{"tab": "Harvest Log"}],
            ),
        ],
        invariants=[
            Invariant(
                id="quantity_never_negative",
                expression="quantity >= 0",
                enforcement="database_check",
            ),
            Invariant(
                id="plant_date_before_harvest",
                expression="plant_date < harvest_date",
                enforcement="application_logic",
            ),
        ],
    )
    return state
