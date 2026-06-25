"""Tests for validation record and coverage report framework."""

from profiler.tools.validation_framework import (
    ValidationRecord,
    CoverageReport,
    compute_coverage_metrics,
)
from profiler.tools.operational_model import (
    OperationalModel,
    Capability,
    Workflow,
    Event,
    Invariant,
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
            workflow_coverage=0.87,
            event_coverage=0.91,
            invariant_coverage=0.75,
        )
        assert report.is_acceptable(threshold=0.80) is False
        assert report.failing_dimensions(threshold=0.80) == ["invariant_coverage"]

    def test_all_passing(self):
        """All dimensions at or above threshold is acceptable."""
        report = CoverageReport(
            data_coverage=0.90,
            workflow_coverage=0.90,
            event_coverage=0.90,
            invariant_coverage=0.90,
        )
        assert report.is_acceptable(threshold=0.80) is True
        assert report.failing_dimensions(threshold=0.80) == []


class TestComputeCoverageMetrics:
    def test_full_coverage(self):
        """All artifacts mapped to model elements yields full coverage."""
        model = OperationalModel(
            capabilities=[Capability(id="c1")],
            workflows=[Workflow(id="w1", evidence=["sheet_a"])],
            events=[Event(id="e1", sourced_from=[{"tab": "SheetA", "column": "Col1"}])],
            invariants=[Invariant(id="i1")],
        )
        artifact_inventory = {"sheet_a": {"columns": ["Col1"]}}
        report = compute_coverage_metrics(model, artifact_inventory)
        assert report.data_coverage == 1.0
        assert report.workflow_coverage == 1.0

    def test_partial_coverage(self):
        """Unmapped artifacts reduce coverage scores."""
        model = OperationalModel(
            workflows=[Workflow(id="w1", evidence=["sheet_a"])],
            events=[],
        )
        artifact_inventory = {
            "sheet_a": {"columns": ["Col1"]},
            "sheet_b": {"columns": ["Col2"]},
        }
        report = compute_coverage_metrics(model, artifact_inventory)
        assert report.workflow_coverage == 0.5
        assert report.data_coverage == 0.0
