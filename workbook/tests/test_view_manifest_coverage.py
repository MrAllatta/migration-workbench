"""Tests for view-manifest-driven view generation and workflow coverage.

Covers:
- Loading and normalizing a view manifest YAML into structured view entries.
- Converting a view-manifest entry into a ``ListArchetype`` with
  model, columns, filters, ordering, and pagination.
- The ``generate_views --archetype-list-from-manifest`` command.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml
from django.core.management import call_command

from workbook.codegen.list_generator import ListArchetype, render_list_view_py

# ── Fixtures ──────────────────────────────────────────────────────────────────


SAMPLE_MANIFEST = {
    "version": "test-v1",
    "source": {"source_id": "test", "provider": "test"},
    "views": [
        {
            "name": "crop_info",
            "entity": "crop",
            "source_tab": "Crop Info",
            "type": "list",
            "filterable_by": ["botanical_family", "product_type"],
            "status_field": None,
            "time_scope": None,
            "editable_fields": ["product_type", "botanical_family"],
        },
        {
            "name": "field_blocks",
            "entity": "field_block",
            "source_tab": "Define Field Blocks",
            "type": "list",
            "filterable_by": [],
            "status_field": None,
            "time_scope": None,
            "editable_fields": ["block_type", "bed_width_feet"],
        },
        {
            "name": "sales_plans",
            "entity": "sales_plan",
            "source_tab": "Sales Channels",
            "type": "list",
            "filterable_by": ["season", "crop"],
            "status_field": None,
            "time_scope": {
                "year_field": "planned_year",
                "week_field": "planned_week",
            },
        },
    ],
}

SAMPLE_CONTRACT_TABLES = {
    "crop": {
        "model_name": "Crop",
        "columns": ["name", "botanical_family", "product_type", "storage_weeks"],
    },
    "field_block": {
        "model_name": "FieldBlock",
        "columns": ["name", "block_type", "bed_width_feet", "acreage"],
    },
    "sales_plan": {
        "model_name": "SalesPlan",
        "columns": ["crop", "season", "planned_year", "planned_week", "quantity"],
    },
}


@pytest.fixture
def sample_manifest_path(tmp_path: Path) -> Path:
    """Write and return a test view-manifest.yaml."""
    path = tmp_path / "view-manifest.yaml"
    with open(path, "w") as f:
        yaml.dump(SAMPLE_MANIFEST, f)
    return path


@pytest.fixture
def sample_contract_path(tmp_path: Path) -> Path:
    """Write and return a minimal schema contract matching sample models."""
    contract = {
        "version": "2.1",
        "tables": [
            {
                "table_name": "crop",
                "suggested_model_name": "Crop",
                "columns": [
                    {"column_name": "name", "inferred_type": "string"},
                    {"column_name": "botanical_family", "inferred_type": "string"},
                    {"column_name": "product_type", "inferred_type": "string"},
                    {"column_name": "storage_weeks", "inferred_type": "integer"},
                ],
            },
            {
                "table_name": "field_block",
                "suggested_model_name": "FieldBlock",
                "columns": [
                    {"column_name": "name", "inferred_type": "string"},
                    {"column_name": "block_type", "inferred_type": "string"},
                    {"column_name": "bed_width_feet", "inferred_type": "integer"},
                    {"column_name": "acreage", "inferred_type": "number"},
                ],
            },
            {
                "table_name": "sales_plan",
                "suggested_model_name": "SalesPlan",
                "columns": [
                    {"column_name": "crop", "inferred_type": "fk"},
                    {"column_name": "season", "inferred_type": "string"},
                    {"column_name": "planned_year", "inferred_type": "integer"},
                    {"column_name": "planned_week", "inferred_type": "integer"},
                    {"column_name": "quantity", "inferred_type": "integer"},
                ],
            },
        ],
    }
    path = tmp_path / "contract.yaml"
    with open(path, "w") as f:
        yaml.dump(contract, f)
    return path


# ── View manifest loader ──────────────────────────────────────────────────────


class TestViewManifestLoader:
    """load_view_manifest: YAML path → normalized view entries."""

    def test_loads_valid_manifest(self, sample_manifest_path: Path):
        """A valid view-manifest.yaml loads and returns the correct number of entries."""
        from workbook.codegen.manifest_loader import load_view_manifest

        views = load_view_manifest(sample_manifest_path)
        assert len(views) == 3

    def test_each_entry_has_required_fields(self, sample_manifest_path: Path):
        """Each loaded entry has name, entity, source_tab, type, and filterable_by."""
        from workbook.codegen.manifest_loader import load_view_manifest

        views = load_view_manifest(sample_manifest_path)
        for entry in views:
            assert "name" in entry
            assert "entity" in entry
            assert "source_tab" in entry
            assert "type" in entry
            assert "filterable_by" in entry

    def test_entries_have_normalized_entity_key(self, sample_manifest_path: Path):
        """Entity keys are normalised to snake_case for model name matching."""
        from workbook.codegen.manifest_loader import load_view_manifest

        views = load_view_manifest(sample_manifest_path)
        entities = [v["entity"] for v in views]
        assert "crop" in entities
        assert "field_block" in entities
        assert "sales_plan" in entities


# ── Manifest-to-archetype adapter ─────────────────────────────────────────────


class TestManifestToArchetype:
    """manifest_to_list_archetype: manifest entry + contract → ListArchetype."""

    def test_entry_with_filters_produces_list_archetype(
        self, sample_manifest_path: Path
    ):
        """A crop-info manifest entry with filterable_by produces a ListArchetype
        with filters matching filterable_by."""
        from workbook.codegen.manifest_loader import (
            load_view_manifest,
            manifest_to_list_archetype,
        )

        views = load_view_manifest(sample_manifest_path)
        crop_entry = next(v for v in views if v["entity"] == "crop")

        archetype = manifest_to_list_archetype(
            crop_entry,
            model_name="Crop",
        )

        assert isinstance(archetype, ListArchetype)
        assert archetype.model == "Crop"
        assert "botanical_family" in archetype.filters
        assert "product_type" in archetype.filters

    def test_entry_without_filters_has_defaults(self, sample_manifest_path: Path):
        """A field-block entry with no filterable_by produces a ListArchetype
        with sensible defaults."""
        from workbook.codegen.manifest_loader import (
            load_view_manifest,
            manifest_to_list_archetype,
        )

        views = load_view_manifest(sample_manifest_path)
        fb_entry = next(v for v in views if v["entity"] == "field_block")

        archetype = manifest_to_list_archetype(
            fb_entry,
            model_name="FieldBlock",
        )

        assert archetype.model == "FieldBlock"
        assert len(archetype.filters) == 0
        assert archetype.paginate_by == 50
        assert len(archetype.columns) > 0

    def test_entry_with_time_scope_uses_year_week(self, sample_manifest_path: Path):
        """An entry with time_scope uses year_field and week_field in ordering/filters."""
        from workbook.codegen.manifest_loader import (
            load_view_manifest,
            manifest_to_list_archetype,
        )

        views = load_view_manifest(sample_manifest_path)
        sp_entry = next(v for v in views if v["entity"] == "sales_plan")

        archetype = manifest_to_list_archetype(
            sp_entry,
            model_name="SalesPlan",
        )

        assert archetype.model == "SalesPlan"
        # Should include year and week fields in ordering
        ordering_str = " ".join(archetype.ordering)
        assert "planned_year" in ordering_str
        assert "planned_week" in ordering_str

    def test_archetype_renders_valid_view_code(self, sample_manifest_path: Path):
        """The ListArchetype from a manifest entry renders valid Python."""
        from workbook.codegen.manifest_loader import (
            load_view_manifest,
            manifest_to_list_archetype,
        )

        views = load_view_manifest(sample_manifest_path)
        crop_entry = next(v for v in views if v["entity"] == "crop")

        archetype = manifest_to_list_archetype(
            crop_entry,
            model_name="Crop",
        )
        view_source = render_list_view_py(archetype)

        ast.parse(view_source)
        assert "CropListView" in view_source
        assert "filterable_by" not in view_source  # must not leak manifest terminology

    def test_unknown_entity_derives_model_name(self, sample_manifest_path: Path):
        """An entry with an unknown entity derives a model name from the entity key."""
        from workbook.codegen.manifest_loader import (
            load_view_manifest,
            manifest_to_list_archetype,
        )

        _ = load_view_manifest(sample_manifest_path)
        bad_entry = {"name": "mystery", "entity": "unknown_entity"}

        archetype = manifest_to_list_archetype(bad_entry)
        assert archetype.model == "UnknownEntity"

    def test_coverage_counts(
        self, sample_manifest_path: Path, sample_contract_path: Path
    ):
        """All manifest entries can produce a ListArchetype given a contract."""
        from workbook.codegen.manifest_loader import (
            load_view_manifest,
            manifest_to_list_archetype,
        )

        views = load_view_manifest(sample_manifest_path)
        model_map = {
            "crop": "Crop",
            "field_block": "FieldBlock",
            "sales_plan": "SalesPlan",
        }

        archetypes = []
        for entry in views:
            entity = entry["entity"]
            if entity not in model_map:
                continue
            archetype = manifest_to_list_archetype(entry, model_name=model_map[entity])
            archetypes.append(archetype)

        assert len(archetypes) == 3
        for arch in archetypes:
            view_source = render_list_view_py(arch)
            ast.parse(view_source)


# ── Management command integration ─────────────────────────────────────────────


SAMPLE_CONTRACT_FOR_COMMAND = {
    "version": "2.1",
    "tables": [
        {
            "model_name": "Crop",
            "model_meta": {"app_label": "core"},
            "columns": [
                {"name": "id", "class": "models.BigAutoField"},
                {"name": "name", "class": "models.CharField"},
                {"name": "botanical_family", "class": "models.CharField"},
                {"name": "product_type", "class": "models.CharField"},
            ],
        },
        {
            "model_name": "FieldBlock",
            "model_meta": {"app_label": "core"},
            "columns": [
                {"name": "id", "class": "models.BigAutoField"},
                {"name": "name", "class": "models.CharField"},
                {"name": "block_type", "class": "models.CharField"},
            ],
        },
    ],
}


class TestGenerateViewsListFromManifest:
    """``generate_views --archetype-list-from-manifest`` writes list views."""

    def _write_contract(self, tmp_path: Path) -> Path:
        path = tmp_path / "contract.yaml"
        with open(path, "w") as f:
            yaml.dump(SAMPLE_CONTRACT_FOR_COMMAND, f)
        return path

    def test_list_from_manifest_creates_views_auto(self, tmp_path: Path):
        """The --archetype-list-from-manifest flag writes views_auto.py."""
        contract_path = self._write_contract(tmp_path)
        manifest_path = tmp_path / "view-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(SAMPLE_MANIFEST, f)
        out_dir = tmp_path / "out"

        call_command(
            "generate_views",
            contract=str(contract_path),
            out_dir=str(out_dir),
            archetype_list_from_manifest=str(manifest_path),
            force=True,
        )

        assert (out_dir / "views_auto.py").exists()
        assert (out_dir / "urls_auto.py").exists()

    def test_list_from_manifest_includes_all_entries(self, tmp_path: Path):
        """All three manifest entries produce list views in the output."""
        contract_path = self._write_contract(tmp_path)
        manifest_path = tmp_path / "view-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(SAMPLE_MANIFEST, f)
        out_dir = tmp_path / "out"

        call_command(
            "generate_views",
            contract=str(contract_path),
            out_dir=str(out_dir),
            archetype_list_from_manifest=str(manifest_path),
            force=True,
        )

        views_source = (out_dir / "views_auto.py").read_text()
        assert "CropListView" in views_source
        assert "FieldBlockListView" in views_source
        assert "SalesPlanListView" in views_source

    def test_list_from_manifest_views_are_valid_python(self, tmp_path: Path):
        """The generated views_auto.py is syntactically valid Python."""
        contract_path = self._write_contract(tmp_path)
        manifest_path = tmp_path / "view-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(SAMPLE_MANIFEST, f)
        out_dir = tmp_path / "out"

        call_command(
            "generate_views",
            contract=str(contract_path),
            out_dir=str(out_dir),
            archetype_list_from_manifest=str(manifest_path),
            force=True,
        )

        views_source = (out_dir / "views_auto.py").read_text()
        ast.parse(views_source)

    def test_list_from_manifest_filters_appear_in_views(self, tmp_path: Path):
        """Generated list views include filter logic for filterable_by fields."""
        contract_path = self._write_contract(tmp_path)
        manifest_path = tmp_path / "view-manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(SAMPLE_MANIFEST, f)
        out_dir = tmp_path / "out"

        call_command(
            "generate_views",
            contract=str(contract_path),
            out_dir=str(out_dir),
            archetype_list_from_manifest=str(manifest_path),
            force=True,
        )

        views_source = (out_dir / "views_auto.py").read_text()
        # CropListView should filter by botanical_family
        assert "botanical_family" in views_source
        # CropListView should filter by product_type
        assert "product_type" in views_source
        # SalesPlanListView should filter by season
        assert "season" in views_source
