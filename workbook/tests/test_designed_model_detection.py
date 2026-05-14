"""Tests for designed_model_detection module."""

import pytest
from workbook.codegen.designed_model_detection import (
    find_column_overlap_groups,
    suggest_designed_model,
)


def test_scaffold_includes_designed_models():
    """scaffold_workbook_schema emits designed models when tabs overlap."""
    from django.core.management import call_command
    from io import StringIO
    import tempfile, json
    from pathlib import Path

    bundle_config = {
        "tabs": [
            {
                "worksheet_title": "Spring Planting",
                "output_path": "spring.csv",
                "required_headers": ["crop", "variety", "bed", "date"],
            },
            {
                "worksheet_title": "Fall Planting",
                "output_path": "fall.csv",
                "required_headers": ["crop", "variety", "bed", "seed_source"],
            },
        ]
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as cfg:
        json.dump(bundle_config, cfg)
        cfg_path = cfg.name
    out_path = cfg_path.replace(".json", ".yaml")

    try:
        out = StringIO()
        call_command(
            "scaffold_workbook_schema",
            "--bundle-config", cfg_path,
            "--out", out_path,
            "--contract-version", "1.3",
            stdout=out,
        )
        import yaml
        with open(out_path) as f:
            contract = yaml.safe_load(f)
        tables = contract.get("tables", [])
        source_aligned = [t for t in tables if t.get("bundle_worksheet_title")]
        designed = [t for t in tables if t.get("source_tab") is None
                     and t.get("bundle_worksheet_title") is None]
        assert len(source_aligned) >= 2
        assert len(designed) >= 1
        assert designed[0]["suggested_model_name"] is not None
    finally:
        Path(cfg_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)


class TestFindColumnOverlapGroups:
    """Tests for column-overlap clustering logic."""

    def test_no_overlap_returns_empty(self):
        """Tabs with disjoint column sets produce no clusters."""
        tab_columns = {
            "Clients": {"id", "name", "email"},
            "Orders": {"order_id", "product", "quantity"},
        }
        result = find_column_overlap_groups(
            tab_columns=tab_columns,
            min_overlap_ratio=0.5,
        )
        assert result == []

    def test_high_overlap_produces_cluster(self):
        """Tabs sharing >50% columns produce a cluster entry."""
        tab_columns = {
            "Spring Planting": {"crop", "variety", "bed", "date", "notes"},
            "Fall Planting": {"crop", "variety", "bed", "date", "seed_source"},
            "Harvest": {"crop", "variety", "date", "weight", "quality"},
        }
        result = find_column_overlap_groups(
            tab_columns=tab_columns,
            min_overlap_ratio=0.5,
        )
        assert any(
            g for g in result
            if set(g["tab_names"]) == {"Spring Planting", "Fall Planting"}
        )
        assert any(
            g for g in result
            if set(g["tab_names"]) == {"Spring Planting", "Harvest"}
        )

    def test_suggested_model_structure(self):
        """A cluster produces a suggested designed model dict."""
        cluster = {
            "tab_names": ["Planting Log", "Planting Schedule"],
            "shared_columns": ["crop", "variety", "date", "bed"],
            "unique_columns": {
                "Planting Log": {"notes", "seed_lot"},
                "Planting Schedule": {"planned_quantity", "expected_yield"},
            },
        }
        result = suggest_designed_model(
            cluster=cluster,
            suggested_name="PlantingEvent",
            source_provider="google_sheets",
        )
        assert result["suggested_model_name"] == "PlantingEvent"
        assert result["source_tab"] is None
        shared_names = {c["suggested_field_name"] for c in result["columns"]}
        assert "crop" in shared_names
        assert "variety" in shared_names
        extra_names = {c["suggested_field_name"] for c in result["extra_fields"]}
        assert "notes" in extra_names
        assert "seed_lot" in extra_names
        assert "planned_quantity" in extra_names
