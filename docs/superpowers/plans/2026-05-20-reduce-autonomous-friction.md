# Reduce Autonomous Pipeline Friction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fail-fast guardrails to the autonomous pipeline so invalid upstream data (empty domain context, pivot tables, bad identifiers) is caught at the exact point of failure with actionable error messages.

**Architecture:** A lightweight pre-flight script validates environment setup before any heavy commands run. The profiler and scaffold commands gain hard validation rules that exit with structured `FAIL[<id>]` messages. A strict contract-validation gate stops the pipeline before code generation. Defense-in-depth warnings in the codegen layer catch any identifiers that slip through.

**Tech Stack:** Python 3.12, Django management commands, PyYAML, pytest, standard library (`keyword`, `pathlib`, `subprocess`).

---

## File Structure

| File | Responsibility |
|------|-------------|
| `scripts/preflight.py` | Environment gate: venv, `wb` CLI, domain_context.yaml population |
| `scripts/tests/test_preflight.py` | Unit tests for preflight checks |
| `Makefile` | New `preflight` target; `validate-contract` gets `--strict` support |
| `profiler/tools/domain_context.py` | New `has_meaningful_vocabulary()` helper |
| `profiler/tests/test_domain_context.py` | Tests for vocabulary helper |
| `profiler/management/commands/profile_cohort_corpus.py` | Exit fast when vocabulary empty |
| `workbook/field_mapping.py` | New `is_valid_python_identifier()` helper |
| `workbook/management/commands/scaffold_workbook_schema.py` | Three hard guardrails: null model_name, pivot table, invalid identifiers |
| `workbook/tests/test_scaffold_workbook_schema.py` | Tests for each guardrail |
| `workbook/management/commands/validate_contract.py` | Strict mode with identifier + duplicate checks |
| `workbook/tests/test_validate_contract.py` | Tests for strict-mode checks |
| `workbook/codegen/contract.py` | Helpers for strict validation (`_check_identifiers`, `_check_duplicates`) |
| `deployment/wb_cli.py` | Forward `--strict` flag to `wb validate contract` |
| `workbook/codegen/python_render.py` | Warn when `to_python_identifier` sanitizes a field name |
| `workbook/codegen/model_generator.py` | Collect and emit codegen warnings to stdout |
| `AUTONOMOUS_RUN_PROMPT.md` | Restructure into explicit gated phases; add `make install` and `scripts/preflight.py` |

---

### Task 1: Preflight Environment Gate (`scripts/preflight.py`)

**Files:**
- Create: `scripts/preflight.py`
- Create: `scripts/tests/test_preflight.py`

- [ ] **Step 1: Write failing tests**

```python
# scripts/tests/test_preflight.py
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add repo root to path so scripts/ modules are importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.preflight import run_preflight, PREFLIGHT_CHECKS


class TestRunPreflight:
    def test_missing_venv_fails(self, tmp_path):
        with patch("scripts.preflight.VENV_DIR", tmp_path / ".venv"):
            with pytest.raises(SystemExit) as exc_info:
                run_preflight()
        assert exc_info.value.code == 1

    def test_empty_domain_context_fails(self, tmp_path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "bin").mkdir()
        (venv / "bin" / "python").write_text("")
        (venv / "bin" / "wb").write_text("")
        domain_context = tmp_path / "domain_context.yaml"
        domain_context.write_text("domain: ''\nyear_scope:\n  active: []\nvocabulary:\n  operational: []\n")
        with patch("scripts.preflight.VENV_DIR", venv):
            with patch("scripts.preflight.DOMAIN_CONTEXT_PATH", domain_context):
                with pytest.raises(SystemExit) as exc_info:
                    run_preflight()
        assert exc_info.value.code == 1

    def test_populated_domain_context_passes(self, tmp_path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "bin").mkdir()
        (venv / "bin" / "python").write_text("")
        (venv / "bin" / "wb").write_text("")
        domain_context = tmp_path / "domain_context.yaml"
        domain_context.write_text(
            "domain: farm_management\nyear_scope:\n  active: [2025]\nvocabulary:\n  operational: [crop]\n"
        )
        with patch("scripts.preflight.VENV_DIR", venv):
            with patch("scripts.preflight.DOMAIN_CONTEXT_PATH", domain_context):
                run_preflight()  # should not raise
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
.venv/bin/python -m pytest scripts/tests/test_preflight.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.preflight'`

- [ ] **Step 3: Implement `scripts/preflight.py`**

```python
#!/usr/bin/env python3
"""Environment pre-flight gate for the autonomous pipeline.

Exits with a structured FAIL message if any prerequisite is missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

# Paths are relative to the repo root when executed from there.
VENV_DIR = Path(".venv")
DOMAIN_CONTEXT_PATH = Path("config/domain_context.yaml")
WB_PATH = VENV_DIR / "bin" / "wb"


def _emit(check_id: str, message: str, action: str) -> None:
    print(f"FAIL[{check_id}]: {message}")
    print(f"  → Action: {action}")


def run_preflight() -> None:
    """Run all pre-flight checks. Exits with code 1 on any failure."""
    failed = False

    if not VENV_DIR.is_dir():
        _emit(
            "PREFLIGHT_VENV_MISSING",
            f"Virtual environment not found at {VENV_DIR}",
            "Run `make install` to create the venv and install dependencies.",
        )
        failed = True

    wb_on_path = False
    try:
        import shutil
        wb_on_path = shutil.which("wb") is not None
    except Exception:
        pass

    if not wb_on_path and not WB_PATH.exists():
        _emit(
            "PREFLIGHT_WB_NOT_FOUND",
            "'wb' CLI is not on PATH and not found at .venv/bin/wb",
            "Run `make install` or ensure .venv/bin is on your PATH.",
        )
        failed = True

    if DOMAIN_CONTEXT_PATH.exists():
        raw = yaml.safe_load(DOMAIN_CONTEXT_PATH.read_text(encoding="utf-8")) or {}
        domain = str(raw.get("domain", "")).strip()
        if not domain:
            _emit(
                "PREFLIGHT_DOMAIN_EMPTY",
                f'{DOMAIN_CONTEXT_PATH} has empty "domain"',
                'Edit the file and set domain (e.g. "farm_management").',
            )
            failed = True
        year_scope = raw.get("year_scope") or {}
        active = year_scope.get("active") or []
        if not active:
            _emit(
                "PREFLIGHT_YEAR_SCOPE_EMPTY",
                f'{DOMAIN_CONTEXT_PATH} has empty year_scope.active',
                "Add at least one active year (e.g. [2025]).",
            )
            failed = True
        vocab = raw.get("vocabulary") or {}
        operational = vocab.get("operational") or []
        reference = vocab.get("reference") or []
        if not operational and not reference:
            _emit(
                "PREFLIGHT_VOCABULARY_EMPTY",
                f'{DOMAIN_CONTEXT_PATH} vocabulary is empty',
                "Add at least one token to vocabulary.operational or vocabulary.reference.",
            )
            failed = True
    else:
        _emit(
            "PREFLIGHT_DOMAIN_CONTEXT_MISSING",
            f"Domain context not found: {DOMAIN_CONTEXT_PATH}",
            "Create it (see example_data/domain_context.example.yaml).",
        )
        failed = True

    if failed:
        sys.exit(1)

    print("PASS: preflight checks OK")


if __name__ == "__main__":
    run_preflight()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
.venv/bin/python -m pytest scripts/tests/test_preflight.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/preflight.py scripts/tests/test_preflight.py
git commit -m "feat: add preflight environment gate script with tests"
```

---

### Task 2: Makefile — Add `preflight` Target and Update `validate-contract`

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add `preflight` target and wire `--strict` into `validate-contract`**

In `Makefile`, add after the `install` target:

```makefile
preflight:
	$(PYTHON) scripts/preflight.py
```

Change the `validate-contract` target from:

```makefile
validate-contract:
	wb validate contract --contract "$(CONTRACT)"
```

to:

```makefile
validate-contract:
	wb validate contract --contract "$(CONTRACT)" $(if $(STRICT),--strict)
```

This lets callers run `make validate-contract CONTRACT=... STRICT=1` for strict mode.

- [ ] **Step 2: Verify Makefile syntax**

```bash
make -n preflight
make -n validate-contract CONTRACT=build/schema-contract.yaml STRICT=1
```

Expected: dry-run output shows correct command lines with no errors.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat: add make preflight target and strict mode for validate-contract"
```

---

### Task 3: Domain Context Vocabulary Helper

**Files:**
- Modify: `profiler/tools/domain_context.py`
- Create/Extend: `profiler/tests/test_domain_context.py`

- [ ] **Step 1: Write failing test**

```python
# profiler/tests/test_domain_context.py
import pytest
from profiler.tools.domain_context import DomainContext, has_meaningful_vocabulary


def test_has_meaningful_vocabulary_empty():
    ctx = DomainContext()
    assert not has_meaningful_vocabulary(ctx)


def test_has_meaningful_vocabulary_with_operational():
    ctx = DomainContext()
    ctx.vocabulary.operational = ["crop"]
    assert has_meaningful_vocabulary(ctx)


def test_has_meaningful_vocabulary_with_reference():
    ctx = DomainContext()
    ctx.vocabulary.reference = ["variety"]
    assert has_meaningful_vocabulary(ctx)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
.venv/bin/python -m pytest profiler/tests/test_domain_context.py -v
```

Expected: `AttributeError: module 'profiler.tools.domain_context' has no attribute 'has_meaningful_vocabulary'`

- [ ] **Step 3: Implement helper**

In `profiler/tools/domain_context.py`, append before the final `return` in the module (or at the bottom):

```python
def has_meaningful_vocabulary(domain_context: DomainContext | None) -> bool:
    """Return True if the domain context has at least one operational or reference token."""
    if domain_context is None:
        return False
    return bool(
        domain_context.vocabulary.operational or domain_context.vocabulary.reference
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
.venv/bin/python -m pytest profiler/tests/test_domain_context.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add profiler/tools/domain_context.py profiler/tests/test_domain_context.py
git commit -m "feat: add has_meaningful_vocabulary helper to domain context"
```

---

### Task 4: Profiler Vocabulary Enforcement

**Files:**
- Modify: `profiler/management/commands/profile_cohort_corpus.py`

- [ ] **Step 1: Read current command to find insertion point**

Open `profiler/management/commands/profile_cohort_corpus.py` and locate where the command loads/configures the cohort corpus. The vocabulary check should happen **after** `domain_context` is loaded but **before** any tab scoring begins.

- [ ] **Step 2: Add vocabulary guard**

Insert an import:

```python
from profiler.tools.domain_context import has_meaningful_vocabulary
```

After the `domain_context` object is loaded (likely near where `load_domain_context` is called), add:

```python
if not has_meaningful_vocabulary(domain_context):
    self.stderr.write(
        self.style.ERROR(
            "FAIL[PROFILER_EMPTY_VOCABULARY]: Domain context vocabulary is empty\n"
            "  → Action: Populate vocabulary.operational / vocabulary.reference "
            "in domain_context.yaml and re-run phase 1.\n"
        )
    )
    raise CommandError("Profiler cannot proceed with empty vocabulary.")
```

- [ ] **Step 3: Smoke-test the command still loads**

```bash
DB_ENGINE=sqlite .venv/bin/python manage.py profile_cohort_corpus --help
```

Expected: help text prints without import errors.

- [ ] **Step 4: Commit**

```bash
git add profiler/management/commands/profile_cohort_corpus.py
git commit -m "feat: fail fast in profiler when domain vocabulary is empty"
```

---

### Task 5: Field-Mapping Identifier Helper

**Files:**
- Modify: `workbook/field_mapping.py`
- Create/Extend: `workbook/tests/test_field_mapping.py`

- [ ] **Step 1: Write failing test**

```python
# workbook/tests/test_field_mapping.py
import keyword
import pytest
from workbook.field_mapping import is_valid_python_identifier, suggested_field_name


def test_is_valid_python_identifier_good():
    assert is_valid_python_identifier("crop_variety")
    assert is_valid_python_identifier("name_2")


def test_is_valid_python_identifier_starts_with_digit():
    assert not is_valid_python_identifier("1")
    assert not is_valid_python_identifier("201_unit")


def test_is_valid_python_identifier_keyword():
    assert not is_valid_python_identifier("yield")
    assert not is_valid_python_identifier("class")
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
.venv/bin/python -m pytest workbook/tests/test_field_mapping.py -v
```

Expected: `AttributeError: module 'workbook.field_mapping' has no attribute 'is_valid_python_identifier'`

- [ ] **Step 3: Implement helper**

In `workbook/field_mapping.py`, add after the existing imports:

```python
import keyword
```

Then add the function right after `suggested_field_name`:

```python
def is_valid_python_identifier(name: str) -> bool:
    """Return True if *name* is a valid Python identifier and not a reserved keyword."""
    s = str(name)
    return s.isidentifier() and not keyword.iskeyword(s)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
.venv/bin/python -m pytest workbook/tests/test_field_mapping.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add workbook/field_mapping.py workbook/tests/test_field_mapping.py
git commit -m "feat: add is_valid_python_identifier helper for field names"
```

---

### Task 6: Scaffold Guardrails

**Files:**
- Modify: `workbook/management/commands/scaffold_workbook_schema.py`
- Create/Extend: `workbook/tests/test_scaffold_workbook_schema.py`

- [ ] **Step 1: Add imports and helpers to scaffold command**

At the top of `workbook/management/commands/scaffold_workbook_schema.py`, add:

```python
import keyword
from workbook.field_mapping import is_valid_python_identifier
```

- [ ] **Step 2: Add validation helpers inside the command module**

Append these functions before `class Command`:

```python
def _check_null_model_names(tables: list[dict]) -> list[str]:
    """Return error messages for tables with empty model_name."""
    errors: list[str] = []
    for table in tables:
        model_name = str(table.get("model_name", "")).strip()
        if not model_name:
            tab_title = table.get("bundle_worksheet_title", "?")
            errors.append(
                f'FAIL[SCAFFOLD_NULL_MODEL_NAME]: Tab "{tab_title}" produced empty model_name\n'
                "  → Action: Deduplicate the tab across year workbooks or set a unique suggested_model_name\n"
                f"  (Table: {tab_title}, Field: model_name)"
            )
    return errors


def _check_pivot_tables(table: dict) -> list[str]:
    """Return error messages if the table looks like a pivot table."""
    errors: list[str] = []
    columns = table.get("columns", [])
    if not columns:
        return errors
    headers = [col.get("source_column", "").strip() for col in columns]
    numeric_headers = [h for h in headers if h.isdigit()]
    if len(numeric_headers) / len(headers) > 0.5:
        tab_title = table.get("bundle_worksheet_title", "?")
        numeric_list = ", ".join(numeric_headers[:10])
        errors.append(
            f'FAIL[SCAFFOLD_PIVOT_TABLE]: Tab "{tab_title}" appears to be a pivot table '
            f"(numeric headers: {numeric_list})\n"
            "  → Action: Add it to vocabulary.derived or exclude it from the corpus config.\n"
            f"  (Table: {tab_title})"
        )
    return errors


def _check_invalid_identifiers(table: dict) -> list[str]:
    """Return error messages for invalid field or model names."""
    errors: list[str] = []
    model_name = str(table.get("model_name", "")).strip()
    if model_name and not is_valid_python_identifier(model_name):
        errors.append(
            f'FAIL[SCAFFOLD_INVALID_IDENTIFIER]: model_name "{model_name}" is not a valid Python identifier\n'
            "  → Action: Rename the source tab or set an explicit suggested_model_name.\n"
            f"  (Table: {table.get('bundle_worksheet_title', '?')}, Field: model_name)"
        )
    for col in table.get("columns", []):
        field_name = col.get("suggested_field_name", "")
        if field_name and not is_valid_python_identifier(field_name):
            errors.append(
                f'FAIL[SCAFFOLD_INVALID_IDENTIFIER]: Field name "{field_name}" is not a valid Python identifier\n'
                "  → Action: Rename the source column header or add a column alias in the bundle config.\n"
                f"  (Table: {table.get('bundle_worksheet_title', '?')}, Field: {field_name})"
            )
    return errors
```

- [ ] **Step 3: Wire validations into `_build_cohort_contract` and `_handle_bundle_config`**

In `_build_cohort_contract`, after the `for result in coverage_payload.get("results", []):` loop finishes and `_inject_designed_models(tables)` has run, add:

```python
    errors: list[str] = []
    errors.extend(_check_null_model_names(tables))
    for table in tables:
        errors.extend(_check_pivot_tables(table))
        errors.extend(_check_invalid_identifiers(table))
    if errors:
        raise CommandError("\n".join(errors))
```

Do the same inside `_handle_bundle_config` after the call to `build_contract(...)` and after `_inject_designed_models(tables)`.

- [ ] **Step 4: Write tests for guardrails**

```python
# workbook/tests/test_scaffold_workbook_schema.py
import pytest
from django.core.management import CommandError
from workbook.management.commands.scaffold_workbook_schema import (
    _check_invalid_identifiers,
    _check_null_model_names,
    _check_pivot_tables,
)


def test_check_null_model_names_finds_empty():
    tables = [{"bundle_worksheet_title": "Final Report", "model_name": ""}]
    errors = _check_null_model_names(tables)
    assert len(errors) == 1
    assert "SCAFFOLD_NULL_MODEL_NAME" in errors[0]


def test_check_pivot_table_detects_numeric_headers():
    table = {
        "bundle_worksheet_title": "Irrigation",
        "columns": [
            {"source_column": "1"},
            {"source_column": "6"},
            {"source_column": "7"},
            {"source_column": "Total"},
        ],
    }
    errors = _check_pivot_tables(table)
    assert len(errors) == 1
    assert "SCAFFOLD_PIVOT_TABLE" in errors[0]


def test_check_invalid_identifier_detects_digit_prefix():
    table = {
        "bundle_worksheet_title": "Unit",
        "model_name": "Unit",
        "columns": [{"suggested_field_name": "201_unit"}],
    }
    errors = _check_invalid_identifiers(table)
    assert any("201_unit" in e for e in errors)
    assert any("SCAFFOLD_INVALID_IDENTIFIER" in e for e in errors)
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
.venv/bin/python -m pytest workbook/tests/test_scaffold_workbook_schema.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add workbook/management/commands/scaffold_workbook_schema.py workbook/tests/test_scaffold_workbook_schema.py
git commit -m "feat: add scaffold guardrails for null model names, pivot tables, and invalid identifiers"
```

---

### Task 7: Strict Contract Validation

**Files:**
- Modify: `workbook/management/commands/validate_contract.py`
- Modify: `workbook/codegen/contract.py`
- Modify: `deployment/wb_cli.py`
- Create/Extend: `workbook/tests/test_validate_contract.py`

- [ ] **Step 1: Add strict helpers to `workbook/codegen/contract.py`**

Append these functions at the bottom of the module:

```python
def strict_validate_contract(contract: dict[str, Any]) -> list[str]:
    """Run strict validation checks and return a list of error messages.

    Checks:
    - No model_name is null or empty.
    - Every suggested_field_name is a valid Python identifier and not a keyword.
    - No duplicate model_name values exist across tables.
    - No suggested_field_name starts with a digit.
    """
    import keyword

    errors: list[str] = []
    tables = list(contract.get("tables") or [])
    model_names: list[str] = []

    for table in tables:
        model_name = str(table.get("model_name", "")).strip()
        if not model_name:
            label = table.get("suggested_model_name", "?")
            errors.append(
                f"FAIL[VALIDATE_NULL_MODEL]: Table '{label}' has empty model_name"
            )
            continue
        model_names.append(model_name)

    seen_model_names: set[str] = set()
    for mn in model_names:
        if mn in seen_model_names:
            errors.append(
                f'FAIL[VALIDATE_DUPLICATE_MODEL]: Duplicate model_name "{mn}" (2+ tables)'
                "\n  → Action: Merge the duplicate tables or give them distinct model_name values."
            )
        seen_model_names.add(mn)

    for table in tables:
        model_name = str(table.get("model_name", "")).strip()
        for col in table.get("columns", []):
            field_name = col.get("suggested_field_name", "")
            if not field_name:
                continue
            if not str(field_name).isidentifier() or keyword.iskeyword(str(field_name)):
                errors.append(
                    f'FAIL[VALIDATE_INVALID_FIELD_NAME]: Field "{field_name}" in model "{model_name}" '
                    f"is not a valid Python identifier\n"
                    "  → Action: Rename the source column in the contract."
                )
            elif str(field_name)[0].isdigit():
                errors.append(
                    f'FAIL[VALIDATE_INVALID_FIELD_NAME]: Field "{field_name}" in model "{model_name}" '
                    f"starts with a digit\n"
                    "  → Action: Rename the source column in the contract."
                )

    return errors
```

- [ ] **Step 2: Wire `--strict` into `validate_contract` command**

Open `workbook/management/commands/validate_contract.py`. Add `--strict` argument:

```python
parser.add_argument(
    "--strict",
    action="store_true",
    help="Enable strict mode: enforce valid Python identifiers and no duplicate model names",
)
```

In `handle`, after the existing validation logic, add:

```python
if options["strict"]:
    from workbook.codegen.contract import strict_validate_contract
    strict_errors = strict_validate_contract(contract)
    for err in strict_errors:
        self.stdout.write(self.style.ERROR(err))
    if strict_errors:
        raise CommandError(f"Strict validation failed with {len(strict_errors)} error(s).")
```

- [ ] **Step 3: Wire `--strict` into `wb_cli.py`**

In `deployment/wb_cli.py`, locate `_contract_validate` and change:

```python
call_command(Command, contract=args.contract)
```

to:

```python
kwargs = {"contract": args.contract}
if getattr(args, "strict", False):
    kwargs["strict"] = True
call_command(Command, **kwargs)
```

Also add the `--strict` argument to the `validate_cmd` parser:

```python
validate_cmd.add_argument("--strict", action="store_true")
```

- [ ] **Step 4: Write tests for strict validation**

```python
# workbook/tests/test_validate_contract.py
import pytest
from workbook.codegen.contract import strict_validate_contract


def test_strict_validate_duplicate_model():
    contract = {
        "tables": [
            {"model_name": "Crop", "columns": []},
            {"model_name": "Crop", "columns": []},
        ]
    }
    errors = strict_validate_contract(contract)
    assert any("VALIDATE_DUPLICATE_MODEL" in e for e in errors)


def test_strict_validate_invalid_field():
    contract = {
        "tables": [
            {
                "model_name": "Unit",
                "columns": [{"suggested_field_name": "201_unit"}],
            }
        ]
    }
    errors = strict_validate_contract(contract)
    assert any("VALIDATE_INVALID_FIELD_NAME" in e for e in errors)
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
.venv/bin/python -m pytest workbook/tests/test_validate_contract.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add workbook/management/commands/validate_contract.py workbook/codegen/contract.py deployment/wb_cli.py workbook/tests/test_validate_contract.py
git commit -m "feat: add strict contract validation for identifiers and duplicate models"
```

---

### Task 8: Codegen Defense-in-Depth Warnings

**Files:**
- Modify: `workbook/codegen/python_render.py`
- Modify: `workbook/codegen/model_generator.py`

- [ ] **Step 1: Add warning emission in `python_render.py`**

In `workbook/codegen/python_render.py`, change `render_field` to collect warnings. Since it currently returns a string, the simplest approach is to add a module-level warning list or change the return type. A less invasive approach: add a helper that returns `(line, warnings)` and update callers.

However, to keep the plan minimal, we can use a module-level list that callers clear and inspect. Add at module level:

```python
_codegen_warnings: list[str] = []


def get_and_clear_codegen_warnings() -> list[str]:
    """Return and clear accumulated codegen warnings."""
    warnings = list(_codegen_warnings)
    _codegen_warnings.clear()
    return warnings
```

Inside `render_field`, after computing `safe_name`, add:

```python
    if safe_name != name:
        _codegen_warnings.append(
            f"WARNING[GEN_SANITIZED_FIELD]: Field '{name}' sanitized to '{safe_name}' "
            f"in model '{model_name or '?'}'\n"
            "  → Action: Fix the source column name in the contract and re-generate."
        )
```

- [ ] **Step 2: Propagate warnings in `model_generator.py`**

In `workbook/codegen/model_generator.py`, at the top, add:

```python
from workbook.codegen.python_render import get_and_clear_codegen_warnings
```

In `render_model`, after the `for f in fields:` loop that calls `render_field`, add:

```python
    for warning in get_and_clear_codegen_warnings():
        lines.append(f"    # {warning.replace(chr(10), chr(10) + '    # ')}")
```

Wait, that would inject comments into the model class. Better: collect warnings at the `render_models_py` level and write them as module-level comments before the imports, or print them to stdout from the management command. The cleaner path is to return warnings from `render_models_py` and let the `generate_models` command print them.

Refined approach:

In `model_generator.py`, change `render_model` signature:

```python
def render_model(
    table: dict[str, Any],
    app_label: str,
    enum_names: set[str] | None = None,
    rendered_model_names: set[str] | None = None,
) -> tuple[str, list[str]]:
```

Make it return `(source, warnings)`. Inside, after `render_field` calls, collect warnings via `get_and_clear_codegen_warnings()`.

Then update `render_models_py`:

```python
def render_models_py(contract: dict[str, Any], app_label: str = "core") -> tuple[str, list[str]]:
    ...
    all_warnings: list[str] = []
    for table in tables:
        source, warnings = render_model(
            table,
            app_label,
            enum_names=set(enums.keys()),
            rendered_model_names=rendered_model_names,
        )
        parts.append(source)
        all_warnings.extend(warnings)
    parts.append("")
    return "\n".join(parts), all_warnings
```

Then in `generate_models.py`, after calling `render_models_py`, print warnings:

```python
source, warnings = render_models_py(contract, app_label=app_label)
for w in warnings:
    self.stdout.write(self.style.WARNING(w))
```

- [ ] **Step 3: Verify no import regressions**

```bash
DB_ENGINE=sqlite .venv/bin/python manage.py generate_models --help
```

Expected: help text prints without import errors.

- [ ] **Step 4: Commit**

```bash
git add workbook/codegen/python_render.py workbook/codegen/model_generator.py workbook/management/commands/generate_models.py
git commit -m "feat: emit warnings when codegen sanitizes field identifiers"
```

---

### Task 9: Scaffold vs Generate Clarity

**Files:**
- Modify: `workbook/codegen/python_render.py`
- Modify: `AUTONOMOUS_RUN_PROMPT.md`

- [ ] **Step 1: Update generated header comment**

In `workbook/codegen/python_render.py`, update `render_import_block`:

```python
def render_import_block(
    app_label: str,
    extra_imports: list[str] | None = None,
) -> str:
    lines: list[str] = [
        "# Generated by: wb generate models",
        "# Source contract: build/schema-contract.yaml",
        "# Do not edit directly — edit the contract and re-run make generate-models",
        "",
        f"# App label: {app_label}",
        "# Last generated: see git history",
        "",
        "from django.db import models",
    ]
    ...
```

- [ ] **Step 2: Redesign `AUTONOMOUS_RUN_PROMPT.md`**

Replace the entire content of `AUTONOMOUS_RUN_PROMPT.md` with:

```markdown
# Autonomous Run Prompt: Execute End-to-End Pipeline

> **For agents working in a scaffolded product repo.** This prompt runs the migration-workbench pipeline based on current state. It checks what exists, runs the next appropriate phase, and reports progress.
>
> **Do not duplicate AGENTS.md content.** Use the Makefile commands directly. Only pause for human decisions at documented judgment points.

---

## Phase 0: Pre-Flight

```bash
# Gate: If any check fails, the script prints a FAIL[<id>] message and exits.
# Action: Follow the printed instructions and re-run this phase.
make install          # idempotent; creates venv if missing
scripts/preflight.py  # checks venv, wb CLI, and domain_context.yaml population
```

---

## Phase 1: Orient (if domain_context.yaml exists)

```bash
# Gate: validate-domain-context fails if the YAML is malformed.
make validate-domain-context DOMAIN_CONTEXT=config/domain_context.yaml

# If no drive tree yet, draft it (Makefile reads DRIVE_FOLDER_ID from .env;
# if missing, the target fails with a clear error.)
if [ ! -f data/profile_snapshots/drive_tree.json ]; then
    make profile-drive-folder
fi

# Extract workbook codes
make extract-workbook-codes DRIVE_TREE=data/profile_snapshots/drive_tree.json COHORT_CORPUS_CONFIG=config/cohort_corpus.json
```

---

## Phase 2: Profiling (if cohort_corpus.json configured)

```bash
# Gate: If domain vocabulary is empty, phase 1 fails with FAIL[PROFILER_EMPTY_VOCABULARY].
# Action: Populate vocabulary.operational / vocabulary.reference in domain_context.yaml.

# Run Phase 1: discovery + tab selection
make profile-cohort-corpus-phase1

# Phase 2: heuristic refinement (re-run without API calls)
make profile-cohort-corpus-phase2

# Phase 3: deep profiling
make profile-cohort-corpus-phase3
```

---

## Phase 3: Schema Contract (if profiler output exists)

```bash
# Gate: scaffold_workbook_schema fails if it detects:
#   - duplicate tabs producing empty model_name  (FAIL[SCAFFOLD_NULL_MODEL_NAME])
#   - pivot tables with numeric column headers    (FAIL[SCAFFOLD_PIVOT_TABLE])
#   - invalid Python identifiers in field names   (FAIL[SCAFFOLD_INVALID_IDENTIFIER])
# Action: Exclude bad tabs from the corpus config or fix source headers.

# If config/contract.yaml doesn't exist, scaffold from profiler output
if [ ! -f config/contract.yaml ]; then
    python manage.py scaffold_workbook_schema \
        --bundle-config config/bundle.json \
        --table-profile build/bundle/structure.json \
        --out config/contract.yaml
fi

# Gate: validate-contract --strict fails on duplicate models or bad identifiers.
# Action: Edit config/contract.yaml to fix the listed issues.
make validate-contract CONTRACT=config/contract.yaml STRICT=1
```

---

## Phase 4: Code Generation (if contract passes strict validation)

```bash
# generate-models reads the contract YAML and writes models_auto.py.
# It does NOT require a stub; the contract itself is the single source of truth.
make generate-models CONTRACT=config/contract.yaml OUT=backend/apps/core/models_auto.py
make generate-admin CONTRACT=config/contract.yaml OUT=backend/apps/core/admin_auto.py
make generate-import CONTRACT=config/contract.yaml OUT=backend/apps/core/imports.py
```

---

## Phase 5: Migration (if generated code exists)

```bash
make migrate
make check
```

---

## Phase 6: View Manifest (if bundle exists)

```bash
# Pull bundle if not exists
if [ ! -d build/bundle ]; then
    make pull-bundle SOURCE_CONFIG=config/bundle.json
fi

# Generate view manifest
make generate-view-manifest CONTRACT=config/contract.yaml
```

---

## Phase 7: Import

```bash
# Preflight (validate-only)
make import-preflight IMPORT_DATA_DIR=build/bundle IMPORT_COMMAND=import_reference_example SUMMARY_JSON=build/preflight-summary.json

# Review SUMMARY_JSON — if errors > 0, stop and report to human

# Apply
make import-apply IMPORT_DATA_DIR=build/bundle IMPORT_COMMAND=import_reference_example SUMMARY_JSON=build/apply-summary.json
```

---

## Summary Report

After running, output a summary:

```
## Pipeline Status

| Phase | Status | Notes |
|-------|--------|-------|
| Pre-flight | ✅/❌ | |
| Orient | ✅/⏭️/❌ | domain_context.yaml exists: yes/no |
| Profiling | ✅/⏭️/❌ | cohort_corpus.json configured: yes/no |
| Schema Contract | ✅/⏭️/❌ | config/contract.yaml exists: yes/no |
| Code Gen | ✅/⏭️/❌ | models_auto.py populated: yes/no |
| Migration | ✅/⏭️/❌ | migrations applied: yes/no |
| View Manifest | ✅/⏭️/❌ | config/view-manifest.yaml exists: yes/no |
| Import | ✅/⏭️/❌ | build/bundle exists: yes/no |

## Human Decision Points Needed

- [ ] Review profiler output (Phase 1-3)
- [ ] Review schema contract draft
- [ ] Review generated code before migrating
- [ ] Review view manifest before admin regen
- [ ] Review import preflight summary
```

---

## End of Prompt
```

- [ ] **Step 3: Commit**

```bash
git add workbook/codegen/python_render.py AUTONOMOUS_RUN_PROMPT.md
git commit -m "docs: clarify scaffold vs generate roles and redesign autonomous prompt phases"
```

---

## Integration Verification

After all tasks are implemented, run the full gate:

```bash
make chassis-gate
```

Expected: PASS (the existing smoke path exercises scaffold → validate → generate, and must continue to work).

---

## Rollout Notes

- Downstream product repos on `0.x` should expect stricter scaffold behaviour. If they encounter `FAIL[SCAFFOLD_*]` errors, they should fix the upstream data (exclude pivot tables, deduplicate tabs) rather than pinning an older workbench version.
- The autonomous prompt in `AUTONOMOUS_RUN_PROMPT.md` is consumed by agentic runners. Product repos that have vendored their own copy should be updated to match the new gated-phase structure.

---

*Plan complete and saved to `docs/superpowers/plans/2026-05-20-reduce-autonomous-friction.md`.*
