from workbook.schema_contract import (
    build_contract,
    index_table_profile,
    _filter_section_headers,
    _compute_fk_resolutions,
    _suggest_import_keys,
    _add_source_bundle_year,
    _compute_bundle_paths,
)
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
        {
            "suggested_field_name": "crop",
            "source_column": "Crop",
            "django_field_class": "models.CharField",
        },
        {
            "suggested_field_name": "harvest_info",
            "source_column": "HARVEST INFO",
            "django_field_class": "models.TextField",
            "is_section_header": True,
        },
        {
            "suggested_field_name": "block",
            "source_column": "Block",
            "django_field_class": "models.CharField",
        },
    ]
    result = _filter_section_headers(columns)
    assert len(result) == 2
    names = [c["suggested_field_name"] for c in result]
    assert "harvest_info" not in names


def test_filter_section_headers_keeps_normal_columns():
    columns = [
        {
            "suggested_field_name": "crop",
            "source_column": "Crop",
            "django_field_class": "models.CharField",
        },
        {
            "suggested_field_name": "block",
            "source_column": "Block",
            "django_field_class": "models.CharField",
        },
    ]
    result = _filter_section_headers(columns)
    assert len(result) == 2


def test_compute_fk_resolutions_from_column_overlap():
    tables = [
        {
            "suggested_model_name": "CropPlanner",
            "model_name": "CropPlanner",
            "columns": [
                {
                    "suggested_field_name": "block",
                    "source_column": "Block",
                    "django_field_class": "models.CharField",
                    "unique_count": 15,
                    "total_count": 50,
                },
                {
                    "suggested_field_name": "crop",
                    "source_column": "Crop",
                    "django_field_class": "models.CharField",
                },
            ],
        },
        {
            "suggested_model_name": "FieldBlock",
            "model_name": "FieldBlock",
            "columns": [
                {
                    "suggested_field_name": "block",
                    "source_column": "Block",
                    "django_field_class": "models.CharField",
                    "unique_count": 15,
                    "total_count": 15,
                },
                {
                    "suggested_field_name": "description",
                    "source_column": "Description",
                    "django_field_class": "models.TextField",
                },
            ],
        },
    ]
    fks = _compute_fk_resolutions(tables)
    block_fk = [f for f in fks if f["field"] == "block"]
    assert len(block_fk) >= 1
    assert block_fk[0]["target_model"] == "FieldBlock"
    assert block_fk[0]["source"] == "column_overlap"


def test_suggest_import_keys_prefers_unique_name_columns():
    columns = [
        {
            "suggested_field_name": "crop",
            "source_column": "Crop",
            "unique_count": 20,
            "total_count": 50,
        },
        {
            "suggested_field_name": "block",
            "source_column": "Block",
            "unique_count": 15,
            "total_count": 50,
        },
        {
            "suggested_field_name": "product_sku",
            "source_column": "Product SKU",
            "unique_count": 50,
            "total_count": 50,
        },
    ]
    result = _suggest_import_keys(columns)
    assert "fields" in result
    assert "product_sku" in result["fields"]


def test_add_source_bundle_year():
    tables = [
        {
            "suggested_model_name": "Crop",
            "model_name": "Crop",
            "columns": [
                {
                    "suggested_field_name": "crop",
                    "source_column": "Crop",
                    "django_field_class": "models.CharField",
                },
            ],
            "import_config": {},
        },
    ]
    result = _add_source_bundle_year(tables, year=2024)
    assert result[0]["columns"][-1]["suggested_field_name"] == "source_bundle_year"
    assert result[0]["import_config"]["defaults"]["source_bundle_year"] == 2024


def test_add_source_bundle_year_no_year():
    tables = [
        {
            "suggested_model_name": "empty",
            "model_name": "Empty",
            "columns": [],
            "import_config": {},
        }
    ]
    result = _add_source_bundle_year(tables, year=None)
    assert result == tables


def test_compute_bundle_paths_with_year():
    tables = [
        {
            "suggested_model_name": "Crop",
            "model_name": "Crop",
            "bundle_worksheet_title": "Crop Info",
            "import_config": {},
        },
    ]
    result = _compute_bundle_paths(tables, year=2024)
    assert result[0]["import_config"]["bundle_path"] == "2024/crop_info.csv"


def test_compute_bundle_paths_without_year():
    tables = [
        {
            "suggested_model_name": "Crop",
            "model_name": "Crop",
            "bundle_worksheet_title": "Crop Info",
            "import_config": {},
        },
    ]
    result = _compute_bundle_paths(tables, year=None)
    assert result[0]["import_config"]["bundle_path"] == "crop_info.csv"


def test_index_table_profile_returns_formula_classifications():
    payload = {
        "summary": {
            "table_name": "Orders",
            "columns": [
                {"name": "Total", "format_type": "number", "has_formula": True},
            ],
            "relation_columns": [],
            "formula_classifications": [
                {
                    "column_name": "Total",
                    "formula_text": "Sum([Items].[Amount])",
                    "classification": "expansion_formula",
                    "confidence": "high",
                }
            ],
        }
    }
    name, col_meta, rels, fcs = index_table_profile(payload)
    assert name == "Orders"
    assert len(fcs) == 1
    assert fcs[0]["classification"] == "expansion_formula"


def test_build_contract_marks_expansion_formula_as_computed():
    bundle = {
        "provider": "coda",
        "tabs": [
            {
                "worksheet_title": "Orders",
                "output_path": "reference/orders.csv",
                "required_headers": ["Total"],
            }
        ],
    }
    tp = {
        "summary": {
            "table_name": "Orders",
            "columns": [
                {
                    "name": "Total",
                    "format_type": "number",
                    "has_formula": True,
                    "null_rate": 0.0,
                    "is_relation_type": False,
                },
            ],
            "relation_columns": [],
            "formula_classifications": [
                {
                    "column_name": "Total",
                    "formula_text": "Sum([Items].[Amount])",
                    "classification": "expansion_formula",
                    "confidence": "high",
                }
            ],
        }
    }
    contract = build_contract(bundle, table_profiles={"Orders": tp})
    table = contract["tables"][0]
    total_col = next(c for c in table["columns"] if c["source_column"] == "Total")
    assert total_col["is_computed"] is True
    assert any("coda_formula:expansion_formula" in n for n in total_col["notes"])


def test_build_contract_row_formula_gets_note_not_computed():
    bundle = {
        "provider": "coda",
        "tabs": [
            {
                "worksheet_title": "Orders",
                "output_path": "reference/orders.csv",
                "required_headers": ["Line Total"],
            }
        ],
    }
    tp = {
        "summary": {
            "table_name": "Orders",
            "columns": [
                {
                    "name": "Line Total",
                    "format_type": "number",
                    "has_formula": True,
                    "null_rate": 0.0,
                    "is_relation_type": False,
                },
            ],
            "relation_columns": [],
            "formula_classifications": [
                {
                    "column_name": "Line Total",
                    "formula_text": "thisRow.Price * thisRow.Qty",
                    "classification": "row_formula",
                    "confidence": "high",
                }
            ],
        }
    }
    contract = build_contract(bundle, table_profiles={"Orders": tp})
    table = contract["tables"][0]
    col = next(c for c in table["columns"] if c["source_column"] == "Line Total")
    assert col["is_computed"] is False
    assert any("coda_formula:row_formula" in n for n in col["notes"])


def test_build_contract_hybrid_formula_gets_note():
    bundle = {
        "provider": "coda",
        "tabs": [
            {
                "worksheet_title": "Orders",
                "output_path": "reference/orders.csv",
                "required_headers": ["Weighted"],
            }
        ],
    }
    tp = {
        "summary": {
            "table_name": "Orders",
            "columns": [
                {
                    "name": "Weighted",
                    "format_type": "number",
                    "has_formula": True,
                    "null_rate": 0.0,
                    "is_relation_type": False,
                },
            ],
            "relation_columns": [],
            "formula_classifications": [
                {
                    "column_name": "Weighted",
                    "formula_text": "thisRow.Price * Sum([Items].[Amount])",
                    "classification": "hybrid",
                    "confidence": "medium",
                }
            ],
        }
    }
    contract = build_contract(bundle, table_profiles={"Orders": tp})
    table = contract["tables"][0]
    col = next(c for c in table["columns"] if c["source_column"] == "Weighted")
    assert any("coda_formula:hybrid" in n for n in col["notes"])


def test_build_contract_adds_model_name():
    config = {
        "source": "test",
        "tabs": [
            {
                "worksheet_title": "Sales Channel",
                "output_path": "reference/sales_channels.csv",
                "required_headers": ["Name"],
            }
        ],
    }
    contract = build_contract(config)
    assert len(contract["tables"]) == 1
    table = contract["tables"][0]
    assert "model_name" in table
    assert table["model_name"] == "SalesChannels"


def test_build_contract_coda_relation_column_upgrades_to_fk():
    bundle = {
        "provider": "coda",
        "tabs": [
            {
                "worksheet_title": "Tasks",
                "output_path": "reference/tasks.csv",
                "required_headers": ["Name", "Project"],
            },
            {
                "worksheet_title": "Projects",
                "output_path": "reference/projects.csv",
                "required_headers": ["Name"],
            },
        ],
    }
    tp = {
        "summary": {
            "table_name": "Tasks",
            "columns": [
                {
                    "name": "Name",
                    "format_type": "text",
                    "has_formula": False,
                    "null_rate": 0.0,
                    "is_relation_type": False,
                },
                {
                    "name": "Project",
                    "format_type": "lookup",
                    "has_formula": False,
                    "null_rate": 0.1,
                    "is_relation_type": True,
                },
            ],
            "relation_columns": [
                {
                    "column_name": "Project",
                    "column_type": "lookup",
                    "target_table_name": "Projects",
                    "target_table_id": "t-proj",
                    "is_bidirectional": False,
                    "notes": [],
                }
            ],
        }
    }
    contract = build_contract(
        bundle,
        table_profiles={"Tasks": tp},
    )
    tasks_table = contract["tables"][0]
    assert tasks_table["bundle_worksheet_title"] == "Tasks"
    proj_col = next(c for c in tasks_table["columns"] if c["source_column"] == "Project")
    assert proj_col["django_field_class"] == "models.ForeignKey"
    assert proj_col["django_field_kwargs"]["to"] == "Projects"
    assert "coda_relation:lookup" in proj_col["notes"]
    assert "fk_resolutions" in tasks_table
    fk = tasks_table["fk_resolutions"]
    assert any(f["field"] == "project" and f["target_model"] == "Projects" for f in fk)


def test_build_contract_coda_person_column_upgrades_to_auth_user_fk():
    """Person columns with is_user_reference are upgraded to ForeignKey(auth.User).

    When extract_relation_columns detects a format.type == 'person' column,
    it emits is_user_reference=True and target_table_name='auth.User'.
    build_contract must consume this and set the column's field class to
    ForeignKey with to='auth.User'.
    """
    bundle = {
        "provider": "coda",
        "tabs": [
            {
                "worksheet_title": "WorkOrders",
                "output_path": "domain/work_orders.csv",
                "required_headers": ["Title", "Created By"],
            }
        ],
    }
    tp = {
        "summary": {
            "table_name": "WorkOrders",
            "columns": [
                {
                    "name": "Title",
                    "format_type": "text",
                    "has_formula": False,
                    "null_rate": 0.0,
                    "is_relation_type": False,
                },
                {
                    "name": "Created By",
                    "format_type": "person",
                    "has_formula": False,
                    "null_rate": 0.0,
                    "is_relation_type": False,
                },
            ],
            "relation_columns": [
                {
                    "column_name": "Created By",
                    "column_type": "person",
                    "target_table_name": "auth.User",
                    "target_table_id": None,
                    "is_bidirectional": False,
                    "is_user_reference": True,
                    "notes": ["person_reference_resolved_to_auth_user"],
                }
            ],
        }
    }
    contract = build_contract(bundle, table_profiles={"WorkOrders": tp})
    orders_table = contract["tables"][0]
    assert orders_table["bundle_worksheet_title"] == "WorkOrders"
    creator_col = next(
        c for c in orders_table["columns"] if c["source_column"] == "Created By"
    )
    assert creator_col["django_field_class"] == "models.ForeignKey"
    assert creator_col["django_field_kwargs"]["to"] == "auth.User"
    assert "coda_relation:person" in creator_col["notes"]
    assert "fk_resolutions" in orders_table
    fk = orders_table["fk_resolutions"]
    assert any(
        f["field"] == "created_by"
        and f["target_model"] == "auth.User"
        and f["source"] == "coda_relation_column"
        for f in fk
    )


def test_build_contract_coda_relation_missing_target_uses_todo():
    bundle = {
        "provider": "coda",
        "tabs": [
            {
                "worksheet_title": "Items",
                "output_path": "reference/items.csv",
                "required_headers": ["Name", "Parent"],
            }
        ],
    }
    tp = {
        "summary": {
            "table_name": "Items",
            "columns": [
                {
                    "name": "Name",
                    "format_type": "text",
                    "has_formula": False,
                    "null_rate": 0.0,
                },
                {
                    "name": "Parent",
                    "format_type": "lookup",
                    "has_formula": False,
                    "null_rate": 0.2,
                    "is_relation_type": True,
                },
            ],
            "relation_columns": [
                {
                    "column_name": "Parent",
                    "column_type": "lookup",
                    "target_table_name": None,
                    "target_table_id": None,
                    "is_bidirectional": False,
                    "notes": ["lookup_target_table_not_exposed_in_api"],
                }
            ],
        }
    }
    contract = build_contract(bundle, table_profiles={"Items": tp})
    table = contract["tables"][0]
    parent_col = next(c for c in table["columns"] if c["source_column"] == "Parent")
    assert parent_col["django_field_class"] == "models.ForeignKey"
    assert parent_col["django_field_kwargs"]["to"] == "TODO_Parent"
    assert "fk_resolutions" in table
    fk = table["fk_resolutions"]
    assert any(f["field"] == "parent" and f["target_model"] == "TODO_Parent" for f in fk)
