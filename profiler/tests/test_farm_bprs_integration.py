"""Integration test exercising the BPRS unified pipeline with farm-domain data.

Builds realistic synthetic profiler artifacts (dicts, not files) and runs
the full BPRS pipeline: operational model derivation, state projections,
validation, and coverage computation.
"""

from profiler.tools.operational_model_deriver import _cluster_tabs_into_entities
from profiler.tools.pipeline_state import (
    DeepProfileIndex,
    DiscoveryState,
    DomainKnowledge,
    PipelineState,
)
from profiler.tools.validation_framework import ValidationRecord

# ---------------------------------------------------------------------------
# Realistic farm profiler artifacts (Python dicts, not files)
# ---------------------------------------------------------------------------

DISCOVERY_STATE = {
    "workbook_index": [
        {"tab_title": "Crop Planner 2025", "row_count": 120, "column_count": 6},
        {"tab_title": "Crop Planner 2026", "row_count": 100, "column_count": 6},
        {"tab_title": "Harvest Log", "row_count": 80, "column_count": 5},
        {"tab_title": "Inventory", "row_count": 200, "column_count": 6},
        {"tab_title": "Field Blocks", "row_count": 25, "column_count": 3},
    ],
    "broad_inventory": [],
}

DEEP_PROFILE_ENTRIES = [
    {
        "tab_title": "Crop Planner 2025",
        "columns": [
            {
                "header_label": "Crop",
                "null_rate": 0.0,
                "distinct_values": ["Corn", "Soy", "Wheat"],
            },
            {
                "header_label": "Variety",
                "null_rate": 0.05,
                "distinct_values": ["DKC63-33", "AG24-6", "SY Ovation"],
            },
            {
                "header_label": "Plant Date",
                "null_rate": 0.02,
                "distinct_values": ["2025-03-15", "2025-04-01", "2025-04-20"],
            },
            {
                "header_label": "Field Block",
                "null_rate": 0.0,
                "distinct_values": ["North 40", "River Bottom", "Home Place"],
            },
            {
                "header_label": "Quantity",
                "null_rate": 0.05,
                "distinct_values": ["100", "200", "150"],
            },
            {
                "header_label": "Status",
                "null_rate": 0.0,
                "distinct_values": ["Planned", "Planted", "Growing", "Harvested"],
            },
        ],
        "fk_candidates": [
            {"column": "Field Block", "target": "Field Blocks", "confidence": 0.85},
        ],
    },
    {
        "tab_title": "Crop Planner 2026",
        "columns": [
            {
                "header_label": "Crop",
                "null_rate": 0.0,
                "distinct_values": ["Corn", "Soy", "Wheat"],
            },
            {
                "header_label": "Variety",
                "null_rate": 0.05,
                "distinct_values": ["DKC63-33", "AG24-6", "SY Ovation"],
            },
            {
                "header_label": "Plant Date",
                "null_rate": 0.02,
                "distinct_values": ["2026-03-20", "2026-04-05", "2026-04-25"],
            },
            {
                "header_label": "Field Block",
                "null_rate": 0.0,
                "distinct_values": ["North 40", "River Bottom", "Home Place"],
            },
            {
                "header_label": "Quantity",
                "null_rate": 0.05,
                "distinct_values": ["120", "220", "160"],
            },
            {
                "header_label": "Status",
                "null_rate": 0.0,
                "distinct_values": ["Planned", "Planted"],
            },
        ],
        "fk_candidates": [
            {"column": "Field Block", "target": "Field Blocks", "confidence": 0.85},
        ],
    },
    {
        "tab_title": "Harvest Log",
        "columns": [
            {
                "header_label": "Crop",
                "null_rate": 0.0,
                "distinct_values": ["Corn", "Soy", "Wheat"],
            },
            {
                "header_label": "Harvest Date",
                "null_rate": 0.10,
                "distinct_values": ["2025-09-15", "2025-10-01", "2025-10-20"],
            },
            {
                "header_label": "Field Block",
                "null_rate": 0.0,
                "distinct_values": ["North 40", "River Bottom", "Home Place"],
            },
            {
                "header_label": "Quantity",
                "null_rate": 0.05,
                "distinct_values": ["95", "180", "210"],
            },
            {
                "header_label": "Grade",
                "null_rate": 0.15,
                "distinct_values": ["#1", "#2", "Feed"],
            },
        ],
        "fk_candidates": [
            {"column": "Crop", "target": "Crop Planner 2025", "confidence": 0.60},
        ],
    },
    {
        "tab_title": "Inventory",
        "columns": [
            {
                "header_label": "Item",
                "null_rate": 0.0,
                "distinct_values": ["Seed", "Fertilizer", "Herbicide"],
            },
            {
                "header_label": "Quantity",
                "null_rate": 0.02,
                "distinct_values": ["50", "200", "500"],
            },
            {
                "header_label": "Unit",
                "null_rate": 0.0,
                "distinct_values": ["bags", "gallons", "lbs"],
            },
            {
                "header_label": "Location",
                "null_rate": 0.05,
                "distinct_values": ["Barn A", "Shed 2", "Bin 3"],
            },
            {
                "header_label": "Adjustment Date",
                "null_rate": 0.15,
                "distinct_values": ["2025-01-15", "2025-03-01", "2025-06-10"],
            },
            {
                "header_label": "Quantity on Date",
                "null_rate": 0.18,
                "distinct_values": ["2025-01-15", "2025-03-01", "2025-06-10"],
            },
        ],
        "fk_candidates": [],
    },
    {
        "tab_title": "Field Blocks",
        "columns": [
            {
                "header_label": "Block Name",
                "null_rate": 0.0,
                "distinct_values": ["North 40", "River Bottom", "Home Place"],
            },
            {
                "header_label": "Acreage",
                "null_rate": 0.0,
                "distinct_values": ["40", "60", "80"],
            },
            {
                "header_label": "Soil Type",
                "null_rate": 0.0,
                "distinct_values": ["Clay Loam", "Sandy Loam", "Silt"],
            },
        ],
        "fk_candidates": [],
    },
]

DOMAIN_KNOWLEDGE = {
    "domain": "farm",
    "description": "Row-crop farming operation",
    "vocabulary": {
        "operational": ["planting", "harvest", "inventory management"],
        "reference": ["field blocks", "crop varieties"],
        "support": ["supplies", "equipment"],
        "derived": ["yield analysis", "profitability"],
    },
    "year_scope": {
        "active": [2025, 2026],
        "archived": [2024],
        "forward": [2027],
    },
    "deduplication": {
        "strategy": "latest_year",
        "exceptions": [],
    },
    "entities": [],
    "glossary": {},
    "scope_notes": "Integration test with synthetic farm data",
}


def _build_pipeline_state(tmp_path) -> PipelineState:
    """Build a fully-configured PipelineState with farm profiler artifacts.

    Args:
        tmp_path: Pytest temporary path for checkpoint output.

    Returns:
        PipelineState configured with discovery, deep profiles, and
        domain knowledge populated.
    """
    ps = PipelineState(
        discovery=DiscoveryState(
            source_tree=None,
            workbook_index=list(DISCOVERY_STATE["workbook_index"]),
            broad_inventory=[],
            shortlist=None,
            approved_tabs=None,
        ),
        deep_profile_index=DeepProfileIndex(entries=list(DEEP_PROFILE_ENTRIES)),
        domain_knowledge=DomainKnowledge(
            domain=DOMAIN_KNOWLEDGE["domain"],
            description=DOMAIN_KNOWLEDGE["description"],
            vocabulary=dict(DOMAIN_KNOWLEDGE["vocabulary"]),
            year_scope=dict(DOMAIN_KNOWLEDGE["year_scope"]),
            deduplication=dict(DOMAIN_KNOWLEDGE["deduplication"]),
            entities=list(DOMAIN_KNOWLEDGE["entities"]),
            glossary=dict(DOMAIN_KNOWLEDGE["glossary"]),
            scope_notes=DOMAIN_KNOWLEDGE["scope_notes"],
        ),
    )
    ps.configure(out_dir=tmp_path)
    return ps


def _run_full_pipeline(ps: PipelineState) -> PipelineState:
    """Run the full BPRS pipeline on the given PipelineState.

    Executes derivation, all state projections, and validation.

    Args:
        ps: A configured PipelineState with profiler artifacts.

    Returns:
        The same PipelineState with operational model, projections,
        and coverage report populated.
    """
    ps.derive_operational_model()
    ps.derive_state_projections("schema_contract")
    ps.derive_state_projections("test_scaffold")
    ps.derive_state_projections("doc_scaffold")

    # Manually record a clean validation record (the framework
    # does not auto-create one).
    ps.validation_record = ValidationRecord(
        reviewed_by="integration_test",
        reviewed_with="test_farm_bprs_integration",
        date="2025-01-01",
        approvals=[],
        coverage={},
    )

    ps.validate_operational_model()
    return ps


class TestFarmBPRSIntegration:
    """Integration test suite exercising the full BPRS pipeline with
    realistic farm profiler artifacts.
    """

    def test_full_pipeline_runs_without_error(self, tmp_path):
        """All pipeline phases complete without raising exceptions."""
        ps = _build_pipeline_state(tmp_path)
        _run_full_pipeline(ps)

        assert ps.operational_model is not None
        assert ps.schema_contract is not None
        assert ps.test_scaffold is not None
        assert ps.doc_scaffold is not None
        assert ps.coverage_report is not None

    def test_crop_planner_tabs_cluster(self, tmp_path):
        """Crop Planner 2025 and 2026 cluster into the same entity
        (Jaccard similarity > 0.50).
        """
        ps = _build_pipeline_state(tmp_path)

        # Build the tabs list the same way the deriver does.
        tabs = [
            {
                "tab_title": str(entry.get("tab_title") or ""),
                "columns": [
                    col.get("header_label") for col in (entry.get("columns") or [])
                ],
            }
            for entry in DEEP_PROFILE_ENTRIES
        ]
        clusters = _cluster_tabs_into_entities(tabs)

        # Find the cluster containing "Crop Planner 2025"
        crop_cluster = None
        for cluster in clusters:
            if "Crop Planner 2025" in cluster.get("tabs", []):
                crop_cluster = cluster
                break

        assert crop_cluster is not None, (
            f"No cluster found containing Crop Planner 2025; got clusters: {clusters}"
        )
        cluster_tabs = crop_cluster["tabs"]
        assert "Crop Planner 2026" in cluster_tabs, (
            f"Crop Planner 2026 not in same cluster as Crop Planner 2025; "
            f"cluster tabs: {cluster_tabs}"
        )

    def test_events_preserve_farm_tab_context(self, tmp_path):
        """Every event's sourced_from references a real tab name
        (never 'unknown').
        """
        ps = _build_pipeline_state(tmp_path)
        _run_full_pipeline(ps)

        assert len(ps.operational_model.events) >= 1
        for event in ps.operational_model.events:
            for source in event.sourced_from:
                tab_name = source.get("tab", "")
                assert tab_name != "unknown", (
                    f"Event '{event.id}' has sourced_from tab 'unknown'; "
                    f"full sourced_from: {event.sourced_from}"
                )
                # Each tab name should match a known profiled tab.
                known_tabs = {entry["tab_title"] for entry in DEEP_PROFILE_ENTRIES}
                assert tab_name in known_tabs, (
                    f"Event '{event.id}' sourced from '{tab_name}', "
                    f"which is not in profiled tabs: {known_tabs}"
                )

    def test_derives_quantity_invariant(self, tmp_path):
        """At least one quantity-related invariant is derived from
        the operational model.
        """
        ps = _build_pipeline_state(tmp_path)
        _run_full_pipeline(ps)

        quantity_invariants = [
            inv
            for inv in ps.operational_model.invariants
            if "quantity" in inv.id.lower()
        ]
        assert len(quantity_invariants) >= 1, (
            f"No quantity-related invariants found among: "
            f"{[inv.id for inv in ps.operational_model.invariants]}"
        )

    def test_derives_temporal_events(self, tmp_path):
        """At least 2 temporal events are detected from date-like columns."""
        ps = _build_pipeline_state(tmp_path)
        _run_full_pipeline(ps)

        temporal_keywords = {"date", "time", "timestamp", "log", "at"}
        temporal_events = [
            event
            for event in ps.operational_model.events
            if any(kw in event.id.lower() for kw in temporal_keywords)
        ]
        assert len(temporal_events) >= 2, (
            f"Expected at least 2 temporal events, got {len(temporal_events)}: "
            f"{[event.id for event in ps.operational_model.events]}"
        )

    def test_schema_contract_has_tables(self, tmp_path):
        """Schema contract contains a tables list with at least 2 entries."""
        ps = _build_pipeline_state(tmp_path)
        _run_full_pipeline(ps)

        assert ps.schema_contract is not None
        tables = ps.schema_contract.get("tables") or []
        assert len(tables) >= 2, (
            f"Expected at least 2 schema contract tables, got {len(tables)}: {tables}"
        )

    def test_test_scaffold_is_valid_python(self, tmp_path):
        """The test_scaffold string compiles as valid Python."""
        ps = _build_pipeline_state(tmp_path)
        _run_full_pipeline(ps)

        assert ps.test_scaffold is not None
        # Verify it compiles without syntax errors.
        compile(ps.test_scaffold, "<test_scaffold>", "exec")

    def test_doc_scaffold_has_farm_sections(self, tmp_path):
        """Doc scaffold contains expected document sections:
        Capabilities, Events, Workflows.
        """
        ps = _build_pipeline_state(tmp_path)
        _run_full_pipeline(ps)

        assert ps.doc_scaffold is not None
        required_sections = ["Capabilities", "Events", "Workflows"]
        for section in required_sections:
            assert section in ps.doc_scaffold, (
                f"Doc scaffold missing section '{section}'. "
                f"Available sections: {[s for s in ['Capabilities', 'Events', 'Workflows'] if s in ps.doc_scaffold]}"
            )

    def test_coverage_report_acceptable(self, tmp_path):
        """Overall coverage (average of all four dimensions) >= 50%."""
        ps = _build_pipeline_state(tmp_path)
        _run_full_pipeline(ps)

        assert ps.coverage_report is not None
        dimensions = [
            ps.coverage_report.data_coverage,
            ps.coverage_report.workflow_coverage,
            ps.coverage_report.event_coverage,
            ps.coverage_report.invariant_coverage,
        ]
        average_coverage = sum(dimensions) / len(dimensions)
        assert average_coverage >= 0.50, (
            f"Average coverage {average_coverage:.2%} below 50% threshold; "
            f"dimensions: data={ps.coverage_report.data_coverage:.2%}, "
            f"workflow={ps.coverage_report.workflow_coverage:.2%}, "
            f"event={ps.coverage_report.event_coverage:.2%}, "
            f"invariant={ps.coverage_report.invariant_coverage:.2%}"
        )

    def test_validation_record_no_errors(self, tmp_path):
        """Validation record is populated without errors.

        Asserts the record exists and that no blocking issues were
        recorded (approvals list is non-negative / empty).
        """
        ps = _build_pipeline_state(tmp_path)
        _run_full_pipeline(ps)

        assert ps.validation_record is not None, "Validation record was not created."
        assert ps.validation_record.reviewed_by == "integration_test"
        # Verify the pipeline ran cleanly — no failed approvals.
        for approval in ps.validation_record.approvals:
            assert approval.get("outcome") != "failed", (
                f"Approval {approval} recorded a failure outcome."
            )
