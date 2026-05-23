# Pipeline Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--continue-on-error` / `--write-partial` to `scaffold_workbook_schema`, `generate_models`, `generate_admin`, and `generate_import` so that validation failures emit partial artifacts instead of hard-failing on the first error.

**Architecture:** Introduce a `PartialOutputCollector` dataclass in `workbook/partial_output.py` that accumulates rejected tables with error annotations. `scaffold_workbook_schema` uses it to collect data-quality check failures (null model names, pivot tables, invalid identifiers) and writes valid tables to the contract YAML while writing rejected entries to a companion `schema-contract-rejected.yaml`. The three generator commands pre-validate the contract via `strict_validate_contract`, separate valid from invalid tables, generate code from the clean subset, and write rejections to the same companion file format.

**Tech Stack:** Python 3.11, Django management commands, PyYAML, pytest.

---

## Task 1: Partial-Output Helper

**Files:**
- Create: `workbook/partial_output.py`
- Test: `workbook/tests/test_partial_output.py`

- [ ] **Step 1: Write the helper module**

```python
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RejectedTable:
    """Single table rejection with error annotation."""

    source_tab_title: str | None
    source_workbook_code: str | None
    check_id: str
    message: str
    action: str | None = None


@dataclass
class PartialOutputCollector:
    """Accumulate rejected tables during contract validation or scaffolding."""

    rejected: list[RejectedTable] = field(default_factory=list)

    def add(self, table: dict[str, Any], *, check_id: str, message: str, action: str | None = None) -> None:
        """Record a rejected table."""
        self.rejected.append(
            RejectedTable(
                source_tab_title=table.get("bundle_worksheet_title"),
                source_workbook_code=table.get("workbook_code"),
                check_id=check_id,
                message=message,
                action=action,
            )
        )

    def is_empty(self) -> bool:
        return len(self.rejected) == 0

    def write_rejection_file(self, path: Path) -> None:
        """Serialize rejected tables to YAML."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "rejected_tables": [
                {
                    "table": {
                        "source_tab_title": r.source_tab_title,
                        "source_workbook_code": r.source_workbook_code,
                    },
                    "error": {
                        "check_id": r.check_id,
                        "message": r.message,
                        "action": r.action,
                    },
                }
                for r in self.rejected
            ]
        }
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")

    def summary(self) -> str:
        """Return a human-readable summary string."""
        lines = [f"WARN[SCAFFOLD_PARTIAL_OUTPUT]: wrote partial output."]
        lines.append(f"  Tables rejected: {len(self.rejected)}")
        for r in self.rejected:
            lines.append(f"  - {r.check_id}: {r.message}")
        if self.rejected:
            lines.append("  Action: Review rejected tables, fix upstream data, and re-run without --continue-on-error.")
        return "\n".join(lines)
```

- [ ] **Step 2: Write the test**

```python
from pathlib import Path
import yaml
from workbook.partial_output import PartialOutputCollector, RejectedTable


def test_collector_add_and_summary():
    collector = PartialOutputCollector()
    collector.add(
        {"bundle_worksheet_title": "Irrigation", "workbook_code": "504"},
        check_id="SCAFFOLD_PIVOT_TABLE",
        message="Numeric headers detected",
        action="Exclude from corpus config",
    )
    assert not collector.is_empty()
    summary = collector.summary()
    assert "SCAFFOLD_PARTIAL_OUTPUT" in summary
    assert "Irrigation" in summary


def test_write_rejection_file(tmp_path: Path):
    collector = PartialOutputCollector()
    collector.add(
        {"bundle_worksheet_title": "Irrigation", "workbook_code": "504"},
        check_id="SCAFFOLD_PIVOT_TABLE",
        message="Numeric headers",
    )
    rejection_path = tmp_path / "rejected.yaml"
    collector.write_rejection_file(rejection_path)
    payload = yaml.safe_load(rejection_path.read_text(encoding="utf-8"))
    assert len(payload["rejected_tables"]) == 1
    assert payload["rejected_tables"][0]["error"]["check_id"] == "SCAFFOLD_PIVOT_TABLE"
```

- [ ] **Step 3: Run test**

Run: `.venv/bin/python -m pytest workbook/tests/test_partial_output.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add workbook/partial_output.py workbook/tests/test_partial_output.py
git commit -m "feat: add PartialOutputCollector for resilient scaffolding"
```

---

## Task 2: Scaffold `--continue-on-error`

**Files:**
- Modify: `workbook/management/commands/scaffold_workbook_schema.py`
- Modify: `workbook/tests/test_scaffold_workbook_schema.py`

- [ ] **Step 1: Import and integrate helper**

Add to `workbook/management/commands/scaffold_workbook_schema.py` imports:

```python
from workbook.partial_output import PartialOutputCollector
```

- [ ] **Step 2: Add CLI flag**

In `Command.add_arguments`, add:

```python
parser.add_argument(
    "--continue-on-error",
    action="store_true",
    default=False,
    help="Collect validation errors and write partial contract YAML",
)
```

- [ ] **Step 3: Refactor validation to use collector**

Replace the hard-fail block in `_build_cohort_contract` (around lines 358-364):

```python
# BEFORE:
errors: list[str] = []
errors.extend(_check_null_model_names(tables))
for table in tables:
    errors.extend(_check_pivot_tables(table))
    errors.extend(_check_invalid_identifiers(table))
if errors:
    raise CommandError("\n".join(errors))
```

With:

```python
def _validate_tables_for_scaffold(tables: list[dict[str, Any]], continue_on_error: bool = False) -> tuple[list[dict[str, Any]], PartialOutputCollector]:
    collector = PartialOutputCollector()
    valid_tables: list[dict[str, Any]] = []

    for table in tables:
        # Designed models have no source tab; skip pivot/identifier checks
        if table.get("source_tab") is None and not table.get("bundle_worksheet_title"):
            valid_tables.append(table)
            continue

        # Null model name check
        model_name = str(table.get("model_name", "")).strip()
        if not model_name:
            if continue_on_error:
                collector.add(
                    table,
                    check_id="SCAFFOLD_NULL_MODEL_NAME",
                    message=f"Tab {table.get('bundle_worksheet_title', '?')!r} produced empty model_name",
                    action="Deduplicate the tab across year workbooks or set a unique suggested_model_name",
                )
                continue
            else:
                tab_title = table.get("bundle_worksheet_title") or table.get("suggested_model_name", "?")
                raise CommandError(
                    f'FAIL[SCAFFOLD_NULL_MODEL_NAME]: Tab "{tab_title}" produced empty model_name'
                )

        # Pivot table check
        pivot_errors = _check_pivot_tables(table)
        if pivot_errors:
            if continue_on_error:
                collector.add(
                    table,
                    check_id="SCAFFOLD_PIVOT_TABLE",
                    message=pivot_errors[0].split(":", 1)[1].strip(),
                    action="Add to vocabulary.derived or exclude from corpus config",
                )
                continue
            else:
                raise CommandError(pivot_errors[0])

        # Invalid identifier check
        id_errors = _check_invalid_identifiers(table)
        if id_errors:
            if continue_on_error:
                collector.add(
                    table,
                    check_id="SCAFFOLD_INVALID_IDENTIFIER",
                    message=id_errors[0].split(":", 1)[1].strip(),
                    action="Rename the source column header or add a column alias in the bundle config",
                )
                continue
            else:
                raise CommandError(id_errors[0])

        valid_tables.append(table)

    return valid_tables, collector
```

Then replace the existing validation call in `_build_cohort_contract`:

```python
    tables, collector = _validate_tables_for_scaffold(tables, continue_on_error=continue_on_error)
```

And add the return:

```python
    return contract, collector
```

- [ ] **Step 4: Update handle() for partial output**

In `Command.handle()`, after calling `_build_cohort_contract` or `build_contract`, check the collector:

```python
# In _handle_cohort_corpus:
contract, collector = _build_cohort_contract(deep_dir, coverage_payload, hardened=hardened, continue_on_error=options.get("continue_on_error", False))

# In _handle_bundle_config:
tables, collector = _validate_tables_for_scaffold(tables, continue_on_error=options.get("continue_on_error", False))
contract["tables"] = tables
```

After writing the main contract, write rejection file if any:

```python
if not collector.is_empty():
    rejection_path = out_path.parent / "schema-contract-rejected.yaml"
    collector.write_rejection_file(rejection_path)
    self.stdout.write(self.style.WARNING(collector.summary()))
    self.stdout.write(self.style.WARNING(f"Rejections written to: {rejection_path}"))
```

- [ ] **Step 5: Write test for partial output**

In `workbook/tests/test_scaffold_workbook_schema.py`, add:

```python
from workbook.partial_output import PartialOutputCollector
from workbook.management.commands.scaffold_workbook_schema import _validate_tables_for_scaffold


def test_validate_tables_rejects_pivot_when_continue_on_error():
    tables = [
        {
            "bundle_worksheet_title": "Irrigation",
            "model_name": "Irrigation",
            "columns": [
                {"source_column": "1", "suggested_field_name": "1"},
                {"source_column": "2", "suggested_field_name": "2"},
                {"source_column": "3", "suggested_field_name": "3"},
            ],
        }
    ]
    valid, collector = _validate_tables_for_scaffold(tables, continue_on_error=True)
    assert len(valid) == 0
    assert len(collector.rejected) == 1
    assert collector.rejected[0].check_id == "SCAFFOLD_PIVOT_TABLE"


def test_validate_tables_keeps_valid_and_rejects_invalid():
    tables = [
        {"bundle_worksheet_title": "Good", "model_name": "Good", "columns": []},
        {
            "bundle_worksheet_title": "Irrigation",
            "model_name": "Irrigation",
            "columns": [
                {"source_column": "1", "suggested_field_name": "1"},
                {"source_column": "2", "suggested_field_name": "2"},
                {"source_column": "3", "suggested_field_name": "3"},
            ],
        },
    ]
    valid, collector = _validate_tables_for_scaffold(tables, continue_on_error=True)
    assert len(valid) == 1
    assert valid[0]["model_name"] == "Good"
    assert len(collector.rejected) == 1


def test_validate_tables_skips_designed_models():
    tables = [
        {"source_tab": None, "bundle_worksheet_title": None, "model_name": "DesignedModel", "columns": []},
    ]
    valid, collector = _validate_tables_for_scaffold(tables, continue_on_error=True)
    assert len(valid) == 1
    assert collector.is_empty()
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py -v`
Expected: PASS (existing tests may need `match=` updates if they assert on exact error strings)

- [ ] **Step 7: Commit**

```bash
git add workbook/management/commands/scaffold_workbook_schema.py workbook/tests/test_scaffold_workbook_schema.py
git commit -m "feat: add --continue-on-error to scaffold_workbook_schema"
```

---

## Task 3: Configurable Pivot Threshold

**Files:**
- Modify: `workbook/management/commands/scaffold_workbook_schema.py`
- Modify: `example_data/cohort_corpus.example.json`
- Test: `workbook/tests/test_scaffold_workbook_schema.py`

- [ ] **Step 1: Make pivot threshold configurable**

Change `_check_pivot_tables` signature to accept threshold:

```python
def _check_pivot_tables(table: dict, *, pivot_detection_threshold: float = 0.5) -> list[str]:
```

Inside the function, replace the hard-coded `0.5`:

```python
    if len(numeric_headers) / len(headers) > pivot_detection_threshold:
```

- [ ] **Step 2: Pass threshold from config**

In `_build_cohort_contract`, read the threshold from a new optional parameter:

```python
def _build_cohort_contract(
    deep_dir: Path,
    coverage_payload: dict,
    *,
    hardened: bool = False,
    continue_on_error: bool = False,
    pivot_detection_threshold: float = 0.5,
) -> tuple[dict[str, Any], PartialOutputCollector]:
```

Pass it to `_check_pivot_tables(table, pivot_detection_threshold=pivot_detection_threshold)`.

In `Command._handle_cohort_corpus`, read the threshold from `coverage_payload` metadata or default to 0.5:

```python
pivot_threshold = float(coverage_payload.get("pivot_detection_threshold", 0.5))
```

- [ ] **Step 3: Update example config**

Add to `example_data/cohort_corpus.example.json`:

```json
{
  "pivot_detection_threshold": 0.5,
  "_documentation": {
    ...
    "pivot_detection_threshold": "Ratio of numeric column headers that triggers pivot-table rejection in scaffold_workbook_schema. Set to 1.0 or null to disable."
  }
}
```

- [ ] **Step 4: Write test**

```python
def test_check_pivot_tables_respects_threshold():
    table = {
        "bundle_worksheet_title": "Test",
        "columns": [
            {"source_column": "1"},
            {"source_column": "2"},
            {"source_column": "Name"},
        ],
    }
    assert len(_check_pivot_tables(table, pivot_detection_threshold=0.5)) == 1
    assert len(_check_pivot_tables(table, pivot_detection_threshold=0.9)) == 0
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py::test_check_pivot_tables_respects_threshold -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add workbook/management/commands/scaffold_workbook_schema.py example_data/cohort_corpus.example.json workbook/tests/test_scaffold_workbook_schema.py
git commit -m "feat: make pivot_detection_threshold configurable"
```

---

## Task 4: Generate Models Partial Output

**Files:**
- Modify: `workbook/management/commands/generate_models.py`
- Modify: `workbook/tests/test_generate_models_command.py`

- [ ] **Step 1: Add --continue-on-error flag**

In `add_arguments`:

```python
parser.add_argument(
    "--continue-on-error",
    action="store_true",
    default=False,
    help="Skip invalid tables and generate models for valid ones",
)
```

- [ ] **Step 2: Pre-validate and filter**

In `handle()`, after loading contract:

```python
from workbook.codegen.contract import strict_validate_contract

continue_on_error = options.get("continue_on_error", False)
if continue_on_error:
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
        # Write rejections
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
```

- [ ] **Step 3: Write test**

```python
def test_generate_models_continue_on_error_skips_invalid(tmp_path, monkeypatch):
    from django.core.management import call_command
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        yaml.safe_dump({
            "version": "1.0",
            "tables": [
                {"model_name": "Valid", "columns": [{"suggested_field_name": "name", "django_field_class": "models.CharField", "django_field_kwargs": {"max_length": 100}}]},
                {"model_name": "", "columns": []},
            ],
        })
    )
    out = tmp_path / "models.py"
    call_command("generate_models", contract=str(contract), out=str(out), force=True, continue_on_error=True)
    source = out.read_text()
    assert "class Valid" in source
    assert "class " not in source.replace("class Valid", "")
```

- [ ] **Step 4: Run test**

Run: `.venv/bin/python -m pytest workbook/tests/test_generate_models_command.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add workbook/management/commands/generate_models.py workbook/tests/test_generate_models_command.py
git commit -m "feat: add --continue-on-error to generate_models"
```

---

## Task 5: Generate Admin Partial Output

**Files:**
- Modify: `workbook/management/commands/generate_admin.py`
- Modify: `workbook/tests/test_admin_generator.py`

- [ ] **Step 1: Add --continue-on-error flag**

Same pattern as Task 4.

- [ ] **Step 2: Pre-validate and filter**

Same pattern as Task 4, using `strict_validate_contract`.

- [ ] **Step 3: Write test**

```python
def test_generate_admin_continue_on_error_skips_invalid(tmp_path, monkeypatch):
    from django.core.management import call_command
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        yaml.safe_dump({
            "version": "1.0",
            "tables": [
                {"model_name": "Valid", "columns": [{"suggested_field_name": "name", "django_field_class": "models.CharField", "django_field_kwargs": {"max_length": 100}}]},
                {"model_name": "", "columns": []},
            ],
        })
    )
    out = tmp_path / "admin.py"
    call_command("generate_admin", contract=str(contract), out=str(out), force=True, continue_on_error=True)
    source = out.read_text()
    assert "Valid" in source
```

- [ ] **Step 4: Run test**

Run: `.venv/bin/python -m pytest workbook/tests/test_admin_generator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add workbook/management/commands/generate_admin.py workbook/tests/test_admin_generator.py
git commit -m "feat: add --continue-on-error to generate_admin"
```

---

## Task 6: Generate Import Partial Output

**Files:**
- Modify: `workbook/management/commands/generate_import.py`
- Modify: `workbook/tests/test_generate_import_command.py`

- [ ] **Step 1: Add --continue-on-error flag**

Same pattern as Task 4.

- [ ] **Step 2: Pre-validate and filter**

Same pattern as Task 4, using `strict_validate_contract`.

- [ ] **Step 3: Write test**

```python
def test_generate_import_continue_on_error_skips_invalid(tmp_path, monkeypatch):
    from django.core.management import call_command
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        yaml.safe_dump({
            "version": "1.0",
            "tables": [
                {"model_name": "Valid", "import_config": {"bundle_path": "test.csv"}, "columns": [{"suggested_field_name": "name", "django_field_class": "models.CharField", "django_field_kwargs": {"max_length": 100}}]},
                {"model_name": "", "import_config": {"bundle_path": "test.csv"}, "columns": []},
            ],
        })
    )
    out = tmp_path / "import.py"
    call_command("generate_import", contract=str(contract), out=str(out), force=True, continue_on_error=True)
    source = out.read_text()
    assert "Valid" in source
```

- [ ] **Step 4: Run test**

Run: `.venv/bin/python -m pytest workbook/tests/test_generate_import_command.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add workbook/management/commands/generate_import.py workbook/tests/test_generate_import_command.py
git commit -m "feat: add --continue-on-error to generate_import"
```

---

## Task 7: Regression Guard

- [ ] **Step 1: Run chassis-gate**

```bash
make chassis-gate
```

Expected: All tests pass, lint passes, doc coverage passes.

- [ ] **Step 2: Commit if fixes needed**

If any test failures from string changes, fix and commit.

---

## Self-Review

1. **Spec coverage:**
   - `--continue-on-error` / `--write-partial` for scaffold: ✅ Task 2
   - `--continue-on-error` for generate_models: ✅ Task 4
   - `--continue-on-error` for generate_admin: ✅ Task 5
   - `--continue-on-error` for generate_import: ✅ Task 6
   - Rejection file format (`schema-contract-rejected.yaml`): ✅ Task 1
   - Summary printed to stdout: ✅ Task 2
   - Designed models exempt from pivot/identifier checks: ✅ Task 2 Step 3
   - `pivot_detection_threshold` configurable: ✅ Task 3

2. **Placeholder scan:** No TBD, TODO, or vague steps found.

3. **Type consistency:** `PartialOutputCollector`, `RejectedTable`, `_validate_tables_for_scaffold` return type `(list[dict], PartialOutputCollector)` used consistently.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-21-pipeline-resilience.md`.**
