"""Validation record and coverage report framework.

Captures human review decisions and auto-computed coverage metrics for the
operational model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from profiler.tools.operational_model import OperationalModel


@dataclass
class ValidationRecord:
    """Human review gate output for the operational model."""

    reviewed_by: str = ""
    reviewed_with: str = ""
    date: str = ""
    approvals: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict for serialization."""
        return {
            "reviewed_by": self.reviewed_by,
            "reviewed_with": self.reviewed_with,
            "date": self.date,
            "approvals": list(self.approvals),
            "coverage": dict(self.coverage),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationRecord:
        """Reconstruct from a plain dict."""
        return cls(
            reviewed_by=data.get("reviewed_by", ""),
            reviewed_with=data.get("reviewed_with", ""),
            date=data.get("date", ""),
            approvals=list(data.get("approvals", [])),
            coverage=dict(data.get("coverage", {})),
        )


@dataclass
class CoverageReport:
    """Auto-computed coverage metrics for the operational model."""

    data_coverage: float = 0.0
    workflow_coverage: float = 0.0
    event_coverage: float = 0.0
    invariant_coverage: float = 0.0

    def is_acceptable(self, threshold: float = 0.80) -> bool:
        """Return True if all coverage dimensions meet the threshold."""
        return all(
            dimension >= threshold
            for dimension in [
                self.data_coverage,
                self.workflow_coverage,
                self.event_coverage,
                self.invariant_coverage,
            ]
        )

    def failing_dimensions(self, threshold: float = 0.80) -> list[str]:
        """Return list of dimension names below the threshold."""
        dimensions = {
            "data_coverage": self.data_coverage,
            "workflow_coverage": self.workflow_coverage,
            "event_coverage": self.event_coverage,
            "invariant_coverage": self.invariant_coverage,
        }
        return [
            dimension_name
            for dimension_name, dimension_value in dimensions.items()
            if dimension_value < threshold
        ]

    def to_dict(self) -> dict[str, float]:
        """Convert to a plain dict."""
        return {
            "data_coverage": self.data_coverage,
            "workflow_coverage": self.workflow_coverage,
            "event_coverage": self.event_coverage,
            "invariant_coverage": self.invariant_coverage,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoverageReport:
        """Reconstruct from a plain dict."""
        return cls(
            data_coverage=float(data.get("data_coverage", 0.0)),
            workflow_coverage=float(data.get("workflow_coverage", 0.0)),
            event_coverage=float(data.get("event_coverage", 0.0)),
            invariant_coverage=float(data.get("invariant_coverage", 0.0)),
        )


def compute_coverage_metrics(
    model: OperationalModel,
    artifact_inventory: dict[str, Any],
) -> CoverageReport:
    """Compute coverage metrics by comparing the model against artifact inventory.

    Args:
        model: The operational model to evaluate.
        artifact_inventory: Mapping of artifact IDs to metadata dicts.
            Each metadata dict may contain a ``columns`` list.

    Returns:
        CoverageReport with four dimension scores (0.0–1.0).
    """
    if not artifact_inventory:
        return CoverageReport()

    artifact_ids = set(artifact_inventory.keys())
    total_columns = 0
    for metadata in artifact_inventory.values():
        columns = metadata.get("columns") or []
        total_columns += len(columns)

    # Workflow coverage: fraction of artifacts referenced in workflow evidence
    referenced_artifacts: set[str] = set()
    for workflow in model.workflows:
        referenced_artifacts.update(workflow.evidence)
    workflow_coverage = (
        len(referenced_artifacts & artifact_ids) / len(artifact_ids)
        if artifact_ids
        else 0.0
    )

    # Data coverage: fraction of artifact columns that map to event payloads
    sourced_columns: set[str] = set()
    for event in model.events:
        for source in event.sourced_from:
            tab = source.get("tab", "")
            column = source.get("column", "")
            if tab and column:
                sourced_columns.add(f"{tab}:{column}")

    data_coverage = len(sourced_columns) / total_columns if total_columns > 0 else 0.0

    # Event coverage: fraction of events with non-empty payloads and sources
    event_count = len(model.events)
    well_formed_events = sum(
        1 for event in model.events if event.payload and event.sourced_from
    )
    event_coverage = well_formed_events / event_count if event_count > 0 else 0.0

    # Invariant coverage: always 1.0 if invariants exist (human-confirmed)
    invariant_coverage = 1.0 if model.invariants else 0.0

    return CoverageReport(
        data_coverage=data_coverage,
        workflow_coverage=workflow_coverage,
        event_coverage=event_coverage,
        invariant_coverage=invariant_coverage,
    )
