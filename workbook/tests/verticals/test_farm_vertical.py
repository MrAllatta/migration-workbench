"""Tests for the farm vertical template content.

These tests verify that the farm manifest.yaml loads correctly as a
VerticalTemplate and that its entity templates, field types, admin
blocks, domain vocabulary, and signal thresholds all match expectations.

The tests depend on ``workbook.tools.vertical_registry.load_vertical``
which is provided by Phase 1 of the v0.3.0 vertical templates feature.
If Phase 1 has not been merged yet, these tests will fail with an
ImportError — that is expected and the tests remain valid.
"""

from __future__ import annotations

from workbook.tools.vertical_registry import load_vertical

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _get_column_names(entity_template: dict) -> list[str]:
    """Return list of column names from an entity template dict."""
    return [c["name"] for c in entity_template.get("columns", [])]


def _get_column_types(entity_template: dict) -> dict[str, str]:
    """Return dict mapping column name to data_type from an entity template."""
    return {c["name"]: c["data_type"] for c in entity_template.get("columns", [])}


# ---------------------------------------------------------------------------
# Test 1: Farm vertical loads with 4+ entity templates
# ---------------------------------------------------------------------------


class TestLoadFarmVertical:
    """Verify the farm vertical can be loaded and has expected structure."""

    def test_load_farm_vertical(self) -> None:
        """Farm vertical loads with 4+ entity templates."""
        farm = load_vertical("farm")

        assert farm.name == "farm"
        assert farm.version == "0.1.0"
        assert farm.description
        assert farm.confidence == "exploratory"
        assert farm.entity_templates is not None
        assert len(farm.entity_templates) >= 4

        expected_entities = {"Crop", "FieldBlock", "Season", "PlantingPlan"}
        loaded_entities = set(farm.entity_templates.keys())
        assert expected_entities.issubset(loaded_entities), (
            f"Expected entities {expected_entities}, got {loaded_entities}"
        )


# ---------------------------------------------------------------------------
# Test 2: Crop template has expected fields
# ---------------------------------------------------------------------------


class TestCropEntity:
    """Verify the Crop entity template."""

    def test_farm_entity_crop_fields(self) -> None:
        """Crop template has expected fields: crop_name, variety, days_to_maturity, is_perennial."""
        farm = load_vertical("farm")
        crop = farm.entity_templates["Crop"]

        column_names = _get_column_names(crop)

        assert "crop_name" in column_names
        assert "variety" in column_names
        assert "days_to_maturity" in column_names
        assert "is_perennial" in column_names

        # Verify crop_name is unique and required
        crop_name_def = next(c for c in crop["columns"] if c["name"] == "crop_name")
        assert crop_name_def["unique"] is True
        assert crop_name_def["null"] is False

        # Verify is_perennial defaults to false
        is_perennial_def = next(
            c for c in crop["columns"] if c["name"] == "is_perennial"
        )
        assert is_perennial_def.get("default") is False


# ---------------------------------------------------------------------------
# Test 3: FieldBlock template has expected fields
# ---------------------------------------------------------------------------


class TestFieldBlockEntity:
    """Verify the FieldBlock entity template."""

    def test_farm_entity_field_block_fields(self) -> None:
        """FieldBlock template has expected fields (10+ fields)."""
        farm = load_vertical("farm")
        field_block = farm.entity_templates["FieldBlock"]

        column_names = _get_column_names(field_block)
        assert len(column_names) >= 10, (
            f"FieldBlock has {len(column_names)} fields, expected 10+"
        )

        core_fields = {
            "name",
            "code",
            "acreage",
            "soil_type",
            "irrigation_type",
            "is_active",
            "notes",
        }
        assert core_fields.issubset(column_names), (
            f"Missing core FieldBlock fields. Expected {core_fields}, got {column_names}"
        )

        # Name should be unique
        name_def = next(c for c in field_block["columns"] if c["name"] == "name")
        assert name_def["unique"] is True


# ---------------------------------------------------------------------------
# Test 4: PlantingPlan has 20+ fields with proper FKs
# ---------------------------------------------------------------------------


class TestPlantingPlanEntity:
    """Verify the PlantingPlan entity template."""

    def test_farm_entity_planting_plan_fields(self) -> None:
        """PlantingPlan template has 20+ fields with FK references."""
        farm = load_vertical("farm")
        planting_plan = farm.entity_templates["PlantingPlan"]

        column_names = _get_column_names(planting_plan)
        assert len(column_names) >= 20, (
            f"PlantingPlan has {len(column_names)} fields, expected 20+"
        )

        # Verify FK fields reference other entities
        _column_types = _get_column_types(planting_plan)  # noqa: F841
        fk_columns = [
            c for c in planting_plan["columns"] if c.get("data_type") == "ForeignKey"
        ]
        assert len(fk_columns) >= 3, (
            f"PlantingPlan has {len(fk_columns)} FK fields, expected 3+"
        )

        # Verify specific FK targets
        fk_targets = {c["to"] for c in fk_columns if c.get("to")}
        assert "Crop" in fk_targets, "PlantingPlan should FK to Crop"
        assert "FieldBlock" in fk_targets, "PlantingPlan should FK to FieldBlock"
        assert "Season" in fk_targets, "PlantingPlan should FK to Season"

        # Verify core date fields
        assert "plant_date" in column_names
        assert "expected_harvest_date" in column_names
        assert "actual_harvest_date" in column_names

        # Verify planting_date is required
        plant_date_def = next(
            c for c in planting_plan["columns"] if c["name"] == "plant_date"
        )
        assert plant_date_def["null"] is False

        # Verify status field defaults
        status_def = next(c for c in planting_plan["columns"] if c["name"] == "status")
        assert status_def.get("default") == "planned"

        # Verify import_config has FK lookups
        import_config = planting_plan.get("import_config", {})
        fk_lookups = import_config.get("fk_lookup", {})
        assert "crop" in fk_lookups
        assert "field_block" in fk_lookups
        assert "season" in fk_lookups

        # Verify admin block has raw_id_fields for FKs
        admin_block = planting_plan.get("admin", {})
        raw_id_fields = admin_block.get("raw_id_fields", [])
        assert "crop" in raw_id_fields
        assert "field_block" in raw_id_fields
        assert "season" in raw_id_fields


# ---------------------------------------------------------------------------
# Test 5: Field types match heuristics
# ---------------------------------------------------------------------------


class TestFieldTypes:
    """Verify field types follow the vertical template heuristics."""

    def test_farm_field_types_match_heuristics(self) -> None:
        """CharField for names, DateField for dates, DecimalField for quantities,
        BooleanField for flags, IntegerField for counts."""
        farm = load_vertical("farm")

        # Collect all columns across all entities
        all_columns: list[dict] = []
        for entity_name, template in farm.entity_templates.items():
            for column in template.get("columns", []):
                all_columns.append(column)

        # Names should be CharField
        name_fields = [
            c for c in all_columns if c["name"] in ("crop_name", "name", "variety")
        ]
        for field in name_fields:
            assert field["data_type"] == "CharField", (
                f"Expected CharField for '{field['name']}', got {field['data_type']}"
            )

        # Date fields should be DateField
        date_fields = [
            c
            for c in all_columns
            if "date" in c["name"] or c["name"] in ("plant_date",)
        ]
        for field in date_fields:
            assert field["data_type"] == "DateField", (
                f"Expected DateField for '{field['name']}', got {field['data_type']}"
            )

        # Boolean fields should be BooleanField
        bool_fields = [c for c in all_columns if c.get("data_type") == "BooleanField"]
        bool_names = {c["name"] for c in bool_fields}
        assert "is_perennial" in bool_names
        assert "is_active" in bool_names
        assert "is_organic" in bool_names

        # Integer fields for counts
        count_fields = [c for c in all_columns if c.get("data_type") == "IntegerField"]
        count_names = {c["name"] for c in count_fields}
        assert "days_to_maturity" in count_names
        assert "beds_used" in count_names or "beds_count" in count_names

        # Decimal fields for quantities
        decimal_fields = [
            c for c in all_columns if c.get("data_type") == "DecimalField"
        ]
        decimal_names = {c["name"] for c in decimal_fields}
        assert "acreage" in decimal_names
        assert "quantity_planted" in decimal_names or "yield_expected" in decimal_names


# ---------------------------------------------------------------------------
# Test 6: Generated admin blocks are valid
# ---------------------------------------------------------------------------


class TestAdminBlocks:
    """Verify admin blocks from entity templates are valid."""

    def test_farm_template_generates_valid_admin(self) -> None:
        """Each entity template has a valid admin block with list_display."""
        farm = load_vertical("farm")

        for entity_name, template in farm.entity_templates.items():
            admin_block = template.get("admin")
            assert admin_block is not None, (
                f"Entity '{entity_name}' is missing admin block"
            )
            assert "list_display" in admin_block, (
                f"Entity '{entity_name}' admin block missing list_display"
            )
            assert len(admin_block["list_display"]) >= 2, (
                f"Entity '{entity_name}' list_display has fewer than 2 fields"
            )
            # Verify all list_display fields exist in columns
            column_names = set(_get_column_names(template))
            for display_field in admin_block["list_display"]:
                assert display_field in column_names, (
                    f"Entity '{entity_name}': list_display field '{display_field}' "
                    f"not found in columns"
                )


# ---------------------------------------------------------------------------
# Test 7: Domain context has farm vocabulary
# ---------------------------------------------------------------------------


class TestDomainContext:
    """Verify farm domain vocabulary and glossary."""

    def test_interview_presets_seeded(self) -> None:
        """domain_context has farm vocabulary with operational, reference,
        support, and derived terms."""
        farm = load_vertical("farm")

        domain_context = farm.domain_context
        assert domain_context is not None, "Missing domain_context"

        vocabulary = domain_context.get("vocabulary", {})
        assert "operational" in vocabulary, "Missing operational vocabulary"
        assert "reference" in vocabulary, "Missing reference vocabulary"
        assert "support" in vocabulary, "Missing support vocabulary"
        assert "derived" in vocabulary, "Missing derived vocabulary"

        # Verify known farm terms
        operational = vocabulary["operational"]
        assert "crop" in operational
        assert "field" in operational
        assert "planting" in operational

        # Verify glossary
        glossary = domain_context.get("glossary", {})
        assert "crop" in glossary
        assert glossary["crop"] == "product_variety"

        # Verify entities are defined
        entities = domain_context.get("entities", [])
        assert len(entities) >= 4
        entity_names = {e["name"] for e in entities}
        assert "Crop" in entity_names
        assert "FieldBlock" in entity_names
        assert "Season" in entity_names
        assert "PlantingPlan" in entity_names


# ---------------------------------------------------------------------------
# Test 8: Signal thresholds are populated
# ---------------------------------------------------------------------------


class TestSignalThresholds:
    """Verify farm-specific signal thresholds are populated."""

    def test_signal_thresholds_applied(self) -> None:
        """signal_thresholds are populated with farm-specific values."""
        farm = load_vertical("farm")

        signal_thresholds = farm.signal_thresholds
        assert signal_thresholds is not None, "Missing signal_thresholds"

        # Verify threshold keys
        assert "formula_density_low" in signal_thresholds
        assert "formula_density_high" in signal_thresholds
        assert "cross_sheet_ref_threshold" in signal_thresholds
        assert "expansion_formula_ratio_max" in signal_thresholds

        # Verify farm-specific values (farm operations have denser formulas
        # than generic spreadsheets due to yield/cost calculations)
        assert signal_thresholds["formula_density_low"] > 0
        assert signal_thresholds["formula_density_high"] > 0
        assert signal_thresholds["cross_sheet_ref_threshold"] > 0
        assert signal_thresholds["expansion_formula_ratio_max"] > 0
