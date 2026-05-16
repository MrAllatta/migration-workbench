from workbook.schema_contract import build_contract, _filter_section_headers, _compute_fk_resolutions, _suggest_import_keys, _add_source_bundle_year
from workbook.field_mapping import map_profiler_column_to_django_field


def test_build_contract_with_table_profile():
    bundle = {
        "provider": "coda",
        "doc_url": "https://example.invalid/d",
        "tabs": [
            {
                "worksheet_title": "Clients",
                "output_path": "reference/clients.csv",
                "required_headers": ["First", "Last"],
            }
        ],
    }
    tp = {
        "summary": {
            "table_name": "Clients",
            "columns": [
                {
                    "name": "First",
                    "format_type": "text",
                    "has_formula": False,
                    "null_rate": 0.0,
                    "is_relation_type": False,
                },
                {
                    "name": "Last",
                    "format_type": "checkbox",
                    "has_formula": False,
                    "is_relation_type": False,
                },
            ],
        }
    }
    contract = build_contract(
        bundle,
        doc_profile=None,
        table_profiles={"Clients": tp},
    )
    assert contract["version"] == "1.0"
    assert len(contract["tables"]) == 1
    tab = contract["tables"][0]
    assert tab["suggested_model_name"] == "clients"
    names = [c["source_column"] for c in tab["columns"]]
    assert names[0] == "First"
    assert tab["columns"][0]["django_field_class"] == "models.TextField"


def test_build_contract_bundle_only_falls_back_to_required_headers():
    bundle = {
        "provider": "coda",
        "tabs": [
            {
                "worksheet_title": "Orders",
                "output_path": "sales/orders.csv",
                "required_headers": ["Order Id", "Total"],
            }
        ],
    }
    contract = build_contract(bundle)
    col = contract["tables"][0]["columns"]
    assert len(col) == 2
    assert col[0]["source_column"] == "Order Id"


def test_relation_column_maps_to_foreign_key_placeholder():
    mapped = map_profiler_column_to_django_field(
        {
            "name": "Customer",
            "format_type": "lookup",
            "is_relation_type": True,
            "null_rate": 0.1,
            "sample_size": 500,
        }
    )
    assert mapped["django_field_class"] == "models.ForeignKey"
    assert mapped["django_field_kwargs"]["to"] == "TODO_TargetModel"
    assert any(note.startswith("relation_target_todo") for note in mapped["notes"])


def test_zero_null_rate_does_not_drop_null_for_small_sample():
    mapped = map_profiler_column_to_django_field(
        {
            "name": "Amount",
            "format_type": "number",
            "null_rate": 0,
            "sample_size": 50,
        }
    )
    assert mapped["django_field_class"] == "models.DecimalField"
    assert mapped["django_field_kwargs"]["null"] is True
    assert "nullability_not_hardened_low_sample" in mapped["notes"]


def test_text_type_defaults_to_textfield():
    mapped = map_profiler_column_to_django_field(
        {
            "name": "Notes",
            "format_type": "text",
        }
    )
    assert mapped["django_field_class"] == "models.TextField"
    assert "max_length" not in mapped["django_field_kwargs"]


def test_contract_scaffold_auto_generates_import_config():
    """build_contract should seed import_config for each table."""
    bundle = {
        "provider": "google_sheets",
        "tabs": [
            {
                "worksheet_title": "Crop Info",
                "output_path": "reference/crop_info.csv",
                "required_headers": ["Crop", "Type"],
            },
        ],
    }
    contract = build_contract(bundle)
    table = contract["tables"][0]
    assert "import_config" in table
    assert table["import_config"]["bundle_path"] == "reference/crop_info.csv"
    assert "Crop" in table["import_config"]["required_headers"]
    assert table["import_config"]["unique_on"] is not None


def test_filter_section_headers_removes_all_caps_low_unique():
    columns = [
        {"suggested_field_name": "crop", "source_column": "Crop", "django_field_class": "models.CharField"},
        {"suggested_field_name": "harvest_info", "source_column": "HARVEST INFO", "django_field_class": "models.TextField", "is_section_header": True},
        {"suggested_field_name": "block", "source_column": "Block", "django_field_class": "models.CharField"},
    ]
    result = _filter_section_headers(columns)
    assert len(result) == 2
    names = [c["suggested_field_name"] for c in result]
    assert "harvest_info" not in names


def test_filter_section_headers_keeps_normal_columns():
    columns = [
        {"suggested_field_name": "crop", "source_column": "Crop", "django_field_class": "models.CharField"},
        {"suggested_field_name": "block", "source_column": "Block", "django_field_class": "models.CharField"},
    ]
    result = _filter_section_headers(columns)
    assert len(result) == 2


def test_compute_fk_resolutions_from_column_overlap():
    tables = [
        {"suggested_model_name": "CropPlanner", "columns": [
            {"suggested_field_name": "block", "source_column": "Block", "django_field_class": "models.CharField", "unique_count": 15, "total_count": 50},
            {"suggested_field_name": "crop", "source_column": "Crop", "django_field_class": "models.CharField"},
        ]},
        {"suggested_model_name": "FieldBlock", "columns": [
            {"suggested_field_name": "block", "source_column": "Block", "django_field_class": "models.CharField", "unique_count": 15, "total_count": 15},
            {"suggested_field_name": "description", "source_column": "Description", "django_field_class": "models.TextField"},
        ]},
    ]
    fks = _compute_fk_resolutions(tables)
    block_fk = [f for f in fks if f["field"] == "block"]
    assert len(block_fk) >= 1
    assert block_fk[0]["target_model"] == "FieldBlock"
    assert block_fk[0]["source"] == "column_overlap"


def test_suggest_import_keys_prefers_unique_name_columns():
    columns = [
        {"suggested_field_name": "crop", "source_column": "Crop", "unique_count": 20, "total_count": 50},
        {"suggested_field_name": "block", "source_column": "Block", "unique_count": 15, "total_count": 50},
        {"suggested_field_name": "product_sku", "source_column": "Product SKU", "unique_count": 50, "total_count": 50},
    ]
    result = _suggest_import_keys(columns)
    assert "fields" in result
    assert "product_sku" in result["fields"]


def test_add_source_bundle_year():
    tables = [
        {"suggested_model_name": "Crop", "columns": [
            {"suggested_field_name": "crop", "source_column": "Crop", "django_field_class": "models.CharField"},
        ], "import_config": {}},
    ]
    result = _add_source_bundle_year(tables, year=2024)
    assert result[0]["columns"][-1]["suggested_field_name"] == "source_bundle_year"
    assert result[0]["import_config"]["defaults"]["source_bundle_year"] == 2024


def test_add_source_bundle_year_no_year():
    tables = [{"columns": [], "import_config": {}}]
    result = _add_source_bundle_year(tables, year=None)
    assert result == tables
