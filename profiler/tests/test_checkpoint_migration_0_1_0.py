"""Tests for PipelineState checkpoint migration from 0.0.9 to 0.1.0."""

import yaml

from profiler.tools.pipeline_state import PipelineState


class TestCheckpointMigration:
    def test_migrate_v0_0_9_to_v0_1_0_populates_operational_model(self, tmp_path):
        """Migration populates the operational_model field."""
        old_checkpoint = {
            "version": "0.0.9",
            "discovery": {
                "workbook_index": [],
                "broad_inventory": [],
                "shortlist": None,
                "approved_tabs": None,
            },
            "deep_profile_index": {"entries": []},
            "domain_knowledge": {
                "domain": "farm",
                "vocabulary": {
                    "operational": [],
                    "reference": [],
                    "support": [],
                    "derived": [],
                },
                "year_scope": {"active": [], "archived": [], "forward": []},
                "deduplication": {"strategy": "latest_year", "exceptions": []},
                "entities": [],
                "glossary": {},
                "scope_notes": "",
            },
            "schema_contract": {"tables": [{"suggested_model_name": "crop"}]},
            "interaction_contract": {
                "version": "interaction-contract-1",
                "interviews": [],
            },
            "decisions": [],
        }
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        checkpoint_path.write_text(yaml.safe_dump(old_checkpoint), encoding="utf-8")

        state = PipelineState.load(checkpoint_path)
        assert state.version == "0.2.0"
        assert state.operational_model is not None

    def test_migrate_populates_operational_model(self, tmp_path):
        """Migration derives an operational model from existing fields."""
        old_checkpoint = {
            "version": "0.0.9",
            "discovery": {
                "workbook_index": [{"tab_title": "Crop Planner", "row_count": 100}],
                "broad_inventory": [],
                "shortlist": None,
                "approved_tabs": None,
            },
            "deep_profile_index": {"entries": []},
            "domain_knowledge": {
                "domain": "farm",
                "description": "Test farm domain",
                "vocabulary": {
                    "operational": ["crop", "harvest"],
                    "reference": [],
                    "support": [],
                    "derived": [],
                },
                "year_scope": {"active": [], "archived": [], "forward": []},
                "deduplication": {"strategy": "latest_year", "exceptions": []},
                "entities": [],
                "glossary": {},
                "scope_notes": "",
            },
            "schema_contract": None,
            "interaction_contract": None,
            "decisions": [],
        }
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        checkpoint_path.write_text(yaml.safe_dump(old_checkpoint), encoding="utf-8")

        state = PipelineState.load(checkpoint_path)
        assert state.operational_model is not None
        assert state.operational_model.source_id == "farm"

    def test_new_checkpoint_has_operational_model_field(self, tmp_path):
        """Fresh checkpoint includes operational_model field."""
        state = PipelineState()
        state.operational_model = None
        checkpoint_path = tmp_path / "pipeline-state.yaml"
        state.save_checkpoint(checkpoint_path)

        loaded = PipelineState.load(checkpoint_path)
        assert hasattr(loaded, "operational_model")
