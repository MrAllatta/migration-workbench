# Migration Safety Checks

Interpret `diff_contracts()` output for destructive migration risks and
warn before codegen generates code that would cause data loss or failed
migrations.

## CLI interface

```
wb contract safety --old contracts/v1.yaml --new contracts/v2.yaml [--json]
```

Same pattern as `wb contract diff`. Text output lists risks grouped by
severity; `--json` emits machine-readable list.

## Core function

`migration_safety_checks(diffs: dict[str, Any]) -> list[dict[str, Any]]`

Takes the output of `diff_contracts()` (two contracts already compared)
and returns a list of risk items:

```python
[
    {
        "severity": "DANGER",       # "DANGER" | "WARNING"
        "model": "Crop",
        "field": "legacy_id",       # "" for model-level issues
        "message": "Field removed — existing data will be lost",
        "detail": {"old_class": "models.IntegerField"},
    },
    ...
]
```

### Checks performed

| Check | Severity | Condition |
|-------|----------|-----------|
| Field removed | DANGER | Field present in old, absent in new |
| nullable→non-nullable | DANGER | Old has `null: True`, new has no `null` or `null: False` |
| Field class changed | WARNING | `class` values differ between old and new |
| `max_length` decreased | WARNING | Old `max_length` > new `max_length` |
| `unique=True` added | WARNING | New has `unique: True`, old doesn't |
| Non-nullable field added without default | WARNING | Field added, no `null: True`, no `default` in kwargs |

### Checks explicitly skipped (v1)

- `unique_together` / `indexes` / `constraints` changes — schema-only, not
  destructive to data.
- `choices` changes — no migration impact.
- `help_text` / `verbose_name` changes — cosmetic only.
- `db_table` changes — would create a new table (not destructive), but
  it's an edge case; defer.

## Implementation

Located in `workbook/codegen/contract.py` alongside `diff_contracts()`.

```python
MIGRATION_SEVERITY_DANGER = "DANGER"
MIGRATION_SEVERITY_WARNING = "WARNING"

def migration_safety_checks(diffs: dict[str, Any]) -> list[dict[str, Any]]:
    """Inspect diff output and return migration safety warnings."""
```

The function iterates over `diffs["model_diffs"]` and checks each
`fields_removed`, `fields_changed`, `fields_added` entry for the
conditions above.

For field class changes and kwarg comparisons, it looks at the
`fc["class"]["old"]` vs `fc["class"]["new"]` and
`fc.get("kwargs", {})` entries from the diff.

For nullability detection: checks if `null: True` was present in old
kwargs and absent (or `null: False`) in new kwargs. Since kwargs are
compared as `{"old": ..., "new": ...}`, the check is:
`kwargs_diff.get("null", {}).get("old") is True` and
`kwargs_diff.get("null", {}).get("new") is not True`.

## CLI wiring

Add `_contract_safety()` handler in `deployment/wb_cli.py` with the
same pattern as `_contract_diff()`:

```python
def _contract_safety(args: argparse.Namespace) -> int:
    # load_contract both files
    # diff_contracts(old, new)
    # migration_safety_checks(diffs)
    # render: text or JSON
```

## Out of scope

- Live migration analysis (running against actual DB). This is a static
  contract-level check only.
- Integration with `generate_models`. The first release is a standalone
  CLI check; hooking it into codegen is deferred.
