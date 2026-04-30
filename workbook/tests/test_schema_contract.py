from workbook.schema_contract import build_contract
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
    assert tab["columns"][0]["django_field_class"] == "models.CharField"


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
