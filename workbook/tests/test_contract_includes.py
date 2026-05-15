"""Tests for schema contract YAML includes in workbook.codegen.contract."""

from __future__ import annotations

import pytest

from workbook.codegen.contract import load_contract


def test_include_list_splices_into_tables(tmp_path):
    tables_path = tmp_path / "tables.yaml"
    tables_path.write_text(
        """
- suggested_model_name: inventory
  columns: []
- suggested_model_name: field
  columns: []
""".lstrip(),
        encoding="utf-8",
    )

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        """
version: "1.3"
tables:
  - suggested_model_name: crop
    columns: []
  - !include_list tables.yaml
  - suggested_model_name: farmer
    columns: []
""".lstrip(),
        encoding="utf-8",
    )

    contract = load_contract(contract_path)
    model_names = [t["suggested_model_name"] for t in contract["tables"]]
    assert model_names == ["crop", "inventory", "field", "farmer"]


def test_include_list_requires_a_yaml_list(tmp_path):
    included_path = tmp_path / "not_a_list.yaml"
    included_path.write_text("foo: bar\n", encoding="utf-8")

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        """
version: "1.3"
tables:
  - !include_list not_a_list.yaml
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"include_list expects a YAML list"):
        load_contract(contract_path)


def test_tables_flattening_is_recursive(tmp_path):
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        """
version: "1.3"
tables:
  - - - suggested_model_name: alpha
        columns: []
    - - suggested_model_name: beta
        columns: []
  - suggested_model_name: gamma
    columns: []
""".lstrip(),
        encoding="utf-8",
    )

    contract = load_contract(contract_path)
    model_names = [t["suggested_model_name"] for t in contract["tables"]]
    assert model_names == ["alpha", "beta", "gamma"]
