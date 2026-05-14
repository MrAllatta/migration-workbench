"""Validate a schema-contract YAML file.

Usage: python scripts/validate_contract.py <path-to-contract.yaml>

Checks:
- YAML is parseable
- Contract version is supported
- FK target models exist in the contract
- Column FK references resolve
"""

import sys
from pathlib import Path

import yaml


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_contract.py <contract.yaml>")
        sys.exit(1)

    contract_path = Path(sys.argv[1])
    if not contract_path.is_file():
        print(f"File not found: {contract_path}")
        sys.exit(1)

    raw = contract_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    if not isinstance(data, dict):
        print("ERROR: schema contract must be a YAML mapping")
        sys.exit(1)

    version = str(data.get("version") or "1.0")
    if version not in ("1.0", "1.1", "1.2", "1.3"):
        print(f"ERROR: unsupported version: {version}")
        sys.exit(1)

    tables = data.get("tables") or []
    table_names = {t.get("suggested_model_name", "?") for t in tables}
    print(f"Contract v{version}: {len(tables)} table(s)")
    for name in sorted(table_names):
        print(f"  - {name}")

    exit_code = 0
    for table in tables:
        name = table.get("suggested_model_name", "?")
        for fk_field, fk_cfg in (
            (table.get("import_config") or {}).get("fk_lookup", {}).items()
        ):
            target = fk_cfg.get("model")
            if target and target not in table_names:
                print(
                    f'  WARNING: {name}.{fk_field} FK target "{target}" '
                    f"not in contract tables"
                )
                exit_code = 1
        for col in table.get("columns") or []:
            fname = col.get("suggested_field_name", "?")
            fk_to = (col.get("django_field_kwargs") or {}).get("to")
            if fk_to and fk_to not in table_names and fk_to != "self":
                print(
                    f'  WARNING: {name}.{fname} FK target "{fk_to}" '
                    f"not in contract tables"
                )
                exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
