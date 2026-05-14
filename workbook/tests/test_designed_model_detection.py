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
        )
        assert result["suggested_model_name"] == "PlantingEvent"
        assert result["source_tab"] is None
        shared_names = {c["suggested_field_name"] for c in result["columns"]}
        assert "crop" in shared_names
        assert "variety" in shared_names
        extra_names = set(result["extra_fields"].keys())
        assert "notes" in extra_names
        assert "seed_lot" in extra_names
        assert "planned_quantity" in extra_names


class TestEdgeCases:
    """Edge-case tests for column-overlap clustering."""

    def test_empty_tab_columns(self):
        """Empty tab_columns dict produces no clusters."""
        result = find_column_overlap_groups(tab_columns={})
        assert result == []

    def test_single_tab(self):
        """Single tab produces no clusters."""
        tab_columns = {
            "Solo": {"col_a", "col_b", "col_c"},
        }
        result = find_column_overlap_groups(tab_columns=tab_columns)
        assert result == []

    def test_perfect_overlap_ratio_one(self):
        """min_overlap_ratio=1.0 requires one set to be a subset of the other."""
        # Subset relationship: intersection/min_len = 3/3 = 1.0 → clusters
        tab_columns_subset = {
            "Tab A": {"a", "b", "c"},
            "Tab B": {"a", "b", "c", "d"},
        }
        result = find_column_overlap_groups(
            tab_columns=tab_columns_subset,
            min_overlap_ratio=1.0,
        )
        assert len(result) == 1
        # Disjoint sets: ratio = 0/3 = 0.0 → no cluster
        tab_columns_disjoint = {
            "Tab X": {"a", "b", "c"},
            "Tab Y": {"d", "e", "f"},
        }
        result = find_column_overlap_groups(
            tab_columns=tab_columns_disjoint,
            min_overlap_ratio=1.0,
        )
        assert result == []
        # Identical column sets: ratio = 3/3 = 1.0 → clusters
        tab_columns_identical = {
            "Tab A": {"a", "b", "c"},
            "Tab B": {"a", "b", "c"},
        }
        result = find_column_overlap_groups(
            tab_columns=tab_columns_identical,
            min_overlap_ratio=1.0,
        )
        assert len(result) == 1

    def test_overlap_ratio_zero_clusters_everything(self):
        """min_overlap_ratio=0.0 clusters all pairs with at least one shared column."""
        tab_columns = {
            "Clients": {"id", "name"},
            "Orders": {"order_id", "product", "id"},
        }
        result = find_column_overlap_groups(
            tab_columns=tab_columns,
            min_overlap_ratio=0.0,
        )
        assert len(result) == 1

    def test_tabs_with_zero_columns(self):
        """Tabs with no columns are skipped and produce no clusters."""
        tab_columns = {
            "Empty": set(),
            "Also Empty": set(),
        }
        result = find_column_overlap_groups(tab_columns=tab_columns)
        assert result == []
        # Mix of empty and non-empty: empty skipped, no crash
        tab_columns["Has Columns"] = {"a", "b"}
        result = find_column_overlap_groups(tab_columns=tab_columns)
        assert result == []

    def test_identical_column_sets_cluster_at_default_ratio(self):
        """Identical column sets produce a cluster when ratio >= threshold."""
        tab_columns = {
            "Q1 Data": {"region", "product", "revenue"},
            "Q2 Data": {"region", "product", "revenue"},
        }
        result = find_column_overlap_groups(
            tab_columns=tab_columns,
            min_overlap_ratio=0.5,
        )
        assert len(result) == 1
        entry = result[0]
        assert set(entry["tab_names"]) == {"Q1 Data", "Q2 Data"}
        assert set(entry["shared_columns"]) == {"region", "product", "revenue"}
