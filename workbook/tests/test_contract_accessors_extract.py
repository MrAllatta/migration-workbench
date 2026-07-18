"""Tests for workbook/contract/accessors.py extraction (e04s03).

Extracts field/model accessor functions from workbook/codegen/contract.py
into workbook/contract/accessors.py.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _example_contract() -> str:
    """Return path to a known-valid schema contract fixture."""
    return str(next(_REPO_ROOT.glob("example_data/*contract*.example.yaml")))


def _load_contract() -> dict:
    """Return a loaded contract for accessor testing."""
    from workbook.codegen.contract import load_contract

    return load_contract(_example_contract())


def test_accessors_module_imports() -> None:
    import workbook.contract.accessors  # noqa: F401


ACCESSOR_NAMES = [
    "get_model_name",
    "get_db_table_name",
    "get_model_meta",
    "get_str_template",
    "_resolve_fk_target",
    "_apply_field_override",
    "_normalise_field_class",
    "get_enums",
    "get_admin_config",
    "get_auth_config",
    "get_model_base",
    "get_extra_imports",
    "get_computed_fields",
    "get_is_abstract",
    "has_source_tab",
    "get_hooks",
    "get_import_config",
    "resolve_field_mapping",
]


def test_all_accessors_present() -> None:
    import workbook.contract.accessors as m

    for name in ACCESSOR_NAMES:
        assert callable(getattr(m, name)), f"{name} not callable"


def test_get_model_name_returns_string() -> None:
    from workbook.contract.accessors import get_model_name

    result = get_model_name({"model_name": "TestModel"})
    assert result == "TestModel"


def test_get_model_name_raises_keyerror() -> None:
    from workbook.contract.accessors import get_model_name
    import pytest

    with pytest.raises(KeyError):
        get_model_name({"other": "value"})


def test_get_enums_returns_dict() -> None:
    from workbook.contract.accessors import get_enums

    contract = _load_contract()
    result = get_enums(contract)
    assert isinstance(result, dict)


def test_reimport_identity() -> None:
    """Re-exports from workbook.codegen.contract must be the same objects."""
    from workbook.codegen.contract import (
        get_model_name,
        get_db_table_name,
        get_enums,
        get_admin_config,
        get_auth_config,
        get_hooks,
        get_import_config,
        resolve_field_mapping,
    )
    from workbook.contract.accessors import (
        get_model_name as m_name,
        get_db_table_name as m_db,
        get_enums as m_enums,
        get_admin_config as m_admin,
        get_auth_config as m_auth,
        get_hooks as m_hooks,
        get_import_config as m_import,
        resolve_field_mapping as m_resolve,
    )

    assert get_model_name is m_name
    assert get_db_table_name is m_db
    assert get_enums is m_enums
    assert get_admin_config is m_admin
    assert get_auth_config is m_auth
    assert get_hooks is m_hooks
    assert get_import_config is m_import
    assert resolve_field_mapping is m_resolve
