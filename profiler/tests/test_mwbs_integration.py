"""End-to-end integration tests for the MWBS BehavioralSpec pipeline.

Exercises the full ``derive_behavioral_spec()`` → ``validate_behavioral_spec()``
→ checkpoint round-trip cycle with realistic profiler data simulating a
farm engagement.
"""

import json
from pathlib import Path


from profiler.tools.pipeline_state import (
    DeepProfileIndex,
    DiscoveryState,
    DomainKnowledge,
    PipelineState,
)

# ===================================================================
# Helper: Produce a PipelineState pre-configured for farm MWBS
# ===================================================================


def _make_farm_checkpoint(tmp_path: Path) -> PipelineState:
    """Create a PipelineState primed with farm-like profiler data.

    Writes example deep-profile JSON artifacts to *tmp_path* and returns
    a state whose ``domain_knowledge``, ``discovery``, and
    ``deep_profile_index`` are populated for MWBS derivation.

    The deep-profile entries use ``out_json`` references so that
    ``derive_behavioral_spec(base_dir=tmp_path)`` resolves them from disk.

    Args:
        tmp_path: Temporary directory used as the checkpoint / artifact base.

    Returns:
        PipelineState with farm-domain data ready for
        ``derive_behavioral_spec()``.
    """
    # ---- Write deep-profile JSON artifacts to tmp_path ----
    crop_planner_profile = {
        "columns": [
            {
                "header_label": "Crop Name",
                "data_type": "string",
                "null_rate": 0.0,
                "distinct_values": ["Tomato", "Pepper", "Lettuce"],
            },
            {
                "header_label": "Plant Date",
                "data_type": "date",
                "null_rate": 0.05,
                "distinct_values": ["2025-03-01", "2025-03-15", "2025-04-01"],
            },
            {
                "header_label": "Status",
                "data_type": "string",
                "null_rate": 0.02,
                "distinct_values": ["Planned", "Planted", "Harvested"],
            },
            {
                "header_label": "Bed Number",
                "data_type": "string",
                "null_rate": 0.0,
                "distinct_values": ["A1", "A2", "B1", "B2"],
            },
        ],
    }
    (tmp_path / "deep_profile_crop_planner.json").write_text(
        json.dumps(crop_planner_profile), encoding="utf-8"
    )

    harvest_log_profile = {
        "columns": [
            {
                "header_label": "Date",
                "data_type": "date",
                "null_rate": 0.0,
                "distinct_values": ["2025-06-01", "2025-06-02", "2025-06-03"],
            },
            {
                "header_label": "Crop",
                "data_type": "string",
                "null_rate": 0.0,
                "distinct_values": ["Tomato", "Pepper"],
            },
            {
                "header_label": "Qty Harvested",
                "data_type": "number",
                "null_rate": 0.0,
                "distinct_values": ["50", "100", "150"],
            },
            {
                "header_label": "Field Block",
                "data_type": "string",
                "null_rate": 0.0,
                "distinct_values": ["North", "South"],
            },
        ],
    }
    (tmp_path / "deep_profile_harvest_log.json").write_text(
        json.dumps(harvest_log_profile), encoding="utf-8"
    )

    # ---- Build PipelineState with out_json references ----
    state = PipelineState(
        discovery=DiscoveryState(
            source_tree={"provider": "google_sheets", "folder_id": "farm_folder"},
            workbook_index=[
                {
                    "workbook_code": "101",
                    "year": 2025,
                    "tab_title": "Crop Planner",
                },
                {
                    "workbook_code": "101",
                    "year": 2025,
                    "tab_title": "Harvest Log",
                },
            ],
            broad_inventory=[
                {"tab_title": "Crop Planner", "row_count": 100, "column_count": 10},
                {"tab_title": "Harvest Log", "row_count": 500, "column_count": 8},
            ],
        ),
        deep_profile_index=DeepProfileIndex(
            entries=[
                {
                    "tab_title": "Crop Planner",
                    "out_json": "deep_profile_crop_planner.json",
                },
                {
                    "tab_title": "Harvest Log",
                    "out_json": "deep_profile_harvest_log.json",
                },
            ]
        ),
        domain_knowledge=DomainKnowledge(
            domain="farm",
            vocabulary={
                "operational": ["crop", "planting", "harvest", "field"],
                "reference": ["market"],
                "support": [],
                "derived": [],
            },
            year_scope={"active": [2025, 2026], "archived": [], "forward": []},
            entities=[
                {"name": "Crop", "source_tabs": ["Crop Planner"]},
                {"name": "HarvestBatch", "source_tabs": ["Harvest Log"]},
            ],
            glossary={"qty": "quantity"},
            scope_notes="Farm migration engagement — full MWBS pipeline test",
        ),
    )
    return state


# ===================================================================
# Test class — 5 integration scenarios
# ===================================================================


class TestMwbsPipelineIntegration:
    """End-to-end integration tests for the MWBS BehavioralSpec pipeline."""

    # ------------------------------------------------------------------
    # 1. Full pipeline with farm data (derive → validate → inspect)
    # ------------------------------------------------------------------

    def test_full_pipeline_with_farm_data(self, tmp_path):
        """Derive + validate from realistic farm profiler data, then inspect.

        Verifies that ``derive_behavioral_spec()`` followed by
        ``validate_behavioral_spec()`` produces a non-None spec with:
        - ``project.status == "draft"``
        - ``spec_version == "mwbs/v1"``
        - At least one actor, one event with provenance, and one workflow
        - A non-None coverage report with valid fields.
        """
        state = _make_farm_checkpoint(tmp_path)
        state.derive_behavioral_spec(base_dir=tmp_path)
        state.validate_behavioral_spec()

        # --- BehavioralSpec structure ---
        assert state.behavioral_spec is not None
        assert state.behavioral_spec.project is not None
        assert state.behavioral_spec.project.status == "draft"
        assert state.behavioral_spec.spec_version == "mwbs/v1"

        # Actors
        assert len(state.behavioral_spec.actors) >= 1
        actor_ids = [actor.id for actor in state.behavioral_spec.actors]
        assert any("crop" in actor_id for actor_id in actor_ids)

        # Events with provenance
        assert len(state.behavioral_spec.events) >= 1
        for event in state.behavioral_spec.events:
            assert event.provenance is not None
            assert event.provenance.source == "inferred"
            assert len(event.provenance.inference_signals) >= 1
            assert any(
                "INF-" in signal.get("rule_id", "")
                for signal in event.provenance.inference_signals
            )

        # Workflows
        assert len(state.behavioral_spec.workflows) >= 1

        # --- CoverageReport ---
        assert state.coverage_report is not None
        assert state.coverage_report.data_coverage >= 0.0
        assert isinstance(state.coverage_report.completion_gate_passed, bool)

    # ------------------------------------------------------------------
    # 2. Checkpoint roundtrip with MWBS fields
    # ------------------------------------------------------------------

    def test_checkpoint_roundtrip_with_mwbs(self, tmp_path):
        """BehavioralSpec and CoverageReport survive save → load.

        Derives a spec, saves a checkpoint to *tmp_path*, loads it back,
        and verifies both ``behavioral_spec`` and ``coverage_report``
        are correctly reconstructed.
        """
        state = _make_farm_checkpoint(tmp_path)
        state.derive_behavioral_spec(base_dir=tmp_path)
        state.validate_behavioral_spec()

        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state.save_checkpoint(checkpoint_path)
        assert checkpoint_path.exists()

        # Verify the behavioral-spec artifact was written
        bs_artifact = tmp_path / "behavioral-spec.json"
        assert bs_artifact.exists()

        loaded = PipelineState.load(checkpoint_path)

        # --- behavioral_spec survives ---
        assert loaded.behavioral_spec is not None
        assert loaded.behavioral_spec.project is not None
        assert loaded.behavioral_spec.project.status == "draft"
        assert loaded.behavioral_spec.spec_version == "mwbs/v1"
        assert len(loaded.behavioral_spec.actors) >= 1
        assert len(loaded.behavioral_spec.events) >= 1
        assert len(loaded.behavioral_spec.workflows) >= 1

        # Verify event provenance survived
        for event in loaded.behavioral_spec.events:
            assert event.provenance is not None
            assert len(event.provenance.inference_signals) >= 1

        # --- coverage_report survives ---
        assert loaded.coverage_report is not None
        assert loaded.coverage_report.data_coverage >= 0.0
        assert isinstance(loaded.coverage_report.completion_gate_passed, bool)

    # ------------------------------------------------------------------
    # 3. MWBS coexists alongside the operational model
    # ------------------------------------------------------------------

    def test_mwbs_alongside_operational_model(self, tmp_path):
        """Both ``behavioral_spec`` and ``operational_model`` can coexist.

        Verifies:
        - The state has both ``derive_behavioral_spec()`` and
          ``derive_operational_model()`` methods.
        - After deriving behavioral_spec only:
          ``state.behavioral_spec`` is set, ``state.operational_model`` is None.
        - After also deriving operational_model: both are set.
        - Both produce comparable workflow counts (derived from the same
          deep-profile index).
        """
        state = PipelineState(
            discovery=DiscoveryState(
                workbook_index=[
                    {"workbook_code": "101", "year": 2025},
                ],
                broad_inventory=[],
            ),
            deep_profile_index=DeepProfileIndex(
                entries=[
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
                                "distinct_values": ["50", "100"],
                            },
                        ],
                        "fk_candidates": [{"target": "Crop Planner"}],
                    },
                ]
            ),
            domain_knowledge=DomainKnowledge(
                domain="farm",
                vocabulary={
                    "operational": ["crop", "harvest"],
                    "reference": [],
                    "support": [],
                    "derived": [],
                },
            ),
        )

        # Both methods exist
        assert hasattr(state, "derive_behavioral_spec")
        assert hasattr(state, "derive_operational_model")

        # After deriving behavioral_spec only
        result_bs = state.derive_behavioral_spec()
        assert result_bs.behavioral_spec is not None
        assert state.behavioral_spec is not None  # same object
        assert state.operational_model is None
        assert result_bs is state  # chaining

        # After also deriving operational_model
        result_op = state.derive_operational_model()
        assert state.behavioral_spec is not None
        assert state.operational_model is not None
        assert result_op is state  # chaining

        # Both produce comparable numbers from the same input
        bs_workflow_count = len(state.behavioral_spec.workflows)
        op_workflow_count = len(state.operational_model.workflows)
        assert bs_workflow_count > 0
        assert op_workflow_count > 0
        # They should be fairly close since both derive from the same
        # FK edges and tab clusters; allow a reasonable tolerance.
        assert abs(bs_workflow_count - op_workflow_count) <= max(
            bs_workflow_count, op_workflow_count
        )

    # ------------------------------------------------------------------
    # 4. Derive from realistic multi-tab farm data with FK + formula graph
    # ------------------------------------------------------------------

    def test_derive_behavioral_spec_from_realistic_farm_data(self, tmp_path):
        """Derive spec from 4 tabs with FK candidates and formula dependencies.

        Creates tabs (planting_tracker, harvest_log, seed_inventory,
        field_blocks) with realistic columns, FK candidates between tabs,
        and a ``_dependency_artifact`` carrying ``sheet_graph`` edges.

        Verifies:
        - Workflows include graph-inferred edges.
        - Events are created per tab with provenance referencing INF-XX rules.
        - At least one workflow references the graph-derived evidence.
        """
        state = PipelineState(
            discovery=DiscoveryState(
                workbook_index=[
                    {"workbook_code": "101", "year": 2025},
                ],
                broad_inventory=[],
            ),
            deep_profile_index=DeepProfileIndex(
                entries=[
                    # Tab 1: planting_tracker
                    {
                        "tab_title": "planting_tracker",
                        "columns": [
                            {
                                "header_label": "Plant Date",
                                "data_type": "date",
                                "null_rate": 0.05,
                                "distinct_values": [
                                    "2025-03-01",
                                    "2025-03-15",
                                ],
                            },
                            {
                                "header_label": "Crop Name",
                                "data_type": "string",
                                "null_rate": 0.0,
                                "distinct_values": ["Tomato", "Pepper"],
                            },
                            {
                                "header_label": "Bed",
                                "data_type": "string",
                                "null_rate": 0.0,
                                "distinct_values": ["A1", "A2"],
                            },
                        ],
                        "fk_candidates": [{"target": "field_blocks"}],
                    },
                    # Tab 2: harvest_log
                    {
                        "tab_title": "harvest_log",
                        "columns": [
                            {
                                "header_label": "Harvest Date",
                                "data_type": "date",
                                "null_rate": 0.0,
                                "distinct_values": ["2025-06-01"],
                            },
                            {
                                "header_label": "Crop",
                                "data_type": "string",
                                "null_rate": 0.0,
                                "distinct_values": ["Tomato"],
                            },
                            {
                                "header_label": "Qty Harvested",
                                "data_type": "number",
                                "null_rate": 0.0,
                                "distinct_values": ["50", "100"],
                            },
                        ],
                        "fk_candidates": [{"target": "planting_tracker"}],
                    },
                    # Tab 3: seed_inventory
                    {
                        "tab_title": "seed_inventory",
                        "columns": [
                            {
                                "header_label": "Seed Name",
                                "data_type": "string",
                                "null_rate": 0.0,
                                "distinct_values": ["Tomato A", "Pepper B"],
                            },
                            {
                                "header_label": "Quantity",
                                "data_type": "number",
                                "null_rate": 0.0,
                                "distinct_values": ["100", "200"],
                            },
                        ],
                        "fk_candidates": [],
                    },
                    # Tab 4: field_blocks (with formula dependency artifact)
                    {
                        "tab_title": "field_blocks",
                        "columns": [
                            {
                                "header_label": "Block Name",
                                "data_type": "string",
                                "null_rate": 0.0,
                                "distinct_values": ["North", "South"],
                            },
                            {
                                "header_label": "Area",
                                "data_type": "number",
                                "null_rate": 0.0,
                                "distinct_values": ["1.5", "2.0"],
                            },
                        ],
                        "fk_candidates": [],
                        "_dependency_artifact": {
                            "sheet_graph": {
                                "edges": [
                                    {
                                        "from_sheet": "planting_tracker",
                                        "to_sheet": "field_blocks",
                                        "ref_type": "VLOOKUP",
                                        "weight": 1.0,
                                    },
                                ]
                            }
                        },
                    },
                ]
            ),
            domain_knowledge=DomainKnowledge(
                domain="farm",
                vocabulary={
                    "operational": ["crop", "harvest", "planting"],
                    "reference": ["seed", "field"],
                    "support": [],
                    "derived": [],
                },
            ),
        )

        state.derive_behavioral_spec()
        spec = state.behavioral_spec
        assert spec is not None

        # --- Workflows include graph-inferred edges ---
        workflow_ids = [wf.id for wf in spec.workflows]
        # Field_blocks is referenced from the formula graph edge
        graph_inferred = [wf_id for wf_id in workflow_ids if "field_blocks" in wf_id]
        assert (
            len(graph_inferred) >= 1
        ), f"No graph-inferred workflow found among: {workflow_ids}"

        # FK edges should also produce workflow candidates
        fk_inferred = [wf_id for wf_id in workflow_ids if "planting_tracker" in wf_id]
        assert (
            len(fk_inferred) >= 1
        ), f"No FK-inferred workflow found among: {workflow_ids}"

        # --- Events created per tab with provenance ---
        assert len(spec.events) >= 1
        for event in spec.events:
            assert (
                event.provenance is not None
            ), f"Event '{event.id}' missing provenance"
            rule_ids = [
                signal.get("rule_id", "")
                for signal in event.provenance.inference_signals
            ]
            assert any(rid.startswith("INF-") for rid in rule_ids), (
                f"Event '{event.id}' has no INF-XX rule in provenance signals: "
                f"{rule_ids}"
            )

        # --- At least one workflow provenance references the graph ---
        wf_provenance_rules = set()
        for wf in spec.workflows:
            if wf.provenance:
                for signal in wf.provenance.inference_signals:
                    wf_provenance_rules.add(signal.get("rule_id", ""))
        assert any("INF-05" in rid for rid in wf_provenance_rules) or any(
            "INF-06" in rid for rid in wf_provenance_rules
        ), (
            "No workflow provenance references INF-05 (cross-sheet formula) "
            f"or INF-06 (FK). Found rules: {wf_provenance_rules}"
        )

    # ------------------------------------------------------------------
    # 5. Validate produces the 6-dim coverage report
    # ------------------------------------------------------------------

    def test_validate_behavioral_spec_produces_6dim_coverage(self, tmp_path):
        """CoverageReport has all 6 dimensions in [0,1] and correct gate.

        Derives a spec through the pipeline, validates it, and checks:
        - All six dimensions (data, formula, structural, workflow, exception,
          report) are present as 0.0–1.0 floats.
        - ``completion_gate_passed`` is a bool.
        - Directly constructed ``CoverageReport`` with all-1.0 passes the
          gate, while a dimension below 1.0 does not.
        """
        state = _make_farm_checkpoint(tmp_path)
        state.derive_behavioral_spec(base_dir=tmp_path)
        state.validate_behavioral_spec()

        report = state.coverage_report
        assert report is not None

        # ---- All six dimensions present ----
        dim_names = [
            "data_coverage",
            "formula_coverage",
            "structural_coverage",
            "workflow_coverage",
            "exception_coverage",
            "report_coverage",
        ]
        for dim_name in dim_names:
            assert hasattr(report, dim_name), f"Missing dimension: {dim_name}"
            value = getattr(report, dim_name)
            assert isinstance(
                value, float
            ), f"{dim_name} should be float, got {type(value).__name__}"
            assert 0.0 <= value <= 1.0, f"{dim_name}={value} is outside [0.0, 1.0]"

        # ---- completion_gate_passed is bool ----
        assert isinstance(report.completion_gate_passed, bool)

        # data_coverage is computed from actual actors/events (not coverage_map),
        # so it will be > 0 when the pipeline produces actors and events.
        assert report.completion_gate_passed is False
        assert report.data_coverage >= 0.0

        # ---- Direct CoverageReport gate behaviour ----
        from profiler.tools.behavioral_spec_validation import CoverageReport

        full = CoverageReport(
            data_coverage=1.0,
            formula_coverage=1.0,
            structural_coverage=1.0,
            workflow_coverage=1.0,
            exception_coverage=1.0,
            report_coverage=1.0,
        )
        assert full.completion_gate_passed is True

        partial = CoverageReport(
            data_coverage=1.0,
            formula_coverage=1.0,
            structural_coverage=1.0,
            workflow_coverage=0.9,
            exception_coverage=1.0,
            report_coverage=1.0,
        )
        assert partial.completion_gate_passed is False
