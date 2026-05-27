"""Tests for PipelineState — dataclass, bridge, checkpoint I/O, phase methods."""

import pytest

from profiler.tools.pipeline_state import (
    DeepProfileIndex,
    DiscoveryState,
    DomainKnowledge,
    PipelineState,
)

# ---------------------------------------------------------------------------
# 1. Dataclass defaults
# ---------------------------------------------------------------------------


def test_pipeline_state_defaults():
    """Fresh PipelineState has version="0.1.0" and all sub-objects exist."""
    state = PipelineState()
    assert state.version == "0.1.0"
    assert isinstance(state.discovery, DiscoveryState)
    assert isinstance(state.deep_profile_index, DeepProfileIndex)
    assert isinstance(state.domain_knowledge, DomainKnowledge)
    assert state.schema_contract is None
    assert state.interaction_contract is None


def test_discovery_state_fields():
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


def test_domain_knowledge_fields():
    """All DomainKnowledge fields accept values."""
    dk = DomainKnowledge(
        domain="farm_management",
        vocabulary={"operational": ["crop"], "reference": ["market"]},
        year_scope={"active": [2025, 2026], "archived": [2023]},
        deduplication={"strategy": "latest_year", "exceptions": []},
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


# ---------------------------------------------------------------------------
# 2. Checkpoint I/O
# ---------------------------------------------------------------------------


def test_checkpoint_roundtrip(tmp_path):
    """save_checkpoint → load() preserves all fields."""
    state = PipelineState(
        version="0.1.0",
        discovery=DiscoveryState(
            source_tree={"provider": "google_sheets"},
            workbook_index=[{"workbook_code": "101", "year": 2023}],
        ),
        domain_knowledge=DomainKnowledge(
            domain="test_domain",
            vocabulary={"operational": ["test"]},
        ),
        schema_contract={"tables": []},
    )
    path = tmp_path / "pipeline-state.yaml"
    state.save_checkpoint(path)
    assert path.exists()

    loaded = PipelineState.load(path)
    assert loaded.version == "0.1.0"
    assert loaded.discovery.source_tree == {"provider": "google_sheets"}
    assert loaded.discovery.workbook_index == [{"workbook_code": "101", "year": 2023}]
    assert loaded.domain_knowledge.domain == "test_domain"
    assert loaded.domain_knowledge.vocabulary == {"operational": ["test"]}
    assert loaded.schema_contract == {"tables": []}


def test_load_or_create_creates_fresh(tmp_path):
    """No existing checkpoint → fresh PipelineState from config JSON."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"domain": "test_domain", "cohort_name": "test_cohort"}'
    )
    state = PipelineState.load_or_create(config_path=config_path)
    assert isinstance(state, PipelineState)
    assert state.version == "0.1.0"
    # Domain should be populated from config
    assert state.domain_knowledge.domain == "test_domain"
    # discovery should be fresh (None)
    assert state.discovery.source_tree is None


def test_load_or_create_loads_existing(tmp_path):
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
        config_path=config_path, checkpoint_path=checkpoint_path
    )
    assert loaded.domain_knowledge.domain == "checkpoint_domain"
    assert loaded.discovery.source_tree == {"provider": "coda"}


# ---------------------------------------------------------------------------
# 3. Phase method guard clauses
# ---------------------------------------------------------------------------


def test_discover_requires_no_prior_discovery():
    """RuntimeError if source_tree already set."""
    state = PipelineState(discovery=DiscoveryState(source_tree={}))
    with pytest.raises(RuntimeError, match="source_tree already populated"):
        state.discover()


def test_score_and_select_requires_discovery():
    """RuntimeError if source_tree is None."""
    state = PipelineState()
    with pytest.raises(RuntimeError, match="discover\\(\\) must run first"):
        state.score_and_select()


def test_score_and_select_requires_shortlist():
    """RuntimeError if shortlist is None."""
    state = PipelineState(discovery=DiscoveryState(source_tree={}))
    with pytest.raises(RuntimeError, match="shortlist is None"):
        state.score_and_select()


def test_deep_profile_requires_approved_tabs():
    """RuntimeError if approved_tabs is None."""
    state = PipelineState(
        discovery=DiscoveryState(source_tree={})
    )
    with pytest.raises(RuntimeError, match="no approved_tabs"):
        state.deep_profile()


def test_derive_contracts_requires_deep_profile():
    """RuntimeError if entries empty (NOT is None — entries list is never None)."""
    state = PipelineState()
    # deep_profile_index.entries defaults to [] — never None
    with pytest.raises(RuntimeError, match="deep_profile must run first"):
        state.derive_contracts()


def test_phase_sequencing_happy_path():
    """Full phase order works without errors."""
    state = PipelineState()
    state.discover()
    state.score_and_select()
    state.deep_profile()
    state.deep_profile_index.entries.append({"tab": "Crop Planner"})
    state.derive_contracts()
    # After happy path, discovery fields are populated
    assert state.discovery.source_tree == {}
    assert state.discovery.approved_tabs == {}
    assert isinstance(state.deep_profile_index, DeepProfileIndex)
    assert state.schema_contract == {}
    assert state.interaction_contract == {}


# ---------------------------------------------------------------------------
# 4. YAML readability
# ---------------------------------------------------------------------------


def test_checkpoint_yaml_human_readable(tmp_path):
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
    # Should have block-style YAML (not flow style)
    assert "version: " in raw
    assert "discovery:" in raw
    assert "domain_knowledge:" in raw
    assert "source_tree:" in raw
    assert "provider: google_sheets" in raw
    assert "workbook_index:" in raw
    assert "domain: farm" in raw


# ---------------------------------------------------------------------------
# 5. Domain context bridge
# ---------------------------------------------------------------------------


def test_domain_context_bridge():
    """from_domain_context preserves year_scope, vocabulary, dedup, entities."""
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
            exceptions=[{"tab_title": "Annual Budget"}],
        ),
        entities=[{"name": "Season", "source_tabs": ["Crop Planner"]}],
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


# ---------------------------------------------------------------------------
# 6. Spec example roundtrip
# ---------------------------------------------------------------------------


def test_spec_example_roundtrip(tmp_path):
    """Load the full YAML example from docs/pipeline-state.md spec."""
    # Build a PipelineState matching the spec, save and reload
    state = PipelineState(
        version="0.2.0",
        discovery=DiscoveryState(
            source_tree={
                "provider": "google_sheets",
                "folder_id": "1ABC...",
                "spreadsheets": [
                    {"name": "101_FarmPlan_2023", "id": "1DEF..."},
                ],
            },
            workbook_index=[
                {
                    "workbook_code": "101",
                    "year": 2023,
                    "spreadsheet_id": "1DEF...",
                },
            ],
            broad_inventory=[
                {"_artifact": "data/profile_snapshots/broad_profile_coverage_2026-05-26.json"},
            ],
            shortlist=[
                {
                    "_artifact": "data/profile_snapshots/tab_shortlist_2026-05-26.json",
                    "selection_summary": {
                        "by_workbook_by_year": {
                            "101": {"2023": 4, "2024": 4},
                        },
                        "deduplicated_count": 14,
                        "original_count": 48,
                    },
                },
            ],
            approved_tabs={
                "101": ["Crop Planner", "Field Record", "Harvest Availability"],
            },
        ),
        domain_knowledge=DomainKnowledge(
            domain="farm_management",
            vocabulary={
                "operational": ["crop", "planting", "harvest", "field", "variety"],
                "reference": ["market", "channel", "customer"],
            },
            year_scope={
                "active": [2025, 2026],
                "archived": [2023, 2024],
            },
            deduplication={
                "strategy": "latest_year",
                "exceptions": [
                    {"tab_title": "Annual Budget", "reason": "Changes meaning every year"},
                ],
            },
            entities=[
                {
                    "name": "Season",
                    "source_tabs": ["Crop Planner"],
                    "fields": {
                        "name": {"type": "CharField", "max_length": 100, "unique": True},
                    },
                    "import_key": ["name"],
                },
            ],
            glossary={"qty": "quantity", "amt": "amount"},
            scope_notes="Focus on 2025-2026; 2023-2024 are historical only.",
        ),
        schema_contract={"_artifact": "build/schema-contract.yaml"},
        interaction_contract={"_artifact": "build/interaction-contract.yaml"},
    )

    path = tmp_path / "pipeline-state.yaml"
    state.save_checkpoint(path)

    loaded = PipelineState.load(path)
    assert loaded.version == "0.2.0"
    assert loaded.discovery.source_tree["provider"] == "google_sheets"
    assert loaded.discovery.source_tree["spreadsheets"][0]["name"] == "101_FarmPlan_2023"
    assert loaded.discovery.workbook_index[0]["workbook_code"] == "101"
    assert loaded.discovery.workbook_index[0]["year"] == 2023
    assert loaded.discovery.broad_inventory[0]["_artifact"] == (
        "data/profile_snapshots/broad_profile_coverage_2026-05-26.json"
    )
    assert loaded.discovery.shortlist[0]["selection_summary"]["deduplicated_count"] == 14
    assert loaded.discovery.approved_tabs["101"] == [
        "Crop Planner", "Field Record", "Harvest Availability",
    ]
    assert loaded.domain_knowledge.domain == "farm_management"
    assert loaded.domain_knowledge.vocabulary["operational"] == [
        "crop", "planting", "harvest", "field", "variety",
    ]
    assert loaded.domain_knowledge.year_scope["active"] == [2025, 2026]
    assert loaded.domain_knowledge.deduplication["strategy"] == "latest_year"
    assert loaded.domain_knowledge.entities[0]["name"] == "Season"
    assert loaded.domain_knowledge.glossary["qty"] == "quantity"
    assert loaded.schema_contract["_artifact"] == "build/schema-contract.yaml"
    assert loaded.interaction_contract["_artifact"] == "build/interaction-contract.yaml"
