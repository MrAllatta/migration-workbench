"""Tests for schema contract loading and accessor functions."""

from __future__ import annotations

from workbook.codegen.contract import (
    load_contract_unvalidated,
    get_auth_config,
    resolve_field_mapping,
)


def _v14_contract_yaml(tmp_path) -> str:
    """Write a v1.4 contract with codegen.auth block and return its path."""
    import yaml

    contract = {
        "version": "1.4",
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                ],
                "codegen": {
                    "auth": {
                        "mechanism": "django_groups",
                        "default_owner_role": "field_manager",
                    },
                },
            },
            {
                "suggested_model_name": "planting",
                "model_name": "Planting",
                "columns": [
                    {
                        "suggested_field_name": "crop",
                        "django_field_class": "models.ForeignKey",
                        "django_field_kwargs": {
                            "to": "Crop",
                            "on_delete": "models.PROTECT",
                        },
                    },
                ],
                # No codegen.auth block — should return {}
            },
        ],
    }
    p = tmp_path / "v14_contract.yaml"
    p.write_text(yaml.safe_dump(contract), encoding="utf-8")
    return str(p)


def _v13_contract_yaml(tmp_path) -> str:
    """Write a v1.3 contract without codegen.auth."""
    import yaml

    contract = {
        "version": "1.3",
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                ],
            },
        ],
    }
    p = tmp_path / "v13_contract.yaml"
    p.write_text(yaml.safe_dump(contract), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# get_auth_config
# ---------------------------------------------------------------------------


def test_get_auth_config_v14_returns_expected_dict(tmp_path):
    """get_auth_config should return the codegen.auth block for v1.4."""
    path = _v14_contract_yaml(tmp_path)
    contract = load_contract_unvalidated(path)
    tables = contract["tables"]

    crop_auth = get_auth_config(tables[0])
    assert crop_auth == {
        "mechanism": "django_groups",
        "default_owner_role": "field_manager",
    }


def test_get_auth_config_returns_empty_dict_when_absent(tmp_path):
    """get_auth_config should return {} when codegen.auth is absent."""
    path = _v14_contract_yaml(tmp_path)
    contract = load_contract_unvalidated(path)
    tables = contract["tables"]

    planting_auth = get_auth_config(tables[1])
    assert planting_auth == {}


def test_get_auth_config_v13_returns_empty_dict(tmp_path):
    """get_auth_config should return {} for v1.3 contracts without codegen."""
    path = _v13_contract_yaml(tmp_path)
    contract = load_contract_unvalidated(path)
    tables = contract["tables"]

    crop_auth = get_auth_config(tables[0])
    assert crop_auth == {}


def test_get_auth_config_backward_compatible(tmp_path):
    """Loading a v1.4 contract with codegen.auth should not break v1.3 loading."""
    path_v14 = _v14_contract_yaml(tmp_path)
    contract_v14 = load_contract_unvalidated(path_v14)
    assert contract_v14["version"] == "1.4"
    # Ensure tables still load correctly
    assert len(contract_v14["tables"]) == 2

    path_v13 = _v13_contract_yaml(tmp_path)
    contract_v13 = load_contract_unvalidated(path_v13)
    assert contract_v13["version"] == "1.3"
    assert len(contract_v13["tables"]) == 1


# ---------------------------------------------------------------------------
# resolve_field_mapping
# ---------------------------------------------------------------------------


def test_resolve_field_mapping_from_columns():
    """resolve_field_mapping uses columns[].source_column as baseline."""
    table = {
        "columns": [
            {"source_column": "Crop", "suggested_field_name": "name"},
            {"source_column": "Plant Date", "suggested_field_name": "plant_date"},
            {"source_column": "Beds Used", "suggested_field_name": "beds_used"},
        ],
    }
    result = resolve_field_mapping(table)
    assert result == {
        "name": "Crop",
        "plant_date": "Plant Date",
        "beds_used": "Beds Used",
    }


def test_resolve_field_mapping_empty_columns():
    """resolve_field_mapping returns {} when columns are empty."""
    table = {"columns": []}
    assert resolve_field_mapping(table) == {}


def test_resolve_field_mapping_no_columns_key():
    """resolve_field_mapping returns {} when columns key is absent."""
    table = {"model_name": "Crop"}
    assert resolve_field_mapping(table) == {}


def test_resolve_field_mapping_column_map_overrides_columns():
    """import_config.column_map takes priority over columns[] baseline."""
    table = {
        "columns": [
            {"source_column": "Crop", "suggested_field_name": "name"},
            {"source_column": "Type", "suggested_field_name": "crop_type"},
        ],
        "import_config": {
            "column_map": {
                "crop_type": "Crop Type",  # override
            },
        },
    }
    result = resolve_field_mapping(table)
    assert result == {
        "name": "Crop",
        "crop_type": "Crop Type",
    }


def test_resolve_field_mapping_column_map_adds_new_entries():
    """import_config.column_map can add entries not in columns[]."""
    table = {
        "columns": [
            {"source_column": "Crop", "suggested_field_name": "name"},
        ],
        "import_config": {
            "column_map": {
                "calculated_field": "Hidden Formula Col",
            },
        },
    }
    result = resolve_field_mapping(table)
    assert result == {
        "name": "Crop",
        "calculated_field": "Hidden Formula Col",
    }


def test_resolve_field_mapping_skips_multi_source_entries():
    """List-valued column_map entries are excluded (value-level transform)."""
    table = {
        "columns": [
            {"source_column": "First", "suggested_field_name": "first_name"},
        ],
        "import_config": {
            "column_map": {
                "full_name": ["First Name", "Last Name"],  # multi-source
            },
        },
    }
    result = resolve_field_mapping(table)
    assert result == {
        "first_name": "First",
    }
    assert "full_name" not in result


def test_resolve_field_mapping_without_import_config():
    """resolve_field_mapping works when there is no import_config block."""
    table = {
        "columns": [
            {"source_column": "Crop", "suggested_field_name": "name"},
        ],
    }
    assert resolve_field_mapping(table) == {"name": "Crop"}


def test_resolve_field_mapping_partial_source_columns():
    """columns without source_column are omitted from the mapping."""
    table = {
        "columns": [
            {"source_column": "Crop", "suggested_field_name": "name"},
            {"suggested_field_name": "computed"},     # no source_column
            {"source_column": "Notes", "suggested_field_name": "notes"},
        ],
    }
    result = resolve_field_mapping(table)
    assert result == {
        "name": "Crop",
        "notes": "Notes",
    }
    assert "computed" not in result
