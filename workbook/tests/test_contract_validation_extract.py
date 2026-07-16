"""Tests for workbook/contract/validation.py extraction (e04s04).

Extracts validation functions (_validate_table_exceptions,
validate_contract_tables, strict_validate_contract) from
workbook/codegen/contract.py.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _example_contract() -> str:
    """Return path to a known-valid schema contract fixture."""
    return str(next(_REPO_ROOT.glob("example_data/*contract*.example.yaml")))


def _load_contract_unvalidated() -> dict:
    """Return a loaded but unvalidated contract."""
    from workbook.contract.loading import load_contract_unvalidated
    return load_contract_unvalidated(_example_contract())


def test_validation_module_imports() -> None:
    import workbook.contract.validation  # noqa: F401


def test_validation_module_has_validate_contract_tables() -> None:
    import workbook.contract.validation as m
    assert callable(m.validate_contract_tables)


def test_validation_module_has_strict_validate_contract() -> None:
    import workbook.contract.validation as m
    assert callable(m.strict_validate_contract)


def test_validate_contract_tables_returns_list() -> None:
    """Smoke test: validate a contract via the extracted module."""
    import workbook.contract.validation as m
    contract = _load_contract_unvalidated()
    results = m.validate_contract_tables(contract)
    assert isinstance(results, list)


def test_strict_validate_contract_returns_list() -> None:
    """Smoke test: strict validate via the extracted module."""
    import workbook.contract.validation as m
    contract = _load_contract_unvalidated()
    results = m.strict_validate_contract(contract)
    assert isinstance(results, list)


def test_reimport_identity() -> None:
    """Re-exports from workbook.codegen.contract must be the same objects."""
    from workbook.codegen.contract import (
        validate_contract_tables,
        strict_validate_contract,
    )
    from workbook.contract.validation import (
        validate_contract_tables as v_tables,
        strict_validate_contract as v_strict,
    )
    assert validate_contract_tables is v_tables
    assert strict_validate_contract is v_strict
