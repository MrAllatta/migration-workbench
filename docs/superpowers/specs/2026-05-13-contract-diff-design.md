# Contract diff tool

Compare two schema-contract YAML files and emit a structured delta of
models, fields, and meta options.  Essential for drift checking and code
review across contract versions.

## CLI interface

```
wb contract diff --old contracts/v1.yaml --new contracts/v2.yaml [--json]
```

Follows the existing `wb` CLI pattern (`deployment/wb_cli.py`): `--json`
flag switches from human-readable text output to machine-readable JSON.

## Core function

`diff_contracts(old: dict, new: dict) -> dict` in
`workbook/codegen/contract.py` (alongside `review_contract`).

Takes two normalised contract dicts (already loaded and validated via
`load_contract`).  Returns a dict with keyed diff sections.

### Model matching

Models are matched by `suggested_model_name` (case-sensitive exact match).
No fuzzy rename detection.  Models present in only one contract are
reported as "added" or "removed".

### Field comparison

Fields are resolved via `get_fields()` (so `field_overrides`,
`fk_resolutions`, and `extra_fields` are accounted for).  Matched by field
`name` within each model.

For each matched field, compare:
- `class` (e.g. `models.CharField` → `models.TextField`)
- `kwargs` dict keys and values (added kwargs, removed kwargs, changed values)

### Meta comparison

Compare the resolved `model_meta` dict for each matched model:
- `unique_together`
- `indexes`
- `constraints`
- `ordering`
- `verbose_name`
- `db_table`
- `app_label`

Boolean/is_abstract/computed_fields/hooks/import_config/str_template are out
of scope for the initial implementation.

## Return value

```python
{
    "models_added": ["ModelName", ...],
    "models_removed": ["ModelName", ...],
    "model_diffs": {
        "ModelName": {
            "fields_added": [
                {"name": "field_name", "class": "models.CharField",
                 "kwargs": {"max_length": 100}}
            ],
            "fields_removed": [
                {"name": "old_field", ...}
            ],
            "fields_changed": [
                {
                    "name": "field_name",
                    "class": {"old": "models.TextField", "new": "models.CharField"},
                    "kwargs": {
                        "max_length": {"old": None, "new": 100},
                        "blank": {"old": True, "new": False},
                    }
                }
            ],
            "meta_changed": {
                "unique_together": {"old": [["name"]], "new": [["name", "variety"]]},
                "ordering": {"old": ["name"], "new": None},
                ...
            }
        }
    }
}
```

A key is absent (or `None`) when there is no change for that category.

## Text output format

```
=== Models ===
  Added:   InventoryEntry, FieldEvent
  Removed: LegacyCrop

=== Model: Crop ===
  Fields added:
    + variety (CharField, max_length=100, null=True)
  Fields removed:
    - legacy_id (IntegerField)
  Fields changed:
    ~ name: CharField max_length: 100 → 200
    ~ crop_type: TextField → CharField
  Meta changes:
    ~ unique_together: [["name"]] → [["name", "variety"]]
    - ordering: ["-name"]
```

## Implementation plan

1. Implement `diff_contracts()` in `contract.py` with model/field/meta comparison.
2. Add `_contract_diff()` handler + CLI wiring in `deployment/wb_cli.py`.
3. Add unit tests in `workbook/tests/test_schema_contract.py`.
4. Verify 222+ existing tests still pass.
