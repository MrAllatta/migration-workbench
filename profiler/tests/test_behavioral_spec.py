"""Tests for the MWBS BehavioralSpec dataclass layer."""


from profiler.tools.behavioral_spec import (
    MWBS_SPEC_VERSION,
    AcceptanceCriterion,
    AcceptanceTest,
    Actor,
    AmendmentEntry,
    BehavioralEvent,
    BehavioralSpec,
    BehavioralWorkflow,
    BusinessRule,
    BusinessSection,
    CoverageMap,
    CoverageMapSummary,
    CoverageMapWorkflow,
    Decision,
    Detection,
    ExceptionResponse,
    JobStory,
    MwbsProject,
    PayloadField,
    Placeholder,
    Provenance,
    Report,
    ScopeExclusion,
    SignOffBlock,
    SignOffDeveloper,
    SignOffOperator,
    WorkflowDataEntry,
    WorkflowException,
    WorkflowInput,
    WorkflowOperational,
    WorkflowStep,
)


class TestDefaults:
    """Minimal construction uses default values (Issue 1)."""

    def test_mwbs_project_defaults(self):
        """MwbsProject uses sensible defaults."""
        proj = MwbsProject()
        assert proj.name == ""
        assert proj.version == 1
        assert proj.status == "draft"
        assert proj.source_files == []
        assert proj.operator == ""

    def test_business_section_defaults(self):
        """BusinessSection defaults are empty containers."""
        biz = BusinessSection()
        assert biz.name == ""
        assert biz.domain == ""
        assert biz.description == ""
        assert biz.peak_operational_periods == []

    def test_actor_defaults(self):
        """Actor uses not_yet_elicited for access_level."""
        actor = Actor()
        assert actor.id == ""
        assert actor.responsibilities == []
        assert actor.access_level == "not_yet_elicited"

    def test_payload_field_defaults(self):
        """PayloadField has required=False by default."""
        pf = PayloadField()
        assert pf.field == ""
        assert pf.type == ""
        assert pf.required is False

    def test_provenance_defaults(self):
        """Provenance defaults to inferred source and verification_required=True."""
        prov = Provenance()
        assert prov.source == "inferred"
        assert prov.verification_required is True
        assert prov.inference_signals == []
        assert prov.elicited_elements == []

    def test_behavioral_event_defaults(self):
        """BehavioralEvent defaults are empty containers."""
        event = BehavioralEvent()
        assert event.id == ""
        assert event.payload == []
        assert event.consumed_by == []

    def test_job_story_defaults(self):
        """JobStory fields default to empty strings."""
        js = JobStory()
        assert js.when == ""
        assert js.i_need_to == ""
        assert js.so_i_can == ""

    def test_workflow_step_defaults(self):
        """WorkflowStep has optional emits/contains_decision as None."""
        step = WorkflowStep()
        assert step.id == ""
        assert step.system_provides == []
        assert step.contains_decision is None
        assert step.emits is None

    def test_workflow_input_defaults(self):
        """WorkflowInput has source_event/defaults."""
        inp = WorkflowInput()
        assert inp.id == ""
        assert inp.source_event is None
        assert inp.description == ""

    def test_workflow_operational_defaults(self):
        """WorkflowOperational defaults to zero/false."""
        op = WorkflowOperational()
        assert op.max_steps == 0
        assert op.mobile_required is False
        assert op.spreadsheet_access == ""

    def test_workflow_data_entry_defaults(self):
        """WorkflowDataEntry defaults to empty/false."""
        de = WorkflowDataEntry()
        assert de.frequency == ""
        assert de.batch_capable is False

    def test_behavioral_workflow_defaults(self):
        """BehavioralWorkflow defaults are empty containers."""
        wf = BehavioralWorkflow()
        assert wf.id == ""
        assert wf.steps == []
        assert wf.decisions == []
        assert wf.exceptions == []
        assert wf.acceptance_tests == []
        assert wf.job_story is None
        assert wf.operational is None
        assert wf.data_entry is None
        assert wf.provenance is None

    def test_decision_defaults(self):
        """Decision uses human_only automation_level."""
        dec = Decision()
        assert dec.id == ""
        assert dec.information_system_must_provide == []
        assert dec.automation_level == "human_only"

    def test_detection_defaults(self):
        """Detection defaults to empty strings."""
        det = Detection()
        assert det.method == ""
        assert det.trigger == ""

    def test_exception_response_defaults(self):
        """ExceptionResponse defaults to empty strings."""
        resp = ExceptionResponse()
        assert resp.id == ""
        assert resp.action == ""
        assert resp.description == ""

    def test_workflow_exception_defaults(self):
        """WorkflowException uses warning severity."""
        exc = WorkflowException()
        assert exc.id == ""
        assert exc.severity == "warning"
        assert exc.responses == []
        assert exc.detection is None
        assert exc.provenance is None

    def test_business_rule_defaults(self):
        """BusinessRule uses warning severity."""
        rule = BusinessRule()
        assert rule.id == ""
        assert rule.severity == "warning"
        assert rule.provenance is None

    def test_report_defaults(self):
        """Report has workflows_supported (not decisions_supported)."""
        rpt = Report()
        assert rpt.id == ""
        assert rpt.workflows_supported == []
        assert rpt.operational == {}
        assert rpt.format_notes == ""

    def test_acceptance_criterion_defaults(self):
        """AcceptanceCriterion defaults verification_required to True."""
        ac = AcceptanceCriterion()
        assert ac.id == ""
        assert ac.verification_required is True
        assert ac.notes == ""

    def test_acceptance_test_defaults(self):
        """AcceptanceTest defaults are empty containers."""
        at = AcceptanceTest()
        assert at.id == ""
        assert at.criteria == []
        assert at.scenario == {}

    def test_coverage_map_workflow_defaults(self):
        """CoverageMapWorkflow defaults to zero."""
        cmw = CoverageMapWorkflow()
        assert cmw.id == ""
        assert cmw.criteria_count == 0

    def test_coverage_map_summary_defaults(self):
        """CoverageMapSummary defaults to zero."""
        cms = CoverageMapSummary()
        assert cms.total_workflows == 0
        assert cms.total_events == 0
        assert cms.total_decisions == 0
        assert cms.dimensions_covered == 0
        assert cms.behavioral_coverage_pct == 0.0

    def test_sign_off_operator_defaults(self):
        """SignOffOperator defaults to empty signatures."""
        op = SignOffOperator()
        assert op.name == ""
        assert op.signature == ""

    def test_sign_off_developer_defaults(self):
        """SignOffDeveloper defaults to empty."""
        dev = SignOffDeveloper()
        assert dev.name == ""
        assert dev.date == ""

    def test_scope_exclusion_defaults(self):
        """ScopeExclusion defaults to empty strings."""
        se = ScopeExclusion()
        assert se.workflow == ""
        assert se.reason == ""

    def test_amendment_entry_defaults(self):
        """AmendmentEntry defaults to not re-signed."""
        ae = AmendmentEntry()
        assert ae.date == ""
        assert ae.re_signed is False

    def test_sign_off_block_defaults(self):
        """SignOffBlock defaults with empty containers."""
        so = SignOffBlock()
        assert so.statement == ""
        assert so.operator is None
        assert so.developer is None
        assert so.scope_exclusions == []
        assert so.amendment_log == []

    def test_behavioral_spec_defaults(self):
        """BehavioralSpec uses MWBS_SPEC_VERSION."""
        spec = BehavioralSpec()
        assert spec.spec_version == MWBS_SPEC_VERSION
        assert spec.schema == "mwbs/v1"
        assert spec.project is None
        assert spec.actors == []
        assert spec.events == []

    def test_placeholder_defaults(self):
        """Placeholder defaults to empty strings."""
        ph = Placeholder()
        assert ph.field_path == ""
        assert ph.description == ""


class TestFullConstruction:
    """Full construction with all fields specified."""

    def test_behavioral_spec_full(self):
        """Build a complete spec with all sections populated."""
        spec = BehavioralSpec(
            spec_version="mwbs/v1",
            schema="mwbs/v1",
            project=MwbsProject(
                name="TestFarm",
                source_files=["src.csv"],
                profiler_run_date="2026-06-01",
                version=1,
                status="draft",
                developer="dev",
                operator="op",
            ),
            business=BusinessSection(
                name="TestFarm",
                domain="farm",
                description="A test farm.",
                peak_operational_periods=["Market season"],
            ),
            actors=[
                Actor(
                    id="field_manager",
                    name="Field Manager",
                    responsibilities=["Harvest planning"],
                    time_pressures=["Market morning"],
                    access_level="full",
                )
            ],
            events=[
                BehavioralEvent(
                    id="harvest_order_generated",
                    name="HarvestOrderGenerated",
                    description="Order created.",
                    producer="field_manager",
                    payload=[
                        PayloadField(field="crop", type="string", required=True),
                        PayloadField(field="quantity", type="integer", required=True),
                    ],
                    consumed_by=["inventory"],
                    provenance=Provenance(
                        source="inferred",
                        inference_signals=[{"rule": "INF-04", "signal": "Print range"}],
                    ),
                )
            ],
            workflows=[
                BehavioralWorkflow(
                    id="weekly_harvest_planning",
                    title="Weekly Harvest Planning",
                    job_story=JobStory(
                        when="Monday morning",
                        i_need_to="generate picking list",
                        so_i_can="brief crew",
                    ),
                    actor="field_manager",
                    frequency="weekly",
                    peak_pressure="Monday 5:30am",
                    trigger={"type": "scheduled", "description": "Weekly start"},
                    inputs=[WorkflowInput(id="orders", source_event="OrderConfirmed")],
                    steps=[
                        WorkflowStep(
                            id="step_01",
                            title="Review orders",
                            description="Review all orders",
                            actor_action="review",
                            system_provides=["Order list"],
                            contains_decision=None,
                            emits=None,
                        )
                    ],
                    emits=["HarvestOrderGenerated"],
                    decisions=[{"ref": "prioritize_harvest_when_short"}],
                    exceptions=[{"ref": "EX-harvest-001"}],
                    acceptance_tests=[{"ref": "AT-harvest-001"}],
                    operational=WorkflowOperational(
                        max_steps=4,
                        max_duration_minutes=5,
                        spreadsheet_access="forbidden",
                        mobile_required=True,
                        offline_required=True,
                    ),
                    data_entry=WorkflowDataEntry(
                        frequency="weekly",
                        volume="low",
                        preferred_input="mobile",
                        batch_capable=False,
                    ),
                    priority=1,
                    provenance=Provenance(
                        source="hybrid",
                        inference_signals=[{"rule": "INF-09", "signal": "Repeated"}],
                    ),
                )
            ],
            decisions=[
                Decision(
                    id="prioritize_harvest_when_short",
                    title="Harvest Prioritisation",
                    within_workflow="weekly_harvest_planning",
                    within_step="step_02",
                    description="When short, prioritise.",
                    information_system_must_provide=["Available qty"],
                    criteria_actor_applies=["CSA first"],
                    outcome="harvest_priority_assignment",
                    outcome_recorded_as="HarvestPrioritySet",
                    automation_level="human_only",
                    rationale="Relationship judgment.",
                    provenance=Provenance(source="elicited"),
                )
            ],
            exceptions=[
                WorkflowException(
                    id="EX-harvest-001",
                    title="Insufficient Inventory",
                    workflow="weekly_harvest_planning",
                    condition="Qty < committed",
                    severity="warning",
                    detection=Detection(method="system_computed", trigger="step_02"),
                    responses=[
                        ExceptionResponse(
                            id="r1",
                            action="flag_shortfall",
                            mechanism="inline",
                            actor="system",
                            emits="ShortfallRecorded",
                            description="Flag shortfall items.",
                        )
                    ],
                    current_handling="Pencil cross-out",
                    migration_improvement="Auto notification",
                    provenance=Provenance(source="elicited"),
                )
            ],
            rules=[
                BusinessRule(
                    id="BR-001",
                    title="Non-Negative Inventory",
                    expression="current_inventory >= 0",
                    severity="error",
                    applies_to="all_adjustments",
                    violation_response="block_and_alert",
                    provenance=Provenance(source="inferred"),
                )
            ],
            reports=[
                Report(
                    id="RPT-001",
                    title="Weekly Picking List",
                    audience="field_manager",
                    frequency="weekly",
                    format="unknown",
                    format_notes="[REQUIRES_ELICITATION: Best format?]",
                    source_events=["HarvestOrderGenerated"],
                    displays=["Crop", "Bed"],
                    workflows_supported=["weekly_harvest_planning"],
                    operational={"must_function_offline": True},
                    provenance=Provenance(source="inferred"),
                )
            ],
            acceptance_tests=[
                AcceptanceTest(
                    id="AT-harvest-001",
                    workflow="weekly_harvest_planning",
                    priority=1,
                    scenario={
                        "given": ["confirmed_orders_exist"],
                        "when": {"actor": "field_manager", "action": "generate_plan"},
                        "then": ["HarvestOrderGenerated"],
                    },
                    criteria=[
                        AcceptanceCriterion(
                            id="AT-harvest-001-C1",
                            type="completion",
                            description="All items in harvest order.",
                            assertion="count(items) == count(orders)",
                            test_type="automated",
                            verification_required=False,
                            verifier="",
                            notes="",
                        )
                    ],
                )
            ],
            coverage_map=CoverageMap(
                workflows=[
                    CoverageMapWorkflow(
                        id="weekly_harvest_planning",
                        title="Weekly Harvest Planning",
                        source="hybrid",
                        priority=1,
                        status="draft",
                        acceptance_test="AT-harvest-001",
                        criteria_count=1,
                        verification_required_count=0,
                        exceptions_documented=1,
                    )
                ],
                summary=CoverageMapSummary(
                    total_workflows=1,
                    total_events=1,
                    total_decisions=1,
                    total_exceptions=1,
                    total_rules=1,
                    total_reports=1,
                    total_tests=1,
                    dimensions_covered=6,
                    gaps=0,
                    behavioral_coverage_pct=100.0,
                    spreadsheet_independence_pct=0.0,
                    signed_off=0,
                ),
            ),
            sign_off=SignOffBlock(
                statement="I confirm this spec.",
                operator=SignOffOperator(name="Farmer", date="", signature=""),
                developer=SignOffDeveloper(name="Dev", date=""),
                scope_exclusions=[
                    ScopeExclusion(
                        workflow="WF-03",
                        reason="Deferred",
                        deferred_to="Phase 2",
                    )
                ],
                amendment_log=[
                    AmendmentEntry(
                        date="2026-07-01",
                        affected_workflow="weekly_harvest_planning",
                        change_description="Updated step order.",
                        re_signed=False,
                    )
                ],
            ),
        )
        # Verify top-level fields
        assert spec.project is not None
        assert spec.project.name == "TestFarm"
        assert len(spec.actors) == 1
        assert len(spec.events) == 1
        assert len(spec.workflows) == 1
        assert len(spec.decisions) == 1
        assert len(spec.exceptions) == 1
        assert len(spec.rules) == 1
        assert len(spec.reports) == 1
        assert len(spec.acceptance_tests) == 1
        assert spec.coverage_map is not None
        assert len(spec.coverage_map.workflows) == 1
        assert spec.coverage_map.summary is not None
        assert spec.coverage_map.summary.total_workflows == 1
        assert spec.sign_off is not None
        assert len(spec.sign_off.scope_exclusions) == 1
        assert len(spec.sign_off.amendment_log) == 1

        # Verify nested structures
        event = spec.events[0]
        assert len(event.payload) == 2
        assert event.payload[0].field == "crop"
        assert event.payload[0].required is True
        assert event.provenance is not None
        assert event.provenance.source == "inferred"

        wf = spec.workflows[0]
        assert wf.job_story is not None
        assert wf.job_story.when == "Monday morning"
        assert len(wf.steps) == 1
        assert wf.operational is not None
        assert wf.operational.mobile_required is True
        assert wf.data_entry is not None
        assert wf.data_entry.batch_capable is False
        assert wf.decisions == [{"ref": "prioritize_harvest_when_short"}]

        exc = spec.exceptions[0]
        assert exc.detection is not None
        assert exc.detection.method == "system_computed"
        assert len(exc.responses) == 1
        assert exc.responses[0].description == "Flag shortfall items."

        rpt = spec.reports[0]
        assert rpt.format == "unknown"
        assert rpt.format_notes != ""
        assert rpt.workflows_supported == ["weekly_harvest_planning"]

        at = spec.acceptance_tests[0]
        assert len(at.criteria) == 1
        assert at.criteria[0].type == "completion"
        assert at.criteria[0].verification_required is False

        d = spec.decisions[0]
        assert d.automation_level == "human_only"
        assert d.outcome_recorded_as == "HarvestPrioritySet"


class TestRoundTrip:
    """to_dict / from_dict / to_yaml / from_yaml round-trip (Issues 3, 4)."""

    def test_to_dict(self):
        """to_dict returns a dict with top-level keys."""
        spec = BehavioralSpec(
            project=MwbsProject(name="Test"),
            business=BusinessSection(name="TestBiz"),
        )
        data = spec.to_dict()
        assert isinstance(data, dict)
        assert data["spec_version"] == MWBS_SPEC_VERSION
        assert data["schema"] == "mwbs/v1"
        assert data["project"]["name"] == "Test"
        assert data["business"]["name"] == "TestBiz"
        # None values should be skipped
        assert "sign_off" not in data

    def test_to_dict_with_all_sections(self):
        """to_dict includes all populated sections."""
        spec = BehavioralSpec(
            actors=[Actor(id="a1")],
            events=[BehavioralEvent(id="e1")],
            workflows=[BehavioralWorkflow(id="w1")],
            decisions=[Decision(id="d1")],
            exceptions=[WorkflowException(id="ex1")],
            rules=[BusinessRule(id="r1")],
            reports=[Report(id="rp1")],
            acceptance_tests=[AcceptanceTest(id="at1")],
            coverage_map=CoverageMap(summary=CoverageMapSummary()),
            sign_off=SignOffBlock(operator=SignOffOperator(name="Op")),
        )
        data = spec.to_dict()
        assert len(data["actors"]) == 1
        assert len(data["events"]) == 1
        assert len(data["workflows"]) == 1
        assert len(data["decisions"]) == 1
        assert len(data["exceptions"]) == 1
        assert len(data["rules"]) == 1
        assert len(data["reports"]) == 1
        assert len(data["acceptance_tests"]) == 1
        assert "coverage_map" in data
        assert "sign_off" in data
        assert data["sign_off"]["operator"]["name"] == "Op"

    def test_from_dict(self):
        """from_dict reconstructs a spec from a plain dict."""
        data = {
            "spec_version": "mwbs/v1",
            "schema": "mwbs/v1",
            "project": {"name": "FromDict", "version": 2},
            "business": {"name": "Biz", "domain": "farm"},
            "actors": [{"id": "a1", "name": "Actor One", "access_level": "full"}],
            "events": [
                {
                    "id": "e1",
                    "name": "EventOne",
                    "producer": "a1",
                    "payload": [{"field": "f1", "type": "string", "required": True}],
                    "consumed_by": ["w1"],
                    "provenance": {"source": "inferred"},
                }
            ],
            "workflows": [
                {
                    "id": "w1",
                    "title": "Workflow One",
                    "job_story": {
                        "when": "test",
                        "i_need_to": "do",
                        "so_i_can": "done",
                    },
                    "actor": "a1",
                    "frequency": "weekly",
                    "steps": [
                        {"id": "s1", "title": "Step 1", "actor_action": "review"}
                    ],
                    "operational": {"max_steps": 3, "spreadsheet_access": "forbidden"},
                    "data_entry": {"frequency": "weekly", "batch_capable": True},
                    "provenance": {"source": "hybrid"},
                }
            ],
            "decisions": [{"id": "d1", "title": "Decision 1"}],
            "exceptions": [
                {
                    "id": "ex1",
                    "title": "Exc 1",
                    "workflow": "w1",
                    "condition": "bad state",
                    "detection": {"method": "check", "trigger": "step"},
                    "responses": [{"id": "r1", "action": "fix", "actor": "system"}],
                }
            ],
            "rules": [{"id": "r1", "title": "Rule 1", "expression": "x > 0"}],
            "reports": [
                {
                    "id": "rp1",
                    "title": "Report 1",
                    "format": "unknown",
                    "format_notes": "TBD",
                    "workflows_supported": ["w1"],
                }
            ],
            "acceptance_tests": [
                {
                    "id": "at1",
                    "workflow": "w1",
                    "criteria": [{"id": "c1", "type": "completion"}],
                }
            ],
            "coverage_map": {
                "workflows": [{"id": "w1", "title": "WF", "source": "hybrid"}],
                "summary": {
                    "total_workflows": 1,
                    "total_events": 1,
                    "total_decisions": 1,
                    "total_exceptions": 1,
                    "total_rules": 1,
                    "total_reports": 1,
                    "total_tests": 1,
                    "behavioral_coverage_pct": 100,
                },
            },
            "sign_off": {
                "statement": "Confirmed.",
                "operator": {"name": "Op", "date": "2026-07-01"},
                "developer": {"name": "Dev"},
            },
        }
        spec = BehavioralSpec.from_dict(data)
        assert spec.spec_version == "mwbs/v1"
        assert spec.project is not None
        assert spec.project.name == "FromDict"
        assert spec.project.version == 2
        assert spec.business is not None
        assert spec.business.name == "Biz"
        assert len(spec.actors) == 1
        assert spec.actors[0].access_level == "full"
        assert len(spec.events) == 1
        assert spec.events[0].payload[0].field == "f1"
        assert spec.events[0].provenance is not None
        assert len(spec.workflows) == 1
        assert spec.workflows[0].job_story is not None
        assert spec.workflows[0].job_story.when == "test"
        assert spec.workflows[0].operational is not None
        assert spec.workflows[0].operational.spreadsheet_access == "forbidden"
        assert spec.workflows[0].data_entry is not None
        assert spec.workflows[0].data_entry.batch_capable is True
        assert spec.workflows[0].provenance is not None
        assert len(spec.decisions) == 1
        assert len(spec.exceptions) == 1
        assert spec.exceptions[0].detection is not None
        assert spec.exceptions[0].responses[0].action == "fix"
        assert len(spec.rules) == 1
        assert len(spec.reports) == 1
        assert spec.reports[0].format_notes == "TBD"
        assert spec.reports[0].workflows_supported == ["w1"]
        assert len(spec.acceptance_tests) == 1
        assert spec.acceptance_tests[0].criteria[0].type == "completion"
        assert spec.coverage_map is not None
        assert spec.coverage_map.summary is not None
        assert spec.coverage_map.summary.total_workflows == 1
        assert len(spec.coverage_map.workflows) == 1
        assert spec.sign_off is not None
        assert spec.sign_off.operator is not None
        assert spec.sign_off.operator.name == "Op"
        assert spec.sign_off.developer is not None
        assert spec.sign_off.developer.name == "Dev"

    def test_to_dict_from_dict_round_trip(self):
        """to_dict then from_dict preserves all data."""
        original = BehavioralSpec(
            actors=[Actor(id="a1", name="Actor One")],
            events=[
                BehavioralEvent(
                    id="e1",
                    payload=[PayloadField(field="f1", type="int")],
                    provenance=Provenance(source="inferred"),
                )
            ],
            workflows=[
                BehavioralWorkflow(
                    id="w1",
                    steps=[WorkflowStep(id="s1", title="Step")],
                    operational=WorkflowOperational(max_steps=2),
                )
            ],
            decisions=[Decision(id="d1", outcome_recorded_as="Done")],
            exceptions=[
                WorkflowException(
                    id="ex1",
                    detection=Detection(method="auto"),
                    responses=[ExceptionResponse(id="r1", action="alert")],
                )
            ],
            rules=[BusinessRule(id="r1", expression="true")],
            reports=[Report(id="rp1", workflows_supported=["w1"])],
            acceptance_tests=[
                AcceptanceTest(
                    id="at1",
                    criteria=[AcceptanceCriterion(id="c1", type="completion")],
                )
            ],
            coverage_map=CoverageMap(
                workflows=[CoverageMapWorkflow(id="w1")],
                summary=CoverageMapSummary(total_workflows=1),
            ),
            sign_off=SignOffBlock(
                operator=SignOffOperator(name="Op"),
                developer=SignOffDeveloper(name="Dev"),
            ),
        )
        data = original.to_dict()
        restored = BehavioralSpec.from_dict(data)
        assert restored.actors[0].id == "a1"
        assert restored.events[0].payload[0].field == "f1"
        assert restored.events[0].provenance is not None
        assert restored.workflows[0].steps[0].id == "s1"
        assert restored.workflows[0].operational is not None
        assert restored.workflows[0].operational.max_steps == 2
        assert restored.decisions[0].outcome_recorded_as == "Done"
        assert restored.exceptions[0].detection is not None
        assert restored.exceptions[0].detection.method == "auto"
        assert restored.exceptions[0].responses[0].action == "alert"
        assert restored.rules[0].expression == "true"
        assert restored.reports[0].workflows_supported == ["w1"]
        assert restored.acceptance_tests[0].criteria[0].type == "completion"
        assert restored.coverage_map is not None
        assert restored.coverage_map.workflows[0].id == "w1"
        assert restored.coverage_map.summary is not None
        assert restored.coverage_map.summary.total_workflows == 1
        assert restored.sign_off is not None
        assert restored.sign_off.operator is not None
        assert restored.sign_off.operator.name == "Op"
        assert restored.sign_off.developer is not None
        assert restored.sign_off.developer.name == "Dev"

    def test_yaml_round_trip(self, tmp_path):
        """to_yaml then from_yaml preserves all fields."""
        original = BehavioralSpec(
            project=MwbsProject(name="YAMLTest"),
            actors=[Actor(id="a1", name="Actor")],
            events=[BehavioralEvent(id="e1", producer="a1")],
            workflows=[BehavioralWorkflow(id="w1", actor="a1")],
            decisions=[Decision(id="d1")],
            exceptions=[WorkflowException(id="ex1", condition="err")],
            rules=[BusinessRule(id="r1")],
            reports=[Report(id="rp1")],
            acceptance_tests=[AcceptanceTest(id="at1")],
            coverage_map=CoverageMap(summary=CoverageMapSummary()),
            sign_off=SignOffBlock(statement="OK"),
        )
        yaml_path = tmp_path / "test_spec.yaml"
        original.to_yaml(yaml_path)
        restored = BehavioralSpec.from_yaml(yaml_path)
        assert restored.project is not None
        assert restored.project.name == "YAMLTest"
        assert len(restored.actors) == 1
        assert restored.actors[0].id == "a1"
        assert len(restored.events) == 1
        assert restored.events[0].producer == "a1"
        assert restored.coverage_map is not None
        assert restored.coverage_map.summary is not None
        assert restored.sign_off is not None
        assert restored.sign_off.statement == "OK"

    def test_from_yaml_not_mapping(self, tmp_path):
        """from_yaml raises ValueError for non-mapping YAML."""
        import yaml

        path = tmp_path / "bad.yaml"
        path.write_text(yaml.safe_dump(["not", "a", "dict"]), encoding="utf-8")
        import pytest

        with pytest.raises(ValueError, match="not a mapping"):
            BehavioralSpec.from_yaml(path)


class TestPlaceholders:
    """Placeholder detection (Issues 5, 6)."""

    def test_placeholders_detected(self):
        """placeholders() finds [REQUIRES_ELICITATION] markers."""
        spec = BehavioralSpec(
            actors=[
                Actor(
                    id="fm",
                    time_pressures=[
                        "[REQUIRES_ELICITATION: What are the morning deadlines?]"
                    ],
                )
            ],
            workflows=[
                BehavioralWorkflow(
                    id="w1",
                    job_story=JobStory(
                        when="[REQUIRES_ELICITATION: When does planning happen?]",
                    ),
                )
            ],
        )
        results = spec.placeholders()
        assert len(results) >= 2
        descriptions = [p.description for p in results]
        assert "What are the morning deadlines?" in descriptions
        assert "When does planning happen?" in descriptions

    def test_placeholders_empty(self):
        """placeholders() returns empty list when no markers exist."""
        spec = BehavioralSpec(
            project=MwbsProject(name="Clean"),
            actors=[Actor(id="fm", access_level="full")],
        )
        results = spec.placeholders()
        assert results == []

    def test_placeholders_in_nested_structures(self):
        """placeholders() finds markers in nested fields like job_story."""
        spec = BehavioralSpec(
            workflows=[
                BehavioralWorkflow(
                    id="w1",
                    job_story=JobStory(
                        when="[REQUIRES_ELICITATION: When?]",
                        i_need_to="Do the thing",
                        so_i_can="[REQUIRES_ELICITATION: Why is this needed?]",
                    ),
                    steps=[
                        WorkflowStep(
                            id="s1",
                            description="[REQUIRES_ELICITATION: What happens here?]",
                        )
                    ],
                    operational=WorkflowOperational(
                        spreadsheet_access="[REQUIRES_ELICITATION: Offline needed?]"
                    ),
                )
            ]
        )
        results = spec.placeholders()
        assert len(results) >= 4
        descriptions = [p.description for p in results]
        assert "When?" in descriptions
        assert "Why is this needed?" in descriptions
        assert "What happens here?" in descriptions
        assert "Offline needed?" in descriptions


class TestProvenanceDefaults:
    """Provenance default verification (Issue 8)."""

    def test_provenance_default_verification_required(self):
        """Provenance() has verification_required=True."""
        prov = Provenance()
        assert prov.verification_required is True

    def test_provenance_default_source(self):
        """Provenance() has source='inferred'."""
        prov = Provenance()
        assert prov.source == "inferred"

    def test_provenance_empty_lists(self):
        """Provenance() has empty inference_signals and elicited_elements."""
        prov = Provenance()
        assert prov.inference_signals == []
        assert prov.elicited_elements == []


class TestWorkflowFeatures:
    """Specific workflow features that must match the spec."""

    def test_workflow_decisions_list(self):
        """Workflow has top-level decisions list."""
        wf = BehavioralWorkflow(
            id="w1",
            decisions=[{"ref": "d1"}, {"ref": "d2"}],
        )
        assert len(wf.decisions) == 2
        assert wf.decisions[0]["ref"] == "d1"

    def test_workflow_acceptance_tests_list(self):
        """Workflow has top-level acceptance_tests list."""
        wf = BehavioralWorkflow(
            id="w1",
            acceptance_tests=[{"ref": "AT-w1-001"}],
        )
        assert len(wf.acceptance_tests) == 1

    def test_workflow_exceptions_list(self):
        """Workflow has top-level exceptions list."""
        wf = BehavioralWorkflow(
            id="w1",
            exceptions=[{"ref": "EX-w1-001"}, {"ref": "EX-w1-002"}],
        )
        assert len(wf.exceptions) == 2

    def test_report_has_workflows_supported(self):
        """Report uses workflows_supported not decisions_supported."""
        rpt = Report(
            id="r1",
            workflows_supported=["w1", "w2"],
        )
        assert hasattr(rpt, "workflows_supported")
        assert not hasattr(rpt, "decisions_supported")
        assert rpt.workflows_supported == ["w1", "w2"]

    def test_report_has_format_notes(self):
        """Report has format_notes for elicitation text."""
        rpt = Report(
            id="r1",
            format="unknown",
            format_notes="[REQUIRES_ELICITATION: Best format?]",
        )
        assert rpt.format == "unknown"
        assert rpt.format_notes == "[REQUIRES_ELICITATION: Best format?]"

    def test_exception_severity_values(self):
        """Exception severity accepts valid values."""
        w = WorkflowException(id="e1", severity="warning")
        e = WorkflowException(id="e2", severity="error")
        b = WorkflowException(id="e3", severity="blocking")
        assert w.severity == "warning"
        assert e.severity == "error"
        assert b.severity == "blocking"

    def test_decision_automation_levels(self):
        """Decision automation_level accepts valid values."""
        h = Decision(id="d1", automation_level="human_only")
        s = Decision(id="d2", automation_level="system_suggests")
        f = Decision(id="d3", automation_level="fully_automated")
        assert h.automation_level == "human_only"
        assert s.automation_level == "system_suggests"
        assert f.automation_level == "fully_automated"

    def test_coverage_map_summary_full(self):
        """CoverageMapSummary has all fields including dimensions_covered."""
        sm = CoverageMapSummary(
            total_workflows=5,
            total_events=9,
            total_decisions=4,
            total_exceptions=10,
            total_rules=5,
            total_reports=3,
            total_tests=5,
            dimensions_covered=6,
            gaps=0,
            behavioral_coverage_pct=100.0,
            spreadsheet_independence_pct=0.0,
            signed_off=0,
        )
        assert sm.dimensions_covered == 6
        assert sm.behavioral_coverage_pct == 100.0


class TestSpecVersion:
    """MWBS_SPEC_VERSION constant."""

    def test_spec_version_constant(self):
        """MWBS_SPEC_VERSION is mwbs/v1."""
        assert MWBS_SPEC_VERSION == "mwbs/v1"

    def test_behavioral_spec_default_version(self):
        """BehavioralSpec uses the MWBS_SPEC_VERSION constant."""
        spec = BehavioralSpec()
        assert spec.spec_version == MWBS_SPEC_VERSION
