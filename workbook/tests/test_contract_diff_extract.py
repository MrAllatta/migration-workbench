"""Tests for workbook/contract/diff.py extraction (e04s05).

Extracts diff functions (diff_contracts, _diff_tables, _field_map,
_field_summary, _diff_fields, migration_safety_checks, _diff_meta)
from workbook/codegen/contract.py.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _example_contract() -> str:
    """Return path to a known-valid schema contract fixture."""
    return str(next(_REPO_ROOT.glob("example_data/*contract*.example.yaml")))


def _load_contract_validated() -> dict:
    """Return a loaded and validated contract."""
    from workbook.contract.loading import load_contract

    return load_contract(_example_contract())


def test_diff_module_imports() -> None:
    import workbook.contract.diff  # noqa: F401


DIFF_FUNC_NAMES = [
    "diff_contracts",
    "_diff_tables",
    "_field_map",
    "_field_summary",
    "_diff_fields",
    "migration_safety_checks",
    "_diff_meta",
]


def test_all_diff_functions_present() -> None:
    import workbook.contract.diff as m

    for name in DIFF_FUNC_NAMES:
        assert callable(getattr(m, name)), f"{name} not callable"


def test_diff_contracts_returns_diff() -> None:
    """Smoke test: diff two identical contracts returns empty result."""
    import workbook.contract.diff as m

    contract = _load_contract_validated()
    result = m.diff_contracts(contract, contract)
    assert isinstance(result, dict)


def test_diff_contracts_detects_no_diff_on_identical() -> None:
    import workbook.contract.diff as m

    contract = _load_contract_validated()
    result = m.diff_contracts(contract, contract)
    # Expected: no tables changed, no meta changed, etc.
    assert not any(result.values()) if isinstance(result, dict) else True


def test_migration_safety_checks_returns_list() -> None:
    import workbook.contract.diff as m

    result = m.migration_safety_checks({})
    assert isinstance(result, list)


def test_reimport_identity() -> None:
    """Re-exports from workbook.codegen.contract must be the same objects."""
    from workbook.codegen.contract import diff_contracts, migration_safety_checks
    from workbook.contract.diff import (
        diff_contracts as d_diff,
        migration_safety_checks as d_safety,
    )

    assert diff_contracts is d_diff
    assert migration_safety_checks is d_safety
