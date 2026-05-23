# Generator and Scaffold Resilience Refactor

**Date:** 2026-05-23
**Status:** Draft — pending implementation plan
**Scope:** `workbook` app (codegen, scaffold commands, partial output, exceptions)

---

## Problem

The `--continue-on-error` resilience feature was recently added to four commands:

- `scaffold_workbook_schema`
- `generate_models`
- `generate_admin`
- `generate_import`

It works, but the implementation has four coherence problems that accrue technical debt:

1. **Triplicated logic.** The load → validate → partition → write-rejections flow is copy-pasted with near-identical code across `generate_models.py`, `generate_admin.py`, and `generate_import.py`. Any behavior change requires editing three files.
2. **Loss of `!include` support.** The three generator commands bypassed `load_contract()` (which supports `!include` / `!include_list` tags) and replaced it with raw `yaml.safe_load()`, breaking contract composition for any user who relies on YAML includes.
3. **Fragile error matching.** Invalid tables are identified by doing `any(model_name in err for err in validation_errors)` against human-readable error strings. A model named `"Sale"` will be incorrectly flagged if an error mentions `"SaleItem"`.
4. **Rejection file collision.** All four commands write to the same path, `schema-contract-rejected.yaml`. A normal pipeline run (scaffold → models → admin → import) clobbers the rejection file at each step.

Additionally, two smaller issues exist:

5. **`UserFacingError` is defined but mostly unused.** The scaffold validation sites still raise plain `CommandError` and then parse strings to backfill structure into `PartialOutputCollector`.
6. **`pivot_detection_threshold` is inconsistently wired.** The cohort-corpus scaffold path reads the threshold from `coverage_payload`, but the bundle-config path hardcodes `0.5`.

---

## Goals

1. Centralize the load → validate → partition → write-rejections flow into one shared helper used by all four commands.
2. Restore `!include` / `!include_list` support in the generator commands.
3. Replace string-based error classification with structured validation results carrying an explicit `model_name` field.
4. Eliminate rejection-file collision by deriving the filename from the command’s output file.
5. Convert scaffold validation sites to raise `UserFacingError` natively, preserving `check_id` and `action` without string parsing.
6. Make `pivot_detection_threshold` consistently configurable across both scaffold code paths.

Non-goals:

- New CLI commands (e.g., `wb rejected summary`).
- Append-only event logs or JSONL rejection formats.
- Changes to `PartialOutputCollector`’s public interface beyond consuming `ValidationResult`.

---

## Design

### 1. `ValidationResult` — structured validation output

New module: `workbook/codegen/validation_pipeline.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ValidationResult:
    """A single validation finding against a contract table.

    Attributes:
        model_name: The contract table model_name that triggered the finding,
            or None for global-level errors that are not table-specific.
        check_id: Stable machine-readable identifier, e.g. ``WORKBOOK-CONTRACT-001``.
        message: Human-readable description of the problem.
        action: Concrete instruction the operator can follow to fix it.
        severity: ``error`` or ``warning``. Only ``error`` severity causes a table
            to be dropped during partition. Global errors (model_name=None)
            always cause hard failure regardless of ``--continue-on-error``.
    """

    model_name: str | None
    check_id: str
    message: str
    action: str | None = None
    severity: Literal["error", "warning"] = "error"
```

### 2. Refactor `strict_validate_contract` to return `list[ValidationResult]`

In `workbook/codegen/contract.py`, change the signature of `strict_validate_contract`:

```python
def strict_validate_contract(contract: dict[str, Any]) -> list[ValidationResult]:
    ...
```

Every check that currently appends a `str` to an `errors` list will instead yield a `ValidationResult` with the affected `model_name` explicitly set.

**Example:** The duplicate-model-name check currently does:

```python
errors.append(f"Duplicate model_name {model_name!r}")
```

It will become:

```python
results.append(
    ValidationResult(
        model_name=model_name,
        check_id="WORKBOOK-CONTRACT-003",
        message=f"Duplicate model_name {model_name!r}",
        action="Rename one of the duplicate tables or merge them",
    )
)
```

**Backwards compatibility:** The existing `validate_contract_tables()` function (which returns `list[str]` of warnings) remains unchanged. This refactor only touches `strict_validate_contract`.

### 3. Shared partition helper

Same module: `workbook/codegen/validation_pipeline.py`

```python
from pathlib import Path
from typing import Any

from workbench.exceptions import UserFacingError
from workbook.partial_output import PartialOutputCollector


class GlobalValidationError(UserFacingError):
    """Raised when a ValidationResult has model_name=None (global scope).

    These errors are not table-specific and always cause hard failure,
    even with ``--continue-on-error``.
    """


def partition_contract_on_validation(
    contract: dict[str, Any],
    results: list[ValidationResult],
    *,
    out_path: Path,
) -> tuple[dict[str, Any], PartialOutputCollector]:
    """Drop tables with error-level results and write rejections.

    Args:
        contract: The loaded (unvalidated) contract dict.
        results: Output from ``strict_validate_contract``.
        out_path: Path the *successful* output will be written to. Used to derive
            the rejection file name so parallel/sequential commands do not collide.

    Returns:
        A tuple of (clean_contract, collector). The clean_contract is a shallow
        copy with only valid tables retained. The collector contains rejections
        for every dropped table.

    Raises:
        GlobalValidationError: If any result has ``model_name=None`` and
            ``severity="error"``. These are structural problems (e.g. missing
            ``tables`` key) that cannot be recovered from by dropping a single table.
    """
```

**Partition logic:**

1. **Global errors first:** If any `ValidationResult` has `model_name=None` and `severity="error"`, raise `GlobalValidationError` immediately. This is a hard failure regardless of `--continue-on-error` — the contract structure itself is broken. The error message lists all global errors.
2. Collect all `model_name`s that appear in any `ValidationResult` with `severity == "error"`.
3. Build `clean_contract = dict(contract)`; filter `clean_contract["tables"]` to tables whose `model_name` is NOT in that set.
4. Build a lookup `table_by_model_name` from the original contract tables.
5. For each dropped table, find the first `ValidationResult` for that `model_name` and call `PartialOutputCollector.add(...)` using the result's own `check_id`, `message`, and `action`.
6. If the collector is not empty, derive `rejection_path = out_path.parent / (out_path.stem + "-rejected.yaml")` and call `collector.write_rejection_file(rejection_path)`.
7. Return `(clean_contract, collector)`.

### 4. Restore `!include` — split `load_contract`

In `workbook/codegen/contract.py`:

```python
def load_contract_unvalidated(base_path: str | Path) -> dict[str, Any]:
    """Load a contract YAML, resolving ``!include`` / ``!include_list`` tags.

    Does *not* run validation. Returns the raw dict.
    """
    ...


def load_contract(base_path: str | Path) -> dict[str, Any]:
    """Load and strictly validate a contract YAML.

    Raises ``ValueError`` (or ``UserFacingError`` for include problems) if
    validation fails.
    """
    contract = load_contract_unvalidated(base_path)
    results = strict_validate_contract(contract)
    if results:
        lines = [f"  {r.check_id}: {r.message}" for r in results]
        if any(r.action for r in results):
            lines.append("Suggested actions:")
            for r in results:
                if r.action:
                    lines.append(f"  - {r.action}")
        raise ValueError("Contract validation failed:\n" + "\n".join(lines))
    return contract
```

The custom YAML loader (with cyclic-include detection and missing-file handling, already converted to `UserFacingError` in commit `8140e75`) lives inside `load_contract_unvalidated`.

### 5. Generator command refactor

Each of the three generator commands (`generate_models`, `generate_admin`, `generate_import`) changes as follows:

**Before (current):**

```python
contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
# ... triplicated validation + partition + rejection logic
```

**After:**

```python
from workbook.codegen.contract import load_contract_unvalidated, strict_validate_contract
from workbook.codegen.validation_pipeline import partition_contract_on_validation

contract = load_contract_unvalidated(str(contract_path))

if options.get("continue_on_error") and contract.get("tables"):
    results = strict_validate_contract(contract)
    contract, collector = partition_contract_on_validation(
        contract,
        results,
        out_path=out_path,
    )
    if not collector.is_empty():
        self.stdout.write(self.style.WARNING(collector.summary()))

# proceed with validate_contract_tables warnings as before
warnings = validate_contract_tables(contract)
```

The ~40 lines of triplicated validation/partition code in each command is deleted and replaced by the 6-line block above.

### 6. Scaffold command refactor

`scaffold_workbook_schema` already has `_validate_tables_for_scaffold`, which is the *right* pattern. Two changes:

1. `_check_null_model_names`, `_check_pivot_tables`, and `_check_invalid_identifiers` raise `UserFacingError` instead of `CommandError`.
2. `_validate_tables_for_scaffold` catches `UserFacingError` when `continue_on_error=True` and feeds it into `PartialOutputCollector.add()` without string parsing.

**Signatures change from returning `list[str]` to raising:**

- `_check_null_model_names` and `_check_pivot_tables` each produce at most one finding, so they raise a single `UserFacingError`.
- `_check_invalid_identifiers` can produce multiple findings (one per invalid field name). It changes to an inner loop that raises one `UserFacingError` per invalid field. The calling code in `_validate_tables_for_scaffold` wraps each check call in its own try/except, so each invalid field is individually collected or re-raised.

Example for `_check_pivot_tables`:

```python
from workbench.exceptions import UserFacingError

def _check_pivot_tables(table: dict, *, pivot_detection_threshold: float = 0.5) -> None:
    """Raise UserFacingError if the table looks like a pivot table."""
    columns = table.get("columns", [])
    if not columns:
        return
    headers = [col.get("source_column", "").strip() for col in columns]
    numeric_headers = [h for h in headers if h.isdigit()]
    if len(numeric_headers) / len(headers) > pivot_detection_threshold:
        tab_title = table.get("bundle_worksheet_title", "?")
        numeric_list = ", ".join(numeric_headers[:10])
        raise UserFacingError(
            f"Tab {tab_title!r} has numeric headers ({numeric_list}) — likely a pivot table",
            action="Add to vocabulary.derived or exclude from corpus config",
            check_id="SCAFFOLD_PIVOT_TABLE",
        )
```

Example for `_check_invalid_identifiers` (multi-error raise pattern):

```python
def _check_invalid_identifiers(table: dict) -> None:
    """Raise UserFacingError per invalid field or model name."""
    model_name = str(table.get("model_name", "")).strip()
    tab_title = table.get("bundle_worksheet_title", "?")
    if model_name and not is_valid_python_identifier(model_name):
        raise UserFacingError(
            f"model_name {model_name!r} is not a valid Python identifier",
            action="Rename the source tab or set an explicit suggested_model_name",
            check_id="SCAFFOLD_INVALID_IDENTIFIER",
        )
    for col in table.get("columns", []):
        field_name = col.get("suggested_field_name", "")
        if field_name and not is_valid_python_identifier(field_name):
            raise UserFacingError(
                f"Field name {field_name!r!r} is not a valid Python identifier",
                action="Rename the source column header or add a column alias in the bundle config",
                check_id="SCAFFOLD_INVALID_IDENTIFIER",
            )
```

And in `_validate_tables_for_scaffold`:

```python
from workbench.exceptions import UserFacingError

checks = [
    lambda: _check_null_model_names(table),
    lambda: _check_pivot_tables(table, pivot_detection_threshold=pivot_detection_threshold),
    lambda: _check_invalid_identifiers(table),
]
for check in checks:
    try:
        check()
    except UserFacingError as exc:
        if continue_on_error:
            collector.add(
                table,
                check_id=exc.check_id,
                message=str(exc),
                action=exc.action,
            )
            continue
        raise CommandError(str(exc)) from exc
```

Note: The loop structure above means that when `continue_on_error=True`, each check runs independently — if `_check_null_model_names` adds a rejection, `_check_pivot_tables` still runs for the same table. When not continuing on error, the first `UserFacingError` terminates validation for that table immediately (same behavior as today).

### 7. Rejection file naming convention

The `partition_contract_on_validation` helper derives the rejection path from the *output file* path:

```python
rejection_path = out_path.parent / (out_path.stem + "-rejected.yaml")
```

For a command writing to `backend/apps/core/models_auto.py`, the rejection file is `backend/apps/core/models_auto-rejected.yaml`.

For `scaffold_workbook_schema` writing to `schema-contract.yaml`, the rejection file is `schema-contract-rejected.yaml` (same as today).

This means a standard pipeline run produces up to four rejection files, none overwriting another:

1. `schema-contract-rejected.yaml`
2. `models_auto-rejected.yaml`
3. `admin_auto-rejected.yaml`
4. `import_core-rejected.yaml`

### 8. Pivot detection threshold consistency

Add a `--pivot-detection-threshold` CLI argument to `scaffold_workbook_schema`:

```python
parser.add_argument(
    "--pivot-detection-threshold",
    type=float,
    default=0.5,
    help="Fraction of numeric column headers required to flag a table as a pivot (default 0.5)",
)
```

**Bundle-config path:** Pass the CLI value straight through to `_validate_tables_for_scaffold(..., pivot_detection_threshold=options["pivot_detection_threshold"])`.

**Cohort-corpus path:** Use `coverage_payload.get("pivot_detection_threshold", cli_threshold)` if the payload has a key, else `cli_threshold`. The CLI flag is an absolute override. If the operator passes `--pivot-detection-threshold 0.7`, that value is used regardless of the corpus payload. If the operator omits the flag, the corpus payload’s threshold (or the default 0.5) is used.

---

## Files touched

| File | Change |
|---|---|
| `workbook/codegen/validation_pipeline.py` | **New.** `ValidationResult`, `GlobalValidationError`, `partition_contract_on_validation`. |
| `workbook/codegen/contract.py` | Refactor `strict_validate_contract` to return `list[ValidationResult]`; add `load_contract_unvalidated`; keep `load_contract` backwards-compatible (format `ValidationResult` list into `ValueError`). |
| `workbook/management/commands/generate_models.py` | Replace triplicated validation logic with shared helper; restore `load_contract_unvalidated`. |
| `workbook/management/commands/generate_admin.py` | Same as above. |
| `workbook/management/commands/generate_import.py` | Same as above. |
| `workbook/management/commands/validate_contract.py` | Update `strict_validate_contract` call site: iterate `ValidationResult` objects, use `.check_id` and `.message` instead of treating results as `str`. |
| `workbook/management/commands/scaffold_workbook_schema.py` | Convert `_check_*` functions to raise `UserFacingError`; refactor `_validate_tables_for_scaffold` to use a check loop; wire `--pivot-detection-threshold` through both paths. |
| `workbook/tests/test_validation_pipeline.py` | **New.** Tests for `ValidationResult`, `partition_contract_on_validation`, `GlobalValidationError` on global-scope results. |
| `workbook/tests/test_contract.py` (or existing) | Update `strict_validate_contract` tests for new return type (`list[ValidationResult]`). |
| `workbook/tests/test_generate_models_command.py` | Update tests for shared helper usage. |
| `workbook/tests/test_admin_generator.py` | Update tests for shared helper usage. |
| `workbook/tests/test_generate_import_command.py` | Update tests for shared helper usage. |
| `workbook/tests/test_scaffold_workbook_schema.py` | Add tests for `--pivot-detection-threshold`, `UserFacingError` paths, and multi-error per table with `continue_on_error`. |

---

## Testing

1. **Unit:** `test_validation_pipeline.py` covers:
   - `partition_contract_on_validation` drops only tables with `severity="error"`.
   - Warnings (`severity="warning"`) do not cause dropping.
   - Rejection file is derived from `out_path`.
   - `PartialOutputCollector` entries carry the original `ValidationResult.check_id`.
   - `GlobalValidationError` is raised when any `ValidationResult` has `model_name=None` and `severity="error"`.
   - `GlobalValidationError` is NOT raised when `model_name=None` results have `severity="warning"`.

2. **Integration:** Each generator command test exercises:
   - A contract with one invalid table + `--continue-on-error`.
   - Asserts the rejection file is written to the command-specific path.
   - Asserts the generated output file still contains the valid tables.

3. **Integration:** `validate_contract.py` test exercises:
   - `validate_contract --strict` prints `ValidationResult.check_id` and `.message` (not raw `str`).
   - Exit code and summary remain correct.

4. **Regression:**
   - A contract using `!include` tags loads successfully through the generator commands.
   - `load_contract()` (the old path) still raises on invalid contracts.

5. **Scaffold multi-error:**
   - A table with both a pivot-table structure and an invalid model name: both `UserFacingError`s are collected when `--continue-on-error` is set.
   - A table with multiple invalid field names: the first invalid field raises, subsequent fields in the same check call are not reached (single-raise pattern).

---

## Rollback / risk

- `strict_validate_contract` changes its return type from `list[str]` to `list[ValidationResult]`. There are four call sites outside the three generators:
  - `workbook/management/commands/validate_contract.py:48-53` — iterates errors as `str`. Update to use `result.check_id` and `result.message`.
  - `workbook/tests/test_validate_contract.py` — asserts on `strict_validate_contract` return values. Update for `ValidationResult` objects.
- The three generator commands previously bypassed `load_contract`. Restoring the YAML custom loader re-enables `!include` — this is a fix, not a risk, but verify no tests relied on `yaml.safe_load` behavior.
- `PartialOutputCollector.add()` currently accepts `check_id`, `message`, `action` as kwargs. The new code uses the same kwargs. No interface change needed there.
- `_check_invalid_identifiers` currently returns all invalid fields in one call. After the refactor it raises on the first invalid field per call. Tests that assert on multiple errors from one `_check_invalid_identifiers` call need updating to call it once per field or use `_validate_tables_for_scaffold` at the integration level.

---

## Dependencies

None outside the existing codebase. This is a pure refactor.

---

## Future work (out of scope)

- Append-only JSONL event log for multi-run analysis.
- `wb rejected summary` CLI command.
- Propagate `ValidationResult` into `validate_contract_tables` warnings as well, unifying the entire validation surface under one structured type.
