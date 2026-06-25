"""Tests for new PipelineState phase methods."""

import json

import pytest

from profiler.tools.pipeline_state import (
    DeepProfileIndex,
    DiscoveryState,
    DomainKnowledge,
    PipelineState,
)


class TestDeriveOperationalModelPhase:
    def test_derive_operational_model_populates_field(self, tmp_path):
        """Phase method derives operational model from profiler artifacts."""
        state = PipelineState()
        state.discovery.workbook_index = [
            {"tab_title": "Crop Planner", "row_count": 100}
        ]
        state.deep_profile_index.entries = [
            {
                "tab_title": "Crop Planner",
                "columns": [
                    {
                        "header_label": "Plant Date",
                        "null_rate": 0.05,
                        "distinct_values": ["2025-01-01"],
                    },
                ],
            }
        ]
        state.domain_knowledge.domain = "farm"
        state.configure(out_dir=tmp_path)

        state.derive_operational_model()
        assert state.operational_model is not None
        assert state.operational_model.source_id == "farm"

    def test_derive_state_projections_requires_operational_model(self, tmp_path):
        """Projection phase guards against missing operational model."""
        state = PipelineState()
        state.configure(out_dir=tmp_path)
        with pytest.raises(RuntimeError, match="operational_model"):
            state.derive_state_projections()

    def test_validate_operational_model_requires_model(self, tmp_path):
        """Validation phase guards against missing operational model."""
        state = PipelineState()
        state.configure(out_dir=tmp_path)
        with pytest.raises(RuntimeError, match="operational_model"):
            state.validate_operational_model()

    def test_derive_operational_model_resolves_out_json(self, tmp_path):
        """Entries with out_json are resolved from disk before derivation."""
        deep_dir = tmp_path / "deep"
        deep_dir.mkdir()
        deep_file = deep_dir / "test.json"
        deep_file.write_text(
            json.dumps(
                {
                    "columns": [
                        {
                            "header_label": "Plant Date",
                            "null_rate": 0.05,
                            "distinct_values": ["2025-03-01"],
                        },
                    ],
                }
            )
        )

        state = PipelineState(
            discovery=DiscoveryState(workbook_index=[{"tab_title": "Crop"}]),
            deep_profile_index=DeepProfileIndex(
                entries=[
                    {
                        "tab_title": "Crop",
                        "out_json": str(deep_file.relative_to(tmp_path)),
                    }
                ]
            ),
            domain_knowledge=DomainKnowledge(domain="farm"),
        )
        state.configure(out_dir=tmp_path)
        state.derive_operational_model(base_dir=str(tmp_path))
        assert state.operational_model is not None
        assert len(state.operational_model.events) >= 1

    def test_derive_operational_model_parses_raw_deep_profile(self, tmp_path):
        """Entries with raw API data are parsed for column headers."""
        deep_dir = tmp_path / "deep"
        deep_dir.mkdir()
        deep_file = deep_dir / "raw_api.json"
        deep_file.write_text(
            json.dumps(
                {
                    "raw": {
                        "sheets": [
                            {
                                "data": [
                                    {
                                        "rowData": [
                                            {
                                                "values": [
                                                    {"formattedValue": "Plant Date"},
                                                    {"formattedValue": "Quantity"},
                                                ]
                                            },
                                            {
                                                "values": [
                                                    {"formattedValue": "2025-03-01"},
                                                    {"formattedValue": "100"},
                                                ]
                                            },
                                            {
                                                "values": [
                                                    {"formattedValue": "2025-04-01"},
                                                    {"formattedValue": "200"},
                                                ]
                                            },
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    "summary": {"tab_title": "Crop"},
                }
            )
        )

        state = PipelineState(
            discovery=DiscoveryState(workbook_index=[{"tab_title": "Crop"}]),
            deep_profile_index=DeepProfileIndex(
                entries=[
                    {
                        "tab_title": "Crop",
                        "out_json": str(deep_file.relative_to(tmp_path)),
                    }
                ]
            ),
            domain_knowledge=DomainKnowledge(
                domain="farm",
                vocabulary={
                    "operational": [],
                    "reference": [],
                    "support": [],
                    "derived": [],
                },
            ),
        )
        state.configure(out_dir=tmp_path)
        state.derive_operational_model(base_dir=str(tmp_path))
        assert state.operational_model is not None
        assert len(state.operational_model.events) >= 1
        assert any("plant_date" in event.id for event in state.operational_model.events)
