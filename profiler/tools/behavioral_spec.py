"""MWBS dataclasses — Migration Workbench Behavioral Specification.

This module defines the full MWBS schema as Python dataclasses with
to_dict/from_dict/to_yaml/from_yaml serialization and a recursive
placeholder scanner for elicitation markers.

This is an evolutionary replacement for profiler.tools.operational_model.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

MWBS_SPEC_VERSION = "mwbs/v1"

_ELICITATION_PATTERN = re.compile(r"\[REQUIRES_ELICITATION:\s*(.*?)\]")


def _skip_none(value: Any) -> Any:
    """Recursively remove mapping entries whose values are None.

    Note: empty containers may remain after filtering.
    """
    if isinstance(value, dict):
        cleaned = {k: _skip_none(v) for k, v in value.items() if v is not None}
        # Keep empty dicts that represent meaningful empty containers
        return cleaned
    if isinstance(value, list):
        return [_skip_none(item) for item in value if item is not None]
    return value


def _coerce_str(value: Any) -> str:
    """Coerce a scalar to str (handle YAML int/float parsed as non-string)."""
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return ""
    return str(value)


def _filter_dc_kwargs(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Filter *data* to only include keys declared as fields on *cls*.

    This prevents ``TypeError`` when deserialising hand-edited YAML that
    may contain keys not defined on the target dataclass.

    Args:
        cls: The dataclass type whose field names define the allowed keys.
        data: A dictionary of key-value pairs (typically parsed from YAML).

    Returns:
        A new dict containing only the keys that match *cls*'s declared fields.
    """
    valid = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in valid}


# ---------------------------------------------------------------------------
# Nested / leaf dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MwbsProject:
    """Project metadata block in the MWBS document header."""

    name: str = ""
    source_files: list[str] = field(default_factory=list)
    profiler_run_date: str = ""
    elicitor_run_date: str = ""
    elicitation_session_date: str = ""
    version: int = 1
    status: str = "draft"
    developer: str = ""
    operator: str = ""


@dataclass
class BusinessSection:
    """Business context — name, domain, description, peak periods."""

    name: str = ""
    domain: str = ""
    description: str = ""
    peak_operational_periods: list[str] = field(default_factory=list)


@dataclass
class Actor:
    """A business participant who triggers or participates in workflows."""

    id: str = ""
    name: str = ""
    responsibilities: list[str] = field(default_factory=list)
    time_pressures: list[str] = field(default_factory=list)
    access_level: str = "not_yet_elicited"


@dataclass
class PayloadField:
    """A typed field within an event payload."""

    field: str = ""
    type: str = ""
    required: bool = False


@dataclass
class Provenance:
    """Provenance record tracking how an element was derived."""

    source: str = "inferred"  # inferred | elicited | hybrid
    inference_signals: list[dict[str, str]] = field(default_factory=list)
    elicited_elements: list[str] = field(default_factory=list)
    verification_required: bool = True


@dataclass
class BehavioralEvent:
    """A discrete, named, past-tense business fact."""

    id: str = ""
    name: str = ""
    description: str = ""
    producer: str = ""
    payload: list[PayloadField] = field(default_factory=list)
    consumed_by: list[str] = field(default_factory=list)
    provenance: Provenance | None = None


@dataclass
class JobStory:
    """Human-readable job story for a workflow."""

    when: str = ""
    i_need_to: str = ""
    so_i_can: str = ""


@dataclass
class WorkflowStep:
    """An individual step within a workflow."""

    id: str = ""
    title: str = ""
    description: str = ""
    actor_action: str = ""
    system_provides: list[str] = field(default_factory=list)
    contains_decision: str | None = None
    emits: str | None = None


@dataclass
class WorkflowInput:
    """An input consumed by a workflow, sourced from an event."""

    id: str = ""
    source_event: str | None = None
    description: str = ""


@dataclass
class WorkflowOperational:
    """Operational constraints for a workflow."""

    max_steps: int = 0
    max_duration_minutes: int = 0
    spreadsheet_access: str = ""
    mobile_required: bool = False
    offline_required: bool = False


@dataclass
class WorkflowDataEntry:
    """Data-entry characteristics for a workflow."""

    frequency: str = ""
    volume: str = ""
    preferred_input: str = ""
    batch_capable: bool = False


@dataclass
class BehavioralWorkflow:
    """A complete workflow specification — the primary migration unit."""

    id: str = ""
    title: str = ""
    job_story: JobStory | None = None
    actor: str = ""
    frequency: str = ""
    peak_pressure: str = ""
    trigger: dict[str, str] = field(default_factory=dict)
    inputs: list[WorkflowInput] = field(default_factory=list)
    steps: list[WorkflowStep] = field(default_factory=list)
    emits: list[str] = field(default_factory=list)
    decisions: list[dict[str, str]] = field(default_factory=list)
    exceptions: list[dict[str, str]] = field(default_factory=list)
    acceptance_tests: list[dict[str, str]] = field(default_factory=list)
    operational: WorkflowOperational | None = None
    data_entry: WorkflowDataEntry | None = None
    priority: int = 0
    provenance: Provenance | None = None


@dataclass
class Decision:
    """A human judgment point within a workflow."""

    id: str = ""
    title: str = ""
    within_workflow: str = ""
    within_step: str = ""
    description: str = ""
    information_system_must_provide: list[str] = field(default_factory=list)
    criteria_actor_applies: list[str] = field(default_factory=list)
    outcome: str = ""
    outcome_recorded_as: str = ""
    automation_level: str = "human_only"  # human_only|system_suggests|fully_automated
    rationale: str = ""
    provenance: Provenance | None = None


@dataclass
class Detection:
    """How an exception is detected."""

    method: str = ""
    trigger: str = ""


@dataclass
class ExceptionResponse:
    """A response action for an exception."""

    id: str = ""
    action: str = ""
    mechanism: str = ""
    actor: str = ""
    emits: str = ""
    description: str = ""


@dataclass
class WorkflowException:
    """A documented exception path within a workflow."""

    id: str = ""
    title: str = ""
    workflow: str = ""
    condition: str = ""
    severity: str = "warning"  # warning | error | blocking
    detection: Detection | None = None
    responses: list[ExceptionResponse] = field(default_factory=list)
    current_handling: str = ""
    migration_improvement: str = ""
    provenance: Provenance | None = None


@dataclass
class BusinessRule:
    """A workflow-independent business constraint."""

    id: str = ""
    title: str = ""
    expression: str = ""
    severity: str = "warning"
    applies_to: str = ""
    violation_response: str = ""
    provenance: Provenance | None = None


@dataclass
class Report:
    """An operational report artifact that supports specific decisions."""

    id: str = ""
    title: str = ""
    audience: str = ""
    frequency: str = ""
    format: str = ""
    format_notes: str = ""
    source_events: list[str] = field(default_factory=list)
    displays: list[str] = field(default_factory=list)
    workflows_supported: list[str] = field(default_factory=list)
    operational: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None


@dataclass
class AcceptanceCriterion:
    """A typed, testable acceptance criterion for a workflow."""

    id: str = ""
    type: str = ""  # completion|coverage|accuracy|sequence|speed|recovery|independence
    description: str = ""
    assertion: str = ""
    test_type: str = ""  # automated|performance|manual
    verifier: str = ""
    verification_required: bool = True
    threshold_seconds: int | None = None
    notes: str = ""


@dataclass
class AcceptanceTest:
    """A collection of acceptance criteria for a workflow."""

    id: str = ""
    workflow: str = ""
    priority: int = 0
    scenario: dict[str, Any] = field(default_factory=dict)
    criteria: list[AcceptanceCriterion] = field(default_factory=list)


@dataclass
class CoverageMapWorkflow:
    """A single workflow's entry in the coverage map."""

    id: str = ""
    title: str = ""
    source: str = ""
    priority: int = 0
    status: str = ""
    acceptance_test: str = ""
    criteria_count: int = 0
    verification_required_count: int = 0
    exceptions_documented: int = 0


@dataclass
class CoverageMapSummary:
    """Aggregate summary of the coverage map."""

    total_workflows: int = 0
    total_events: int = 0
    total_decisions: int = 0
    total_exceptions: int = 0
    total_rules: int = 0
    total_reports: int = 0
    total_tests: int = 0
    dimensions_covered: int = 0
    gaps: int = 0
    behavioral_coverage_pct: float = 0.0
    spreadsheet_independence_pct: float = 0.0
    signed_off: int = 0


@dataclass
class CoverageMap:
    """Project management view of behavioral coverage."""

    workflows: list[CoverageMapWorkflow] = field(default_factory=list)
    summary: CoverageMapSummary | None = None


@dataclass
class SignOffOperator:
    """Operator sign-off details."""

    name: str = ""
    date: str = ""
    signature: str = ""


@dataclass
class SignOffDeveloper:
    """Developer sign-off details."""

    name: str = ""
    date: str = ""


@dataclass
class ScopeExclusion:
    """A workflow excluded from the current migration scope."""

    workflow: str = ""
    reason: str = ""
    deferred_to: str = ""


@dataclass
class AmendmentEntry:
    """An amendment log entry recording a post-sign-off change."""

    date: str = ""
    affected_workflow: str = ""
    change_description: str = ""
    re_signed: bool = False


@dataclass
class SignOffBlock:
    """The sign-off block concluding a signed MWBS document."""

    statement: str = ""
    operator: SignOffOperator | None = None
    developer: SignOffDeveloper | None = None
    scope_exclusions: list[ScopeExclusion] = field(default_factory=list)
    amendment_log: list[AmendmentEntry] = field(default_factory=list)


@dataclass
class Placeholder:
    """A detected REQUIRES_ELICITATION marker in the spec."""

    field_path: str = ""
    description: str = ""
    section: str = ""
    workflow_id: str = ""
    reason: str = ""


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


@dataclass
class BehavioralSpec:
    """Root MWBS document — the Migration Workbench Behavioral Specification."""

    spec_version: str = MWBS_SPEC_VERSION
    schema: str = "mwbs/v1"
    project: MwbsProject | None = None
    business: BusinessSection | None = None
    actors: list[Actor] = field(default_factory=list)
    events: list[BehavioralEvent] = field(default_factory=list)
    workflows: list[BehavioralWorkflow] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    exceptions: list[WorkflowException] = field(default_factory=list)
    rules: list[BusinessRule] = field(default_factory=list)
    reports: list[Report] = field(default_factory=list)
    acceptance_tests: list[AcceptanceTest] = field(default_factory=list)
    coverage_map: CoverageMap | None = None
    sign_off: SignOffBlock | None = None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for YAML/JSON output.

        Returns:
            A dictionary with all fields, skipping None values.
        """
        raw = asdict(self)
        cleaned: dict[str, Any] = {}
        for key, value in raw.items():
            if value is None:
                continue
            cleaned[key] = _skip_none(value)
        return cleaned

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BehavioralSpec:
        """Reconstruct from a plain dict.

        Handles the full shape of the farm-mwbs-draft.yaml file including
        all nested dataclass structures.

        Args:
            data: Dictionary with keys matching MWBS schema fields.

        Returns:
            A new BehavioralSpec instance populated from the dict.
        """
        # -- helpers -------------------------------------------------------
        def _build_payload(payload_data: Any) -> list[PayloadField]:
            if not isinstance(payload_data, list):
                return []
            return [PayloadField(**pf) for pf in payload_data]

        def _build_provenance(prov_data: Any) -> Provenance | None:
            if isinstance(prov_data, dict):
                return Provenance(**_filter_dc_kwargs(Provenance, prov_data))
            return None

        def _build_job_story(js_data: Any) -> JobStory | None:
            if isinstance(js_data, dict):
                return JobStory(**_filter_dc_kwargs(JobStory, js_data))
            return None

        def _build_steps(steps_data: Any) -> list[WorkflowStep]:
            if not isinstance(steps_data, list):
                return []
            return [WorkflowStep(**s) for s in steps_data]

        def _build_inputs(inputs_data: Any) -> list[WorkflowInput]:
            if not isinstance(inputs_data, list):
                return []
            return [WorkflowInput(**i) for i in inputs_data]

        def _build_operational(op_data: Any) -> WorkflowOperational | None:
            if isinstance(op_data, dict):
                return WorkflowOperational(**_filter_dc_kwargs(WorkflowOperational, op_data))
            return None

        def _build_data_entry(de_data: Any) -> WorkflowDataEntry | None:
            if isinstance(de_data, dict):
                return WorkflowDataEntry(**_filter_dc_kwargs(WorkflowDataEntry, de_data))
            return None

        def _build_detection(det_data: Any) -> Detection | None:
            if isinstance(det_data, dict):
                return Detection(**_filter_dc_kwargs(Detection, det_data))
            return None

        def _build_responses(resp_data: Any) -> list[ExceptionResponse]:
            if not isinstance(resp_data, list):
                return []
            return [ExceptionResponse(**r) for r in resp_data]

        def _build_workflow_criteria(crit_data: Any) -> list[AcceptanceCriterion]:
            if not isinstance(crit_data, list):
                return []
            return [AcceptanceCriterion(**c) for c in crit_data]

        def _build_coverage_workflows(cw_data: Any) -> list[CoverageMapWorkflow]:
            if not isinstance(cw_data, list):
                return []
            return [CoverageMapWorkflow(**w) for w in cw_data]

        def _build_scope_exclusions(ex_data: Any) -> list[ScopeExclusion]:
            if not isinstance(ex_data, list):
                return []
            return [ScopeExclusion(**s) for s in ex_data]

        def _build_amendment_log(am_data: Any) -> list[AmendmentEntry]:
            if not isinstance(am_data, list):
                return []
            return [AmendmentEntry(**a) for a in am_data]

        def _build_sign_off_operator(op_data: Any) -> SignOffOperator | None:
            if isinstance(op_data, dict):
                return SignOffOperator(**_filter_dc_kwargs(SignOffOperator, op_data))
            return None

        def _build_sign_off_developer(dev_data: Any) -> SignOffDeveloper | None:
            if isinstance(dev_data, dict):
                return SignOffDeveloper(**_filter_dc_kwargs(SignOffDeveloper, dev_data))
            return None

        # -- top-level construction ---------------------------------------
        project = None
        if isinstance(data.get("project"), dict):
            project = MwbsProject(**_filter_dc_kwargs(MwbsProject, data["project"]))

        business = None
        if isinstance(data.get("business"), dict):
            business = BusinessSection(**_filter_dc_kwargs(BusinessSection, data["business"]))

        actors = [Actor(**_filter_dc_kwargs(Actor, a)) for a in data.get("actors", []) if isinstance(a, dict)]

        events = []
        for evt_data in data.get("events", []):
            if isinstance(evt_data, dict):
                events.append(
                    BehavioralEvent(
                        id=evt_data.get("id", ""),
                        name=evt_data.get("name", ""),
                        description=evt_data.get("description", ""),
                        producer=evt_data.get("producer", ""),
                        payload=_build_payload(evt_data.get("payload")),
                        consumed_by=evt_data.get("consumed_by", []),
                        provenance=_build_provenance(evt_data.get("provenance")),
                    )
                )

        workflows = []
        for wf_data in data.get("workflows", []):
            if isinstance(wf_data, dict):
                workflows.append(
                    BehavioralWorkflow(
                        id=wf_data.get("id", ""),
                        title=wf_data.get("title", ""),
                        job_story=_build_job_story(wf_data.get("job_story")),
                        actor=wf_data.get("actor", ""),
                        frequency=wf_data.get("frequency", ""),
                        peak_pressure=wf_data.get("peak_pressure", ""),
                        trigger=wf_data.get("trigger", {}),
                        inputs=_build_inputs(wf_data.get("inputs")),
                        steps=_build_steps(wf_data.get("steps")),
                        emits=wf_data.get("emits", []),
                        decisions=wf_data.get("decisions", []),
                        exceptions=wf_data.get("exceptions", []),
                        acceptance_tests=wf_data.get("acceptance_tests", []),
                        operational=_build_operational(wf_data.get("operational")),
                        data_entry=_build_data_entry(wf_data.get("data_entry")),
                        priority=wf_data.get("priority", 0),
                        provenance=_build_provenance(wf_data.get("provenance")),
                    )
                )

        decisions = []
        for dec_data in data.get("decisions", []):
            if isinstance(dec_data, dict):
                decisions.append(
                    Decision(
                        id=dec_data.get("id", ""),
                        title=dec_data.get("title", ""),
                        within_workflow=dec_data.get("within_workflow", ""),
                        within_step=dec_data.get("within_step", ""),
                        description=dec_data.get("description", ""),
                        information_system_must_provide=dec_data.get(
                            "information_system_must_provide", []
                        ),
                        criteria_actor_applies=dec_data.get(
                            "criteria_actor_applies", []
                        ),
                        outcome=dec_data.get("outcome", ""),
                        outcome_recorded_as=dec_data.get("outcome_recorded_as", ""),
                        automation_level=dec_data.get("automation_level", "human_only"),
                        rationale=dec_data.get("rationale", ""),
                        provenance=_build_provenance(dec_data.get("provenance")),
                    )
                )

        exceptions = []
        for exc_data in data.get("exceptions", []):
            if isinstance(exc_data, dict):
                exceptions.append(
                    WorkflowException(
                        id=exc_data.get("id", ""),
                        title=exc_data.get("title", ""),
                        workflow=exc_data.get("workflow", ""),
                        condition=exc_data.get("condition", ""),
                        severity=exc_data.get("severity", "warning"),
                        detection=_build_detection(exc_data.get("detection")),
                        responses=_build_responses(exc_data.get("responses")),
                        current_handling=exc_data.get("current_handling", ""),
                        migration_improvement=exc_data.get("migration_improvement", ""),
                        provenance=_build_provenance(exc_data.get("provenance")),
                    )
                )

        rules = []
        for rule_data in data.get("rules", []):
            if isinstance(rule_data, dict):
                rules.append(
                    BusinessRule(
                        id=rule_data.get("id", ""),
                        title=rule_data.get("title", ""),
                        expression=rule_data.get("expression", ""),
                        severity=rule_data.get("severity", "warning"),
                        applies_to=rule_data.get("applies_to", ""),
                        violation_response=rule_data.get("violation_response", ""),
                        provenance=_build_provenance(rule_data.get("provenance")),
                    )
                )

        reports = []
        for rpt_data in data.get("reports", []):
            if isinstance(rpt_data, dict):
                reports.append(
                    Report(
                        id=rpt_data.get("id", ""),
                        title=rpt_data.get("title", ""),
                        audience=rpt_data.get("audience", ""),
                        frequency=rpt_data.get("frequency", ""),
                        format=rpt_data.get("format", ""),
                        format_notes=rpt_data.get("format_notes", ""),
                        source_events=rpt_data.get("source_events", []),
                        displays=rpt_data.get("displays", []),
                        workflows_supported=rpt_data.get("workflows_supported", []),
                        operational=rpt_data.get("operational", {}),
                        provenance=_build_provenance(rpt_data.get("provenance")),
                    )
                )

        acceptance_tests = []
        for at_data in data.get("acceptance_tests", []):
            if isinstance(at_data, dict):
                acceptance_tests.append(
                    AcceptanceTest(
                        id=at_data.get("id", ""),
                        workflow=at_data.get("workflow", ""),
                        priority=at_data.get("priority", 0),
                        scenario=at_data.get("scenario", {}),
                        criteria=_build_workflow_criteria(at_data.get("criteria")),
                    )
                )

        coverage_map = None
        if isinstance(data.get("coverage_map"), dict):
            cm_data = data["coverage_map"]
            summary = None
            if isinstance(cm_data.get("summary"), dict):
                summary = CoverageMapSummary(**_filter_dc_kwargs(CoverageMapSummary, cm_data["summary"]))
            coverage_map = CoverageMap(
                workflows=_build_coverage_workflows(cm_data.get("workflows")),
                summary=summary,
            )

        sign_off = None
        if isinstance(data.get("sign_off"), dict):
            so_data = data["sign_off"]
            sign_off = SignOffBlock(
                statement=so_data.get("statement", ""),
                operator=_build_sign_off_operator(so_data.get("operator")),
                developer=_build_sign_off_developer(so_data.get("developer")),
                scope_exclusions=_build_scope_exclusions(
                    so_data.get("scope_exclusions")
                ),
                amendment_log=_build_amendment_log(so_data.get("amendment_log")),
            )

        return cls(
            spec_version=_coerce_str(data.get("spec_version", MWBS_SPEC_VERSION)),
            schema=data.get("schema", "mwbs/v1"),
            project=project,
            business=business,
            actors=actors,
            events=events,
            workflows=workflows,
            decisions=decisions,
            exceptions=exceptions,
            rules=rules,
            reports=reports,
            acceptance_tests=acceptance_tests,
            coverage_map=coverage_map,
            sign_off=sign_off,
        )

    def to_yaml(self, path: str | Path) -> None:
        """Serialize to YAML file.

        Args:
            path: Filesystem path for the output YAML file.
        """
        import yaml  # type: ignore[import-untyped]

        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> BehavioralSpec:
        """Deserialize from YAML file.

        Args:
            path: Filesystem path to the YAML file.

        Returns:
            A new BehavioralSpec instance populated from the YAML content.

        Raises:
            ValueError: If the YAML root is not a mapping.
        """
        import yaml  # type: ignore[import-untyped]

        file_path = Path(path)
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"YAML at {file_path} is not a mapping.")
        return cls.from_dict(raw)

    # ------------------------------------------------------------------
    # Placeholder scanner
    # ------------------------------------------------------------------

    def placeholders(self) -> list[Placeholder]:
        """Scan all string fields for ``[REQUIRES_ELICITATION: ...]`` markers.

        Returns:
            A list of Placeholder records, one per detected marker.
        """
        results: list[Placeholder] = []
        raw = _as_plain_dict(self)
        _scan_recursive(raw, "", results)
        return results


# ---------------------------------------------------------------------------
# Placeholder scanning helpers
# ---------------------------------------------------------------------------


def _as_plain_dict(obj: Any) -> Any:
    """Convert a dataclass tree to plain dicts/lists for uniform scanning."""
    if hasattr(obj, "__dataclass_fields__"):
        return {field_name: _as_plain_dict(getattr(obj, field_name))
                for field_name in obj.__dataclass_fields__}
    if isinstance(obj, list):
        return [_as_plain_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _as_plain_dict(v) for k, v in obj.items()}
    return obj


def _scan_recursive(
    value: Any,
    path: str,
    results: list[Placeholder],
) -> None:
    """Recursively scan *value* for elicitation markers at *path*."""
    if isinstance(value, str):
        for match in _ELICITATION_PATTERN.finditer(value):
            description_text = match.group(1).strip()
            # Determine section and workflow_id from path
            parts = path.split(".")
            section = _infer_section(parts)
            workflow_id = _infer_workflow_id(parts)
            results.append(
                Placeholder(
                    field_path=path,
                    description=description_text,
                    section=section,
                    workflow_id=workflow_id,
                    reason="",
                )
            )
    elif isinstance(value, dict):
        for key, child in value.items():
            _scan_recursive(child, f"{path}.{key}" if path else key, results)
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _scan_recursive(item, f"{path}[{idx}]", results)


def _infer_section(parts: list[str]) -> str:
    """Try to infer the MWBS section name from a dotted field path."""
    if not parts:
        return ""
    top = parts[0]
    section_map = {
        "actors": "actors",
        "events": "events",
        "workflows": "workflows",
        "decisions": "decisions",
        "exceptions": "exceptions",
        "rules": "rules",
        "reports": "reports",
        "acceptance_tests": "acceptance_tests",
        "business": "business",
        "project": "project",
    }
    return section_map.get(top, "")


def _infer_workflow_id(parts: list[str]) -> str:
    """Try to infer the workflow ID from a dotted field path."""
    # Pattern: workflows[N].... or exceptions[N].workflow is the workflow id
    # Pattern: decisions[N].within_workflow
    if len(parts) >= 2 and parts[0] == "workflows" and parts[1].startswith("["):
        return parts[1].strip("[]")
    if len(parts) >= 2 and parts[0] == "exceptions":
        # Look for a 'workflow' key in siblings — not possible here, skip
        return ""
    if len(parts) >= 3 and parts[0] == "decisions":
        return parts[2] if len(parts) > 2 else ""
    return ""
