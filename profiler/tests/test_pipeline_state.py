"""Tests for PipelineState — dataclass, checkpoint I/O, phase methods, artifacts."""

import tomllib
from pathlib import Path

import pytest

from profiler.tools.pipeline_state import (
    DecisionRecord,
    DeepProfileIndex,
    DiscoveryState,
    DomainKnowledge,
    PipelineState,
)


# ---------------------------------------------------------------------------
# 1. Dataclass defaults
# ---------------------------------------------------------------------------


class TestDataclassDefaults:
    """Verify default field values for each dataclass."""

    def test_pipeline_state_defaults(self):
        """Fresh PipelineState has version="0.0.9" and all sub-objects."""
        state = PipelineState()
        assert state.version == "0.0.9"
        assert isinstance(state.discovery, DiscoveryState)
        assert isinstance(state.deep_profile_index, DeepProfileIndex)
        assert isinstance(state.domain_knowledge, DomainKnowledge)
        assert state.schema_contract is None
        assert state.interaction_contract is None
        assert state.decisions == []

    def test_discovery_state_empty(self):
        """All DiscoveryState fields start as empty or None."""
        ds = DiscoveryState()
        assert ds.source_tree is None
        assert ds.workbook_index == []
        assert ds.broad_inventory == []
        assert ds.shortlist is None
        assert ds.approved_tabs is None

    def test_discovery_state_fields(self):
        """All DiscoveryState fields accept values."""
        ds = DiscoveryState(
            source_tree={"provider": "google_sheets"},
            workbook_index=[{"workbook_code": "101", "year": 2023}],
            broad_inventory=[{"tab": "Sheet1", "rows": 100}],
            shortlist=[{"tab": "Sheet1", "score": 0.9}],
            approved_tabs={"101": ["Crop Planner"]},
        )
        assert ds.source_tree == {"provider": "google_sheets"}
        assert ds.workbook_index == [{"workbook_code": "101", "year": 2023}]
        assert ds.broad_inventory == [{"tab": "Sheet1", "rows": 100}]
        assert ds.shortlist == [{"tab": "Sheet1", "score": 0.9}]
        assert ds.approved_tabs == {"101": ["Crop Planner"]}

    def test_domain_knowledge_fields(self):
        """All DomainKnowledge fields accept values."""
        dk = DomainKnowledge(
            domain="farm_management",
            vocabulary={
                "operational": ["crop"],
                "reference": ["market"],
                "support": [],
                "derived": [],
            },
            year_scope={
                "active": [2025, 2026],
                "archived": [2023],
                "forward": [],
            },
            deduplication={
                "strategy": "latest_year",
                "exceptions": [],
            },
            entities=[{"name": "Season", "source_tabs": ["Crop Planner"]}],
            glossary={"qty": "quantity"},
            scope_notes="Focus on 2025",
        )
        assert dk.domain == "farm_management"
        assert dk.vocabulary["operational"] == ["crop"]
        assert dk.year_scope["active"] == [2025, 2026]
        assert dk.deduplication["strategy"] == "latest_year"
        assert len(dk.entities) == 1
        assert dk.glossary["qty"] == "quantity"
        assert dk.scope_notes == "Focus on 2025"

    def test_deep_profile_index_defaults(self):
        """DeepProfileIndex starts with an empty entries list."""
        dpi = DeepProfileIndex()
        assert dpi.entries == []


# ---------------------------------------------------------------------------
# 2. DecisionRecord tests
# ---------------------------------------------------------------------------


class TestDecisionRecord:
    """Verify DecisionRecord dataclass and PipelineState.decisions."""

    def test_empty_decisions_default(self):
        """Fresh PipelineState has empty decisions list."""
        state = PipelineState()
        assert state.decisions == []

    def test_record_decision_appends(self):
        """Calling record_decision() adds to the decisions list."""
        state = PipelineState()
        state.record_decision(
            decision_id="sel_001",
            phase="score_and_select",
            description="Selected Crop Planner tab for deep profiling",
            outcome="approved",
        )
        assert len(state.decisions) == 1

    def test_record_decision_returns_record(self):
        """record_decision() returns the DecisionRecord with timestamp."""
        state = PipelineState()
        record = state.record_decision(
            decision_id="sel_002",
            phase="derive_contracts",
            description="Accepted schema contract",
            outcome="approved",
            confidence=0.95,
        )
        assert isinstance(record, DecisionRecord)
        assert record.decision_id == "sel_002"
        assert record.timestamp != ""  # timestamp is set
        assert record.phase == "derive_contracts"
        assert record.confidence == 0.95

    def test_decisions_survive_round_trip(self, tmp_path):
        """Decisions are preserved through save-checkpoint → load cycle."""
        state = PipelineState()
        state.record_decision(
            decision_id="sel_001",
            phase="score_and_select",
            description="Selected tabs",
            outcome="approved",
        )
        path = tmp_path / "pipeline-state.yaml"
        state.save_checkpoint(path)

        loaded = PipelineState.load(path)
        assert len(loaded.decisions) == 1
        assert loaded.decisions[0].decision_id == "sel_001"
        assert loaded.decisions[0].phase == "score_and_select"
        assert loaded.decisions[0].outcome == "approved"

    def test_decision_record_fields(self):
        """All DecisionRecord fields are stored correctly."""
        record = DecisionRecord(
            decision_id="dec_003",
            timestamp="2026-05-27T12:00:00+00:00",
            phase="deep_profile",
            description="Profiled sheet with 20 columns",
            outcome="approved",
            confidence=0.75,
            metadata={"column_count": 20, "tab_title": "Crop Planner"},
        )
        assert record.decision_id == "dec_003"
        assert record.timestamp == "2026-05-27T12:00:00+00:00"
        assert record.phase == "deep_profile"
        assert record.description == "Profiled sheet with 20 columns"
        assert record.outcome == "approved"
        assert record.confidence == 0.75
        assert record.metadata == {"column_count": 20, "tab_title": "Crop Planner"}


# ---------------------------------------------------------------------------
# 3. Checkpoint I/O
# ---------------------------------------------------------------------------


class TestCheckpointRoundTrip:
    """Verify save_checkpoint → load preserves state."""

    def test_empty_state_round_trip(self, tmp_path: Path):
        """An empty state saves and reloads as empty."""
        checkpoint = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.save_checkpoint(checkpoint)

        loaded = PipelineState.load(checkpoint)
        assert loaded.version == "0.0.9"
        assert loaded.discovery.source_tree == {}
        assert loaded.discovery.approved_tabs == {}
        assert loaded.domain_knowledge.domain == ""

    def test_approved_tabs_preserved(self, tmp_path: Path):
        """Human edits to approved_tabs survive round-trip."""
        checkpoint = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.discovery.approved_tabs = {
            "101": ["Crop Planner", "Field Record"],
            "501": ["Harvest Availability"],
        }
        state.save_checkpoint(checkpoint)

        loaded = PipelineState.load(checkpoint)
        assert loaded.discovery.approved_tabs == {
            "101": ["Crop Planner", "Field Record"],
            "501": ["Harvest Availability"],
        }

    def test_domain_knowledge_preserved(self, tmp_path: Path):
        """Domain knowledge round-trips through checkpoint."""
        checkpoint = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.domain_knowledge.domain = "farm_management"
        state.domain_knowledge.vocabulary = {
            "operational": ["crop", "harvest"],
            "reference": [],
            "support": [],
            "derived": [],
        }
        state.domain_knowledge.year_scope = {
            "active": [2025, 2026],
            "archived": [2023, 2024],
            "forward": [],
        }
        state.save_checkpoint(checkpoint)

        loaded = PipelineState.load(checkpoint)
        assert loaded.domain_knowledge.domain == "farm_management"
        assert loaded.domain_knowledge.vocabulary["operational"] == [
            "crop",
            "harvest",
        ]
        assert loaded.domain_knowledge.year_scope["active"] == [2025, 2026]

    def test_checkpoint_roundtrip_full(self, tmp_path):
        """Full PipelineState round-trips with all data intact."""
        state = PipelineState(
            version="0.0.9",
            discovery=DiscoveryState(
                source_tree={"provider": "google_sheets"},
                workbook_index=[{"workbook_code": "101", "year": 2023}],
            ),
            deep_profile_index=DeepProfileIndex(
                entries=[{"tab": "Crop Planner", "profiled": True}],
            ),
            domain_knowledge=DomainKnowledge(
                domain="test_domain",
                vocabulary={
                    "operational": ["test"],
                    "reference": [],
                    "support": [],
                    "derived": [],
                },
            ),
            schema_contract={"tables": []},
        )
        state.record_decision(
            decision_id="sel_001",
            phase="score_and_select",
            description="Selected Crop Planner tab for deep profiling",
            outcome="approved",
            confidence=0.85,
        )
        path = tmp_path / "pipeline-state.yaml"
        state.save_checkpoint(path)
        assert path.exists()

        loaded = PipelineState.load(path)
        assert loaded.version == "0.0.9"
        assert loaded.discovery.source_tree == {"provider": "google_sheets"}
        assert loaded.discovery.workbook_index == [
            {"workbook_code": "101", "year": 2023}
        ]
        assert loaded.deep_profile_index.entries == [
            {"tab": "Crop Planner", "profiled": True}
        ]
        assert loaded.domain_knowledge.domain == "test_domain"
        assert loaded.domain_knowledge.vocabulary == {
            "operational": ["test"],
            "reference": [],
            "support": [],
            "derived": [],
        }
        # schema_contract is now eagerly resolved from artifact
        assert loaded.schema_contract == {"tables": []}
        # decisions survive round-trip
        assert len(loaded.decisions) == 1
        assert loaded.decisions[0].decision_id == "sel_001"
        assert loaded.decisions[0].phase == "score_and_select"
        assert loaded.decisions[0].outcome == "approved"

    def test_missing_checkpoint_returns_empty_state(self, tmp_path: Path):
        """Loading a non-existent checkpoint returns an empty state."""
        checkpoint = tmp_path / "nonexistent.yaml"
        loaded = PipelineState.load(checkpoint)
        assert loaded.version == "0.0.9"
        assert loaded.discovery.approved_tabs is None


class TestLoadOrCreate:
    """Verify load_or_create behaviour."""

    def test_load_or_create_creates_fresh(self, tmp_path):
        """No existing checkpoint → fresh PipelineState from config JSON."""
        config_path = tmp_path / "config.json"
        config_path.write_text(
            '{"domain": "test_domain", "cohort_name": "test_cohort"}'
        )
        state = PipelineState.load_or_create(config_path=config_path)
        assert isinstance(state, PipelineState)
        assert state.version == "0.0.9"
        assert state.domain_knowledge.domain == "test_domain"
        assert state.discovery.source_tree is None

    def test_load_or_create_loads_existing(self, tmp_path):
        """Existing checkpoint → loads it (ignores config)."""
        config_path = tmp_path / "config.json"
        config_path.write_text('{"domain": "ignored_domain"}')

        original = PipelineState(
            domain_knowledge=DomainKnowledge(domain="checkpoint_domain"),
            discovery=DiscoveryState(source_tree={"provider": "coda"}),
        )
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        original.save_checkpoint(checkpoint_path)

        loaded = PipelineState.load_or_create(
            config_path=config_path,
            checkpoint_path=checkpoint_path,
        )
        assert loaded.domain_knowledge.domain == "checkpoint_domain"
        assert loaded.discovery.source_tree == {"provider": "coda"}

    def test_load_or_create_creates_new_when_missing(self, tmp_path: Path):
        """load_or_create returns a new state when file is missing."""
        checkpoint = tmp_path / "new.yaml"
        state = PipelineState.load_or_create(
            config_path=tmp_path / "nonexistent.json",
            checkpoint_path=checkpoint,
        )
        assert state.version == "0.0.9"
        assert not checkpoint.exists()

    def test_load_or_create_loads_existing_simple(self, tmp_path: Path):
        """load_or_create loads existing checkpoint when present."""
        config_path = tmp_path / "config.json"
        config_path.write_text('{"domain": "seed"}')

        checkpoint = tmp_path / "existing.yaml"
        original = PipelineState()
        original.discovery.approved_tabs = {"101": ["Crop Planner"]}
        original.save_checkpoint(checkpoint)

        loaded = PipelineState.load_or_create(
            config_path=config_path,
            checkpoint_path=checkpoint,
        )
        assert loaded.discovery.approved_tabs == {"101": ["Crop Planner"]}


# ---------------------------------------------------------------------------
# 3. Phase method guard clauses
# ---------------------------------------------------------------------------


class TestPhaseGuardClauses:
    """Verify each phase enforces ordering constraints."""

    def test_discover_requires_no_prior_discovery(self):
        """RuntimeError if source_tree already populated."""
        state = PipelineState(
            discovery=DiscoveryState(source_tree={"provider": "gsheets"})
        )
        with pytest.raises(RuntimeError, match="source_tree already populated"):
            state.discover()

    def test_score_and_select_requires_discovery(self):
        """RuntimeError if source_tree is empty."""
        state = PipelineState()
        with pytest.raises(
            RuntimeError, match="discover\\(\\) must run first"
        ):
            state.score_and_select()

    def test_score_and_select_requires_shortlist(self):
        """RuntimeError if shortlist is empty."""
        state = PipelineState(
            discovery=DiscoveryState(source_tree={})
        )
        with pytest.raises(RuntimeError, match="shortlist is None"):
            state.score_and_select()

    def test_deep_profile_requires_approved_tabs(self):
        """RuntimeError if approved_tabs is empty."""
        state = PipelineState(
            discovery=DiscoveryState(source_tree={})
        )
        with pytest.raises(RuntimeError, match="no approved_tabs"):
            state.deep_profile()

    def test_derive_contracts_requires_deep_profile(self):
        """RuntimeError if entries is empty."""
        state = PipelineState()
        with pytest.raises(
            RuntimeError, match="deep_profile must run first"
        ):
            state.derive_contracts()

    def test_phase_sequencing_happy_path(self):
        """Full phase order works without errors."""
        state = PipelineState()
        state.discover()
        state.score_and_select()
        state.deep_profile()
        state.deep_profile_index.entries.append(
            {"tab": "Crop Planner"}
        )
        state.derive_contracts()
        assert state.discovery.source_tree == {}
        assert state.discovery.approved_tabs == {}
        assert isinstance(state.deep_profile_index, DeepProfileIndex)
        assert state.schema_contract == {}
        assert state.interaction_contract == {}


# ---------------------------------------------------------------------------
# 4. YAML readability
# ---------------------------------------------------------------------------


class TestYamlReadability:
    """Saved YAML should be human-reviewable."""

    def test_checkpoint_yaml_human_readable(self, tmp_path):
        """Saved YAML uses block style with field names present."""
        state = PipelineState(
            discovery=DiscoveryState(
                source_tree={"provider": "google_sheets"},
                workbook_index=[{"workbook_code": "101"}],
            ),
            domain_knowledge=DomainKnowledge(domain="farm"),
        )
        path = tmp_path / "pipeline-state.yaml"
        state.save_checkpoint(path)

        raw = path.read_text()
        assert "version: " in raw
        assert "discovery:" in raw
        assert "domain_knowledge:" in raw
        assert "source_tree:" in raw
        assert "provider: google_sheets" in raw
        assert "workbook_index:" in raw
        assert "domain: farm" in raw

    def test_large_fields_externalized(self, tmp_path):
        """broad_inventory and shortlist are external to the YAML."""
        checkpoint = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.discovery.broad_inventory = [
            {"tab_title": "Crop Planner", "row_count": 100},
        ]
        state.discovery.shortlist = [
            {"tab_title": "Crop Planner", "score": 0.9},
        ]
        state.save_checkpoint(checkpoint)

        yaml_text = checkpoint.read_text()
        assert "_artifact" in yaml_text
        assert "pipeline-state-broad_inventory.json" in yaml_text


# ---------------------------------------------------------------------------
# 5. Domain context bridge
# ---------------------------------------------------------------------------


class TestDomainContextBridge:
    """DomainContext → DomainKnowledge conversion."""

    def test_domain_context_bridge(self):
        """from_domain_context preserves all fields."""
        from profiler.tools.domain_context import DomainContext as DC

        ctx = DC(
            domain="farm_management",
            description="Farm ops",
            year_scope=DC.YearScope(
                active=[2025, 2026],
                archived=[2023, 2024],
                forward=[2027],
            ),
            vocabulary=DC.VocabularyContext(
                operational=["crop", "planting"],
                reference=["market"],
                support=["index"],
                derived=["summary"],
            ),
            deduplication=DC.DeduplicationContext(
                strategy="latest_year",
                exceptions=[
                    {"tab_title": "Annual Budget"}
                ],
            ),
            entities=[
                {
                    "name": "Season",
                    "source_tabs": ["Crop Planner"],
                }
            ],
            glossary={"qty": "quantity"},
            scope_notes="Focus on 2025-2026",
        )

        dk = DomainKnowledge.from_domain_context(ctx)
        assert dk.domain == "farm_management"
        assert dk.year_scope == {
            "active": [2025, 2026],
            "archived": [2023, 2024],
            "forward": [2027],
        }
        assert dk.vocabulary == {
            "operational": ["crop", "planting"],
            "reference": ["market"],
            "support": ["index"],
            "derived": ["summary"],
        }
        assert dk.deduplication == {
            "strategy": "latest_year",
            "exceptions": [{"tab_title": "Annual Budget"}],
        }
        assert len(dk.entities) == 1
        assert dk.entities[0]["name"] == "Season"
        assert dk.glossary["qty"] == "quantity"
        assert dk.scope_notes == "Focus on 2025-2026"

    def test_from_domain_context_none(self):
        """from_domain_context(None) returns an empty instance."""
        dk = DomainKnowledge.from_domain_context(None)
        assert dk.domain == ""
        assert dk.vocabulary == {
            "operational": [],
            "reference": [],
            "support": [],
            "derived": [],
        }


# ---------------------------------------------------------------------------
# 6. Artifact references
# ---------------------------------------------------------------------------


class TestArtifactReferences:
    """Verify large data is externalized to JSON and resolved on load."""

    def test_broad_inventory_written_as_artifact(self, tmp_path: Path):
        """broad_inventory is externalized to a JSON artifact."""
        checkpoint = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.discovery.broad_inventory = [
            {"tab_title": "Crop Planner", "row_count": 100},
            {"tab_title": "Field Record", "row_count": 50},
        ]
        state.save_checkpoint(checkpoint)

        yaml_text = checkpoint.read_text()
        assert "_artifact" in yaml_text
        assert "pipeline-state-broad_inventory.json" in yaml_text

    def test_artifact_resolved_on_load(self, tmp_path: Path):
        """Loading resolves artifact references back to inline data."""
        checkpoint = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.discovery.broad_inventory = [
            {"tab_title": "Crop Planner", "row_count": 100},
        ]
        state.save_checkpoint(checkpoint)

        loaded = PipelineState.load(checkpoint)
        assert loaded.discovery.broad_inventory == [
            {"tab_title": "Crop Planner", "row_count": 100},
        ]

    def test_missing_artifact_returns_empty_list(self, tmp_path: Path):
        """Missing artifact files are gracefully handled as empty lists."""
        checkpoint = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.discovery.broad_inventory = [
            {"tab_title": "Test"}
        ]
        state.save_checkpoint(checkpoint)

        # Delete the artifact file
        artifact = tmp_path / "pipeline-state-broad_inventory.json"
        artifact.unlink()

        loaded = PipelineState.load(checkpoint)
        assert loaded.discovery.broad_inventory == []

    def test_deep_profile_index_as_artifact(self, tmp_path: Path):
        """DeepProfileIndex entries are externalized when present."""
        checkpoint = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.deep_profile_index.entries = [
            {"tab": "Crop Planner", "columns": 20},
        ]
        state.save_checkpoint(checkpoint)

        yaml_text = checkpoint.read_text()
        assert "_artifact" in yaml_text
        assert "pipeline-state-deep-profiles.json" in yaml_text

    def test_deep_profile_index_resolved_on_load(self, tmp_path: Path):
        """DeepProfileIndex entries resolve correctly from artifact."""
        checkpoint = tmp_path / "pipeline-state.yaml"
        state = PipelineState()
        state.deep_profile_index.entries = [
            {"tab": "Crop Planner", "columns": 20},
        ]
        state.save_checkpoint(checkpoint)

        loaded = PipelineState.load(checkpoint)
        assert loaded.deep_profile_index.entries == [
            {"tab": "Crop Planner", "columns": 20},
        ]


# ---------------------------------------------------------------------------
# 7. Spec example roundtrip
# ---------------------------------------------------------------------------


class TestSpecExample:
    """Full PipelineState matching the docs/pipeline-state.md spec."""

    def test_spec_example_roundtrip(self, tmp_path):
        """Load the full YAML example from the design spec."""
        state = PipelineState(
            version="0.0.9",
            discovery=DiscoveryState(
                source_tree={
                    "provider": "google_sheets",
                    "folder_id": "1ABC...",
                    "spreadsheets": [
                        {
                            "name": "101_FarmPlan_2023",
                            "id": "1DEF...",
                        },
                    ],
                },
                workbook_index=[
                    {
                        "workbook_code": "101",
                        "year": 2023,
                        "spreadsheet_id": "1DEF...",
                    },
                ],
                approved_tabs={
                    "101": [
                        "Crop Planner",
                        "Field Record",
                        "Harvest Availability",
                    ],
                },
            ),
            domain_knowledge=DomainKnowledge(
                domain="farm_management",
                vocabulary={
                    "operational": [
                        "crop",
                        "planting",
                        "harvest",
                        "field",
                        "variety",
                    ],
                    "reference": ["market", "channel", "customer"],
                    "support": [],
                    "derived": [],
                },
                year_scope={
                    "active": [2025, 2026],
                    "archived": [2023, 2024],
                    "forward": [],
                },
                deduplication={
                    "strategy": "latest_year",
                    "exceptions": [
                        {
                            "tab_title": "Annual Budget",
                            "reason": "Changes meaning every year",
                        },
                    ],
                },
                entities=[
                    {
                        "name": "Season",
                        "source_tabs": ["Crop Planner"],
                        "fields": {
                            "name": {
                                "type": "CharField",
                                "max_length": 100,
                                "unique": True,
                            },
                        },
                        "import_key": ["name"],
                    },
                ],
                glossary={"qty": "quantity", "amt": "amount"},
                scope_notes=(
                    "Focus on 2025-2026; "
                    "2023-2024 are historical only."
                ),
            ),
            schema_contract={"tables": []},
            interaction_contract={"views": []},
        )

        path = tmp_path / "pipeline-state.yaml"
        state.save_checkpoint(path)

        loaded = PipelineState.load(path)
        assert loaded.version == "0.0.9"
        assert (
            loaded.discovery.source_tree["provider"] == "google_sheets"
        )
        assert (
            loaded.discovery.source_tree["spreadsheets"][0]["name"]
            == "101_FarmPlan_2023"
        )
        assert (
            loaded.discovery.workbook_index[0]["workbook_code"] == "101"
        )
        assert loaded.discovery.workbook_index[0]["year"] == 2023
        assert loaded.discovery.approved_tabs["101"] == [
            "Crop Planner",
            "Field Record",
            "Harvest Availability",
        ]
        assert loaded.domain_knowledge.domain == "farm_management"
        assert loaded.domain_knowledge.vocabulary["operational"] == [
            "crop",
            "planting",
            "harvest",
            "field",
            "variety",
        ]
        assert loaded.domain_knowledge.year_scope["active"] == [
            2025,
            2026,
        ]
        assert (
            loaded.domain_knowledge.deduplication["strategy"]
            == "latest_year"
        )
        assert (
            loaded.domain_knowledge.entities[0]["name"] == "Season"
        )


# ---------------------------------------------------------------------------
# 8. Post-init validation
# ---------------------------------------------------------------------------


class TestPostInitValidation:
    """Verify __post_init__ catches invalid states."""

    def test_domain_knowledge_rejects_missing_vocab_keys(self):
        """Missing vocabulary keys raise ValueError."""
        from profiler.tools.pipeline_state import DomainKnowledge

        with pytest.raises(ValueError, match="vocabulary must contain keys"):
            DomainKnowledge(vocabulary={"operational": []})

    def test_domain_knowledge_rejects_missing_year_scope_keys(self):
        """Missing year_scope keys raise ValueError."""
        from profiler.tools.pipeline_state import DomainKnowledge

        with pytest.raises(ValueError, match="year_scope must contain keys"):
            DomainKnowledge(year_scope={"active": []})

    def test_discovery_state_rejects_wrong_source_tree_type(self):
        """source_tree as non-dict raises TypeError."""
        from profiler.tools.pipeline_state import DiscoveryState

        with pytest.raises(TypeError, match="source_tree must be dict or None"):
            DiscoveryState(source_tree="not_a_dict")

    def test_pipeline_state_rejects_wrong_discovery_type(self):
        """discovery as non-DiscoveryState raises TypeError."""
        from profiler.tools.pipeline_state import PipelineState

        with pytest.raises(TypeError, match="discovery must be DiscoveryState"):
            PipelineState(discovery="bad")


# ---------------------------------------------------------------------------
# 9. Version consistency
# ---------------------------------------------------------------------------


class TestVersionConsistency:
    """PipelineState.version must match pyproject.toml project version."""

    def test_version_matches_pyproject_toml(self) -> None:
        """Assert PipelineState default version equals pyproject.toml version."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        pyproject_path = repo_root / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        pyproject_version = data["project"]["version"]
        assert PipelineState.version == pyproject_version, (
            f"PipelineState.version ({PipelineState.version}) "
            f"!= pyproject.toml version ({pyproject_version})"
        )


# ---------------------------------------------------------------------------
# 10. Version migration
# ---------------------------------------------------------------------------


class TestVersionMigration:
    """Verify version comparison and migration application."""

    def test_version_less_than(self):
        """_version_less_than compares correctly."""
        from profiler.tools.pipeline_state import _version_less_than as vlt

        assert vlt("0.0.8", "0.0.9")
        assert vlt("0.0.9", "0.1.0")
        assert not vlt("0.0.9", "0.0.9")
        assert not vlt("0.1.0", "0.0.9")

    def test_version_less_eq(self):
        """_version_less_eq compares correctly."""
        from profiler.tools.pipeline_state import _version_less_eq as vle

        assert vle("0.0.9", "0.0.9")
        assert vle("0.0.8", "0.0.9")
        assert not vle("0.1.0", "0.0.9")

    def test_apply_migrations_bumps_version(self, tmp_path):
        """Old version checkpoint gets version bumped."""
        import yaml

        raw = {
            "version": "0.0.8",
            "discovery": {
                "source_tree": {},
                "workbook_index": [],
                "broad_inventory": [],
                "shortlist": [],
                "approved_tabs": {},
            },
            "domain_knowledge": {
                "domain": "test",
                "description": "",
                "vocabulary": {
                    "operational": [],
                    "reference": [],
                    "support": [],
                    "derived": [],
                },
                "year_scope": {
                    "active": [],
                    "archived": [],
                    "forward": [],
                },
                "deduplication": {
                    "strategy": "latest_year",
                    "exceptions": [],
                },
                "entities": [],
                "glossary": {},
                "scope_notes": "",
            },
        }
        path = tmp_path / "old-state.yaml"
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")

        from profiler.tools.pipeline_state import PipelineState

        loaded = PipelineState.load(path)
        assert loaded.version == "0.0.9"
        assert loaded.domain_knowledge.domain == "test"


# ---------------------------------------------------------------------------
# 11. Contract resolution
# ---------------------------------------------------------------------------


class TestContractResolution:
    """Verify contract artifacts survive save_checkpoint → load."""

    def test_schema_contract_round_trip(self, tmp_path):
        """Schema contract is preserved through checkpoint save/load."""
        state = PipelineState(
            schema_contract={"tables": [{"name": "CropPlan"}]},
        )
        path = tmp_path / "state.yaml"
        state.save_checkpoint(path)

        loaded = PipelineState.load(path)
        assert loaded.schema_contract == {"tables": [{"name": "CropPlan"}]}

    def test_interaction_contract_round_trip(self, tmp_path):
        """Interaction contract is preserved through checkpoint save/load."""
        state = PipelineState(
            interaction_contract={"views": [{"name": "crop_list"}]},
        )
        path = tmp_path / "state.yaml"
        state.save_checkpoint(path)

        loaded = PipelineState.load(path)
        assert loaded.interaction_contract == {"views": [{"name": "crop_list"}]}

    def test_contracts_default_to_none(self):
        """Fresh state has None contracts."""
        state = PipelineState()
        assert state.schema_contract is None
        assert state.interaction_contract is None


class TestArtifactPaths:
    """Verify artifact paths are derived from checkpoint location."""

    def test_contract_artifact_paths_relative_to_checkpoint(self, tmp_path):
        """Contract artifact paths are checkpoint-relative, not hardcoded."""
        state = PipelineState(
            schema_contract={"tables": []},
            interaction_contract={"views": []},
        )
        path = tmp_path / "checkpoints" / "pipeline-state.yaml"
        path.parent.mkdir(parents=True)
        state.save_checkpoint(path)

        yaml_text = path.read_text()
        assert "schema-contract.yaml" in yaml_text
        assert "interaction-contract.yaml" in yaml_text
        assert "build/" not in yaml_text  # No hardcoded build/ path
