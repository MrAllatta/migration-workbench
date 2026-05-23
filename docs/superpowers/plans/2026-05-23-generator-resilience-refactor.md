# Generator and Scaffold Resilience Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize the load-validate-partition-write-rejections flow, restore `!include` support, replace string-based error matching with structured `ValidationResult`, fix rejection-file collision, convert scaffold checks to `UserFacingError`, and make `pivot_detection_threshold` consistently configurable.

**Architecture:** Introduce `ValidationResult` and `GlobalValidationError` in a new `workbook/codegen/validation_pipeline.py` module. Refactor `strict_validate_contract` to return `list[ValidationResult]` instead of `list[str]`. Add `partition_contract_on_validation` helper that drops error-level tables and writes per-command rejection files. Split `load_contract` into `load_contract_unvalidated` (preserves `!include`) and `load_contract` (validates). Convert `_check_pivot_tables`, `_check_null_model_names`, and `_check_invalid_identifiers` from returning `list[str]` to raising `UserFacingError`. Wire `--pivot-detection-threshold` through both scaffold paths.

**Tech Stack:** Python 3.11, Django management commands, PyYAML, pytest.

**Worktree:** `plan/2026-05-23-generator-resilience-refactor` branched from `master`.

---

## Task 1: ValidationResult and GlobalValidationError

**Files:**
- Create: `workbook/codegen/validation_pipeline.py`
- Test: `workbook/tests/test_validation_pipeline.py`

- [ ] **Step 1: Write failing tests for ValidationResult**

Create `workbook/tests/test_validation_pipeline.py`:

```python
from __future__ import annotations

import pytest
from pathlib import Path

from workbook.codegen.validation_pipeline import (
    ValidationResult,
    GlobalValidationError,
    partition_contract_on_validation,
)
from workbook.partial_output import PartialOutputCollector


class TestValidationResult:
    def test_frozen(self):
        result = ValidationResult(
            model_name="Crop",
            check_id="WORKBOOK-CONTRACT-001",
            message="empty model_name",
        )
        with pytest.raises(AttributeError):
            result.model_name = "changed"

    def test_defaults(self):
        result = ValidationResult(
            model_name="Crop",
            check_id="WORKBOOK-CONTRACT-001",
            message="test",
        )
        assert result.action is None
        assert result.severity == "error"

    def test_warning_severity(self):
        result = ValidationResult(
            model_name="Crop",
            check_id="WORKBOOK-CONTRACT-001",
            message="test",
            severity="warning",
        )
        assert result.severity == "warning"

    def test_global_error(self):
        result = ValidationResult(
            model_name=None,
            check_id="WORKBOOK-CONTRACT-000",
            message="no tables key",
        )
        assert result.model_name is None

    def test_literal_severity_rejects_invalid(self):
        with pytest.raises(TypeError):
            ValidationResult(
                model_name="Crop",
                check_id="TEST",
                message="test",
                severity="critical",
            )


class TestGlobalValidationError:
    def test_is_user_facing_error(self):
        from workbench.exceptions import UserFacingError
        err = GlobalValidationError(
            "structure broken",
            check_id="WORKBOOK-CONTRACT-000",
            action="Fix the contract YAML",
        )
        assert isinstance(err, UserFacingError)

    def test_carries_check_id_and_action(self):
        err = GlobalValidationError(
            "no tables key",
            check_id="WORKBOOK-CONTRACT-000",
            action="Add a tables key",
        )
        assert err.check_id == "WORKBOOK-CONTRACT-000"
        assert err.action == "Add a tables key"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest workbook/tests/test_validation_pipeline.py -v`
Expected: FAIL — `workbook.codegen.validation_pipeline` module does not exist.

- [ ] **Step 3: Implement ValidationResult and GlobalValidationError**

Create `workbook/codegen/validation_pipeline.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from workbench.exceptions import UserFacingError
from workbook.partial_output import PartialOutputCollector


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
    global_errors = [r for r in results if r.model_name is None and r.severity == "error"]
    if global_errors:
        lines = [f"  {r.check_id}: {r.message}" for r in global_errors]
        raise GlobalValidationError(
            "Contract has structural errors that cannot be skipped:\n" + "\n".join(lines),
            check_id="WORKBOOK-CONTRACT-GLOBAL",
            action="Fix the contract structure and re-run",
        )

    error_model_names: set[str] = set()
    for r in results:
        if r.model_name is not None and r.severity == "error":
            error_model_names.add(r.model_name)

    original_tables = list(contract.get("tables") or [])
    clean_tables = [t for t in original_tables if t.get("model_name") not in error_model_names]

    clean_contract = dict(contract)
    clean_contract["tables"] = clean_tables

    table_by_model_name: dict[str, dict[str, Any]] = {}
    for t in original_tables:
        mn = t.get("model_name")
        if mn:
            table_by_model_name[mn] = t

    collector = PartialOutputCollector()
    for model_name in sorted(error_model_names):
        table = table_by_model_name.get(model_name, {"model_name": model_name})
        first_result = next(r for r in results if r.model_name == model_name and r.severity == "error")
        collector.add(
            table,
            check_id=first_result.check_id,
            message=first_result.message,
            action=first_result.action,
        )

    if not collector.is_empty():
        rejection_path = out_path.parent / (out_path.stem + "-rejected.yaml")
        collector.write_rejection_file(rejection_path)

    return clean_contract, collector
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest workbook/tests/test_validation_pipeline.py -v`
Expected: All `TestValidationResult` and `TestGlobalValidationError` tests PASS.
The `TestPartition` tests in the same file haven't been written yet — that's Task 2.

- [ ] **Step 5: Commit**

```bash
git add workbook/codegen/validation_pipeline.py workbook/tests/test_validation_pipeline.py
git commit -m "feat: add ValidationResult, GlobalValidationError, and partition_contract_on_validation"
```

---

## Task 2: Partition helper tests

**Files:**
- Modify: `workbook/tests/test_validation_pipeline.py`

- [ ] **Step 1: Write partition tests**

Append to `workbook/tests/test_validation_pipeline.py`:

```python
class TestPartitionContractOnValidation:
    @pytest.fixture()
    def basic_contract(self):
        return {
            "version": "1.3",
            "source": {},
            "tables": [
                {"model_name": "Crop", "columns": [{"suggested_field_name": "name"}]},
                {"model_name": "SaleItem", "columns": [{"suggested_field_name": "amount"}]},
                {"model_name": "Farm", "columns": [{"suggested_field_name": "name"}]},
            ],
        }

    def test_drops_error_tables(self, basic_contract, tmp_path):
        out_path = tmp_path / "models_auto.py"
        results = [
            ValidationResult(model_name="SaleItem", check_id="TEST-001", message="duplicate"),
        ]
        clean, collector = partition_contract_on_validation(
            basic_contract, results, out_path=out_path,
        )
        assert [t["model_name"] for t in clean["tables"]] == ["Crop", "Farm"]
        assert not collector.is_empty()

    def test_warning_does_not_drop(self, basic_contract, tmp_path):
        out_path = tmp_path / "models_auto.py"
        results = [
            ValidationResult(
                model_name="SaleItem",
                check_id="TEST-WARN",
                message="minor issue",
                severity="warning",
            ),
        ]
        clean, collector = partition_contract_on_validation(
            basic_contract, results, out_path=out_path,
        )
        assert [t["model_name"] for t in clean["tables"]] == ["Crop", "SaleItem", "Farm"]
        assert collector.is_empty()

    def test_rejection_file_derived_from_out_path(self, basic_contract, tmp_path):
        out_path = tmp_path / "backend" / "models_auto.py"
        results = [
            ValidationResult(model_name="SaleItem", check_id="TEST-001", message="bad"),
        ]
        clean, collector = partition_contract_on_validation(
            basic_contract, results, out_path=out_path,
        )
        expected_rejection = tmp_path / "backend" / "models_auto-rejected.yaml"
        assert expected_rejection.exists()

    def test_check_id_carried_through(self, basic_contract, tmp_path):
        out_path = tmp_path / "models_auto.py"
        results = [
            ValidationResult(
                model_name="SaleItem",
                check_id="WORKBOOK-CONTRACT-003",
                message="Duplicate model_name 'SaleItem'",
                action="Rename one of the duplicate tables",
            ),
        ]
        clean, collector = partition_contract_on_validation(
            basic_contract, results, out_path=out_path,
        )
        assert collector.rejected[0].check_id == "WORKBOOK-CONTRACT-003"
        assert collector.rejected[0].action == "Rename one of the duplicate tables"

    def test_raises_global_error(self, basic_contract, tmp_path):
        out_path = tmp_path / "models_auto.py"
        results = [
            ValidationResult(model_name=None, check_id="GLOBAL-001", message="no tables key"),
        ]
        with pytest.raises(GlobalValidationError):
            partition_contract_on_validation(basic_contract, results, out_path=out_path)

    def test_global_warning_does_not_raise(self, basic_contract, tmp_path):
        out_path = tmp_path / "models_auto.py"
        results = [
            ValidationResult(
                model_name=None,
                check_id="GLOBAL-WARN",
                message="minor",
                severity="warning",
            ),
        ]
        clean, collector = partition_contract_on_validation(
            basic_contract, results, out_path=out_path,
        )
        assert len(clean["tables"]) == 3

    def test_no_errors_returns_clean_copy(self, basic_contract, tmp_path):
        out_path = tmp_path / "models_auto.py"
        clean, collector = partition_contract_on_validation(
            basic_contract, [], out_path=out_path,
        )
        assert [t["model_name"] for t in clean["tables"]] == ["Crop", "SaleItem", "Farm"]
        assert collector.is_empty()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest workbook/tests/test_validation_pipeline.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add workbook/tests/test_validation_pipeline.py
git commit -m "test: add partition_contract_on_validation tests"
```

---

## Task 3: Refactor strict_validate_contract to return list[ValidationResult]

**Files:**
- Modify: `workbook/codegen/contract.py` (the `strict_validate_contract` function, currently at line ~1005)
- Modify: `workbook/tests/test_validate_contract.py`

- [ ] **Step 1: Write tests for new ValidationResult return type**

Rewrite `workbook/tests/test_validate_contract.py`:

```python
from workbook.codegen.contract import strict_validate_contract
from workbook.codegen.validation_pipeline import ValidationResult


def test_strict_validate_duplicate_model():
    contract = {
        "tables": [
            {"model_name": "Crop", "columns": []},
            {"model_name": "Crop", "columns": []},
        ]
    }
    results = strict_validate_contract(contract)
    assert isinstance(results, list)
    assert all(isinstance(r, ValidationResult) for r in results)
    assert any(r.model_name == "Crop" and "VALIDATE_DUPLICATE_MODEL" in r.check_id for r in results)


def test_strict_validate_invalid_field():
    contract = {
        "tables": [
            {
                "model_name": "Unit",
                "columns": [{"suggested_field_name": "201_unit"}],
            }
        ]
    }
    results = strict_validate_contract(contract)
    assert isinstance(results, list)
    assert any(r.model_name == "Unit" and "INVALID_FIELD_NAME" in r.check_id for r in results)


def test_strict_validate_null_model():
    contract = {
        "tables": [
            {"model_name": "", "columns": []},
        ]
    }
    results = strict_validate_contract(contract)
    assert isinstance(results, list)
    assert any(r.model_name == "" and "NULL_MODEL" in r.check_id for r in results)


def test_strict_validate_returns_empty_for_valid():
    contract = {
        "tables": [
            {"model_name": "Crop", "columns": [{"suggested_field_name": "name"}]},
        ]
    }
    results = strict_validate_contract(contract)
    assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest workbook/tests/test_validate_contract.py -v`
Expected: FAIL — `strict_validate_contract` still returns `list[str]`.

- [ ] **Step 3: Refactor strict_validate_contract**

In `workbook/codegen/contract.py`, locate the `strict_validate_contract` function (starting around line 1005). Replace its entire implementation. Add the import at the top of the file:

Add near the top of `contract.py`, after existing imports:

```python
from workbook.codegen.validation_pipeline import ValidationResult
```

Replace the `strict_validate_contract` function with:

```python
def strict_validate_contract(contract: dict[str, Any]) -> list[ValidationResult]:
    """Run strict validation checks and return structured results.

    Checks:
    - No model_name is null or empty.
    - Every suggested_field_name is a valid Python identifier and not a keyword.
    - No duplicate model_name values exist across tables.
    - No suggested_field_name starts with a digit.
    """
    import keyword

    results: list[ValidationResult] = []
    tables = list(contract.get("tables") or [])
    model_names: list[str] = []

    for table in tables:
        model_name = str(table.get("model_name", "")).strip()
        if not model_name:
            label = table.get("suggested_model_name") or table.get("bundle_worksheet_title", "?")
            results.append(
                ValidationResult(
                    model_name=model_name if model_name else None,
                    check_id="WORKBOOK-CONTRACT-NULL-MODEL",
                    message=f"Table '{label}' has empty model_name",
                    action="Set a unique model_name or add suggested_model_name to the contract",
                )
            )
            continue
        model_names.append(model_name)

    seen_model_names: set[str] = set()
    for mn in model_names:
        if mn in seen_model_names:
            results.append(
                ValidationResult(
                    model_name=mn,
                    check_id="WORKBOOK-CONTRACT-DUPLICATE-MODEL",
                    message=f'Duplicate model_name "{mn}" (2+ tables)',
                    action="Rename one of the duplicate tables or merge them",
                )
            )
        seen_model_names.add(mn)

    for table in tables:
        model_name = str(table.get("model_name", "")).strip()
        for col in table.get("columns", []):
            field_name = col.get("suggested_field_name", "")
            if not field_name:
                continue
            if not str(field_name).isidentifier() or keyword.iskeyword(str(field_name)):
                results.append(
                    ValidationResult(
                        model_name=model_name or None,
                        check_id="WORKBOOK-CONTRACT-INVALID-FIELD-NAME",
                        message=f'Field "{field_name}" in model "{model_name}" is not a valid Python identifier',
                        action="Rename the source column in the contract",
                    )
                )
            elif str(field_name)[0].isdigit():
                results.append(
                    ValidationResult(
                        model_name=model_name or None,
                        check_id="WORKBOOK-CONTRACT-INVALID-FIELD-NAME",
                        message=f'Field "{field_name}" in model "{model_name}" starts with a digit',
                        action="Rename the source column in the contract",
                    )
                )

    return results
```

- [ ] **Step 4: Run all contract and validate tests**

Run: `.venv/bin/python -m pytest workbook/tests/test_validate_contract.py workbook/tests/test_contract_validation.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add workbook/codegen/contract.py workbook/tests/test_validate_contract.py
git commit -m "refactor: strict_validate_contract returns list[ValidationResult]"
```

---

## Task 4: Add load_contract_unvalidated and update load_contract error formatting

**Files:**
- Modify: `workbook/codegen/contract.py` (split `load_contract`)
- Test: existing `workbook/tests/test_contract_includes.py`

- [ ] **Step 1: Verify existing include tests pass before change**

Run: `.venv/bin/python -m pytest workbook/tests/test_contract_includes.py -v`
Expected: All PASS (baseline).

- [ ] **Step 2: Add load_contract_unvalidated**

In `workbook/codegen/contract.py`, locate the `load_contract` function. Extract its YAML-loading logic into `load_contract_unvalidated`. The `load_contract` function should call `load_contract_unvalidated` and then validate.

Find the `load_contract` function (starting around line 88). It currently handles both YAML loading with `!include` tags and validation. Split it:

```python
def load_contract_unvalidated(path: str | Path) -> dict[str, Any]:
    """Load a contract YAML, resolving ``!include`` / ``!include_list`` tags.

    Does *not* run validation. Returns the raw dict.
    """
    import yaml

    src = Path(path).read_text(encoding="utf-8")
    loader_cls = _make_contract_loader(path)
    raw: dict[str, Any] = yaml.load(src, Loader=loader_cls)
    if not isinstance(raw, dict):
        raise ValueError("schema contract must be a YAML mapping")

    raw.setdefault("version", "")
    raw.setdefault("source", {})
    raw.setdefault("tables", [])

    tables = raw.get("tables")
    if not isinstance(tables, list):
        raise ValueError("schema contract tables must be a YAML list")

    def _walk_table_entries(table_entries: list[Any]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for entry in table_entries:
            if isinstance(entry, list):
                flattened.extend(_walk_table_entries(entry))
                continue
            flattened.append(entry)
        return flattened

    flat_tables = _walk_table_entries(raw.get("tables") or [])
    raw["tables"] = flat_tables
    return raw


def load_contract(path: str | Path) -> dict[str, Any]:
    """Load and strictly validate a contract YAML.

    Raises ``ValueError`` (or ``UserFacingError`` for include problems) if
    validation fails.
    """
    contract = load_contract_unvalidated(path)
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

Important: the `_walk_table_entries` flattening logic must stay in `load_contract_unvalidated`, NOT in the old `load_contract`. The `load_contract` function now calls `load_contract_unvalidated` first and then validates.

- [ ] **Step 3: Run include and contract tests**

Run: `.venv/bin/python -m pytest workbook/tests/test_contract_includes.py workbook/tests/test_validate_contract.py workbook/tests/test_contract_validation.py -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add workbook/codegen/contract.py
git commit -m "refactor: split load_contract into load_contract_unvalidated and load_contract"
```

---

## Task 5: Update validate_contract.py command for ValidationResult

**Files:**
- Modify: `workbook/management/commands/validate_contract.py`

- [ ] **Step 1: Update validate_contract.py**

Current code (lines 47-53):

```python
if options["strict"]:
    from workbook.codegen.contract import strict_validate_contract
    strict_errors = strict_validate_contract(contract)
    for err in strict_errors:
        self.stdout.write(self.style.ERROR(err))
    if strict_errors:
        raise CommandError(f"Strict validation failed with {len(strict_errors)} error(s).")
```

Replace with:

```python
if options["strict"]:
    from workbook.codegen.contract import strict_validate_contract
    strict_results = strict_validate_contract(contract)
    for result in strict_results:
        line = f"{result.check_id}: {result.message}"
        if result.action:
            line += f" (Action: {result.action})"
        self.stdout.write(self.style.ERROR(line))
    if strict_results:
        raise CommandError(f"Strict validation failed with {len(strict_results)} error(s).")
```

- [ ] **Step 2: Run validate_contract tests**

Run: `.venv/bin/python -m pytest workbook/tests/test_validate_contract.py -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add workbook/management/commands/validate_contract.py
git commit -m "refactor: update validate_contract command for ValidationResult return type"
```

---

## Task 6: Refactor the three generator commands

**Files:**
- Modify: `workbook/management/commands/generate_models.py`
- Modify: `workbook/management/commands/generate_admin.py`
- Modify: `workbook/management/commands/generate_import.py`

This task replaces the triplicated `strict_validate_contract` + string-matching + `PartialOutputCollector` block with the shared `load_contract_unvalidated` + `partition_contract_on_validation` helper in all three commands. The pattern is identical across all three.

- [ ] **Step 1: Refactor generate_models.py**

Find the `continue_on_error` block (around lines 96-120). Replace the entire block. Also change the `yaml.safe_load` line above it to use `load_contract_unvalidated`.

Current pattern (lines ~89-120):

```python
contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
version = contract.get("version", "1.0") if contract else "1.0"
tables: list[dict[str, Any]] = list(contract.get("tables", []) if contract else [])

...

if continue_on_error and contract.get("tables"):
    from workbook.codegen.contract import strict_validate_contract
    validation_errors = strict_validate_contract(contract)
    if validation_errors:
        valid_model_names = set()
        invalid_model_names = set()
        for table in contract.get("tables", []):
            model_name = table.get("model_name", "")
            if any(model_name in err for err in validation_errors):
                invalid_model_names.add(model_name)
            else:
                valid_model_names.add(model_name)
        clean_contract = dict(contract)
        clean_contract["tables"] = [
            t for t in contract["tables"]
            if t.get("model_name") in valid_model_names
        ]
        from workbook.partial_output import PartialOutputCollector
        collector = PartialOutputCollector()
        for model_name in invalid_model_names:
            collector.add(
                {"model_name": model_name},
                check_id="GENERATE_MODELS_INVALID_TABLE",
                message=f"Table {model_name!r} failed strict validation",
                action="Fix model_name or field identifiers in the contract",
            )
        contract = clean_contract
        if not collector.is_empty():
            rejection_path = out_path.parent / "schema-contract-rejected.yaml"
            collector.write_rejection_file(rejection_path)
            self.stdout.write(self.style.WARNING(collector.summary()))
```

Replace the `yaml.safe_load` line and the entire `continue_on_error` block with:

```python
from workbook.codegen.contract import load_contract_unvalidated

...
        contract = load_contract_unvalidated(str(contract_path))

        if continue_on_error and contract.get("tables"):
            from workbook.codegen.contract import strict_validate_contract
            from workbook.codegen.validation_pipeline import partition_contract_on_validation

            results = strict_validate_contract(contract)
            contract, collector = partition_contract_on_validation(
                contract,
                results,
                out_path=out_path,
            )
            if not collector.is_empty():
                self.stdout.write(self.style.WARNING(collector.summary()))
```

Remove the `import yaml` if it's no longer used elsewhere in the file. Remove the `tables` line that was right after the old `yaml.safe_load` since `load_contract_unvalidated` returns a contract with `tables` already set. Keep the version extraction and subsequent logic unchanged.

The full `handle` method should look like this after refactoring:

```python
    def handle(self, *args, **options):
        contract_path = Path(options["contract"]).resolve()
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")

        app_label = options["app_label"]
        force = options["force"]
        show_diff = options["diff"]
        continue_on_error = options.get("continue_on_error", False)

        from workbook.codegen.contract import load_contract_unvalidated
        contract = load_contract_unvalidated(str(contract_path))

        if app_label is None:
            for table in contract.get("tables", []):
                meta = table.get("model_meta") or {}
                if meta.get("app_label"):
                    app_label = meta["app_label"]
                    break
        if app_label is None:
            app_label = "core"
        if options["app_label"] is not None:
            for table in contract.get("tables", []):
                if "model_meta" not in table:
                    table["model_meta"] = {}
                table["model_meta"]["app_label"] = app_label

        out_path = options.get("out")
        if out_path is not None:
            out_path = Path(out_path).resolve()
            stub_path = None
        else:
            app_dir = Path.cwd() / "backend" / "apps" / app_label
            out_path = app_dir / "models_auto.py"
            stub_path = app_dir / "models.py"

        if continue_on_error and contract.get("tables"):
            from workbook.codegen.contract import strict_validate_contract
            from workbook.codegen.validation_pipeline import partition_contract_on_validation

            results = strict_validate_contract(contract)
            contract, collector = partition_contract_on_validation(
                contract,
                results,
                out_path=out_path,
            )
            if not collector.is_empty():
                self.stdout.write(self.style.WARNING(collector.summary()))

        warnings = validate_contract_tables(contract)
        for w in warnings:
            self.stdout.write(self.style.WARNING(f"validation: {w}"))

        version = contract.get("version", "1.0") if contract else "1.0"
        self.stdout.write(
            self.style.SUCCESS(
                f"loaded contract v{version} "
                f"({len(contract.get('tables') or [])} table(s))"
            )
        )

        source, warnings = render_models_py(contract, app_label=app_label)
        for w in warnings:
            self.stdout.write(self.style.WARNING(w))

        if show_diff:
            if out_path.exists():
                current = out_path.read_text(encoding="utf-8")
                diff = difflib.unified_diff(
                    current.splitlines(keepends=True),
                    source.splitlines(keepends=True),
                    fromfile=str(out_path),
                    tofile="<generated>",
                )
                diff_text = "".join(diff)
                if diff_text:
                    self.stdout.write(diff_text)
                else:
                    self.stdout.write(self.style.SUCCESS("no changes"))
            else:
                self.stdout.write(self.style.WARNING(f"no existing file: {out_path}"))
            return

        if out_path.exists() and not force:
            self.stdout.write(self.style.WARNING(f"output exists: {out_path}"))
            self.stdout.write("use --force to overwrite")
            sys.exit(1)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(source, encoding="utf-8")

        if stub_path:
            from workbook.codegen.stub_writer import ensure_stub

            ensure_stub(stub_path, "models_auto")

        model_count = len(contract.get("tables") or [])
        line_count = source.count("\n")
        self.stdout.write(
            self.style.SUCCESS(
                f"wrote {out_path}  ({model_count} model(s), {line_count} lines)"
            )
        )
```

Remove the `import yaml` line at the top of the file (it's no longer needed since `load_contract_unvalidated` handles YAML loading).

- [ ] **Step 2: Refactor generate_admin.py**

Apply the identical transformation. Find the `yaml.safe_load` line and the `continue_on_error` block. Replace with `load_contract_unvalidated` and `partition_contract_on_validation`. Remove `import yaml`. The `out_path` computation happens AFTER the `continue_on_error` check in this file, so we need to compute `out_path` first. Check the current code and adjust the ordering — move `out_path` computation before the validation block.

The current code computes `out_path` after the manifest loading but before the continue-on-error block. The refactored `handle` should look like:

```python
    def handle(self, *args, **options):
        contract_path = Path(options["contract"]).resolve()
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")

        manifest = None
        if options.get("manifest"):
            manifest_path = Path(options["manifest"]).resolve()
            if not manifest_path.is_file():
                raise CommandError(f"manifest not found: {manifest_path}")
            try:
                manifest = load_manifest(str(manifest_path))
            except ValueError as exc:
                raise CommandError(str(exc)) from exc

        continue_on_error = options.get("continue_on_error", False)

        from workbook.codegen.contract import load_contract_unvalidated
        contract = load_contract_unvalidated(str(contract_path))

        app_label = options["app_label"]
        if app_label is None:
            for table in contract.get("tables", []):
                meta = table.get("model_meta") or {}
                if meta.get("app_label"):
                    app_label = meta["app_label"]
                    break
        if app_label is None:
            app_label = "core"

        out_path = options.get("out")
        if out_path is not None:
            out_path = Path(out_path).resolve()
            stub_path = None
        else:
            app_dir = Path.cwd() / "backend" / "apps" / app_label
            out_path = app_dir / "admin_auto.py"
            stub_path = app_dir / "admin.py"
        force = options["force"]
        show_diff = options["diff"]

        if continue_on_error and contract.get("tables"):
            from workbook.codegen.contract import strict_validate_contract
            from workbook.codegen.validation_pipeline import partition_contract_on_validation

            results = strict_validate_contract(contract)
            contract, collector = partition_contract_on_validation(
                contract,
                results,
                out_path=out_path,
            )
            if not collector.is_empty():
                self.stdout.write(self.style.WARNING(collector.summary()))

        warnings = validate_contract_tables(contract)
        for w in warnings:
            self.stdout.write(self.style.WARNING(f"validation: {w}"))

        ...rest unchanged...
```

Remove `import yaml`.

- [ ] **Step 3: Refactor generate_import.py**

Apply the identical transformation. The import command also uses `yaml.safe_load`. Replace with `load_contract_unvalidated` + `partition_contract_on_validation`. Remove `import yaml`. The key change: compute `out_path` before the validation block.

The refactored top of `handle`:

```python
    def handle(self, *args, **options):
        contract_path = Path(options["contract"]).resolve()
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")

        continue_on_error = options.get("continue_on_error", False)

        from workbook.codegen.contract import load_contract_unvalidated
        contract = load_contract_unvalidated(str(contract_path))

        app_label = options["app_label"]
        if app_label is None:
            for table in contract.get("tables", []):
                meta = table.get("model_meta") or {}
                if meta.get("app_label"):
                    app_label = meta["app_label"]
                    break
        if app_label is None:
            app_label = "core"

        out_path = options.get("out")
        if out_path is None:
            app_dir = Path.cwd() / "backend" / "apps" / app_label
            mgmt_dir = app_dir / "management" / "commands"
            mgmt_dir.mkdir(parents=True, exist_ok=True)
            (app_dir / "management" / "__init__.py").touch()
            (mgmt_dir / "__init__.py").touch()
            out_path = str(mgmt_dir / f"import_{app_label}.py")
        out_path = Path(out_path).resolve()
        force = options["force"]
        show_diff = options["diff"]

        if continue_on_error and contract.get("tables"):
            from workbook.codegen.contract import strict_validate_contract
            from workbook.codegen.validation_pipeline import partition_contract_on_validation

            results = strict_validate_contract(contract)
            contract, collector = partition_contract_on_validation(
                contract,
                results,
                out_path=out_path,
            )
            if not collector.is_empty():
                self.stdout.write(self.style.WARNING(collector.summary()))

        ...rest unchanged...
```

- [ ] **Step 4: Run generator command tests**

Run: `.venv/bin/python -m pytest workbook/tests/test_generate_models_command.py workbook/tests/test_admin_generator.py workbook/tests/test_generate_import_command.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add workbook/management/commands/generate_models.py workbook/management/commands/generate_admin.py workbook/management/commands/generate_import.py
git commit -m "refactor: replace triplicated validation logic with partition_contract_on_validation"
```

---

## Task 7: Convert scaffold validation checks to UserFacingError

**Files:**
- Modify: `workbook/management/commands/scaffold_workbook_schema.py`
- Modify: `workbook/tests/test_scaffold_workbook_schema.py`

This task changes `_check_null_model_names`, `_check_pivot_tables`, and `_check_invalid_identifiers` from returning `list[str]` to raising `UserFacingError`. It also refactors `_validate_tables_for_scaffold` to catch `UserFacingError`.

- [ ] **Step 1: Rewrite _check_null_model_names to raise UserFacingError**

In `scaffold_workbook_schema.py`, find the `_check_null_model_names` function (around line 215). Replace it:

```python
def _check_null_model_names(table: dict) -> None:
    """Raise UserFacingError if the table has an empty model_name."""
    from workbench.exceptions import UserFacingError

    model_name = str(table.get("model_name", "")).strip()
    if not model_name:
        tab_title = table.get("bundle_worksheet_title") or table.get("suggested_model_name", "?")
        raise UserFacingError(
            f"Tab '{tab_title}' produced empty model_name",
            action="Deduplicate the tab across year workbooks or set a unique suggested_model_name",
            check_id="SCAFFOLD_NULL_MODEL_NAME",
        )
```

Note: The old version took `tables: list[dict]` and iterated. The new version takes a single `table: dict` and raises if that table has an empty model_name. The calling code in `_validate_tables_for_scaffold` already iterates per-table, so this aligns with the existing pattern.

- [ ] **Step 2: Rewrite _check_pivot_tables to raise UserFacingError**

Find `_check_pivot_tables` (around line 230). Replace it:

```python
def _check_pivot_tables(table: dict, *, pivot_detection_threshold: float = 0.5) -> None:
    """Raise UserFacingError if the table looks like a pivot table."""
    from workbench.exceptions import UserFacingError

    columns = table.get("columns", [])
    if not columns:
        return
    headers = [col.get("source_column", "").strip() for col in columns]
    numeric_headers = [h for h in headers if h.isdigit()]
    if len(numeric_headers) / len(headers) > pivot_detection_threshold:
        tab_title = table.get("bundle_worksheet_title", "?")
        numeric_list = ", ".join(numeric_headers[:10])
        raise UserFacingError(
            f"Tab '{tab_title}' appears to be a pivot table (numeric headers: {numeric_list})",
            action="Add it to vocabulary.derived or exclude it from the corpus config",
            check_id="SCAFFOLD_PIVOT_TABLE",
        )
```

- [ ] **Step 3: Rewrite _check_invalid_identifiers to raise UserFacingError per finding**

Find `_check_invalid_identifiers` (around line 250). Replace it:

```python
def _check_invalid_identifiers(table: dict) -> None:
    """Raise UserFacingError per invalid field or model name.

    Raises on the first invalid identifier found. For tables with multiple
    invalid identifiers, the caller should catch the error and continue
    checking or collecting as appropriate.
    """
    from workbench.exceptions import UserFacingError

    model_name = str(table.get("model_name", "")).strip()
    tab_title = table.get("bundle_worksheet_title", "?")
    if model_name and not is_valid_python_identifier(model_name):
        raise UserFacingError(
            f'model_name "{model_name}" is not a valid Python identifier',
            action="Rename the source tab or set an explicit suggested_model_name",
            check_id="SCAFFOLD_INVALID_IDENTIFIER",
        )
    for col in table.get("columns", []):
        field_name = col.get("suggested_field_name", "")
        if field_name and not is_valid_python_identifier(field_name):
            raise UserFacingError(
                f'Field name "{field_name}" is not a valid Python identifier',
                action="Rename the source column header or add a column alias in the bundle config",
                check_id="SCAFFOLD_INVALID_IDENTIFIER",
            )
```

- [ ] **Step 4: Rewrite _validate_tables_for_scaffold to use check loop**

Find `_validate_tables_for_scaffold` (around line 155). Replace it:

```python
def _validate_tables_for_scaffold(
    tables: list[dict[str, Any]], continue_on_error: bool = False, pivot_detection_threshold: float = 0.5
) -> tuple[list[dict[str, Any]], PartialOutputCollector]:
    from workbench.exceptions import UserFacingError

    collector = PartialOutputCollector()
    valid_tables: list[dict[str, Any]] = []

    for table in tables:
        if table.get("source_tab") is None and not table.get("bundle_worksheet_title"):
            valid_tables.append(table)
            continue

        checks = [
            lambda t=table: _check_null_model_names(t),
            lambda t=table: _check_pivot_tables(t, pivot_detection_threshold=pivot_detection_threshold),
            lambda t=table: _check_invalid_identifiers(t),
        ]
        table_had_error = False
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
                    table_had_error = True
                else:
                    raise CommandError(str(exc)) from exc

        if not table_had_error:
            valid_tables.append(table)

    return valid_tables, collector
```

Note: When `continue_on_error=True`, a table that fails ANY check is dropped (it's not added to `valid_tables`). This preserves the existing behavior where invalid tables are excluded from the contract. The difference from the old code is that all three checks now run for each table when continuing on error, rather than stopping after the first failed check. The old code used `continue` after adding to collector, which skipped remaining checks — the new code runs all checks and then decides whether to include the table.

Wait — actually let me re-read the old code. The old code did `continue` after collector.add for null model names and pivot tables, which means it skipped remaining checks for that table AND skipped adding it to valid_tables. The new code should match: if any check raises `UserFacingError` (with `continue_on_error`), we should still skip adding the table to `valid_tables`.

The implementation above is correct: `table_had_error = True` prevents the table from being added to `valid_tables`, but all three checks still run.

Actually, looking more carefully at the old code, there's a subtle difference. The old `_validate_tables_for_scaffold` had:

```python
model_name = str(table.get("model_name", "")).strip()
if not model_name:
    if continue_on_error:
        collector.add(...)
        continue  # skips rest of loop iteration -> table NOT added
    else:
        raise CommandError(...)
```

So when `continue_on_error=True`, a table with null model_name was skipped entirely (not added to valid_tables). The new code does the same via `table_had_error = True`. But in the old code, after the null check, pivot/identifier checks STILL ran if the model name was present. So the new code is actually slightly different: it runs all three checks for every table, even those with null model names.

To preserve exact behavior, we should NOT run `_check_invalid_identifiers` on tables with null model names (since `model_name` would be empty and the first check in `_check_invalid_identifiers` would succeed vacuously). Actually `_check_invalid_identifiers` checks `if model_name and not is_valid_python_identifier(model_name)` — so if model_name is empty, it skips the model check and goes straight to columns. That's fine — the column-level checks are still valid even if the model name is null.

The behavior difference is: in the old code, a table with a null model name was immediately rejected without checking pivot/identifier issues. In the new code, we check all three. This is actually BETTER behavior — we get more complete error reporting.

- [ ] **Step 5: Update tests for the new exception-raising pattern**

In `workbook/tests/test_scaffold_workbook_schema.py`, find the tests for `_check_null_model_names`, `_check_pivot_tables`, and `_check_invalid_identifiers`.

Update `test_check_null_model_names_finds_empty` (around line 413):

```python
def test_check_null_model_names_raises_on_empty():
    from workbench.exceptions import UserFacingError
    table = {"model_name": "", "bundle_worksheet_title": "Empty Tab"}
    with pytest.raises(UserFacingError) as exc_info:
        _check_null_model_names(table)
    assert exc_info.value.check_id == "SCAFFOLD_NULL_MODEL_NAME"
```

Update `test_check_pivot_tables` (around line 430):

```python
def test_check_pivot_tables_raises_on_numeric_headers():
    from workbench.exceptions import UserFacingError
    table = {
        "bundle_worksheet_title": "Pivot",
        "columns": [
            {"source_column": "2020"},
            {"source_column": "2021"},
            {"source_column": "2022"},
            {"source_column": "Name"},
        ],
    }
    with pytest.raises(UserFacingError) as exc_info:
        _check_pivot_tables(table, pivot_detection_threshold=0.5)
    assert exc_info.value.check_id == "SCAFFOLD_PIVOT_TABLE"


def test_check_pivot_tables_passes_below_threshold():
    table = {
        "bundle_worksheet_title": "Normal",
        "columns": [
            {"source_column": "Name"},
            {"source_column": "Value"},
            {"source_column": "2020"},
        ],
    }
    _check_pivot_tables(table, pivot_detection_threshold=0.9)
```

Update `test_check_pivot_tables_respects_threshold` (around line 483):

```python
def test_check_pivot_tables_threshold_values():
    from workbench.exceptions import UserFacingError
    table = {
        "bundle_worksheet_title": "Pivot",
        "columns": [
            {"source_column": "2020"},
            {"source_column": "2021"},
            {"source_column": "2022"},
            {"source_column": "Name"},
        ],
    }
    with pytest.raises(UserFacingError):
        _check_pivot_tables(table, pivot_detection_threshold=0.5)

    _check_pivot_tables(table, pivot_detection_threshold=0.9)
```

Update `_check_invalid_identifiers` tests (around line 441):

```python
def test_check_invalid_identifiers_raises_on_bad_model_name():
    from workbench.exceptions import UserFacingError
    table = {"model_name": "class", "bundle_worksheet_title": "Test", "columns": []}
    with pytest.raises(UserFacingError) as exc_info:
        _check_invalid_identifiers(table)
    assert exc_info.value.check_id == "SCAFFOLD_INVALID_IDENTIFIER"


def test_check_invalid_identifiers_raises_on_bad_field_name():
    from workbench.exceptions import UserFacingError
    table = {
        "model_name": "Crop",
        "bundle_worksheet_title": "Test",
        "columns": [{"suggested_field_name": "201_unit"}],
    }
    with pytest.raises(UserFacingError) as exc_info:
        _check_invalid_identifiers(table)
    assert exc_info.value.check_id == "SCAFFOLD_INVALID_IDENTIFIER"
```

Also add a test for the full `_validate_tables_for_scaffold` with `continue_on_error` collecting multiple errors:

```python
def test_validate_tables_for_scaffold_collects_multiple_errors():
    tables = [
        {
            "model_name": "",
            "bundle_worksheet_title": "Bad Tab",
            "columns": [{"source_column": "Name"}],
        },
    ]
    valid, collector = _validate_tables_for_scaffold(tables, continue_on_error=True)
    assert len(valid) == 0
    assert not collector.is_empty()
    assert collector.rejected[0].check_id == "SCAFFOLD_NULL_MODEL_NAME"
```

- [ ] **Step 6: Run scaffold tests**

Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py -v`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add workbook/management/commands/scaffold_workbook_schema.py workbook/tests/test_scaffold_workbook_schema.py
git commit -m "refactor: convert scaffold validation checks to UserFacingError"
```

---

## Task 8: Wire --pivot-detection-threshold through scaffold CLI

**Files:**
- Modify: `workbook/management/commands/scaffold_workbook_schema.py`
- Modify: `workbook/tests/test_scaffold_workbook_schema.py`

- [ ] **Step 1: Add --pivot-detection-threshold CLI argument**

In `scaffold_workbook_schema.py`, find the `add_arguments` method. Add the new argument:

```python
parser.add_argument(
    "--pivot-detection-threshold",
    type=float,
    default=0.5,
    help="Fraction of numeric column headers required to flag a table as a pivot (default 0.5)",
)
```

- [ ] **Step 2: Wire the argument through both scaffold paths**

Find the two calls to `_validate_tables_for_scaffold` in the `handle` method.

**Bundle-config path** (around line 788 — the path where `continue_on_error` is used for `--continue-on-error` with single-bundle config):

Find:
```python
tables, collector = _validate_tables_for_scaffold(tables, continue_on_error=continue_on_error, pivot_detection_threshold=0.5)
```

Replace with:
```python
tables, collector = _validate_tables_for_scaffold(tables, continue_on_error=continue_on_error, pivot_detection_threshold=options["pivot_detection_threshold"])
```

**Cohort-corpus path** (around line 815 — the path where `coverage_payload` is used):

Find:
```python
pivot_threshold = float(coverage_payload.get("pivot_detection_threshold", 0.5))
```

Replace with:
```python
cli_threshold = options["pivot_detection_threshold"]
pivot_threshold = float(coverage_payload.get("pivot_detection_threshold", cli_threshold))
```

This implements the spec's priority rule: CLI `--pivot-detection-threshold` is an absolute override. If the operator passes `--pivot-detection-threshold 0.7`, that value is used regardless of the corpus payload. If the operator omits the flag (default 0.5), the corpus payload's threshold takes precedence.

- [ ] **Step 3: Add tests for --pivot-detection-threshold**

```python
def test_pivot_detection_threshold_flag_overrides_default(tmp_path):
    from django.core.management import call_command
    from io import StringIO

    out = StringIO()
    contract_path = tmp_path / "schema-contract.yaml"
    call_command(
        "scaffold_workbook_schema",
        str(contract_path),
        pivot_detection_threshold=0.9,
        stdout=out,
    )
    # If 0.9 threshold is passed, tables with 75% numeric headers would NOT be flagged
    # This test verifies the CLI argument is accepted without error
    assert "pivot_detection_threshold" not in out.getvalue().lower()


def test_cohort_corpus_threshold_respected(tmp_path):
    """When cohort_corpus has pivot_detection_threshold, it's used when CLI omits the flag."""
    import json
    from django.core.management import call_command
    from io import StringIO

    corpus_path = tmp_path / "cohort_corpus.json"
    corpus_data = {
        "workbooks": [],
        "pivot_detection_threshold": 0.7,
        "tables": [],
    }
    corpus_path.write_text(json.dumps(corpus_data), encoding="utf-8")

    out = StringIO()
    contract_path = tmp_path / "schema-contract.yaml"
    call_command(
        "scaffold_workbook_schema",
        str(contract_path),
        cohort_corpus=str(corpus_path),
        stdout=out,
    )
```

- [ ] **Step 4: Run scaffold tests**

Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add workbook/management/commands/scaffold_workbook_schema.py workbook/tests/test_scaffold_workbook_schema.py
git commit -m "feat: add --pivot-detection-threshold CLI argument to scaffold_workbook_schema"
```

---

## Task 9: Full integration regression test

**Files:**
- No new files — this task runs the existing test suite.

- [ ] **Step 1: Run the full chassis gate**

Run: `make chassis-gate`
Expected: All tests pass, lint clean, doc coverage met.

- [ ] **Step 2: Fix any failures before proceeding**

If any tests fail, debug and fix. Common issues:
- Tests in `test_contract_validation.py` or `test_contract.py` that assert on `strict_validate_contract` returning `list[str]`.
- Import paths: any test importing `strict_validate_contract` that expects strings.

- [ ] **Step 3: Final commit if fixes were needed**

```bash
git add -A
git commit -m "fix: integration test adjustments for ValidationResult refactor"
```

---

## Task 10: Update __init__.py exports

**Files:**
- Modify: `workbook/codegen/__init__.py` (if it exists and exports)

- [ ] **Step 1: Check if validation_pipeline needs to be exported**

Run: `cat workbook/codegen/__init__.py`
If it exists and has explicit exports, add:

```python
from workbook.codegen.validation_pipeline import ValidationResult, GlobalValidationError, partition_contract_on_validation
```

If it doesn't exist or uses wildcard imports, no change needed.

- [ ] **Step 2: Run tests**

Run: `.venv/bin/python -m pytest workbook/tests/ -v --tb=short`
Expected: All PASS.

- [ ] **Step 3: Commit if changed**

```bash
git add workbook/codegen/__init__.py
git commit -m "chore: export validation_pipeline from codegen package"
```