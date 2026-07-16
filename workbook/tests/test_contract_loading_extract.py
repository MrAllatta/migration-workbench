"""Tests for workbook/contract/loading.py extraction (e04s02).

Extracts loading functions (_make_contract_loader, load_contract_unvalidated,
load_contract) from workbook/codegen/contract.py into workbook/contract/loading.py.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _example_contract() -> str:
    """Return path to a known-valid schema contract fixture."""
    return str(next(_REPO_ROOT.glob("example_data/*contract*.example.yaml")))


def test_loading_module_imports() -> None:
    import workbook.contract.loading  # noqa: F401


def test_loading_module_has_make_contract_loader() -> None:
    import workbook.contract.loading as m
    assert callable(m._make_contract_loader)


def test_loading_module_has_load_contract_unvalidated() -> None:
    import workbook.contract.loading as m
    assert callable(m.load_contract_unvalidated)


def test_loading_module_has_load_contract() -> None:
    import workbook.contract.loading as m
    assert callable(m.load_contract)


def test_load_contract_unvalidated_returns_dict() -> None:
    """Smoke test: load a valid contract via the extracted module."""
    import workbook.contract.loading as m
    contract = m.load_contract_unvalidated(_example_contract())
    assert isinstance(contract, dict)
    assert "tables" in contract
    assert "version" in contract


def test_load_contract_returns_dict() -> None:
    """Smoke test: load and validate a contract via the extracted module."""
    import workbook.contract.loading as m
    contract = m.load_contract(_example_contract())
    assert isinstance(contract, dict)
    assert "tables" in contract


def test_reimport_identity_loading_apis() -> None:
    """Re-exports from workbook.codegen.contract must be the same objects."""
    from workbook.codegen.contract import (
        load_contract,
        load_contract_unvalidated,
    )
    from workbook.contract.loading import (
        load_contract as m_load,
        load_contract_unvalidated as m_load_unvalidated,
    )
    assert load_contract is m_load
    assert load_contract_unvalidated is m_load_unvalidated
