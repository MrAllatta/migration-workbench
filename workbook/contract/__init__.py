"""Contract layer: loading, accessors, validation, and diff for schema contracts.

Split from ``workbook/codegen/contract.py`` during the
``contract-layer-split`` epic (e04, version 0.9.8).

Each responsibility lives in its own module:

- ``loading`` — YAML loading, ``!include`` support, normalisation
- ``accessors`` — model/field/admin/import config lookups
- ``validation`` — structural and strict validation rules
- ``diff`` — contract comparison and migration safety checks
"""
