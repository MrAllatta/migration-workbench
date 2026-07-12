"""Tests for the scaffold_workbook_schema management command."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from workbook.management.commands.scaffold_workbook_schema import (
    _to_pascal_case,
    _flag_fk_columns,
    _flag_computed_fields,
    _suggest_tab_merges,
    _merge_domain_knowledge,
    _harden_contract,
    _infer_format_type_from_samples,
    _check_null_model_names,
    _check_pivot_tables,
    _check_invalid_identifiers,
    _sanitize_python_identifier,
    _sanitize_table_identifiers,
    _validate_tables_for_scaffold,
)
from workbook.schema_contract import build_contract


def test_to_pascal_case_preserves_pascalcase():
    """Input that is already PascalCase passes through unchanged."""
    assert _to_pascal_case("SalesChannel") == "SalesChannel"
    assert _to_pascal_case("FarmUser") == "FarmUser"
    assert _to_pascal_case("FieldBlock") == "FieldBlock"


def test_to_pascal_case_converts_snake_case():
    """Standard snake_case to PascalCase conversion still works."""
    assert _to_pascal_case("sales_channel") == "SalesChannel"
    assert _to_pascal_case("farm_user") == "FarmUser"
    assert _to_pascal_case("field_block") == "FieldBlock"


def test_scaffold_stores_app_label_in_contract(tmp_path, monkeypatch):
    """scaffold_workbook_schema should store --models-app-label in each table's model_meta."""
    bundle = tmp_path / "bundle.json"
    bundle.write_text(
        '{"provider": "coda", "doc_url": "...", "doc_id": "x", "source_id": "x", "tabs": [{"worksheet_title": "Test", "output_path": "t.csv", "required_headers": ["A"]}]}'
    )
    table_profile = tmp_path / "profile.json"
    table_profile.write_text(
        '{"summary": {"doc_name": "D", "table_id": "t", "table_name": "Test", "columns": [{"name": "A", "format_type": "text"}]}, "columns_raw": [], "rows_sample": []}'
    )
    out = tmp_path / "contract.yaml"

    call_command(
        "scaffold_workbook_schema",
        bundle_config=str(bundle),
        table_profile=[str(table_profile)],
        models_app_label="testapp",
        out=str(out),
    )

    import yaml

    contract = yaml.safe_load(out.read_text())
    for table in contract.get("tables", []):
        meta = table.get("model_meta", {})
        assert (
            meta.get("app_label") == "testapp"
        ), f"Expected app_label='testapp', got {meta.get('app_label')!r}"


def test_flag_fk_columns_detects_id_suffix():
    """Columns ending in _id get flagged with suggested_fk_target."""
    columns = [
        {"suggested_field_name": "season_id", "source_column": "Season ID"},
        {"suggested_field_name": "name", "source_column": "Name"},
    ]
    _flag_fk_columns(columns)
    assert columns[0].get("suggested_fk_target") == "Season"
    assert columns[0].get("review_note") is not None
    assert "suggested_fk_target" not in columns[1]


def test_flag_fk_columns_detects_entity_names():
    """Columns named after known entities (channel, season, etc.) get flagged."""
    columns = [
        {"suggested_field_name": "channel", "source_column": "Channel"},
        {"suggested_field_name": "season", "source_column": "Season"},
    ]
    _flag_fk_columns(columns)
    assert columns[0].get("suggested_fk_target") == "Channel"
    assert columns[1].get("suggested_fk_target") == "Season"


def test_flag_fk_columns_skips_self_reference():
    """A column like ``client_id`` in the ``Clients`` table should not be
    flagged as a FK — it's the table's own primary key."""
    columns = [
        {"suggested_field_name": "client_id", "source_column": "Client ID"},
    ]
    _flag_fk_columns(columns, table_name="Clients")
    assert columns[0].get("suggested_fk_target") is None
    assert columns[0].get("review_note") is None


def test_flag_fk_columns_skips_formula_derived():
    """A column with ``has_formula: True`` should not be auto-detected as
    a FK — in Coda, formula columns are typically previews of an already-
    mapped relation column."""
    columns = [
        {
            "suggested_field_name": "instrument_id",
            "source_column": "Instrument ID",
            "has_formula": True,
        },
    ]
    _flag_fk_columns(columns, table_name="Clients")
    assert columns[0].get("suggested_fk_target") is None


def test_flag_fk_columns_does_not_skip_foreign_fk():
    """A column like ``farm_id`` in the ``Clients`` table should still be
    flagged, because ``Farm`` is not the table's own model."""
    columns = [
        {"suggested_field_name": "farm_id", "source_column": "Farm ID"},
    ]
    _flag_fk_columns(columns, table_name="Clients")
    assert columns[0].get("suggested_fk_target") == "Farm"


def test_flag_computed_fields_moves_formula_columns():
    """Columns with formula_pattern row_formula or expansion_formula move to computed_fields."""
    table = {
        "suggested_model_name": "CropPlan",
        "columns": [
            {"suggested_field_name": "name", "formula_pattern": "raw"},
            {"suggested_field_name": "yield_est", "formula_pattern": "row_formula"},
            {"suggested_field_name": "total", "formula_pattern": "expansion_formula"},
        ],
    }
    _flag_computed_fields(table)
    remaining = {c["suggested_field_name"] for c in table["columns"]}
    assert "name" in remaining
    assert "yield_est" not in remaining
    assert "total" not in remaining
    computed = table.get("computed_fields", {})
    assert "yield_est" in computed
    assert "total" in computed
    assert "return_type" in computed["yield_est"]
    assert "expression" in computed["yield_est"]


def test_harden_contract_preserves_existing_bundle_path():
    contract = {
        "tables": [
            {
                "suggested_model_name": "Sales Channel",
                "model_name": "SalesChannel",
                "bundle_worksheet_title": "Sales Channels",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "source_column": "Name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 120},
                        "notes": [],
                    }
                ],
                "import_config": {
                    "bundle_path": "reference/sales_channels.csv",
                },
            }
        ]
    }
    _harden_contract(contract)
    assert (
        contract["tables"][0]["import_config"].get("bundle_path")
        == "reference/sales_channels.csv"
    )


def test_harden_contract_derives_bundle_path_when_missing():
    contract = {
        "tables": [
            {
                "suggested_model_name": "Farm",
                "model_name": "Farm",
                "bundle_worksheet_title": "Farms",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "source_column": "Name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 120},
                        "notes": [],
                    }
                ],
            }
        ]
    }
    _harden_contract(contract)
    assert "bundle_path" in contract["tables"][0]["import_config"]
    assert (
        contract["tables"][0]["import_config"]["bundle_path"] == "reference/farms.csv"
    )


def test_flag_computed_fields_skips_missing_pattern():
    """Columns without a formula_pattern field are left as-is."""
    table = {
        "columns": [
            {"suggested_field_name": "name"},
        ],
    }
    _flag_computed_fields(table)
    assert len(table["columns"]) == 1


def test_suggest_tab_merges_groups_by_shared_headers():
    """Tabs sharing 2+ column headers get merge_candidates."""
    tabs = {
        "Crop Planner": {"columns": ["Crop", "Week", "Block", "Variety"]},
        "Crop Plan 501": {"columns": ["Crop", "Week", "Block", "Yield"]},
        "Harvest": {"columns": ["Date", "Weight", "Block"]},
    }
    result = _suggest_tab_merges(tabs)
    assert any(r["tabs"] == {"Crop Planner", "Crop Plan 501"} for r in result)
    assert not any("Harvest" in r["tabs"] for r in result)


def test_domain_knowledge_merge_overrides_field_types():
    """Domain knowledge field types override profiler-inferred types for matching fields."""
    domain = {
        "entities": {
            "Season": {
                "fields": {
                    "name": {"type": "CharField", "max_length": 200},
                    "year": {"type": "PositiveIntegerField"},
                },
                "source_tabs": ["Crop Planner"],
            }
        }
    }
    tables = [
        {
            "suggested_model_name": "Season",
            "bundle_worksheet_title": "Crop Planner",
            "columns": [
                {
                    "suggested_field_name": "name",
                    "django_field_class": "models.TextField",
                },
                {
                    "suggested_field_name": "year",
                    "django_field_class": "models.TextField",
                },
                {
                    "suggested_field_name": "notes",
                    "django_field_class": "models.TextField",
                },
            ],
        }
    ]
    _merge_domain_knowledge(tables, domain)
    season = tables[0]
    cols_by_name = {c["suggested_field_name"]: c for c in season["columns"]}
    assert cols_by_name["name"]["django_field_class"] == "CharField"
    assert cols_by_name["name"]["max_length"] == 200
    assert cols_by_name["year"]["django_field_class"] == "PositiveIntegerField"
    assert cols_by_name["notes"].get("review_note") is not None


def test_domain_knowledge_merge_warns_unmatched_entities():
    """Domain entities not matched to any profiler tab produce a warning."""
    domain = {
        "entities": {
            "GhostEntity": {
                "fields": {"name": {"type": "CharField"}},
                "source_tabs": ["Nonexistent Tab"],
            }
        }
    }
    warnings = []
    _merge_domain_knowledge([], domain, warnings.append)
    assert any("GhostEntity" in w for w in warnings)


def test_build_contract_passes_enrichment_fields_through():
    """build_contract() should include enrichment fields in column dicts."""
    bundle_config = {
        "provider": "coda",
        "doc_url": "https://example.com",
        "doc_id": "abc123",
        "source_id": "src1",
        "tabs": [
            {
                "worksheet_title": "Seasons",
                "output_path": "data/seasons.csv",
                "required_headers": ["Season ID", "Name", "Crop ID", "Computed Total"],
            }
        ],
    }
    doc_profile = {
        "tables": [
            {
                "name": "Seasons",
                "columns": [
                    {
                        "name": "Season ID",
                        "format_type": "text",
                        "suggested_entity": "Season",
                        "suggested_fk_target": None,
                        "is_computed": False,
                        "is_import_key_candidate": True,
                        "cross_tab_group": None,
                    },
                    {
                        "name": "Name",
                        "format_type": "text",
                        "suggested_entity": None,
                        "suggested_fk_target": None,
                        "is_computed": False,
                        "is_import_key_candidate": False,
                        "cross_tab_group": None,
                    },
                    {
                        "name": "Crop ID",
                        "format_type": "text",
                        "suggested_entity": "Crop",
                        "suggested_fk_target": "Crop",
                        "is_computed": False,
                        "is_import_key_candidate": False,
                        "cross_tab_group": "crop_data",
                    },
                    {
                        "name": "Computed Total",
                        "format_type": "number",
                        "suggested_entity": None,
                        "suggested_fk_target": None,
                        "is_computed": True,
                        "is_import_key_candidate": False,
                        "cross_tab_group": None,
                    },
                ],
            }
        ],
    }
    contract = build_contract(bundle_config, doc_profile=doc_profile)
    tables = contract["tables"]
    assert len(tables) == 1
    cols = tables[0]["columns"]
    cols_by_name = {c["source_column"]: c for c in cols}

    assert cols_by_name["Season ID"]["is_import_key_candidate"] is True
    assert cols_by_name["Season ID"]["suggested_entity"] == "Season"

    assert cols_by_name["Crop ID"]["suggested_fk_target"] == "Crop"
    assert cols_by_name["Crop ID"]["cross_tab_group"] == "crop_data"

    assert cols_by_name["Computed Total"]["is_computed"] is True

    assert cols_by_name["Name"]["is_computed"] is False
    assert cols_by_name["Name"]["is_import_key_candidate"] is False


def test_flag_fk_columns_skips_profiler_enriched_columns():
    """_flag_fk_columns() should skip columns that already have suggested_fk_target."""
    columns = [
        {
            "suggested_field_name": "season_id",
            "source_column": "Season ID",
            "suggested_fk_target": "SeasonProfile",
        },
        {"suggested_field_name": "crop_id", "source_column": "Crop ID"},
    ]
    _flag_fk_columns(columns)
    assert columns[0]["suggested_fk_target"] == "SeasonProfile"
    assert columns[1]["suggested_fk_target"] == "Crop"


def test_flag_computed_fields_catches_is_computed():
    """_flag_computed_fields() should move columns with is_computed=True to computed_fields."""
    table = {
        "suggested_model_name": "CropPlan",
        "columns": [
            {
                "suggested_field_name": "name",
                "formula_pattern": None,
                "is_computed": False,
            },
            {
                "suggested_field_name": "total",
                "formula_pattern": None,
                "is_computed": True,
                "source_column": "Total",
                "django_field_class": "models.FloatField",
            },
            {
                "suggested_field_name": "yield_est",
                "formula_pattern": "row_formula",
                "source_column": "Yield Est",
            },
        ],
    }
    _flag_computed_fields(table)
    remaining = {c["suggested_field_name"] for c in table["columns"]}
    assert "name" in remaining
    assert "total" not in remaining
    assert "yield_est" not in remaining
    computed = table.get("computed_fields", {})
    assert "total" in computed
    assert "yield_est" in computed


def test_infer_format_type_empty_input():
    """Empty list of sample values returns 'text'."""
    assert _infer_format_type_from_samples([]) == "text"


def test_infer_format_type_all_empty_strings():
    """List of only empty strings returns 'text'."""
    assert _infer_format_type_from_samples(["", "", ""]) == "text"


def test_infer_format_type_boolean():
    """Values matching boolean patterns return 'checkbox'."""
    assert _infer_format_type_from_samples(["TRUE", "FALSE", "Yes", "No"]) == "checkbox"
    assert _infer_format_type_from_samples(["yes", "no", "1", "0"]) == "checkbox"


def test_infer_format_type_dates():
    """ISO date strings return 'date'."""
    assert (
        _infer_format_type_from_samples(["2024-01-15", "2025-03-20", "2026-11-01"])
        == "date"
    )
    assert (
        _infer_format_type_from_samples(["2024-01-15 09:30", "2025-03-20 14:00", ""])
        == "date"
    )


def test_infer_format_type_numbers():
    """Numeric strings (with optional $, %, commas) return 'number'."""
    assert _infer_format_type_from_samples(["42", "3.14"]) == "number"
    assert _infer_format_type_from_samples(["$12.50", "1,000", "50%"]) == "number"
    assert _infer_format_type_from_samples(["42", "3.14", "", "1", "5"]) == "number"


def test_infer_format_type_mixed_fallback():
    """Mixed content with no clear pattern falls back to 'text'."""
    assert _infer_format_type_from_samples(["hello", "42", "TRUE"]) == "text"
    assert _infer_format_type_from_samples(["hello world"]) == "text"


def test_check_null_model_names_finds_empty():
    tables = [{"bundle_worksheet_title": "Final Report", "model_name": ""}]
    errors = _check_null_model_names(tables)
    assert len(errors) == 1
    assert "SCAFFOLD_NULL_MODEL_NAME" in errors[0]


def test_check_pivot_table_detects_numeric_headers():
    table = {
        "bundle_worksheet_title": "Irrigation",
        "columns": [
            {"source_column": "1"},
            {"source_column": "6"},
            {"source_column": "7"},
            {"source_column": "Total"},
        ],
    }
    errors = _check_pivot_tables(table)
    assert len(errors) == 1
    assert "SCAFFOLD_PIVOT_TABLE" in errors[0]


def test_check_invalid_identifier_detects_digit_prefix():
    table = {
        "bundle_worksheet_title": "Unit",
        "model_name": "Unit",
        "columns": [{"suggested_field_name": "201_unit"}],
    }
    errors = _check_invalid_identifiers(table)
    assert any("201_unit" in e for e in errors)
    assert any("SCAFFOLD_INVALID_IDENTIFIER" in e for e in errors)


def test_validate_tables_rejects_pivot_when_continue_on_error():
    tables = [
        {
            "bundle_worksheet_title": "Irrigation",
            "model_name": "Irrigation",
            "columns": [
                {"source_column": "1", "suggested_field_name": "1"},
                {"source_column": "2", "suggested_field_name": "2"},
                {"source_column": "3", "suggested_field_name": "3"},
            ],
        }
    ]
    valid, collector = _validate_tables_for_scaffold(tables, continue_on_error=True)
    assert len(valid) == 0
    assert len(collector.rejected) == 1
    assert collector.rejected[0].check_id == "SCAFFOLD_PIVOT_TABLE"


def test_validate_tables_keeps_valid_and_rejects_invalid():
    tables = [
        {"bundle_worksheet_title": "Good", "model_name": "Good", "columns": []},
        {
            "bundle_worksheet_title": "Irrigation",
            "model_name": "Irrigation",
            "columns": [
                {"source_column": "1", "suggested_field_name": "1"},
                {"source_column": "2", "suggested_field_name": "2"},
                {"source_column": "3", "suggested_field_name": "3"},
            ],
        },
    ]
    valid, collector = _validate_tables_for_scaffold(tables, continue_on_error=True)
    assert len(valid) == 1
    assert valid[0]["model_name"] == "Good"
    assert len(collector.rejected) == 1


def test_check_pivot_tables_respects_threshold():
    from workbook.management.commands.scaffold_workbook_schema import (
        _check_pivot_tables,
    )

    table = {
        "bundle_worksheet_title": "Test",
        "columns": [
            {"source_column": "1"},
            {"source_column": "2"},
            {"source_column": "Name"},
        ],
    }
    assert len(_check_pivot_tables(table, pivot_detection_threshold=0.5)) == 1
    assert len(_check_pivot_tables(table, pivot_detection_threshold=0.9)) == 0


def test_validate_tables_skips_designed_models():
    tables = [
        {
            "source_tab": None,
            "bundle_worksheet_title": None,
            "model_name": "DesignedModel",
            "columns": [],
        },
    ]
    valid, collector = _validate_tables_for_scaffold(tables, continue_on_error=True)
    assert len(valid) == 1
    assert collector.is_empty()


# ── Identifier sanitization ──────────────────────────────────────────────


def test_sanitize_python_identifier_prepends_field_for_leading_digit():
    """Leading digits get field_ prefix."""
    assert _sanitize_python_identifier("0_00") == "field_0_00"
    assert _sanitize_python_identifier("201_unit") == "field_201_unit"


def test_sanitize_python_identifier_replaces_invalid_chars():
    """Non-alphanumeric, non-underscore characters are replaced with _."""
    assert _sanitize_python_identifier("has space") == "has_space"
    assert _sanitize_python_identifier("dash-ed") == "dash_ed"
    assert _sanitize_python_identifier("special!char") == "special_char"


def test_sanitize_python_identifier_preserves_valid():
    """Already valid identifiers pass through unchanged."""
    assert _sanitize_python_identifier("valid_name") == "valid_name"
    assert _sanitize_python_identifier("name") == "name"
    assert _sanitize_python_identifier("field_0_00") == "field_0_00"


def test_sanitize_python_identifier_empty_or_underscores():
    """Empty or all-underscore input falls back to 'field'."""
    assert _sanitize_python_identifier("") == "field"
    assert _sanitize_python_identifier("___") == "field"


def test_sanitize_table_identifiers_sanitizes_invalid():
    """Invalid model_name and field names are sanitized in-place."""
    table = {
        "bundle_worksheet_title": "Sales Channels",
        "model_name": "0_00",
        "columns": [
            {"suggested_field_name": "valid_name"},
            {"suggested_field_name": "201_unit"},
        ],
    }
    result = _sanitize_table_identifiers(table)
    assert table["model_name"] == "field_0_00"
    assert table["columns"][1]["suggested_field_name"] == "field_201_unit"
    assert table["columns"][0]["suggested_field_name"] == "valid_name"
    assert len(result) == 2
    assert ("0_00", "field_0_00") in result
    assert ("201_unit", "field_201_unit") in result


def test_sanitize_table_identifiers_records_meta():
    """Sanitized identifiers are recorded in table _meta."""
    table = {
        "bundle_worksheet_title": "Test",
        "model_name": "Test",
        "columns": [
            {"suggested_field_name": "0_00"},
        ],
    }
    _sanitize_table_identifiers(table)
    meta = table.get("_meta", {})
    sanitized = meta.get("sanitized_identifiers", [])
    assert len(sanitized) == 1
    assert sanitized[0]["original"] == "0_00"
    assert sanitized[0]["sanitized"] == "field_0_00"


def test_sanitize_table_identifiers_noop_for_valid():
    """No sanitization happens when all identifiers are valid."""
    table = {
        "bundle_worksheet_title": "Test",
        "model_name": "TestModel",
        "columns": [
            {"suggested_field_name": "name"},
            {"suggested_field_name": "count"},
        ],
    }
    result = _sanitize_table_identifiers(table)
    assert len(result) == 0
    assert "_meta" not in table


def test_validate_tables_sanitizes_by_default():
    """Without --strict-identifiers, invalid identifiers are sanitized, not aborted."""
    tables = [
        {
            "bundle_worksheet_title": "Sales Channels",
            "model_name": "SalesChannel",
            "columns": [
                {"suggested_field_name": "0_00", "source_column": "0_00"},
            ],
        },
    ]
    valid, collector = _validate_tables_for_scaffold(tables, continue_on_error=False)
    assert len(valid) == 1
    assert valid[0]["columns"][0]["suggested_field_name"] == "field_0_00"
    assert collector.is_empty()


def test_validate_tables_strict_identifiers_raises():
    """With --strict-identifiers, invalid identifiers raise CommandError."""
    tables = [
        {
            "bundle_worksheet_title": "Sales Channels",
            "model_name": "SalesChannel",
            "columns": [
                {"suggested_field_name": "0_00"},
            ],
        },
    ]
    with pytest.raises(CommandError, match="SCAFFOLD_INVALID_IDENTIFIER"):
        _validate_tables_for_scaffold(tables, strict_identifiers=True)


def test_validate_tables_strict_identifiers_continue_on_error():
    """With strict + continue_on_error, invalid identifiers skip the table."""
    tables = [
        {
            "bundle_worksheet_title": "Good",
            "model_name": "Good",
            "columns": [{"suggested_field_name": "name"}],
        },
        {
            "bundle_worksheet_title": "Bad",
            "model_name": "Bad",
            "columns": [{"suggested_field_name": "0_00"}],
        },
    ]
    valid, collector = _validate_tables_for_scaffold(
        tables, continue_on_error=True, strict_identifiers=True
    )
    assert len(valid) == 1
    assert valid[0]["model_name"] == "Good"
    assert len(collector.rejected) == 1
    assert collector.rejected[0].check_id == "SCAFFOLD_INVALID_IDENTIFIER"
