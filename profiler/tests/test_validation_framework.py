"""Tests for validation record and coverage report framework."""

from profiler.tools.validation_framework import (
    ValidationRecord,
    CoverageReport,
    compute_coverage_metrics,
)
from profiler.tools.behavioral_spec import (
    BehavioralSpec,
    CoverageMap,
    CoverageMapSummary,
    CoverageMapWorkflow,
)


class TestValidationRecord:
    def test_minimal_record(self):
        """Minimal record uses empty defaults."""
        record = ValidationRecord(reviewed_by="consultant")
        assert record.reviewed_by == "consultant"
        assert record.approvals == []

    def test_approval_layer_status(self):
        """Approval layers preserve status and notes."""
        record = ValidationRecord(
            reviewed_by="consultant",
            approvals=[
                {"layer": "capabilities", "status": "approved"},
                {
                    "layer": "workflows",
                    "status": "modified",
                    "notes": "Added emergency workflow",
                },
            ],
        )
        assert record.approvals[1]["status"] == "modified"

    def test_record_to_dict(self):
        """Round-trip through dict preserves fields."""
        record = ValidationRecord(reviewed_by="alice", reviewed_with="bob")
        data = record.to_dict()
        assert data["reviewed_by"] == "alice"
        assert data["coverage"] == {}


class TestCoverageReport:
    def test_coverage_thresholds(self):
        """Report identifies failing dimensions below threshold."""
        report = CoverageReport(
            data_coverage=0.94,
            formula_coverage=0.88,
            structural_coverage=0.91,
            workflow_coverage=0.87,
            exception_coverage=0.95,
            report_coverage=0.75,
        )
        assert report.is_acceptable(threshold=0.80) is False
        assert report.failing_dimensions(threshold=0.80) == ["report_coverage"]

    def test_all_passing(self):
        """All dimensions at or above threshold is acceptable."""
        report = CoverageReport(
            data_coverage=0.90,
            formula_coverage=0.90,
            structural_coverage=0.90,
            workflow_coverage=0.90,
            exception_coverage=0.90,
            report_coverage=0.90,
        )
        assert report.is_acceptable(threshold=0.80) is True
        assert report.failing_dimensions(threshold=0.80) == []

    def test_completion_gate_passed(self):
        """completion_gate_passed is True only when ALL six dimensions == 1.0."""
        perfect = CoverageReport(
            data_coverage=1.0,
            formula_coverage=1.0,
            structural_coverage=1.0,
            workflow_coverage=1.0,
            exception_coverage=1.0,
            report_coverage=1.0,
        )
        assert perfect.completion_gate_passed is True

        almost = CoverageReport(
            data_coverage=1.0,
            formula_coverage=1.0,
            structural_coverage=1.0,
            workflow_coverage=1.0,
            exception_coverage=1.0,
            report_coverage=0.99,
        )
        assert almost.completion_gate_passed is False


class TestComputeCoverageMetrics:
    def test_full_coverage(self):
        """Full behavioral_coverage_pct yields full structural coverage only.

        Note: structural_coverage derives from coverage_map; other
        dimensions compute independently from actual artifacts, so they
        are 0.0 when the spec has no actors, events, or populated workflows.
        """
        spec = BehavioralSpec(
            coverage_map=CoverageMap(
                workflows=[CoverageMapWorkflow(id="w1")],
                summary=CoverageMapSummary(
                    total_workflows=2,
                    dimensions_covered=2,
                    behavioral_coverage_pct=100.0,
                ),
            ),
        )
        report = compute_coverage_metrics(spec)
        assert report.structural_coverage == 1.0
        assert report.data_coverage == 0.0
        assert report.formula_coverage == 0.0
        assert report.workflow_coverage == 0.0
        assert report.exception_coverage == 0.0
        assert report.report_coverage == 0.0

    def test_partial_coverage(self):
        """Partial behavioral_coverage_pct reduces structural_coverage only."""
        spec = BehavioralSpec(
            coverage_map=CoverageMap(
                workflows=[CoverageMapWorkflow(id="w1")],
                summary=CoverageMapSummary(
                    total_workflows=4,
                    dimensions_covered=1,
                    behavioral_coverage_pct=25.0,
                ),
            ),
        )
        report = compute_coverage_metrics(spec)
        assert report.structural_coverage == 0.25
        assert report.data_coverage == 0.0
        assert report.formula_coverage == 0.0
        assert report.workflow_coverage == 0.0
        assert report.exception_coverage == 0.0
        assert report.report_coverage == 0.0

    def test_no_coverage_map_returns_zeros(self):
        """BehavioralSpec without a coverage map yields all-zero report."""
        spec = BehavioralSpec()
        report = compute_coverage_metrics(spec)
        for dim in [
            "data_coverage",
            "formula_coverage",
            "structural_coverage",
            "workflow_coverage",
            "exception_coverage",
            "report_coverage",
        ]:
            assert getattr(report, dim) == 0.0
