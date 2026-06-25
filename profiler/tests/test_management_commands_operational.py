"""Smoke tests for operational model management commands."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from profiler.tools.pipeline_state import PipelineState


class TestDeriveOperationalModelCommand:
    """Tests for derive_operational_model management command."""

    def test_command_runs(self, tmp_path, settings):
        """Command derives operational model and writes YAML."""
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.domain_knowledge.domain = "test"
        state.discovery.workbook_index = [{"tab_title": "Sheet1", "row_count": 10}]
        state.save_checkpoint(checkpoint_path)

        out_path = tmp_path / "operational-model.yaml"
        call_command(
            "derive_operational_model",
            checkpoint=str(checkpoint_path),
            out=str(out_path),
            stdout=StringIO(),
        )
        assert out_path.exists()

    def test_command_fails_without_domain(self, tmp_path, settings):
        """Command errors when domain_knowledge is empty."""
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.save_checkpoint(checkpoint_path)

        with pytest.raises(RuntimeError):
            call_command(
                "derive_operational_model",
                checkpoint=str(checkpoint_path),
                stdout=StringIO(),
            )


class TestDeriveStateProjectionsCommand:
    """Tests for derive_state_projections management command."""

    def test_command_runs(self, tmp_path, settings):
        """Command derives schema contract projection from operational model."""
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.domain_knowledge.domain = "test"
        state.discovery.workbook_index = [{"tab_title": "Sheet1", "row_count": 10}]
        state.derive_operational_model()
        state.save_checkpoint(checkpoint_path)

        out_path = tmp_path / "schema-contract.yaml"
        call_command(
            "derive_state_projections",
            checkpoint=str(checkpoint_path),
            out=str(out_path),
            stdout=StringIO(),
        )
        assert out_path.exists()

    def test_command_fails_without_operational_model(self, tmp_path, settings):
        """Command errors when operational model is missing."""
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.save_checkpoint(checkpoint_path)

        with pytest.raises(CommandError):
            call_command(
                "derive_state_projections",
                checkpoint=str(checkpoint_path),
                stdout=StringIO(),
            )


class TestValidateOperationalModelCommand:
    """Tests for validate_operational_model management command."""

    def test_command_computes_coverage(self, tmp_path, settings):
        """Command computes and reports coverage metrics."""
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.domain_knowledge.domain = "test"
        state.discovery.workbook_index = [{"tab_title": "Sheet1"}]
        state.derive_operational_model()
        state.save_checkpoint(checkpoint_path)

        out = StringIO()
        call_command(
            "validate_operational_model",
            checkpoint=str(checkpoint_path),
            threshold=0.0,
            stdout=out,
        )
        assert "Data coverage" in out.getvalue()

    def test_command_fails_without_operational_model(self, tmp_path, settings):
        """Command errors when operational model is missing."""
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.save_checkpoint(checkpoint_path)

        with pytest.raises(CommandError):
            call_command(
                "validate_operational_model",
                checkpoint=str(checkpoint_path),
                stdout=StringIO(),
            )
