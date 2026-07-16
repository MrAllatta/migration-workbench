"""Inventory: workbook/codegen/contract.py baseline.

Story: e04s01 (contract-layer-split)
Baseline: 1241 lines, captured at commit 630883e (pre-split).

This file captures the pre-extraction state. Each test will be
updated as functions move to workbook/contract/{loading,accessors,
validation,diff}.py.

Seams identified (from grep of function boundaries):
- Loading (lines 19-165): _make_contract_loader, load_contract_unvalidated, load_contract
- Accessors (lines 199-510): get_model_name, get_db_table_name, get_model_meta,
  get_str_template, _resolve_fk_target, _apply_field_override, _normalise_field_class,
  get_enums, get_admin_config, get_auth_config, get_model_base, get_extra_imports,
  get_computed_fields, get_is_abstract, has_source_tab, get_hooks, get_import_config,
  resolve_field_mapping
- Review/utilities (lines 620-860): review_contract, _field_class_short,
  assign_import_tiers, get_fields
- Validation (lines 512-617, 1171+): _validate_table_exceptions,
  validate_contract_tables, strict_validate_contract
- Diff (lines 861-1170): diff_contracts, _diff_tables, _field_map,
  _field_summary, _diff_fields, migration_safety_checks, _diff_meta
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_contract_baseline_line_count() -> None:
    """Record the pre-split line count for tracking."""
    source = _REPO_ROOT / "workbook" / "codegen" / "contract.py"
    lines = len(source.read_text().splitlines())
    baseline = 259
    assert lines == baseline, (
        f"contract.py is {lines} lines; expected {baseline} baseline. "
        "If you intentionally changed the file, update the baseline."
    )


def test_load_contract_is_importable() -> None:
    """Core loading API must still be importable from the canonical location."""
    from workbook.codegen.contract import load_contract
    assert callable(load_contract)


def test_all_major_apis_smoke() -> None:
    """All public API functions must be importable from contract.py."""
    from workbook.codegen.contract import (
        load_contract,
        load_contract_unvalidated,
        get_model_name,
        get_db_table_name,
        get_fields,
        diff_contracts,
        review_contract,
        validate_contract_tables,
        strict_validate_contract,
        migration_safety_checks,
        assign_import_tiers,
        resolve_field_mapping,
    )
    for name, fn in locals().items():
        if name.startswith("test_"):
            continue
        assert callable(fn), f"{name} is not callable"
