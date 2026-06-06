"""Tests for the vertical template registry."""

from __future__ import annotations

import copy
from pathlib import Path
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from workbook.tools.vertical_registry import (
    VerticalTemplate,
    apply_vertical_to_schema,
    discover_verticals,
    load_vertical,
    merge_entity_template,
    score_tab_against_templates,
)


# ---------------------------------------------------------------------------
# discover_verticals
# ---------------------------------------------------------------------------


def test_discover_example_vertical():
    """discover_verticals() returns the example vertical."""
    verticals = discover_verticals()
    names = [v["name"] for v in verticals]
    assert "example" in names
    example = next(v for v in verticals if v["name"] == "example")
    assert example["version"] == "0.1.0"
    assert example["confidence"] == "exploratory"
    assert example["source"] == "package"


def test_discover_empty():
    """No spurious results from empty directories (no file fixture needed)."""
    verticals = discover_verticals()
    # Should only contain real verticals, not random dirs.
    for v in verticals:
        assert isinstance(v["name"], str)
        assert v["name"]
        assert v["version"]


# ---------------------------------------------------------------------------
# load_vertical
# ---------------------------------------------------------------------------


def test_load_example_vertical():
    """load_vertical('example') returns a valid VerticalTemplate."""
    template = load_vertical("example")
    assert isinstance(template, VerticalTemplate)
    assert template.name == "example"
    assert template.version == "0.1.0"
    assert template.description == "Example vertical template for testing"
    assert template.confidence == "exploratory"
    assert template.entity_templates is not None
    assert "Widget" in template.entity_templates
    assert "Category" in template.entity_templates
    assert template.domain_context is not None


def test_load_nonexistent_raises():
    """load_vertical('nonexistent') raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_vertical("nonexistent")


# ---------------------------------------------------------------------------
# merge_entity_template
# ---------------------------------------------------------------------------


def test_merge_entity_template_fields():
    """Existing fields in the contract table win over template fields."""
    contract_table = {
        "model_name": "Widget",
        "columns": [
            {
                "suggested_field_name": "name",
                "source_column": "Name",
                "django_field_class": "models.CharField",
                "django_field_kwargs": {"max_length": 300, "null": False},
            },
            {
                "suggested_field_name": "quantity",
                "source_column": "Qty",
                "django_field_class": "models.IntegerField",
                "django_field_kwargs": {"null": False, "default": 1},
            },
        ],
    }
    entity_template = {
        "columns": [
            {
                "name": "name",
                "data_type": "CharField",
                "max_length": 200,
                "null": False,
            },
            {
                "name": "quantity",
                "data_type": "IntegerField",
                "null": False,
                "default": 0,
            },
        ],
    }
    merged = merge_entity_template(contract_table, entity_template)
    # Contract fields should win: max_length stays 300, quantity default stays 1
    columns = merged["columns"]
    name_col = next(c for c in columns if c["suggested_field_name"] == "name")
    qty_col = next(c for c in columns if c["suggested_field_name"] == "quantity")
    assert name_col["django_field_kwargs"]["max_length"] == 300
    assert qty_col["django_field_kwargs"]["default"] == 1


def test_merge_entity_template_new_fields():
    """Template can add fields that do not exist in the contract table."""
    contract_table = {
        "model_name": "Widget",
        "columns": [
            {
                "suggested_field_name": "name",
                "source_column": "Name",
                "django_field_class": "models.CharField",
                "django_field_kwargs": {"max_length": 200, "null": False},
            },
        ],
    }
    entity_template = {
        "columns": [
            {
                "name": "name",
                "data_type": "CharField",
                "max_length": 200,
                "null": False,
            },
            {
                "name": "quantity",
                "data_type": "IntegerField",
                "null": False,
                "default": 0,
            },
        ],
    }
    merged = merge_entity_template(contract_table, entity_template)
    column_names = [c["suggested_field_name"] for c in merged["columns"]]
    assert "name" in column_names
    assert "quantity" in column_names


def test_merge_entity_template_admin():
    """Admin blocks from template are merged into the contract table."""
    contract_table = {
        "model_name": "Widget",
        "columns": [
            {
                "suggested_field_name": "name",
                "source_column": "Name",
                "django_field_class": "models.CharField",
                "django_field_kwargs": {"max_length": 200},
            },
        ],
    }
    entity_template = {
        "columns": [
            {
                "name": "name",
                "data_type": "CharField",
                "max_length": 200,
                "null": False,
            },
        ],
        "admin": {
            "list_display": ["name", "quantity"],
            "search_fields": ["name"],
        },
    }
    merged = merge_entity_template(contract_table, entity_template)
    assert "admin" in merged
    assert merged["admin"]["list_display"] == ["name", "quantity"]
    assert merged["admin"]["search_fields"] == ["name"]


def test_merge_entity_template_import_config():
    """Import config from template is merged into the contract table."""
    contract_table = {
        "model_name": "Widget",
        "columns": [
            {
                "suggested_field_name": "name",
                "source_column": "Name",
                "django_field_class": "models.CharField",
                "django_field_kwargs": {"max_length": 200},
            },
        ],
    }
    entity_template = {
        "columns": [
            {
                "name": "name",
                "data_type": "CharField",
                "max_length": 200,
                "null": False,
            },
        ],
        "import_config": {
            "unique_on": ["name"],
            "column_map": {"name": "Name"},
        },
    }
    merged = merge_entity_template(contract_table, entity_template)
    assert "import_config" in merged
    assert merged["import_config"]["unique_on"] == ["name"]


def test_merge_priority_user_wins():
    """User-provided field type overrides template field type."""
    contract_table = {
        "model_name": "Widget",
        "columns": [
            {
                "suggested_field_name": "quantity",
                "source_column": "Quantity",
                "django_field_class": "models.DecimalField",
                "django_field_kwargs": {
                    "max_digits": 10,
                    "decimal_places": 2,
                    "null": False,
                    "default": 0.0,
                },
            },
        ],
    }
    entity_template = {
        "columns": [
            {
                "name": "quantity",
                "data_type": "IntegerField",
                "null": False,
                "default": 0,
            },
        ],
    }
    merged = merge_entity_template(contract_table, entity_template)
    qty_col = next(
        c
        for c in merged["columns"]
        if c["suggested_field_name"] == "quantity"
    )
    # User's DecimalField should win over template's IntegerField
    assert qty_col["django_field_class"] == "models.DecimalField"
    assert qty_col["django_field_kwargs"]["max_digits"] == 10


# ---------------------------------------------------------------------------
# apply_vertical_to_schema
# ---------------------------------------------------------------------------


def _make_vertical(entity_templates: dict | None = None) -> VerticalTemplate:
    """Helper to build a VerticalTemplate for testing."""
    return VerticalTemplate(
        name="test",
        version="0.1.0",
        description="Test vertical",
        entity_templates=entity_templates or {},
    )


def test_apply_vertical_to_schema_entity_match():
    """Schema table with matching model name gets enriched by entity template."""
    vertical = _make_vertical(
        {
            "Widget": {
                "columns": [
                    {
                        "name": "name",
                        "data_type": "CharField",
                        "max_length": 200,
                        "null": False,
                    },
                ],
                "admin": {
                    "list_display": ["name"],
                },
            },
        }
    )
    schema_contract = {
        "tables": [
            {
                "model_name": "Widget",
                "bundle_worksheet_title": "Widgets",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "source_column": "Name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200, "null": False},
                    },
                ],
            },
            {
                "model_name": "Other",
                "bundle_worksheet_title": "Others",
                "columns": [
                    {
                        "suggested_field_name": "other_name",
                        "source_column": "Other",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 100},
                    },
                ],
            },
        ]
    }
    enriched = apply_vertical_to_schema(schema_contract, vertical)
    widget_table = enriched["tables"][0]
    assert "admin" in widget_table
    assert widget_table["admin"]["list_display"] == ["name"]
    other_table = enriched["tables"][1]
    assert "admin" not in other_table


def test_apply_vertical_to_schema_no_match():
    """Schema table with no matching entity template is unchanged."""
    vertical = _make_vertical(
        {
            "Widget": {
                "columns": [
                    {
                        "name": "name",
                        "data_type": "CharField",
                        "max_length": 200,
                    },
                ],
            },
        }
    )
    schema_contract = {
        "tables": [
            {
                "model_name": "Other",
                "columns": [
                    {
                        "suggested_field_name": "other_name",
                        "source_column": "Other",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 100},
                    },
                ],
            },
        ]
    }
    enriched = apply_vertical_to_schema(copy.deepcopy(schema_contract), vertical)
    assert enriched["tables"] == schema_contract["tables"]


# ---------------------------------------------------------------------------
# User vertical overrides package template
# ---------------------------------------------------------------------------


def test_user_vertical_overrides_package(tmp_path: Path):
    """User-supplied vertical_dir template wins over built-in template."""
    user_dir = tmp_path / "verticals"
    user_manifest = user_dir / "example" / "manifest.yaml"
    user_manifest.parent.mkdir(parents=True)
    user_manifest.write_text(
        "name: example\n"
        'version: "0.2.0"\n'
        "description: User overridden example\n"
        "confidence: medium\n"
        "entity_templates:\n"
        "  Widget:\n"
        "    columns:\n"
        '      - name: name\n'
        "        data_type: CharField\n"
        "        max_length: 500\n"
        "        null: false\n"
    )
    template = load_vertical("example", vertical_dir=str(user_dir))
    assert template.version == "0.2.0"
    assert template.description == "User overridden example"
    assert template.confidence == "medium"
    # Field from user template should have max_length 500
    widget = template.entity_templates["Widget"]
    name_col = next(c for c in widget["columns"] if c["name"] == "name")
    assert name_col["max_length"] == 500


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_vertical_flag_on_scaffold(tmp_path: Path):
    """--vertical flag is accepted on scaffold command."""
    out = tmp_path / "contract.yaml"
    # Use minimal bundle config with --vertical example; this should not crash.
    call_command(
        "scaffold_workbook_schema",
        "--vertical",
        "example",
        "--bundle-config",
        str(
            Path(__file__).parent.parent.parent
            / "example_data"
            / "scaffold_workbook_bundle.example.json"
        ),
        "--out",
        str(out),
    )
    assert out.exists()
    import yaml
    with out.open() as f:
        contract_data = yaml.safe_load(f) or {}
    for table in contract_data.get("tables", []):
        assert "admin" not in table, f"Table {table.get('model_name')} got unexpected vertical admin block"


def test_no_vertical_flag_disabled(tmp_path: Path):
    """--no-vertical flag disables vertical template loading."""
    out = tmp_path / "contract.yaml"
    call_command(
        "scaffold_workbook_schema",
        "--no-vertical",
        "--bundle-config",
        str(
            Path(__file__).parent.parent.parent
            / "example_data"
            / "scaffold_workbook_bundle.example.json"
        ),
        "--out",
        str(out),
    )
    assert out.exists()


def test_score_tab_exact_title_match():
    """Tab titled 'Widget' scores high for Widget entity."""
    # Load the example vertical
    vertical = load_vertical("example")
    
    # Score a tab with exact title match; "name" is in GENERIC_HEADERS
    # so it is excluded from column-overlap scoring. Only "quantity"
    # (non-generic) counts toward the field score.
    results = score_tab_against_templates("Widget", ["quantity"], vertical)
    
    # Should find Widget with high confidence
    assert len(results) > 0
    widget_result = next((r for r in results if r["entity_name"] == "Widget"), None)
    assert widget_result is not None
    # Title exact match → 1.0, field score 1/1 → 1.0, weighted: 1.0
    assert widget_result["confidence"] >= 0.9
    assert "quantity" in widget_result["matched_headers"]


def test_score_tab_partial_field_match():
    """Tab with one non-generic field match gets moderate score."""
    # Load the example vertical
    vertical = load_vertical("example")
    
    # Score a tab with partial field match.
    # The Widget template has non-generic column "quantity" only
    # (since "name" is in GENERIC_HEADERS). A tab that includes
    # "quantity" gets a field score of 1/1 = 1.0, but a mismatched
    # title ("Other Tab" vs "Widget") gives a low title score.
    results = score_tab_against_templates("Other Tab", ["quantity"], vertical)
    
    # Should find Widget with moderate confidence
    assert len(results) > 0
    widget_result = next((r for r in results if r["entity_name"] == "Widget"), None)
    assert widget_result is not None
    # Title mismatch → ~0.0 title score, field match 1/1 → 1.0
    # Weighted: 0.4 * 0.0 + 0.6 * 1.0 = 0.6
    assert widget_result["confidence"] >= 0.5
    assert widget_result["confidence"] <= 0.7
    assert "quantity" in widget_result["matched_headers"]


def test_vertical_cli_invalid_name(tmp_path: Path):
    """Passing a nonexistent vertical name produces a clear error."""
    out = tmp_path / "contract.yaml"
    with pytest.raises(CommandError) as exc_info:
        call_command(
            "scaffold_workbook_schema",
            "--vertical",
            "nonexistent",
            "--bundle-config",
            str(
                Path(__file__).parent.parent.parent
                / "example_data"
                / "scaffold_workbook_bundle.example.json"
            ),
            "--out",
            str(out),
        )
    assert "nonexistent" in str(exc_info.value)


def test_apply_vertical_domain_context_merge():
    """apply_vertical_domain_context() merges domain vocab correctly."""
    from workbook.tools.vertical_registry import apply_vertical_domain_context, VerticalTemplate
    
    # Create a vertical with domain context
    vertical = VerticalTemplate(
        name="test",
        version="0.1.0",
        description="Test vertical",
        domain_context={
            "vocabulary": {
                "operational": ["crop", "field"],
                "reference": ["type", "unit"]
            },
            "glossary": {
                "crop": "product_variety",
                "field": "land_area"
            },
            "entities": [
                {"name": "Crop", "description": "A crop variety"},
                {"name": "Field", "description": "A field"}
            ]
        },
        entity_templates={}  # Initialize to empty dict to avoid None
    )
    
    # Existing domain context with some overlapping and some new keys
    existing = {
        "vocabulary": {
            "operational": ["planting", "harvest"],  # "planting" and "harvest" are new
            "lookup": ["category"]  # entirely new category
        },
        "glossary": {
            "planting": "seeding_event",  # new glossary entry
            "crop": "cultivar"  # conflicts with vertical's "crop": "product_variety"
        },
        "entities": [
            {"name": "Planting", "description": "A planting event"},  # new entity
            {"name": "Crop", "description": "A cultivated plant"}  # conflicts with vertical's Crop
        ]
    }
    
    result = apply_vertical_domain_context(vertical, existing)
    
    # Verify vocabulary merge: existing wins on conflict within subkeys
    assert result["vocabulary"]["operational"] == ["planting", "harvest"]  # existing wins
    assert result["vocabulary"]["reference"] == ["type", "unit"]  # from vertical
    assert result["vocabulary"]["lookup"] == ["category"]  # from existing (new category)
    
    # Verify glossary merge: existing wins on conflict within subkeys
    assert result["glossary"]["crop"] == "cultivar"  # existing wins
    assert result["glossary"]["field"] == "land_area"  # from vertical
    assert result["glossary"]["planting"] == "seeding_event"  # from existing
    
    # Verify entities merge: existing wins on conflict within subkeys
    entity_names = [e["name"] for e in result["entities"]]
    assert "Planting" in entity_names  # from existing
    assert "Crop" in entity_names  # from existing (conflict resolved)
    assert "Field" in entity_names  # from vertical
    
    # Verify that existing Crop description wins over vertical's
    crop_entity = next(e for e in result["entities"] if e["name"] == "Crop")
    assert crop_entity["description"] == "A cultivated plant"  # from existing


def test_apply_vertical_domain_context_user_wins():
    """apply_vertical_domain_context() ensures existing context overrides vertical."""
    from workbook.tools.vertical_registry import apply_vertical_domain_context, VerticalTemplate
    
    # Create a vertical with domain context
    vertical = VerticalTemplate(
        name="test",
        version="0.1.0",
        description="Test vertical",
        domain_context={
            "vocabulary": {
                "operational": ["crop", "field"]
            },
            "glossary": {
                "crop": "product_variety"
            },
            "entities": [
                {"name": "Crop", "description": "A crop variety"}
            ]
        },
        entity_templates={}  # Initialize to empty dict to avoid None
    )
    
    # Existing domain context that should override vertical
    existing = {
        "vocabulary": {
            "operational": ["plant"]  # completely different value
        },
        "glossary": {
            "crop": "cultivar"  # different value
        },
        "entities": [
            {"name": "Crop", "description": "A cultivated plant"}  # different description
        ]
    }
    
    result = apply_vertical_domain_context(vertical, existing)
    
    # Existing should win completely for conflicting keys
    assert result["vocabulary"]["operational"] == ["plant"]  # existing value
    assert result["glossary"]["crop"] == "cultivar"  # existing value
    
    # Entity from existing should win
    crop_entity = next(e for e in result["entities"] if e["name"] == "Crop")
    assert crop_entity["description"] == "A cultivated plant"  # existing value
    
    # Test with None existing context
    result_none = apply_vertical_domain_context(vertical, None)
    assert result_none == vertical.domain_context
    
    # Test with empty existing context
    result_empty = apply_vertical_domain_context(vertical, {})
    assert result_empty == vertical.domain_context
