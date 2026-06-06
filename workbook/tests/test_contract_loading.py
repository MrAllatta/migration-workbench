"""Tests for schema contract loading and accessor functions."""

from __future__ import annotations

from workbook.codegen.contract import load_contract_unvalidated, get_auth_config


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
