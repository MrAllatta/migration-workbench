"""Tests for the MWBS Behavioral Spec Elicitor.

Covers:
- InferenceRule dataclass and INFERENCE_RULES catalog
- InferenceConfidenceLog dataclass
- generate_placeholders() for un-inferrable elements
- generate_elicitation_worksheet() Markdown output
- derive_behavioral_spec() producing valid BehavioralSpec
- Backward-compat helpers and derive_operational_model()
"""

from profiler.tools.behavioral_spec import (
    Actor,
    BehavioralSpec,
    BehavioralWorkflow,
    Decision,
    JobStory,
    MwbsProject,
    WorkflowDataEntry,
    WorkflowException,
    WorkflowOperational,
)
from profiler.tools.behavioral_spec_elicitor import (
    INFERENCE_RULES,
    InferenceConfidenceLog,
    InferenceRule,
    _cluster_tabs_into_entities,
    _derive_actors,
    _derive_invariants_from_events,
    _infer_candidate_events,
    _infer_commands_from_tabs,
    _infer_workflows_from_clusters,
    _infer_workflows_from_graph,
    _lookup_rule,
    _provenance_from_rule,
    derive_behavioral_spec,
    derive_operational_model,
    generate_elicitation_worksheet,
    generate_placeholders,
)
from profiler.tools.operational_model import OperationalModel

# ===================================================================
# InferenceRule dataclass
# ===================================================================


class TestInferenceRule:
    """InferenceRule dataclass defaults and construction."""

    def test_defaults(self):
        """InferenceRule uses empty string defaults and 0.5 weight."""
        rule = InferenceRule()
        assert rule.id == ""
        assert rule.name == ""
        assert rule.signal == ""
        assert rule.infers == ""
        assert rule.confidence_weight == 0.5

    def test_custom_values(self):
        """InferenceRule accepts custom values."""
        rule = InferenceRule(
            id="INF-99",
            name="test_rule",
            signal="Test signal",
            infers="Test infers",
            confidence_weight=0.9,
        )
        assert rule.id == "INF-99"
        assert rule.name == "test_rule"
        assert rule.confidence_weight == 0.9


# ===================================================================
# INFERENCE_RULES catalog
# ===================================================================


class TestInferenceRulesCatalog:
    """INFERENCE_RULES has all 12 rules with correct fields."""

    def test_catalog_has_12_rules(self):
        """INFERENCE_RULES contains exactly 12 entries."""
        assert len(INFERENCE_RULES) == 12

    def test_all_rules_have_ids(self):
        """All rules have non-empty IDs."""
        ids = [rule.id for rule in INFERENCE_RULES]
        for rule_id in ids:
            assert rule_id, "Rule with empty id found"
        assert ids == [f"INF-{i:02d}" for i in range(1, 13)]

    def test_all_rules_have_non_empty_names(self):
        """All rules have non-empty names."""
        for rule in INFERENCE_RULES:
            assert rule.name, f"Rule {rule.id} has empty name"

    def test_all_rules_have_signals(self):
        """All rules have non-empty signals."""
        for rule in INFERENCE_RULES:
            assert rule.signal, f"Rule {rule.id} has empty signal"

    def test_all_rules_have_infers(self):
        """All rules have non-empty infers."""
        for rule in INFERENCE_RULES:
            assert rule.infers, f"Rule {rule.id} has empty infers"

    def test_confidence_weights_in_range(self):
        """All confidence weights are between 0.0 and 1.0."""
        for rule in INFERENCE_RULES:
            assert 0.0 <= rule.confidence_weight <= 1.0, (
                f"Rule {rule.id} has weight {rule.confidence_weight} "
                f"outside [0.0, 1.0]"
            )

    def test_lookup_rule_found(self):
        """_lookup_rule returns the correct rule."""
        rule = _lookup_rule("INF-01")
        assert rule is not None
        assert rule.id == "INF-01"
        assert rule.name == "tab_title_entity"

    def test_lookup_rule_not_found(self):
        """_lookup_rule returns None for unknown rule id."""
        rule = _lookup_rule("INF-99")
        assert rule is None

    def test_inf_01_tab_title_entity(self):
        """INF-01 has expected attributes."""
        rule = _lookup_rule("INF-01")
        assert rule.name == "tab_title_entity"
        assert "entity" in rule.infers.lower()
        assert rule.confidence_weight == 0.8

    def test_inf_05_cross_sheet_formula(self):
        """INF-05 has expected attributes."""
        rule = _lookup_rule("INF-05")
        assert rule.name == "cross_sheet_formula"
        assert "dependency" in rule.infers.lower()
        assert rule.confidence_weight == 0.8

    def test_inf_11_boolean_column(self):
        """INF-11 has expected attributes."""
        rule = _lookup_rule("INF-11")
        assert rule.name == "boolean_column"
        assert "flag" in rule.infers.lower()
        assert rule.confidence_weight == 0.7


# ===================================================================
# InferenceConfidenceLog dataclass
# ===================================================================


class TestInferenceConfidenceLog:
    """InferenceConfidenceLog dataclass defaults."""

    def test_defaults(self):
        """InferenceConfidenceLog uses empty defaults."""
        log = InferenceConfidenceLog()
        assert log.element_id == ""
        assert log.element_type == ""
        assert log.inference_rule_id == ""
        assert log.confidence_weight == 0.0
        assert log.signals_found == []
        assert log.verified is False

    def test_custom_values(self):
        """InferenceConfidenceLog accepts custom values."""
        log = InferenceConfidenceLog(
            element_id="evt_plant_date",
            element_type="event",
            inference_rule_id="INF-03",
            confidence_weight=0.6,
            signals_found=["Plant Date", "date keyword"],
            verified=True,
        )
        assert log.element_id == "evt_plant_date"
        assert log.element_type == "event"
        assert log.inference_rule_id == "INF-03"
        assert log.signals_found == ["Plant Date", "date keyword"]
        assert log.verified is True


# ===================================================================
# Provenance helper
# ===================================================================


class TestProvenanceHelper:
    """_provenance_from_rule builds correct Provenance records."""

    def test_with_valid_rule(self):
        """Valid rule id produces provenance with inference signals."""
        prov = _provenance_from_rule("INF-01")
        assert prov.source == "inferred"
        assert len(prov.inference_signals) == 1
        assert prov.inference_signals[0]["rule_id"] == "INF-01"
        assert prov.verification_required is True

    def test_with_custom_signals(self):
        """Additional signals are appended to inference_signals."""
        signals = [{"source_column": "Crop Name"}]
        prov = _provenance_from_rule("INF-02", signals=signals)
        assert len(prov.inference_signals) == 2
        assert prov.inference_signals[1]["source_column"] == "Crop Name"


# ===================================================================
# generate_placeholders
# ===================================================================


def _make_spec_with_gaps() -> BehavioralSpec:
    """Build a BehavioralSpec with fields that need elicitation."""
    return BehavioralSpec(
        spec_version="mwbs/v1",
        project=MwbsProject(name="Test", status="draft"),
        actors=[
            Actor(
                id="field_manager",
                name="Field Manager",
                time_pressures=[],
            ),
        ],
        workflows=[
            BehavioralWorkflow(
                id="wf_harvest",
                title="Harvest Planning",
                job_story=JobStory(when="", i_need_to="Harvest", so_i_can="Plan"),
                decisions=[{"id": "dec_start", "criteria_actor_applies": []}],
                exceptions=[{"id": "exc_weather", "current_handling": ""}],
                operational=WorkflowOperational(max_duration_minutes=0),
                data_entry=WorkflowDataEntry(preferred_input=""),
                priority=0,
            ),
            BehavioralWorkflow(
                id="wf_planting",
                title="Planting Schedule",
                job_story=JobStory(when="Spring", i_need_to="Plant", so_i_can="Grow"),
                decisions=[],
                exceptions=[],
                operational=WorkflowOperational(max_duration_minutes=30),
                data_entry=WorkflowDataEntry(preferred_input="Mobile App"),
                priority=2,
            ),
        ],
        decisions=[
            Decision(
                id="dec_priority",
                title="Harvest Priority",
                criteria_actor_applies=[],
                within_workflow="wf_harvest",
            ),
        ],
        exceptions=[
            WorkflowException(
                id="exc_weather",
                workflow="wf_harvest",
                current_handling="",
            ),
        ],
    )


class TestGeneratePlaceholders:
    """generate_placeholders creates placeholders for un-inferrable fields."""

    def test_generates_placeholders(self):
        """A spec with gaps produces multiple placeholders."""
        spec = _make_spec_with_gaps()
        placeholders = generate_placeholders(spec)
        assert len(placeholders) >= 1

    def test_max_duration_placeholder(self):
        """Workflow with zero max_duration gets a placeholder."""
        spec = _make_spec_with_gaps()
        placeholders = generate_placeholders(spec)
        max_duration_ph = [
            p for p in placeholders if "max_duration_minutes" in p.field_path
        ]
        assert len(max_duration_ph) >= 1
        assert any("wf_harvest" in p.workflow_id for p in max_duration_ph)

    def test_job_story_when_placeholder(self):
        """Workflow with empty job_story.when gets a placeholder."""
        spec = _make_spec_with_gaps()
        placeholders = generate_placeholders(spec)
        when_ph = [p for p in placeholders if "job_story.when" in p.field_path]
        assert len(when_ph) >= 1
        assert any("wf_harvest" in p.workflow_id for p in when_ph)

    def test_preferred_input_placeholder(self):
        """Workflow with empty preferred_input gets a placeholder."""
        spec = _make_spec_with_gaps()
        placeholders = generate_placeholders(spec)
        input_ph = [p for p in placeholders if "preferred_input" in p.field_path]
        assert len(input_ph) >= 1
        assert any("wf_harvest" in p.workflow_id for p in input_ph)

    def test_priority_placeholder(self):
        """Workflow with zero priority gets a placeholder."""
        spec = _make_spec_with_gaps()
        placeholders = generate_placeholders(spec)
        priority_ph = [p for p in placeholders if "priority" in p.field_path]
        assert len(priority_ph) >= 1
        assert any("wf_harvest" in p.workflow_id for p in priority_ph)

    def test_decision_criteria_placeholder(self):
        """Decision with empty criteria gets a placeholder."""
        spec = _make_spec_with_gaps()
        placeholders = generate_placeholders(spec)
        criteria_ph = [
            p for p in placeholders if "criteria_actor_applies" in p.field_path
        ]
        assert len(criteria_ph) >= 1

    def test_exception_current_handling_placeholder(self):
        """Exception with empty current_handling gets a placeholder."""
        spec = _make_spec_with_gaps()
        placeholders = generate_placeholders(spec)
        handling_ph = [p for p in placeholders if "current_handling" in p.field_path]
        assert len(handling_ph) >= 1

    def test_actor_time_pressures_placeholder(self):
        """Actor with empty time_pressures gets a placeholder."""
        spec = _make_spec_with_gaps()
        placeholders = generate_placeholders(spec)
        time_ph = [p for p in placeholders if "time_pressures" in p.field_path]
        assert len(time_ph) >= 1

    def test_workflow_with_complete_data_has_fewer_placeholders(self):
        """A complete workflow generates fewer placeholders."""
        spec = _make_spec_with_gaps()
        # wf_planting has most fields filled
        placeholders = generate_placeholders(spec)
        planting_ph = [p for p in placeholders if p.workflow_id == "wf_planting"]
        harvest_ph = [p for p in placeholders if p.workflow_id == "wf_harvest"]
        # wf_planting should have fewer placeholders than wf_harvest
        # (both still have some gaps like decisions/exceptions criteria)
        assert len(planting_ph) <= len(harvest_ph)

    def test_placeholder_fields(self):
        """Each placeholder has all required fields populated."""
        spec = _make_spec_with_gaps()
        placeholders = generate_placeholders(spec)
        for ph in placeholders:
            assert ph.field_path, "Placeholder missing field_path"
            assert ph.description, "Placeholder missing description"
            # section, workflow_id, and reason are allowed to be empty
            # for some placeholder types

    def test_accepts_dict_input(self):
        """generate_placeholders also accepts a plain dict."""
        spec_dict = {
            "spec_version": "mwbs/v1",
            "project": {"name": "Test", "status": "draft"},
            "actors": [{"id": "op", "name": "Operator", "time_pressures": []}],
            "workflows": [
                {
                    "id": "wf_test",
                    "title": "Test WF",
                    "operational": {"max_duration_minutes": 0},
                    "priority": 0,
                }
            ],
        }
        placeholders = generate_placeholders(spec_dict)
        assert len(placeholders) >= 1
        paths = [p.field_path for p in placeholders]
        assert any("max_duration_minutes" in path for path in paths)
        assert any("priority" in path for path in paths)


# ===================================================================
# generate_elicitation_worksheet
# ===================================================================


class TestGenerateElicitationWorksheet:
    """generate_elicitation_worksheet produces structured Markdown."""

    def test_returns_non_empty_string(self):
        """Worksheet is a non-empty Markdown string."""
        spec = _make_spec_with_gaps()
        worksheet = generate_elicitation_worksheet(spec)
        assert isinstance(worksheet, str)
        assert len(worksheet) > 0

    def test_contains_title(self):
        """Worksheet starts with a top-level title."""
        spec = _make_spec_with_gaps()
        worksheet = generate_elicitation_worksheet(spec)
        assert "# Elicitation Worksheet" in worksheet

    def test_contains_all_6_sections(self):
        """Worksheet has all 6 required sections."""
        spec = _make_spec_with_gaps()
        worksheet = generate_elicitation_worksheet(spec)
        sections = [
            "## Workflow Walk-Through",
            "## Exception Review",
            "## Decision Inventory",
            "## Priority Stack Rank",
            "## Speed Calibration",
            "## Paper Process Inventory",
        ]
        for section_title in sections:
            assert section_title in worksheet, f"Missing section: {section_title}"

    def test_contains_workflow_references(self):
        """Worksheet references workflow ids that have placeholders."""
        spec = _make_spec_with_gaps()
        worksheet = generate_elicitation_worksheet(spec)
        assert "wf_harvest" in worksheet

    def test_workflow_section_has_placeholders(self):
        """Workflow Walk-Through section contains placeholder descriptions."""
        spec = _make_spec_with_gaps()
        worksheet = generate_elicitation_worksheet(spec)
        assert "Maximum duration per workflow session" in worksheet
        assert "Situational context" in worksheet

    def test_handles_empty_spec_gracefully(self):
        """Worksheet handles a spec with no placeholders."""
        spec = BehavioralSpec(
            spec_version="mwbs/v1",
            actors=[Actor(id="op", name="Operator")],
        )
        worksheet = generate_elicitation_worksheet(spec)
        assert "# Elicitation Worksheet" in worksheet
        assert "No items to elicit" in worksheet


# ===================================================================
# Old helpers (unchanged from operational_model_deriver)
# ===================================================================


class TestOldHelpers:
    """The original helper functions still work as before."""

    def test_cluster_tabs_into_entities(self):
        """Tab clustering works with Jaccard similarity."""
        tabs = [
            {"tab_title": "Crop Planner 2025", "columns": ["Crop", "Date", "Status"]},
            {"tab_title": "Crop Planner 2026", "columns": ["Crop", "Date", "Status"]},
            {"tab_title": "Inventory", "columns": ["Item", "Quantity"]},
        ]
        clusters = _cluster_tabs_into_entities(tabs)
        crop_clusters = [c for c in clusters if "Crop" in c["entity_name"]]
        assert len(crop_clusters) >= 1
        assert len(crop_clusters[0]["tabs"]) == 2

    def test_infer_candidate_events(self):
        """Event inference produces candidates from temporal columns."""
        columns = [
            {
                "header_label": "Adjustment Date",
                "null_rate": 0.05,
                "distinct_values": ["2025-01-01", "2025-01-02"],
            },
            {
                "header_label": "Quantity",
                "null_rate": 0.10,
                "distinct_values": ["10", "20"],
            },
            {"header_label": "Notes", "null_rate": 0.60, "distinct_values": []},
        ]
        events = _infer_candidate_events(columns)
        assert len(events) >= 1
        assert events[0]["suggested_event_id"] == "adjustment_date_logged"

    def test_infer_workflows_from_graph(self):
        """Workflow inference from formula graph edges."""
        formula_graph = {
            "edges": [
                {"from": "Crop Planner", "to": "Harvest Record", "ref_type": "VLOOKUP"},
            ]
        }
        workflows = _infer_workflows_from_graph(formula_graph)
        assert len(workflows) >= 1
        assert any(wf["id"] == "crop_planner_to_harvest_record" for wf in workflows)

    def test_infer_workflows_from_clusters(self):
        """Workflow inference from entity clusters."""
        clusters = [
            {
                "entity_name": "Crop",
                "tabs": ["Crop Planner", "Crop by Season", "Crop Info"],
            },
        ]
        workflows = _infer_workflows_from_clusters(clusters)
        assert len(workflows) >= 1
        assert workflows[0]["id"] == "crop_workflow"

    def test_infer_commands_from_tabs(self):
        """Command inference from tab titles with action verbs."""
        tabs = [
            {"tab_title": "Plan Crops"},
            {"tab_title": "Inventory"},
        ]
        commands = _infer_commands_from_tabs(tabs)
        assert len(commands) >= 1
        assert commands[0]["id"] == "plan_crops"

    def test_derive_invariants_from_events(self):
        """Invariant derivation from event payloads."""
        events = [
            {"id": "inventory_adjusted", "payload": ["quantity_before", "item"]},
        ]
        invariants = _derive_invariants_from_events(events)
        assert len(invariants) >= 1
        assert any("quantity" in inv["expression"] for inv in invariants)

    def test_empty_formula_graph(self):
        """No formula graph yields no workflows."""
        workflows = _infer_workflows_from_graph(None)
        assert workflows == []

    def test_single_tab_cluster_no_workflow(self):
        """Single-tab clusters don't generate workflows."""
        clusters = [{"entity_name": "Single", "tabs": ["Only Tab"]}]
        workflows = _infer_workflows_from_clusters(clusters)
        assert workflows == []


# ===================================================================
# derive_behavioral_spec
# ===================================================================


class TestDeriveBehavioralSpec:
    """derive_behavioral_spec produces a valid BehavioralSpec."""

    def test_returns_behavioral_spec(self):
        """Result is a BehavioralSpec instance."""
        discovery = {"workbook_index": [], "broad_inventory": []}
        deep_profile_index = {"entries": []}
        domain_knowledge = {"domain": "test"}
        spec = derive_behavioral_spec(discovery, deep_profile_index, domain_knowledge)
        assert isinstance(spec, BehavioralSpec)

    def test_spec_version_is_mwbs_v1(self):
        """spec_version is set to MWBS_SPEC_VERSION."""
        spec = derive_behavioral_spec(
            {"workbook_index": [], "broad_inventory": []},
            {"entries": []},
            {"domain": "test", "vocabulary": {"operational": ["crop"]}},
        )
        assert spec.spec_version == "mwbs/v1"

    def test_project_status_is_draft(self):
        """Project status is set to draft."""
        spec = derive_behavioral_spec(
            {"workbook_index": [], "broad_inventory": []},
            {"entries": []},
            {"domain": "test", "vocabulary": {"operational": ["crop"]}},
        )
        assert spec.project is not None
        assert spec.project.status == "draft"

    def test_actors_populated(self):
        """Actors are populated from domain vocabulary."""
        spec = derive_behavioral_spec(
            {"workbook_index": [], "broad_inventory": []},
            {"entries": []},
            {"domain": "test", "vocabulary": {"operational": ["crop", "harvest"]}},
        )
        assert len(spec.actors) >= 1
        assert any("crop" in actor.id for actor in spec.actors)

    def test_default_actor_when_no_vocabulary(self):
        """A default actor is created when vocabulary is empty."""
        spec = derive_behavioral_spec(
            {"workbook_index": [], "broad_inventory": []},
            {"entries": []},
            {"domain": "test"},
        )
        assert len(spec.actors) >= 1
        assert spec.actors[0].id == "primary_operator"

    def test_events_from_column_profile(self):
        """Events are inferred from column profiles."""
        discovery = {"workbook_index": [], "broad_inventory": []}
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Crop Planner",
                    "columns": [
                        {
                            "header_label": "Plant Date",
                            "null_rate": 0.05,
                            "distinct_values": ["2025-03-01", "2025-04-01"],
                        },
                    ],
                    "fk_candidates": [],
                }
            ]
        }
        spec = derive_behavioral_spec(discovery, deep_profile_index, {"domain": "test"})
        assert len(spec.events) >= 1
        event_ids = [event.id for event in spec.events]
        assert any("plant_date" in event_id for event_id in event_ids)

    def test_events_have_provenance(self):
        """Events have provenance records with inference rule IDs."""
        discovery = {"workbook_index": [], "broad_inventory": []}
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Crop Planner",
                    "columns": [
                        {
                            "header_label": "Plant Date",
                            "null_rate": 0.05,
                            "distinct_values": ["2025-03-01", "2025-04-01"],
                        },
                    ],
                    "fk_candidates": [],
                }
            ]
        }
        spec = derive_behavioral_spec(discovery, deep_profile_index, {"domain": "test"})
        for event in spec.events:
            assert event.provenance is not None
            assert event.provenance.source == "inferred"
            assert len(event.provenance.inference_signals) >= 1

    def test_workflows_populated(self):
        """Workflows are inferred from profiler data."""
        discovery = {"workbook_index": [], "broad_inventory": []}
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Crop Planner",
                    "columns": [
                        {
                            "header_label": "Crop",
                            "null_rate": 0.0,
                            "distinct_values": ["Tomato", "Pepper"],
                        },
                    ],
                    "fk_candidates": [],
                }
            ]
        }
        spec = derive_behavioral_spec(discovery, deep_profile_index, {"domain": "test"})
        assert len(spec.workflows) >= 1

    def test_workflows_have_provenance(self):
        """Workflows have provenance records."""
        discovery = {"workbook_index": [], "broad_inventory": []}
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Crop Planner",
                    "columns": [
                        {
                            "header_label": "Crop",
                            "null_rate": 0.0,
                            "distinct_values": ["Tomato", "Pepper"],
                        },
                    ],
                    "fk_candidates": [],
                }
            ]
        }
        spec = derive_behavioral_spec(discovery, deep_profile_index, {"domain": "test"})
        for workflow in spec.workflows:
            assert workflow.provenance is not None

    def test_decisions_populated(self):
        """Decisions are populated from workflow triggers."""
        discovery = {"workbook_index": [], "broad_inventory": []}
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Crop Planner",
                    "columns": [
                        {
                            "header_label": "Crop",
                            "null_rate": 0.0,
                            "distinct_values": ["Tomato", "Pepper"],
                        },
                    ],
                    "fk_candidates": [],
                }
            ]
        }
        spec = derive_behavioral_spec(discovery, deep_profile_index, {"domain": "test"})
        assert len(spec.decisions) >= 1

    def test_exceptions_populated(self):
        """Exceptions are populated."""
        discovery = {"workbook_index": [], "broad_inventory": []}
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Crop Planner",
                    "columns": [
                        {
                            "header_label": "Crop",
                            "null_rate": 0.0,
                            "distinct_values": ["Tomato", "Pepper"],
                        },
                    ],
                    "fk_candidates": [],
                }
            ]
        }
        spec = derive_behavioral_spec(discovery, deep_profile_index, {"domain": "test"})
        assert len(spec.exceptions) >= 1

    def test_rules_populated(self):
        """Business rules are populated from invariants."""
        discovery = {"workbook_index": [], "broad_inventory": []}
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Inventory",
                    "columns": [
                        {
                            "header_label": "Quantity",
                            "null_rate": 0.10,
                            "distinct_values": ["10", "20", "30"],
                        },
                    ],
                    "fk_candidates": [],
                }
            ]
        }
        spec = derive_behavioral_spec(discovery, deep_profile_index, {"domain": "test"})
        assert len(spec.rules) >= 1

    def test_fk_edges_produce_workflows(self):
        """FK candidates produce cross-sheet workflow candidates."""
        discovery = {"workbook_index": [], "broad_inventory": []}
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Seed Orders",
                    "columns": [{"header_label": "Seed Name"}],
                    "fk_candidates": [{"target": "Seeds Catalog"}],
                },
                {
                    "tab_title": "Seeds Catalog",
                    "columns": [{"header_label": "Seed Name"}],
                    "fk_candidates": [],
                },
            ]
        }
        spec = derive_behavioral_spec(discovery, deep_profile_index, {"domain": "test"})
        workflow_ids = [wf.id for wf in spec.workflows]
        # Should have a workflow connecting Seed Orders to Seeds Catalog
        assert any("seed" in wf_id.lower() for wf_id in workflow_ids)

    def test_with_realistic_profiler_output(self):
        """Handles a realistic profiler output with multiple tabs."""
        discovery = {
            "workbook_index": [
                {"tab_title": "Crop Planner", "row_count": 50, "column_count": 10},
                {"tab_title": "Harvest Log", "row_count": 200, "column_count": 6},
            ],
            "broad_inventory": [],
        }
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Crop Planner",
                    "columns": [
                        {
                            "header_label": "Crop Name",
                            "null_rate": 0.0,
                            "distinct_values": ["Tomato", "Pepper"],
                        },
                        {
                            "header_label": "Plant Date",
                            "null_rate": 0.05,
                            "distinct_values": ["2025-03-01"],
                        },
                        {
                            "header_label": "Status",
                            "null_rate": 0.02,
                            "distinct_values": ["Planned", "Planted"],
                        },
                    ],
                    "fk_candidates": [],
                },
                {
                    "tab_title": "Harvest Log",
                    "columns": [
                        {
                            "header_label": "Crop",
                            "null_rate": 0.0,
                            "distinct_values": ["Tomato"],
                        },
                        {
                            "header_label": "Qty Harvested",
                            "null_rate": 0.0,
                            "distinct_values": ["100", "200"],
                        },
                    ],
                    "fk_candidates": [{"target": "Crop Planner"}],
                },
            ]
        }
        domain_knowledge = {
            "domain": "farm",
            "vocabulary": {"operational": ["crop", "harvest"]},
        }
        spec = derive_behavioral_spec(discovery, deep_profile_index, domain_knowledge)
        assert isinstance(spec, BehavioralSpec)
        assert len(spec.events) >= 1
        assert len(spec.workflows) >= 1
        assert len(spec.actors) >= 1
        assert len(spec.decisions) >= 1
        assert len(spec.exceptions) >= 1


# ===================================================================
# Actor derivation from interaction contract
# ===================================================================


class TestActorDerivationFromInteractionContract:
    """Actor derivation prefers interaction contract roles over vocabulary."""

    def test_actor_from_interaction_contract(self):
        """Interaction contract role_hints produce Actor names matching roles."""
        interaction_contract = {
            "views": [
                {
                    "workflow_hints": {
                        "role_hints": [
                            {
                                "role": "Field Manager",
                                "description": "Oversees field operations and planting schedules",
                                "access_hints": "field_access",
                            },
                            {
                                "role": "Harvest Coordinator",
                                "description": "Manages harvest logistics",
                                "access_hints": "harvest_access",
                            },
                        ]
                    }
                }
            ]
        }
        domain_knowledge = {
            "domain": "farm",
            "vocabulary": {"operational": ["crop", "harvest", "inventory"]},
        }
        actors = _derive_actors(interaction_contract, domain_knowledge)
        actor_names = [actor.name for actor in actors]
        assert "Field Manager" in actor_names
        assert "Harvest Coordinator" in actor_names
        # Should NOT contain vocabulary-derived actors like "Crop"
        assert "Crop" not in actor_names

    def test_actor_from_interaction_contract_fields(self):
        """Interaction-contract actors have correct id, responsibilities, access_level."""
        interaction_contract = {
            "views": [
                {
                    "workflow_hints": {
                        "role_hints": [
                            {
                                "role": "Field Manager",
                                "description": "Oversees field operations",
                                "access_hints": "field_access",
                            },
                        ]
                    }
                }
            ]
        }
        actors = _derive_actors(interaction_contract, None)
        assert len(actors) == 1
        manager = actors[0]
        assert manager.id == "field_manager"
        assert manager.name == "Field Manager"
        assert "Oversees field operations" in manager.responsibilities
        assert manager.access_level == "field_access"

    def test_actor_fallback_vocabulary(self):
        """Without interaction contract, actors come from vocabulary terms."""
        domain_knowledge = {
            "domain": "farm",
            "vocabulary": {"operational": ["crop", "harvest"]},
        }
        actors = _derive_actors(None, domain_knowledge)
        actor_names = [actor.name for actor in actors]
        assert "Crop" in actor_names
        assert "Harvest" in actor_names

    def test_actor_vocabulary_provenance(self):
        """Vocabulary-derived actors have provenance.source == 'vocabulary_stub'."""
        domain_knowledge = {
            "domain": "farm",
            "vocabulary": {"operational": ["crop"]},
        }
        actors = _derive_actors(None, domain_knowledge)
        assert len(actors) == 1
        actor = actors[0]
        assert actor.provenance is not None
        assert actor.provenance.source == "vocabulary_stub"

    def test_actor_vocabulary_provenance_default_actor(self):
        """Default fallback actor also carries vocabulary_stub provenance."""
        domain_knowledge = {"domain": "farm", "vocabulary": {"operational": []}}
        actors = _derive_actors(None, domain_knowledge)
        assert len(actors) == 1
        assert actors[0].id == "primary_operator"
        assert actors[0].provenance is not None
        assert actors[0].provenance.source == "vocabulary_stub"

    def test_actor_derive_behavioral_spec_with_interaction_contract(self):
        """derive_behavioral_spec uses interaction_contract for actors."""
        interaction_contract = {
            "views": [
                {
                    "workflow_hints": {
                        "role_hints": [
                            {"role": "Field Manager", "description": "Manages fields"},
                        ]
                    }
                }
            ]
        }
        # Even though vocabulary has more terms, the interaction contract
        # should take precedence.
        spec = derive_behavioral_spec(
            discovery={"workbook_index": [], "broad_inventory": []},
            deep_profile_index={"entries": []},
            domain_knowledge={
                "domain": "farm",
                "vocabulary": {"operational": ["crop", "harvest", "inventory"]},
            },
            interaction_contract=interaction_contract,
        )
        assert len(spec.actors) == 1
        assert spec.actors[0].name == "Field Manager"

    def test_actor_derive_behavioral_spec_fallback(self):
        """Without interaction_contract, behavioral spec falls back to vocabulary."""
        spec = derive_behavioral_spec(
            discovery={"workbook_index": [], "broad_inventory": []},
            deep_profile_index={"entries": []},
            domain_knowledge={
                "domain": "farm",
                "vocabulary": {"operational": ["crop", "harvest"]},
            },
            interaction_contract=None,
        )
        assert len(spec.actors) == 2
        actor_names = [actor.name for actor in spec.actors]
        assert "Crop" in actor_names
        assert "Harvest" in actor_names
        # All vocabulary-derived actors have provenance tag
        for actor in spec.actors:
            if actor.id != "primary_operator":
                assert actor.provenance is not None
                assert actor.provenance.source == "vocabulary_stub"


# ===================================================================
# derive_operational_model backward compat
# ===================================================================


class TestDeriveOperationalModelBackwardCompat:
    """derive_operational_model still works (backward compat)."""

    def test_returns_operational_model(self):
        """Result is an OperationalModel instance."""
        discovery = {
            "workbook_index": [
                {"tab_title": "Crop Planner", "row_count": 100, "column_count": 12},
            ],
            "broad_inventory": [],
        }
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Crop Planner",
                    "columns": [
                        {"header_label": "Crop", "is_formula": False},
                        {
                            "header_label": "Plant Date",
                            "is_formula": False,
                            "null_rate": 0.05,
                            "distinct_values": ["2025-03-01"],
                        },
                    ],
                    "fk_candidates": [],
                }
            ]
        }
        domain_knowledge = {"domain": "farm", "vocabulary": {"operational": ["crop"]}}
        model = derive_operational_model(
            discovery=discovery,
            deep_profile_index=deep_profile_index,
            domain_knowledge=domain_knowledge,
        )
        assert isinstance(model, OperationalModel)
        assert model.source_id == "farm"
        assert len(model.events) >= 1
        assert len(model.workflows) >= 1

    def test_capabilities_from_vocabulary(self):
        """Capabilities are derived from domain vocabulary."""
        model = derive_operational_model(
            discovery={"workbook_index": [], "broad_inventory": []},
            deep_profile_index={"entries": []},
            domain_knowledge={
                "domain": "test",
                "vocabulary": {"operational": ["crop", "harvest"]},
            },
        )
        capability_ids = [cap.id for cap in model.capabilities]
        assert "crop" in capability_ids
        assert "harvest" in capability_ids

    def test_default_capabilities(self):
        """Default capabilities when vocabulary is empty."""
        model = derive_operational_model(
            discovery={"workbook_index": [], "broad_inventory": []},
            deep_profile_index={"entries": []},
            domain_knowledge={"domain": "test"},
        )
        assert len(model.capabilities) >= 1
        assert model.capabilities[0].id == "discovered_operations"

    def test_invariants_derived(self):
        """Invariants derived from event payload quantity fields."""
        deep_profile_index = {
            "entries": [
                {
                    "tab_title": "Inventory",
                    "columns": [
                        {
                            "header_label": "Quantity",
                            "null_rate": 0.0,
                            "distinct_values": ["10", "20"],
                        },
                    ],
                    "fk_candidates": [],
                }
            ]
        }
        model = derive_operational_model(
            discovery={"workbook_index": [], "broad_inventory": []},
            deep_profile_index=deep_profile_index,
            domain_knowledge={"domain": "test"},
        )
        assert len(model.invariants) >= 1
        assert any("quantity" in inv.expression for inv in model.invariants)

    def test_empty_profiler_data(self):
        """Handles empty profiler data gracefully."""
        model = derive_operational_model(
            discovery={"workbook_index": [], "broad_inventory": []},
            deep_profile_index={"entries": []},
            domain_knowledge={},
        )
        assert isinstance(model, OperationalModel)
        assert model.source_id == ""
