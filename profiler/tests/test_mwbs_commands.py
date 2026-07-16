"""Tests for MWBS management commands (derive_behavioral_spec and validate_behavioral_spec)."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from profiler.tools.pipeline_state import PipelineState


class TestDeriveBehavioralSpecCommand:
    """Tests for derive_behavioral_spec management command."""

    def test_derive_behavioral_spec_command_creates_spec(self, tmp_path, settings):
        """Command derives behavioral spec and writes YAML."""
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.domain_knowledge.domain = "test"
        state.discovery.workbook_index = [{"tab_title": "Sheet1", "row_count": 10}]
        state.save_checkpoint(checkpoint_path)

        out_path = tmp_path / "behavioral-spec.yaml"
        call_command(
            "derive_behavioral_spec",
            checkpoint=str(checkpoint_path),
            out=str(out_path),
            stdout=StringIO(),
        )
        assert out_path.exists()

    def test_derive_behavioral_spec_command_errors_without_checkpoint(
        self, tmp_path, settings
    ):
        """Command errors when checkpoint file does not exist (empty state, no domain)."""
        out_path = tmp_path / "behavioral-spec.yaml"
        with pytest.raises(RuntimeError):
            call_command(
                "derive_behavioral_spec",
                checkpoint=str(tmp_path / "nonexistent.yaml"),
                out=str(out_path),
                stdout=StringIO(),
            )


class TestValidateBehavioralSpecCommand:
    """Tests for validate_behavioral_spec management command."""

    def test_validate_behavioral_spec_command_computes_coverage(
        self, tmp_path, settings
    ):
        """Command computes and reports coverage metrics."""
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.domain_knowledge.domain = "test"
        state.discovery.workbook_index = [{"tab_title": "Sheet1"}]
        state.derive_behavioral_spec()
        state.save_checkpoint(checkpoint_path)

        out = StringIO()
        call_command(
            "validate_behavioral_spec",
            checkpoint=str(checkpoint_path),
            threshold=0.0,
            stdout=out,
        )
        assert "Data coverage" in out.getvalue()

    def test_validate_behavioral_spec_command_errors_without_behavioral_spec(
        self, tmp_path, settings
    ):
        """Command errors when behavioral spec is missing."""
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.save_checkpoint(checkpoint_path)

        with pytest.raises(CommandError):
            call_command(
                "validate_behavioral_spec",
                checkpoint=str(checkpoint_path),
                stdout=StringIO(),
            )

    def test_validate_behavioral_spec_command_failing_threshold(
        self, tmp_path, settings
    ):
        """Command errors when coverage is below threshold."""
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.domain_knowledge.domain = "test"
        state.discovery.workbook_index = [{"tab_title": "Sheet1"}]
        state.derive_behavioral_spec()
        state.save_checkpoint(checkpoint_path)

        with pytest.raises(CommandError):
            call_command(
                "validate_behavioral_spec",
                checkpoint=str(checkpoint_path),
                threshold=1.0,
                stdout=StringIO(),
            )

    def test_draft_mode(self, tmp_path, settings):
        """Command passes with --draft even when formula/exception/report are 0.0."""
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.domain_knowledge.domain = "test"
        state.discovery.workbook_index = [{"tab_title": "Sheet1"}]
        state.derive_behavioral_spec()
        state.save_checkpoint(checkpoint_path)

        out = StringIO()
        call_command(
            "validate_behavioral_spec",
            checkpoint=str(checkpoint_path),
            draft=True,
            stdout=out,
        )
        assert "Data coverage" in out.getvalue()
        assert "Structural coverage" in out.getvalue()
        assert "Workflow coverage" in out.getvalue()
        assert "Formula coverage" not in out.getvalue()
        assert "Exception coverage" not in out.getvalue()
        assert "Report coverage" not in out.getvalue()

    def test_default_threshold_zero(self):
        """Parser argument default is 0.0."""
        from profiler.management.commands.validate_behavioral_spec import Command

        cmd = Command()
        parser = cmd.create_parser("manage", "validate_behavioral_spec")
        args = parser.parse_args([])
        assert args.threshold == 0.0

    def test_checkpoint_not_saved_on_failure(self, tmp_path, settings):
        """Checkpoint is NOT updated when validation fails."""
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.domain_knowledge.domain = "test"
        state.discovery.workbook_index = [{"tab_title": "Sheet1"}]
        state.derive_behavioral_spec()
        # Run validate_behavioral_spec first to populate coverage_report
        state.validate_behavioral_spec()
        state.save_checkpoint(checkpoint_path)

        # Load the checkpoint to get the original coverage_report
        original_state = PipelineState.load(checkpoint_path)
        assert original_state.coverage_report is not None, (
            "coverage_report must be populated by validate_behavioral_spec"
        )
        original_coverage_report = original_state.coverage_report

        with pytest.raises(CommandError):
            call_command(
                "validate_behavioral_spec",
                checkpoint=str(checkpoint_path),
                threshold=0.5,  # Set threshold high enough to fail
                stdout=StringIO(),
            )

        # Load checkpoint again and verify coverage_report hasn't changed
        # (command should NOT save on failure)
        final_state = PipelineState.load(checkpoint_path)
        assert final_state.coverage_report is not None
        assert (
            final_state.coverage_report.data_coverage
            == original_coverage_report.data_coverage
        )
        assert (
            final_state.coverage_report.formula_coverage
            == original_coverage_report.formula_coverage
        )
        assert (
            final_state.coverage_report.structural_coverage
            == original_coverage_report.structural_coverage
        )
        assert (
            final_state.coverage_report.workflow_coverage
            == original_coverage_report.workflow_coverage
        )
        assert (
            final_state.coverage_report.exception_coverage
            == original_coverage_report.exception_coverage
        )
        assert (
            final_state.coverage_report.report_coverage
            == original_coverage_report.report_coverage
        )
