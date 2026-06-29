"""Tests for MWBS validation rules, CoverageReport, and backward compat."""

from profiler.tools.behavioral_spec import (
    MWBS_SPEC_VERSION,
    AcceptanceCriterion,
    AcceptanceTest,
    Actor,
    BehavioralSpec,
    BehavioralWorkflow,
    CoverageMap,
    CoverageMapSummary,
    CoverageMapWorkflow,
    Decision,
    MwbsProject,
    ScopeExclusion,
    SignOffBlock,
    SignOffDeveloper,
    SignOffOperator,
)
from profiler.tools.behavioral_spec_validation import (
    CoverageReport,
    SignOffBlockShim,
    ValidationRecord,
    compute_coverage_metrics,
    validate_sign_off,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_spec(**overrides: object) -> BehavioralSpec:
    """Build a BehavioralSpec that passes all 12 sign-off validation rules.

    Keyword arguments override top-level spec fields for targeted
    rule-breaking in individual tests.
    """
    spec = BehavioralSpec(
        spec_version=MWBS_SPEC_VERSION,
        project=MwbsProject(name="Test", status="signed_off"),
        actors=[Actor(id="field_manager", name="Field Manager")],
        workflows=[
            BehavioralWorkflow(
                id="wf_harvest",
                title="Harvest Planning",
                actor="field_manager",
                exceptions=[{"ref": "EX-001"}, {"ref": "EX-002"}],
                acceptance_tests=[
                    {"ref": "AT-harvest-001"},
                    {"ref": "AT-harvest-002"},
                ],
                priority=1,
            ),
            BehavioralWorkflow(
                id="wf_planting",
                title="Planting Schedule",
                actor="field_manager",
                exceptions=[{"ref": "EX-003"}],
                acceptance_tests=[
                    {"ref": "AT-planting-001"},
                    {"ref": "AT-planting-002"},
                ],
                priority=2,
            ),
        ],
        decisions=[
            Decision(
                id="dec_priority",
                title="Harvest Priority",
                information_system_must_provide=["inventory_level"],
            ),
        ],
        acceptance_tests=[
            AcceptanceTest(
                id="AT-harvest-001",
                workflow="wf_harvest",
                criteria=[AcceptanceCriterion(id="c1", type="completion")],
            ),
            AcceptanceTest(
                id="AT-harvest-002",
                workflow="wf_harvest",
                criteria=[AcceptanceCriterion(id="c2", type="accuracy")],
            ),
            AcceptanceTest(
                id="AT-planting-001",
                workflow="wf_planting",
                criteria=[AcceptanceCriterion(id="c3", type="completion")],
            ),
            AcceptanceTest(
                id="AT-planting-002",
                workflow="wf_planting",
                criteria=[AcceptanceCriterion(id="c4", type="sequence")],
            ),
        ],
        coverage_map=CoverageMap(
            workflows=[
                CoverageMapWorkflow(id="wf_harvest", title="Harvest"),
                CoverageMapWorkflow(id="wf_planting", title="Planting"),
            ],
            summary=CoverageMapSummary(
                total_workflows=2,
                behavioral_coverage_pct=100.0,
            ),
        ),
        sign_off=SignOffBlock(
            statement="I confirm this specification.",
            operator=SignOffOperator(name="Farmer Jane", date="2026-06-26"),
            developer=SignOffDeveloper(name="Dev"),
        ),
    )

    # Apply overrides after construction so tests can mutate specific fields.
    for key, value in overrides.items():
        setattr(spec, key, value)
    return spec


# ===================================================================
# validate_sign_off — each rule tested individually
# ===================================================================


class TestValidateSignOffValid:
    """A fully signed-off spec passes all 12 checks."""

    def test_valid_spec_returns_empty_list(self):
        """Fully valid spec produces no errors."""
        spec = _make_valid_spec()
        errors = validate_sign_off(spec)
        assert errors == [], f"Expected no errors, got: {errors}"


class TestValidateSignOffRule1:
    """Rule 1: spec_version must be MWBS_SPEC_VERSION."""

    def test_spec_version_wrong(self):
        """Wrong spec_version value produces Rule 1 error."""
        spec = _make_valid_spec(spec_version="mwbs/v0")
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 1" in e]
        assert len(rule_errors) == 1

    def test_spec_version_empty(self):
        """Empty spec_version produces Rule 1 error."""
        spec = _make_valid_spec(spec_version="")
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 1" in e]
        assert len(rule_errors) == 1


class TestValidateSignOffRule2:
    """Rule 2: project.status must be signed_off."""

    def test_status_not_signed_off(self):
        """Incorrect project.status produces Rule 2 error."""
        spec = _make_valid_spec()
        spec.project.status = "draft"  # type: ignore[union-attr]
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 2" in e]
        assert len(rule_errors) == 1

    def test_project_none(self):
        """Missing project produces Rule 2 error."""
        spec = _make_valid_spec(project=None)
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 2" in e]
        assert len(rule_errors) == 1


class TestValidateSignOffRule3:
    """Rule 3: sign_off.operator.name must be non-empty."""

    def test_operator_name_empty(self):
        """Empty operator name produces Rule 3 error."""
        spec = _make_valid_spec()
        spec.sign_off.operator.name = ""  # type: ignore[union-attr]
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 3" in e]
        assert len(rule_errors) == 1

    def test_operator_none(self):
        """Missing operator produces Rule 3 error."""
        spec = _make_valid_spec()
        spec.sign_off.operator = None  # type: ignore[union-attr]
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 3" in e]
        assert len(rule_errors) == 1

    def test_sign_off_none(self):
        """Missing sign_off block produces Rule 3 error."""
        spec = _make_valid_spec(sign_off=None)
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 3" in e]
        assert len(rule_errors) == 1


class TestValidateSignOffRule4:
    """Rule 4: sign_off.operator.date must be non-empty."""

    def test_operator_date_empty(self):
        """Empty operator date produces Rule 4 error."""
        spec = _make_valid_spec()
        spec.sign_off.operator.date = ""  # type: ignore[union-attr]
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 4" in e]
        assert len(rule_errors) == 1


class TestValidateSignOffRule5:
    """Rule 5: at least one actor must be defined."""

    def test_no_actors(self):
        """Empty actors list produces Rule 5 error."""
        spec = _make_valid_spec(actors=[])
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 5" in e]
        assert len(rule_errors) == 1


class TestValidateSignOffRule6:
    """Rule 6: at least one workflow must be defined."""

    def test_no_workflows(self):
        """Empty workflows list produces Rule 6 error."""
        spec = _make_valid_spec(workflows=[])
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 6" in e]
        assert len(rule_errors) == 1


class TestValidateSignOffRule7:
    """Rule 7: every workflow must reference at least one exception."""

    def test_workflow_no_exceptions(self):
        """Workflow with empty exceptions list produces Rule 7 error."""
        spec = _make_valid_spec()
        spec.workflows[0].exceptions = []
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 7" in e]
        assert len(rule_errors) == 1
        assert "wf_harvest" in rule_errors[0]


class TestValidateSignOffRule8:
    """Rule 8: ≥2 acceptance tests, at least one completion-type criterion."""

    def test_workflow_acceptance_too_few(self):
        """Fewer than 2 acceptance tests produces Rule 8 error."""
        spec = _make_valid_spec()
        spec.workflows[0].acceptance_tests = [{"ref": "AT-harvest-001"}]
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 8" in e]
        assert len(rule_errors) == 1

    def test_workflow_no_completion_criterion(self):
        """Acceptance tests without a completion criterion produce Rule 8 error."""
        spec = _make_valid_spec()
        # Add a third acceptance test that is NOT completion type
        spec.acceptance_tests.append(
            AcceptanceTest(
                id="AT-harvest-003",
                workflow="wf_harvest",
                criteria=[AcceptanceCriterion(id="c5", type="accuracy")],
            )
        )
        spec.workflows[0].acceptance_tests = [
            {"ref": "AT-harvest-002"},
            {"ref": "AT-harvest-003"},
        ]
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 8" in e]
        # The harvest workflow's acceptance tests (AT-harvest-002, AT-harvest-003)
        # have only accuracy-type criteria, no completion type.
        assert len(rule_errors) >= 1


class TestValidateSignOffRule9:
    """Rule 9: every workflow must have a non-zero priority."""

    def test_workflow_zero_priority(self):
        """Workflow with priority=0 produces Rule 9 error."""
        spec = _make_valid_spec()
        spec.workflows[0].priority = 0
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 9" in e]
        assert len(rule_errors) == 1
        assert "wf_harvest" in rule_errors[0]


class TestValidateSignOffRule10:
    """Rule 10: every decision must have information_system_must_provide."""

    def test_decision_empty_info_system(self):
        """Decision with empty information_system_must_provide produces Rule 10 error."""
        spec = _make_valid_spec()
        spec.decisions[0].information_system_must_provide = []
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 10" in e]
        assert len(rule_errors) == 1
        assert "dec_priority" in rule_errors[0]


class TestValidateSignOffRule11:
    """Rule 11: no REQUIRES_ELICITATION placeholders may remain."""

    def test_placeholder_detected(self):
        """A spec with REQUIRES_ELICITATION markers produces Rule 11 errors."""
        spec = _make_valid_spec()
        spec.actors[0].time_pressures = [
            "[REQUIRES_ELICITATION: What are peak times?]"
        ]
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 11" in e]
        assert len(rule_errors) == 1
        assert "What are peak times?" in rule_errors[0]


class TestValidateSignOffRule12:
    """Rule 12: coverage map workflow must be in workflows[] or scope_exclusions."""

    def test_candidate_not_in_scope(self):
        """Workflow in coverage_map but not in workflows[] or scope_exclusions."""
        spec = _make_valid_spec()
        # Add a coverage_map workflow that is NOT in workflows[] and NOT excluded
        spec.coverage_map.workflows.append(
            CoverageMapWorkflow(id="wf_missing", title="Missing")
        )
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 12" in e]
        assert len(rule_errors) == 1
        assert "wf_missing" in rule_errors[0]

    def test_excluded_workflow_not_an_error(self):
        """A workflow excluded via scope_exclusions does not trigger Rule 12."""
        spec = _make_valid_spec()
        spec.coverage_map.workflows.append(
            CoverageMapWorkflow(id="wf_deferred", title="Deferred")
        )
        spec.sign_off.scope_exclusions.append(
            ScopeExclusion(
                workflow="wf_deferred",
                reason="Deferred to Phase 2",
            )
        )
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 12" in e]
        assert len(rule_errors) == 0

    def test_present_workflow_not_an_error(self):
        """A workflow in both coverage_map and workflows[] does not trigger Rule 12."""
        spec = _make_valid_spec()
        # wf_harvest is in both coverage_map and workflows[] — no error
        errors = validate_sign_off(spec)
        rule_errors = [e for e in errors if "Rule 12" in e]
        assert len(rule_errors) == 0


# ===================================================================
# CoverageReport — 6 dimensions
# ===================================================================


class TestCoverageReport:
    """CoverageReport with six coverage dimensions."""

    def test_6_dimensions_on_construction(self):
        """All 6 dimensions present with default value 0.0."""
        report = CoverageReport()
        assert report.data_coverage == 0.0
        assert report.formula_coverage == 0.0
        assert report.structural_coverage == 0.0
        assert report.workflow_coverage == 0.0
        assert report.exception_coverage == 0.0
        assert report.report_coverage == 0.0

    def test_6_dimensions_custom_values(self):
        """All 6 dimensions accept custom values."""
        report = CoverageReport(
            data_coverage=0.9,
            formula_coverage=0.8,
            structural_coverage=0.7,
            workflow_coverage=0.6,
            exception_coverage=0.5,
            report_coverage=0.4,
        )
        assert report.data_coverage == 0.9
        assert report.formula_coverage == 0.8
        assert report.structural_coverage == 0.7
        assert report.workflow_coverage == 0.6
        assert report.exception_coverage == 0.5
        assert report.report_coverage == 0.4


class TestCoverageReportIsAcceptable:
    """is_acceptable() threshold check."""

    def test_all_above_threshold(self):
        """All dimensions >= 0.80 returns True."""
        report = CoverageReport(
            data_coverage=0.85,
            formula_coverage=0.90,
            structural_coverage=1.0,
            workflow_coverage=0.95,
            exception_coverage=0.88,
            report_coverage=0.82,
        )
        assert report.is_acceptable() is True

    def test_one_below_threshold(self):
        """Any dimension < 0.80 returns False."""
        report = CoverageReport(
            data_coverage=0.95,
            formula_coverage=0.95,
            structural_coverage=0.95,
            workflow_coverage=0.95,
            exception_coverage=0.95,
            report_coverage=0.70,
        )
        assert report.is_acceptable() is False

    def test_custom_threshold(self):
        """Custom threshold adjusts the pass/fail boundary."""
        report = CoverageReport(
            data_coverage=0.60,
            formula_coverage=0.60,
            structural_coverage=0.60,
            workflow_coverage=0.60,
            exception_coverage=0.60,
            report_coverage=0.60,
        )
        assert report.is_acceptable(threshold=0.50) is True
        assert report.is_acceptable(threshold=0.70) is False


class TestCoverageReportFailingDimensions:
    """failing_dimensions() returns correct list."""

    def test_no_failing(self):
        """All above threshold returns empty list."""
        report = CoverageReport(
            data_coverage=0.95,
            formula_coverage=0.95,
            structural_coverage=0.95,
            workflow_coverage=0.95,
            exception_coverage=0.95,
            report_coverage=0.95,
        )
        assert report.failing_dimensions() == []

    def test_some_failing(self):
        """Returns only dimensions below threshold."""
        report = CoverageReport(
            data_coverage=0.50,
            formula_coverage=0.95,
            structural_coverage=0.50,
            workflow_coverage=0.95,
            exception_coverage=0.95,
            report_coverage=0.95,
        )
        failing = report.failing_dimensions()
        assert "data_coverage" in failing
        assert "structural_coverage" in failing
        assert "formula_coverage" not in failing
        assert len(failing) == 2


class TestCoverageReportCompletionGate:
    """completion_gate_passed property."""

    def test_all_100_percent_passes(self):
        """All six dimensions at 1.0 returns True."""
        report = CoverageReport(
            data_coverage=1.0,
            formula_coverage=1.0,
            structural_coverage=1.0,
            workflow_coverage=1.0,
            exception_coverage=1.0,
            report_coverage=1.0,
        )
        assert report.completion_gate_passed is True

    def test_any_not_100_fails(self):
        """Any dimension below 1.0 returns False."""
        report = CoverageReport(
            data_coverage=1.0,
            formula_coverage=1.0,
            structural_coverage=1.0,
            workflow_coverage=1.0,
            exception_coverage=0.99,
            report_coverage=1.0,
        )
        assert report.completion_gate_passed is False

    def test_all_zero_fails(self):
        """All zeros returns False."""
        report = CoverageReport()
        assert report.completion_gate_passed is False

    def test_completion_gate_is_property(self):
        """completion_gate_passed is a @property, not a method."""
        report = CoverageReport(
            data_coverage=1.0,
            formula_coverage=1.0,
            structural_coverage=1.0,
            workflow_coverage=1.0,
            exception_coverage=1.0,
            report_coverage=1.0,
        )
        # Accessing without () confirms it's a property
        result = report.completion_gate_passed
        assert result is True


class TestCoverageReportRoundTrip:
    """to_dict / from_dict round-trip."""

    def test_to_dict_preserves_all_6(self):
        """to_dict contains all 6 dimension keys."""
        report = CoverageReport(
            data_coverage=0.9,
            formula_coverage=0.8,
            structural_coverage=0.7,
            workflow_coverage=1.0,
            exception_coverage=0.6,
            report_coverage=0.5,
        )
        data = report.to_dict()
        assert data["data_coverage"] == 0.9
        assert data["formula_coverage"] == 0.8
        assert data["structural_coverage"] == 0.7
        assert data["workflow_coverage"] == 1.0
        assert data["exception_coverage"] == 0.6
        assert data["report_coverage"] == 0.5
        assert len(data) == 6

    def test_from_dict_restores_all_6(self):
        """from_dict restores all 6 dimensions."""
        data = {
            "data_coverage": 0.9,
            "formula_coverage": 0.8,
            "structural_coverage": 0.7,
            "workflow_coverage": 1.0,
            "exception_coverage": 0.6,
            "report_coverage": 0.5,
        }
        report = CoverageReport.from_dict(data)
        assert report.data_coverage == 0.9
        assert report.formula_coverage == 0.8
        assert report.structural_coverage == 0.7
        assert report.workflow_coverage == 1.0
        assert report.exception_coverage == 0.6
        assert report.report_coverage == 0.5

    def test_round_trip(self):
        """to_dict then from_dict preserves all data."""
        original = CoverageReport(
            data_coverage=0.95,
            formula_coverage=0.85,
            structural_coverage=0.75,
            workflow_coverage=0.65,
            exception_coverage=0.55,
            report_coverage=0.45,
        )
        data = original.to_dict()
        restored = CoverageReport.from_dict(data)
        assert restored.data_coverage == original.data_coverage
        assert restored.formula_coverage == original.formula_coverage
        assert restored.structural_coverage == original.structural_coverage
        assert restored.workflow_coverage == original.workflow_coverage
        assert restored.exception_coverage == original.exception_coverage
        assert restored.report_coverage == original.report_coverage

    def test_from_dict_missing_dimension_defaults_zero(self):
        """Missing dimensions in dict default to 0.0 (backward compat)."""
        # Old 4-dimension dict — new dimensions should default to 0.0
        data = {
            "data_coverage": 0.9,
            "workflow_coverage": 0.9,
            "event_coverage": 0.9,
            "invariant_coverage": 0.9,
        }
        report = CoverageReport.from_dict(data)
        assert report.data_coverage == 0.9
        assert report.workflow_coverage == 0.9
        # New dimensions default to 0.0
        assert report.formula_coverage == 0.0
        assert report.structural_coverage == 0.0
        assert report.exception_coverage == 0.0
        assert report.report_coverage == 0.0


# ===================================================================
# ValidationRecord (unchanged)
# ===================================================================


class TestValidationRecord:
    """ValidationRecord must remain unchanged from original."""

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
                {"layer": "workflows", "status": "approved"},
                {
                    "layer": "decisions",
                    "status": "modified",
                    "notes": "Added emergency decision",
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

    def test_record_from_dict(self):
        """from_dict restores all fields."""
        data = {
            "reviewed_by": "alice",
            "reviewed_with": "bob",
            "date": "2026-06-26",
            "approvals": [{"layer": "data", "status": "approved"}],
            "coverage": {"pct": 95.0},
        }
        record = ValidationRecord.from_dict(data)
        assert record.reviewed_by == "alice"
        assert len(record.approvals) == 1
        assert record.coverage["pct"] == 95.0


# ===================================================================
# compute_coverage_metrics
# ===================================================================


class TestComputeCoverageMetrics:
    """compute_coverage_metrics derives coverage from BehavioralSpec."""

    def test_full_coverage(self):
        """All dimensions computed independently from actual artifacts."""
        spec = _make_valid_spec()
        report = compute_coverage_metrics(spec)
        # Fixture: 1 actor, 0 events, 2 workflows (no data_entry/job_story),
        # 0 reports, both workflows have exceptions, coverage_map pct=100
        assert report.data_coverage == 0.25      # (1+0) / max(2, 4)
        assert report.formula_coverage == 0.0     # 0/2 with data_entry
        assert report.structural_coverage == 1.0   # 100/100 from coverage_map
        assert report.workflow_coverage == 0.0     # 0/2 with job_stories
        assert report.exception_coverage == 1.0    # 2/2 workflows have exceptions
        assert report.report_coverage == 0.0       # 0/2 reports

    def test_partial_coverage(self):
        """Only structural_coverage varies with behavioral_coverage_pct."""
        spec = _make_valid_spec()
        spec.coverage_map.summary.behavioral_coverage_pct = 50.0
        report = compute_coverage_metrics(spec)
        assert report.data_coverage == 0.25       # unchanged — artifact-based
        assert report.structural_coverage == 0.5   # 50/100 from coverage_map
        assert report.workflow_coverage == 0.0     # 0/2 — no job_stories on fixture

    def test_no_coverage_map(self):
        """Missing coverage_map falls back to steps-based structural."""
        spec = _make_valid_spec(coverage_map=None)
        report = compute_coverage_metrics(spec)
        assert report.data_coverage == 0.25       # artifact-based, unaffected
        assert report.structural_coverage == 0.0   # fallback: 0/2 workflows with steps

    def test_no_summary(self):
        """Missing summary falls back to steps-based structural."""
        spec = _make_valid_spec()
        spec.coverage_map.summary = None
        report = compute_coverage_metrics(spec)
        assert report.data_coverage == 0.25       # artifact-based, unaffected
        assert report.structural_coverage == 0.0   # fallback: 0/2 workflows with steps


# ===================================================================
# SignOffBlockShim
# ===================================================================


class TestSignOffBlockShim:
    """SignOffBlockShim serialization round-trip."""

    def test_to_dict(self):
        """to_dict produces correct keys."""
        shim = SignOffBlockShim(
            statement="Confirmed.",
            operator_name="Farmer",
            operator_date="2026-06-26",
        )
        data = shim.to_dict()
        assert data["statement"] == "Confirmed."
        assert data["operator_name"] == "Farmer"
        assert data["operator_date"] == "2026-06-26"

    def test_from_dict(self):
        """from_dict restores all fields."""
        data = {
            "statement": "Confirmed.",
            "operator_name": "Farmer",
            "operator_date": "2026-06-26",
        }
        shim = SignOffBlockShim.from_dict(data)
        assert shim.statement == "Confirmed."
        assert shim.operator_name == "Farmer"
        assert shim.operator_date == "2026-06-26"

    def test_round_trip(self):
        """to_dict then from_dict preserves data."""
        original = SignOffBlockShim(
            statement="Approved.",
            operator_name="Alice",
            operator_date="2026-07-01",
        )
        data = original.to_dict()
        restored = SignOffBlockShim.from_dict(data)
        assert restored.statement == "Approved."
        assert restored.operator_name == "Alice"
        assert restored.operator_date == "2026-07-01"

    def test_from_sign_off_block(self):
        """from_sign_off_block extracts operator details."""
        block = SignOffBlock(
            statement="Confirmed.",
            operator=SignOffOperator(name="Farmer", date="2026-06-26"),
        )
        shim = SignOffBlockShim.from_sign_off_block(block)
        assert shim.statement == "Confirmed."
        assert shim.operator_name == "Farmer"
        assert shim.operator_date == "2026-06-26"

    def test_from_sign_off_block_no_operator(self):
        """from_sign_off_block with no operator uses empty defaults."""
        block = SignOffBlock(statement="Confirmed.")
        shim = SignOffBlockShim.from_sign_off_block(block)
        assert shim.operator_name == ""
        assert shim.operator_date == ""


# ===================================================================
# Backward compat — validation_framework shim
# ===================================================================


class TestBackwardCompatShim:
    """The validation_framework re-export shim still works."""

    def test_validation_framework_imports(self):
        """CoverageReport, ValidationRecord, compute_coverage_metrics
        are importable from validation_framework."""
        from profiler.tools.validation_framework import (  # noqa: F811
            CoverageReport as OldCoverageReport,
            ValidationRecord as OldValidationRecord,
            compute_coverage_metrics as old_compute,
        )

        # Should be the same class (shim re-exports from behavioral_spec_validation)
        assert OldCoverageReport is CoverageReport
        assert OldValidationRecord is ValidationRecord

        # compute_coverage_metrics should be callable with a BehavioralSpec
        spec = _make_valid_spec()
        report = old_compute(spec)
        assert isinstance(report, CoverageReport)
