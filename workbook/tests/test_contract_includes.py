"""Tests for schema contract YAML includes in workbook.codegen.contract."""

from __future__ import annotations

import pytest

from workbook.codegen.contract import load_contract


def test_include_list_splices_into_tables(tmp_path):
    tables_path = tmp_path / "tables.yaml"
    tables_path.write_text(
        """
- suggested_model_name: inventory
  model_name: Inventory
  columns: []
- suggested_model_name: field
  model_name: Field
  columns: []
""".lstrip(),
        encoding="utf-8",
    )

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        """

tables:
  - suggested_model_name: crop
    model_name: Crop
    columns: []
  - !include_list tables.yaml
  - suggested_model_name: farmer
    model_name: Farmer
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

tables:
  - !include_list not_a_list.yaml
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"include_list expects a YAML list") as excinfo:
        load_contract(contract_path)

    message = str(excinfo.value)
    assert str(included_path) in message
    assert "dict" in message


def test_nested_includes_resolve_relative_to_including_file(tmp_path):
    includes_dir = tmp_path / "includes"
    includes_dir.mkdir()

    nested_tables_path = includes_dir / "nested_tables.yaml"
    nested_tables_path.write_text(
        """
- suggested_model_name: shipment
  model_name: Shipment
  columns: []
""".lstrip(),
        encoding="utf-8",
    )

    tables_path = includes_dir / "tables.yaml"
    tables_path.write_text(
        """
- suggested_model_name: harvest
  model_name: Harvest
  columns: []
- !include_list nested_tables.yaml
""".lstrip(),
        encoding="utf-8",
    )

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        """

tables:
  - !include_list includes/tables.yaml
""".lstrip(),
        encoding="utf-8",
    )

    contract = load_contract(contract_path)
    model_names = [t["suggested_model_name"] for t in contract["tables"]]
    assert model_names == ["harvest", "shipment"]


def test_multi_hop_include_cycle_reports_cyclic_and_file_names(tmp_path):
    first_path = tmp_path / "cycle_first.yaml"
    second_path = tmp_path / "cycle_second.yaml"

    first_path.write_text(
        """
- !include_list cycle_second.yaml
""".lstrip(),
        encoding="utf-8",
    )
    second_path.write_text(
        """
- !include_list cycle_first.yaml
""".lstrip(),
        encoding="utf-8",
    )

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        """

tables:
  - !include_list cycle_first.yaml
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"cyclic include detected") as excinfo:
        load_contract(contract_path)

    message = str(excinfo.value)
    assert first_path.name in message
    assert second_path.name in message


def test_tables_flattening_is_recursive(tmp_path):
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        """

tables:
  - - - suggested_model_name: planting
        model_name: Planting
        columns: []
    - - suggested_model_name: harvest
        model_name: Harvest
        columns: []
  - suggested_model_name: shipment
    model_name: Shipment
    columns: []
""".lstrip(),
        encoding="utf-8",
    )

    contract = load_contract(contract_path)
    model_names = [t["suggested_model_name"] for t in contract["tables"]]
    assert model_names == ["planting", "harvest", "shipment"]


def test_tables_entries_must_be_mappings_includes_type_name(tmp_path):
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        """

tables:
  - suggested_model_name: crop
    model_name: Crop
    columns: []
  - not a mapping
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError, match=r"schema contract tables entries must be mappings"
    ) as excinfo:
        load_contract(contract_path)

    assert "str" in str(excinfo.value)
