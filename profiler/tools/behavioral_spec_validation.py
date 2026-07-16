"""Validation rules, 6-dimension CoverageReport, and SignOffBlock shim for MWBS.

This module provides the validation layer for the Migration Workbench
Behavioral Specification (MWBS) system. It replaces the old 4-dimension
``profiler.tools.validation_framework`` with:

* ``ValidationRecord`` — unchanged 4-field human review gate dataclass.
* ``CoverageReport`` — six coverage dimensions with ``completion_gate_passed``.
* ``validate_sign_off()`` — 12 sign-off validation rules (Section 8.1).
* ``compute_coverage_metrics()`` — coverage from ``BehavioralSpec``.
* ``SignOffBlockShim`` — standalone serialization shim for checkpoint compat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from profiler.tools.behavioral_spec import (
    MWBS_SPEC_VERSION,
    BehavioralSpec,
    BehavioralWorkflow,
    SignOffBlock,
)

# ---------------------------------------------------------------------------
# ValidationRecord (unchanged from original validation_framework.py)
# ---------------------------------------------------------------------------


@dataclass
class ValidationRecord:
    """Human review gate output for the behavioral specification.

    Attributes:
        reviewed_by: Name or identifier of the reviewer.
        reviewed_with: Name or role of the person the review was conducted with.
        date: ISO-format date of the review.
        approvals: List of approval dicts, one per reviewed layer.
        coverage: Arbitrary dict of coverage metadata.
    """

    reviewed_by: str = ""
    reviewed_with: str = ""
    date: str = ""
    approvals: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict for serialization.

        Returns:
            Dictionary with all fields as plain Python types.
        """
        return {
            "reviewed_by": self.reviewed_by,
            "reviewed_with": self.reviewed_with,
            "date": self.date,
            "approvals": list(self.approvals),
            "coverage": dict(self.coverage),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationRecord:
        """Reconstruct from a plain dict.

        Args:
            data: Dictionary with keys matching the dataclass fields.

        Returns:
            A new ValidationRecord instance populated from the dict.
        """
        return cls(
            reviewed_by=data.get("reviewed_by", ""),
            reviewed_with=data.get("reviewed_with", ""),
            date=data.get("date", ""),
            approvals=list(data.get("approvals", [])),
            coverage=dict(data.get("coverage", {})),
        )


# ---------------------------------------------------------------------------
# 6-Dimension CoverageReport
# ---------------------------------------------------------------------------


@dataclass
class CoverageReport:
    """Auto-computed coverage metrics across six dimensions.

    The six dimensions cover data, formula, structural, workflow, exception,
    and report coverage.  Each is a float between 0.0 and 1.0.

    Attributes:
        data_coverage: All source records imported (0.0–1.0).
        formula_coverage: All calculations reproduced (0.0–1.0).
        structural_coverage: All entities have modules (0.0–1.0).
        workflow_coverage: All signed-off workflows executable (0.0–1.0).
        exception_coverage: All documented exceptions handled (0.0–1.0).
        report_coverage: All operational reports available (0.0–1.0).
    """

    data_coverage: float = 0.0
    formula_coverage: float = 0.0
    structural_coverage: float = 0.0
    workflow_coverage: float = 0.0
    exception_coverage: float = 0.0
    report_coverage: float = 0.0

    def is_acceptable(self, threshold: float = 0.80) -> bool:
        """Return True if all coverage dimensions meet the threshold.

        Args:
            threshold: Minimum acceptable coverage value (default 0.80).

        Returns:
            True if all six dimensions are >= *threshold*.
        """
        return all(
            dimension >= threshold
            for dimension in [
                self.data_coverage,
                self.formula_coverage,
                self.structural_coverage,
                self.workflow_coverage,
                self.exception_coverage,
                self.report_coverage,
            ]
        )

    def failing_dimensions(self, threshold: float = 0.80) -> list[str]:
        """Return list of dimension names below the threshold.

        Args:
            threshold: Minimum acceptable coverage value (default 0.80).

        Returns:
            Names of dimensions whose value is strictly below *threshold*.
        """
        dimension_map = {
            "data_coverage": self.data_coverage,
            "formula_coverage": self.formula_coverage,
            "structural_coverage": self.structural_coverage,
            "workflow_coverage": self.workflow_coverage,
            "exception_coverage": self.exception_coverage,
            "report_coverage": self.report_coverage,
        }
        return [
            dimension_name
            for dimension_name, dimension_value in dimension_map.items()
            if dimension_value < threshold
        ]

    @property
    def completion_gate_passed(self) -> bool:
        """Return True only when ALL six dimensions are at 1.0 (100%).

        This is the "Definition of Complete Migration" gate from the
        MWBS specification (Section 9.3).  Returns True only when every
        dimension is exactly 1.0 — no lower value is acceptable for
        completion.
        """
        return all(
            dimension == 1.0
            for dimension in [
                self.data_coverage,
                self.formula_coverage,
                self.structural_coverage,
                self.workflow_coverage,
                self.exception_coverage,
                self.report_coverage,
            ]
        )

    @property
    def auto_derivable_dimensions(self) -> list[str]:
        """Return names of the three auto-derivable dimensions.

        These dimensions are derived automatically from the behavioral spec
        without requiring manual review or intervention:
        - data_coverage
        - structural_coverage
        - workflow_coverage

        Returns:
            List of dimension names that are auto-derivable.
        """
        return ["data_coverage", "structural_coverage", "workflow_coverage"]

    def to_dict(self) -> dict[str, float]:
        """Convert to a plain dict for serialization.

        Returns:
            Dictionary mapping dimension names to their coverage values.
        """
        return {
            "data_coverage": self.data_coverage,
            "formula_coverage": self.formula_coverage,
            "structural_coverage": self.structural_coverage,
            "workflow_coverage": self.workflow_coverage,
            "exception_coverage": self.exception_coverage,
            "report_coverage": self.report_coverage,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoverageReport:
        """Reconstruct from a plain dict.

        Missing or unknown dimensions default to 0.0, providing backward
        compatibility with older 4-dimension checkpoints.

        Args:
            data: Dictionary with dimension names as keys.

        Returns:
            A new CoverageReport instance.
        """
        return cls(
            data_coverage=float(data.get("data_coverage", 0.0)),
            formula_coverage=float(data.get("formula_coverage", 0.0)),
            structural_coverage=float(data.get("structural_coverage", 0.0)),
            workflow_coverage=float(data.get("workflow_coverage", 0.0)),
            exception_coverage=float(data.get("exception_coverage", 0.0)),
            report_coverage=float(data.get("report_coverage", 0.0)),
        )


# ---------------------------------------------------------------------------
# Sign-Off Validation (12 rules from Section 8.1)
# ---------------------------------------------------------------------------


def _check_workflow_acceptance_completion(
    workflow: BehavioralWorkflow,
    spec: BehavioralSpec,
) -> bool:
    """Check whether a workflow has at least one completion-type criterion.

    Iterates the workflow's acceptance-test references, looks each up
    in ``spec.acceptance_tests`` by id, and returns True if any
    referenced test contains a criterion with ``type == "completion"``.

    Args:
        workflow: The workflow whose acceptance tests to inspect.
        spec: The full spec containing acceptance test definitions.

    Returns:
        True if at least one referenced acceptance test has a
        completion-type criterion.
    """
    for test_ref in workflow.acceptance_tests:
        ref_id = test_ref.get("ref") or test_ref.get("id", "")
        if not ref_id:
            continue
        for acceptance_test in spec.acceptance_tests:
            if acceptance_test.id == ref_id:
                for criterion in acceptance_test.criteria:
                    if criterion.type == "completion":
                        return True
    return False


def validate_sign_off(spec: BehavioralSpec) -> list[str]:
    """Run all 12 sign-off validation rules on a BehavioralSpec.

    Rules (from MWBS design spec Section 8.1):

    1. ``spec_version`` present and equals ``MWBS_SPEC_VERSION``.
    2. ``project.status == "signed_off"``.
    3. ``sign_off.operator.name`` is non-empty.
    4. ``sign_off.operator.date`` is non-empty.
    5. At least one actor defined in ``spec.actors``.
    6. At least one workflow defined in ``spec.workflows``.
    7. Every workflow references at least one exception.
    8. Every workflow has at least 2 acceptance tests, and at least one
       acceptance criterion is of type ``"completion"``.
    9. Every workflow has a non-zero ``priority``.
    10. Every decision has ``information_system_must_provide`` populated.
    11. No ``[REQUIRES_ELICITATION]`` placeholders remain in any string field.
    12. Every coverage-map workflow is present in ``workflows[]`` or
        documented in ``scope_exclusions``.

    Args:
        spec: The behavioral specification to validate.

    Returns:
        A list of error messages.  An empty list means all rules pass.
    """
    errors: list[str] = []

    # ---- Rule 1: spec_version ----
    if spec.spec_version != MWBS_SPEC_VERSION:
        errors.append(
            f"Rule 1: spec_version must be '{MWBS_SPEC_VERSION}', "
            f"got '{spec.spec_version}'"
        )

    # ---- Rule 2: project.status ----
    if spec.project is None:
        errors.append("Rule 2: project is missing (status cannot be checked)")
    elif spec.project.status != "signed_off":
        errors.append(
            f"Rule 2: project.status must be 'signed_off', "
            f"got '{spec.project.status}'"
        )

    # ---- Rule 3: operator.name ----
    if spec.sign_off is None:
        errors.append("Rule 3: sign_off is missing (operator cannot be checked)")
    elif spec.sign_off.operator is None:
        errors.append("Rule 3: sign_off.operator is missing (name cannot be checked)")
    elif not spec.sign_off.operator.name.strip():
        errors.append("Rule 3: sign_off.operator.name must be non-empty")

    # ---- Rule 4: operator.date ----
    if spec.sign_off is not None and spec.sign_off.operator is not None:
        if not spec.sign_off.operator.date.strip():
            errors.append("Rule 4: sign_off.operator.date must be non-empty")
    elif spec.sign_off is None:
        pass  # Already reported in Rule 3
    else:
        errors.append("Rule 4: sign_off.operator is missing (date cannot be checked)")

    # ---- Rule 5: actors ----
    if not spec.actors:
        errors.append("Rule 5: at least one actor must be defined")

    # ---- Rule 6: workflows ----
    if not spec.workflows:
        errors.append("Rule 6: at least one workflow must be defined")

    # ---- Rule 7: workflow exceptions ----
    for workflow in spec.workflows:
        if not workflow.exceptions:
            errors.append(f"Rule 7: workflow '{workflow.id}' references no exceptions")

    # ---- Rule 8: workflow acceptance criteria ----
    for workflow in spec.workflows:
        if len(workflow.acceptance_tests) < 2:
            errors.append(
                f"Rule 8: workflow '{workflow.id}' must have at least "
                f"2 acceptance tests (has {len(workflow.acceptance_tests)})"
            )
        elif not _check_workflow_acceptance_completion(workflow, spec):
            errors.append(
                f"Rule 8: workflow '{workflow.id}' must have at least "
                f"one completion-type acceptance criterion"
            )

    # ---- Rule 9: workflow priority ----
    for workflow in spec.workflows:
        if not workflow.priority:
            errors.append(
                f"Rule 9: workflow '{workflow.id}' must have " f"a non-zero priority"
            )

    # ---- Rule 10: decision information_system_must_provide ----
    for decision in spec.decisions:
        if not decision.information_system_must_provide:
            errors.append(
                f"Rule 10: decision '{decision.id}' must have "
                f"information_system_must_provide populated"
            )

    # ---- Rule 11: REQUIRES_ELICITATION placeholders ----
    placeholders = spec.placeholders()
    for placeholder in placeholders:
        errors.append(
            f"Rule 11: placeholder remains at '{placeholder.field_path}': "
            f"{placeholder.description}"
        )

    # ---- Rule 12: coverage-map workflow in scope ----
    if spec.coverage_map is not None:
        workflow_ids = {wf.id for wf in spec.workflows}
        excluded_ids: set[str] = set()
        if spec.sign_off is not None:
            excluded_ids = {
                exclusion.workflow for exclusion in spec.sign_off.scope_exclusions
            }
        for cm_workflow in spec.coverage_map.workflows:
            if (
                cm_workflow.id not in workflow_ids
                and cm_workflow.id not in excluded_ids
            ):
                errors.append(
                    f"Rule 12: coverage_map workflow '{cm_workflow.id}' "
                    f"is not in workflows[] nor documented in "
                    f"scope_exclusions"
                )

    return errors


# ---------------------------------------------------------------------------
# Coverage Metrics Computation
# ---------------------------------------------------------------------------


def compute_coverage_metrics(spec: BehavioralSpec) -> CoverageReport:
    """Compute coverage metrics from a BehavioralSpec.

    Each dimension is computed independently from actual artifact counts:

    - data_coverage: Ratio of actors+events to a baseline (workflows*2, min 2)
    - formula_coverage: Fraction of workflows with data_entry populated
    - structural_coverage: Based on coverage_map summary or 0.5 if no map
    - workflow_coverage: Based on fraction of workflows with job_stories
    - exception_coverage: Fraction of workflows that have documented exceptions
    - report_coverage: Ratio of reports to workflows (capped at 1.0)

    Args:
        spec: The behavioral specification to evaluate.

    Returns:
        CoverageReport with dimension-specific values, or all zeros
        if the spec has no workflows.
    """
    n_workflows = len(spec.workflows) or 1
    n_actors = len(spec.actors)
    n_events = len(spec.events)
    n_reports = len(spec.reports)

    # Data coverage: actors + events relative to workflow count baseline
    baseline = max(2, n_workflows * 2)
    data_coverage = min(1.0, (n_actors + n_events) / baseline)

    # Formula coverage: fraction of workflows with data_entry populated
    workflows_with_data_entry = sum(
        1 for w in spec.workflows if w.data_entry is not None and w.data_entry.frequency
    )
    formula_coverage = workflows_with_data_entry / n_workflows

    # Structural coverage: from coverage_map summary if available
    if spec.coverage_map and spec.coverage_map.summary:
        structural_coverage = spec.coverage_map.summary.behavioral_coverage_pct / 100.0
    else:
        # Fallback: fraction of workflows with defined steps
        workflows_with_steps = sum(1 for w in spec.workflows if w.steps)
        structural_coverage = workflows_with_steps / n_workflows

    # Workflow coverage: fraction of workflows with job_stories
    workflows_with_job_stories = sum(
        1 for w in spec.workflows if w.job_story is not None
    )
    workflow_coverage = workflows_with_job_stories / n_workflows

    # Exception coverage: fraction of workflows with exceptions documented
    workflows_with_exceptions = sum(1 for w in spec.workflows if w.exceptions)
    exception_coverage = min(1.0, workflows_with_exceptions / n_workflows)

    # Report coverage: ratio of reports to workflows
    report_coverage = min(1.0, n_reports / n_workflows)

    return CoverageReport(
        data_coverage=data_coverage,
        formula_coverage=formula_coverage,
        structural_coverage=structural_coverage,
        workflow_coverage=workflow_coverage,
        exception_coverage=exception_coverage,
        report_coverage=report_coverage,
    )


# ---------------------------------------------------------------------------
# SignOffBlockShim — checkpoint serialization compatibility
# ---------------------------------------------------------------------------


@dataclass
class SignOffBlockShim:
    """Backward-compatible sign-off block for checkpoint serialization.

    Provides standalone ``to_dict()`` and ``from_dict()`` methods
    independent of the full ``SignOffBlock`` dataclass in
    ``behavioral_spec.py``.  This shim exists so that
    ``PipelineState`` can persist sign-off data without depending
    on the full MWBS ``SignOffBlock`` nested structure.

    Attributes:
        statement: The sign-off statement text.
        operator_name: Name of the signing operator.
        operator_date: Date of the sign-off.
    """

    statement: str = ""
    operator_name: str = ""
    operator_date: str = ""

    def to_dict(self) -> dict[str, str]:
        """Convert to a plain dict for serialization.

        Returns:
            Dictionary with ``statement``, ``operator_name``, and
            ``operator_date`` keys.
        """
        return {
            "statement": self.statement,
            "operator_name": self.operator_name,
            "operator_date": self.operator_date,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignOffBlockShim:
        """Reconstruct from a plain dict.

        Args:
            data: Dictionary with optional ``statement``, ``operator_name``,
                and ``operator_date`` keys.

        Returns:
            A new SignOffBlockShim instance.
        """
        return cls(
            statement=str(data.get("statement", "")),
            operator_name=str(data.get("operator_name", "")),
            operator_date=str(data.get("operator_date", "")),
        )

    @classmethod
    def from_sign_off_block(cls, block: SignOffBlock) -> SignOffBlockShim:
        """Create a SignOffBlockShim from a behavioral_spec SignOffBlock.

        Args:
            block: A fully constructed ``SignOffBlock`` instance.

        Returns:
            A SignOffBlockShim with the same operator details.
        """
        operator_name = block.operator.name if block.operator else ""
        operator_date = block.operator.date if block.operator else ""
        return cls(
            statement=block.statement,
            operator_name=operator_name,
            operator_date=operator_date,
        )
