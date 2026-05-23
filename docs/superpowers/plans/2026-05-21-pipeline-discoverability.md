# Pipeline Discoverability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every user-facing error self-documenting by introducing a shared `UserFacingError` contract, refactoring Tier 1 error sites across the five apps, adding `_documentation` blocks to config templates, and maintaining a tiered audit catalog.

**Architecture:** Create `workbench/exceptions.py` with `UserFacingError` (pure-Python, no Django) and `command_error()` factory (returns Django `CommandError`). Refactor every Tier 1 error site to use these helpers. Update `cohort_corpus.example.json` and `scripts/new_product.py` to generate `_documentation` blocks describing `tab_selection_overrides` schema. Create `docs/discoverability-audit.md` as a living catalog.

**Tech Stack:** Python 3.11, Django, pytest.

---

## Task 1: UserFacingError Base Contract

**Files:**
- Create: `workbench/__init__.py`
- Create: `workbench/exceptions.py`
- Test: `workbench/tests/test_exceptions.py`

- [ ] **Step 1: Create package and base exception**

```python
# workbench/__init__.py
"""Shared pure-Python utilities for migration-workbench apps.

This package must never import Django or any app-specific module.
It is a leaf dependency so every app can import it without circularity.
"""
```

```python
# workbench/exceptions.py
"""User-facing error contract for migration-workbench.

All exceptions that the user must act on carry enough context to fix the
problem without reading source code.
"""

from __future__ import annotations


class UserFacingError(Exception):
    """Base for exceptions that carry enough context for the user to fix
    the problem without reading source code.
    """

    def __init__(
        self,
        message: str,
        *,
        action: str | None = None,
        valid_values: list[str] | None = None,
        check_id: str | None = None,
    ):
        super().__init__(message)
        self.action = action
        self.valid_values = valid_values
        self.check_id = check_id

    def __str__(self) -> str:
        parts = [self.args[0]]
        if self.valid_values:
            parts.append(f"Valid values: {', '.join(self.valid_values)}.")
        if self.action:
            parts.append(f"Action: {self.action}")
        return " ".join(parts)


def command_error(
    message: str,
    *,
    action: str | None = None,
    valid_values: list[str] | None = None,
    check_id: str | None = None,
) -> Exception:
    """Return a Django CommandError with a fully-explained message.

    This helper must be called, not raised, inside management commands so
    that the caller can still ``raise`` the returned value.
    """
    from django.core.management.base import CommandError

    err = UserFacingError(
        message, action=action, valid_values=valid_values, check_id=check_id
    )
    return CommandError(str(err))
```

- [ ] **Step 2: Write tests**

```python
# workbench/tests/test_exceptions.py
import pytest
from django.core.management.base import CommandError

from workbench.exceptions import UserFacingError, command_error


def test_user_facing_error_str_with_all_fields():
    err = UserFacingError(
        "unknown keys found",
        action="Replace 'include' with 'add' or 'replace'.",
        valid_values=["add", "remove", "replace", "tabs"],
        check_id="PROFILER-OVERRIDE-001",
    )
    text = str(err)
    assert "unknown keys found" in text
    assert "Valid values: add, remove, replace, tabs." in text
    assert "Action: Replace 'include' with 'add' or 'replace'." in text


def test_user_facing_error_str_minimal():
    err = UserFacingError("something went wrong")
    assert str(err) == "something went wrong"


def test_command_error_returns_command_error_instance():
    err = command_error("bad config", check_id="TEST-001")
    assert isinstance(err, CommandError)
    assert "bad config" in str(err)
    assert "TEST-001" in str(err)
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/python -m pytest workbench/tests/test_exceptions.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add workbench/__init__.py workbench/exceptions.py workbench/tests/test_exceptions.py
git commit -m "feat: add UserFacingError contract and command_error helper"
```

---

## Task 2: Refactor Tier 1 Error Sites

**Files:**
- Modify: `profiler/tools/cohort_corpus.py` — `apply_tab_selection_overrides` unknown keys, missing config keys
- Modify: `profiler/tools/coda_corpus.py` — `apply_table_selection_overrides` unknown keys, missing `docs`
- Modify: `connectors/router.py` — unsupported provider
- Modify: `workbook/codegen/contract.py` — cyclic include, missing include file
- Modify: `importer/base.py` — missing data directory
- Test: `profiler/tests/test_cohort_corpus_tools.py` — update `match=` patterns
- Test: `profiler/tests/test_coda_corpus.py` — update `match=` patterns

- [ ] **Step 1: Refactor `profiler/tools/cohort_corpus.py`**

Replace the unknown-keys block (around line 755-761):

```python
# BEFORE:
        unknown = set(entry.keys()) - TAB_SELECTION_OVERRIDE_KEYS
        if unknown:
            valid_keys = ", ".join(sorted(TAB_SELECTION_OVERRIDE_KEYS))
            raise CommandError(
                f"tab_selection_overrides[{workbook_code!r}] has unknown keys: {sorted(unknown)}. "
                f"Valid keys are: {valid_keys}."
            )
```

With:

```python
# AFTER:
        unknown = set(entry.keys()) - TAB_SELECTION_OVERRIDE_KEYS
        if unknown:
            from workbench.exceptions import command_error

            raise command_error(
                f"tab_selection_overrides[{workbook_code!r}] has unknown keys: {sorted(unknown)}.",
                valid_values=sorted(TAB_SELECTION_OVERRIDE_KEYS),
                action=f"Replace the key(s) {sorted(unknown)} with valid keys.",
                check_id="PROFILER-OVERRIDE-001",
            )
```

Replace the missing `in_scope_workbooks` block (around line 1144-1145):

```python
# BEFORE:
    if not in_scope_codes:
        raise CommandError("Config must include non-empty 'in_scope_workbooks'")
```

With:

```python
# AFTER:
    if not in_scope_codes:
        from workbench.exceptions import command_error

        raise command_error(
            "Config must include non-empty 'in_scope_workbooks'.",
            action="Add 'in_scope_workbooks': ['101', '201'] to the corpus config.",
            check_id="PROFILER-CONFIG-001",
        )
```

Replace the missing `folder_id` block (around line 1152-1153):

```python
# BEFORE:
        raise CommandError("folder_id is required when not in a resume mode")
```

With:

```python
# AFTER:
        from workbench.exceptions import command_error

        raise command_error(
            "folder_id is required when not in a resume mode.",
            action="Pass --folder or set DRIVE_FOLDER_ID in .env.",
            check_id="PROFILER-CONFIG-002",
        )
```

- [ ] **Step 2: Refactor `profiler/tools/coda_corpus.py`**

Apply the same pattern to `apply_table_selection_overrides` (around line 229):

```python
        unknown = set(entry.keys()) - TABLE_SELECTION_OVERRIDE_KEYS
        if unknown:
            from workbench.exceptions import command_error

            raise command_error(
                f"table_selection_overrides[{doc_name!r}] has unknown keys: {sorted(unknown)}.",
                valid_values=sorted(TABLE_SELECTION_OVERRIDE_KEYS),
                action=f"Replace the key(s) {sorted(unknown)} with valid keys.",
                check_id="PROFILER-CODA-001",
            )
```

And the missing `docs` block (around line 417-418):

```python
    if not docs:
        from workbench.exceptions import command_error
        raise command_error(
            "Config must include a non-empty 'docs' list.",
            action="Add 'docs': [{'name': 'My Doc', 'doc_id': '...'}] to the corpus config.",
            check_id="PROFILER-CODA-002",
        )
```

- [ ] **Step 3: Refactor `connectors/router.py`**

Replace (around line 38-40):

```python
# BEFORE:
    raise CommandError(
        f"Unsupported provider '{provider}' (expected google_sheets or coda)"
    )
```

With:

```python
# AFTER:
    from workbench.exceptions import command_error

    raise command_error(
        f"Unsupported provider '{provider}'.",
        valid_values=["google_sheets", "coda"],
        action="Set 'provider' to 'google_sheets' or 'coda' in the bundle config.",
        check_id="CONNECTOR-ROUTER-001",
    )
```

- [ ] **Step 4: Refactor `workbook/codegen/contract.py`**

Replace cyclic include (around line 45):

```python
# BEFORE:
            raise ValueError(f"cyclic include detected: {cycle}")
```

With:

```python
# AFTER:
            from workbench.exceptions import UserFacingError
            raise UserFacingError(
                f"cyclic include detected: {cycle}",
                action="Remove the circular !include reference in the contract YAML.",
                check_id="WORKBOOK-CONTRACT-001",
            )
```

Replace missing include file (around line 47):

```python
# BEFORE:
            raise ValueError(f"include file not found: {target}")
```

With:

```python
# AFTER:
            from workbench.exceptions import UserFacingError
            raise UserFacingError(
                f"include file not found: {target}",
                action="Create the missing file or correct the !include path in the contract YAML.",
                check_id="WORKBOOK-CONTRACT-002",
            )
```

- [ ] **Step 5: Refactor `importer/base.py`**

Replace (around line 156):

```python
# BEFORE:
            raise ValueError(f"Data directory not found: {self.data_dir}")
```

With:

```python
# AFTER:
            from workbench.exceptions import UserFacingError
            raise UserFacingError(
                f"Data directory not found: {self.data_dir}",
                action="Create the directory or pass the correct --data-dir path.",
                check_id="IMPORTER-SETUP-001",
            )
```

- [ ] **Step 6: Update tests to assert on enriched messages**

In `profiler/tests/test_cohort_corpus_tools.py`, update `match=` patterns:

```python
# Before:
with pytest.raises(CommandError, match="unknown keys"):

# After:
with pytest.raises(CommandError, match="unknown keys"):
    # same test body; str(CommandError) now contains extra fields,
    # but "unknown keys" still matches.
```

No test body changes needed — the `match=` regex still hits the message substring.

In `profiler/tests/test_coda_corpus.py`, same treatment.

- [ ] **Step 7: Run updated tests**

```bash
.venv/bin/python -m pytest profiler/tests/test_cohort_corpus_tools.py profiler/tests/test_coda_corpus.py -v
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add profiler/tools/cohort_corpus.py profiler/tools/coda_corpus.py connectors/router.py workbook/codegen/contract.py importer/base.py
# If any test files were changed:
git add profiler/tests/test_cohort_corpus_tools.py profiler/tests/test_coda_corpus.py
git commit -m "refactor: enrich Tier 1 error sites with UserFacingError contract"
```

---

## Task 3: Config Self-Documentation

**Files:**
- Modify: `example_data/cohort_corpus.example.json`
- Modify: `scripts/new_product.py`
- Test: `examples/tests/test_new_product_scaffold.py`

- [ ] **Step 1: Update example config with override schema documentation**

In `example_data/cohort_corpus.example.json`, add `tab_selection_overrides` to `_documentation`:

```json
{
  "_documentation": {
    ...existing keys...,
    "tab_selection_overrides": {
      "description": "Per-workbook overrides for the heuristic tab-selection algorithm.",
      "schema": {
        "workbook_code": {
          "replace": {"type": "boolean", "description": "If true, replace the heuristic selection entirely."},
          "tabs": {"type": "list[str]", "description": "Required when replace is true. The full list of tab titles to select."},
          "add": {"type": "list[str]", "description": "Append these tab titles to the heuristic selection."},
          "remove": {"type": "list[str]", "description": "Remove these tab titles from the heuristic selection."}
        }
      },
      "examples": {
        "replace": {"301": {"replace": true, "tabs": ["Plan Board"]}},
        "add_and_remove": {"402": {"add": ["Custom Tab"], "remove": ["Deprecated Tab"]}}
      },
      "common_mistakes": {
        "include": "Use 'add' to append, or 'replace: true' + 'tabs' to override entirely."
      }
    },
    "pivot_detection_threshold": "Ratio of numeric column headers that triggers pivot-table rejection in scaffold_workbook_schema. Set to 1.0 or null to disable."
  },
  ...rest of config...
}
```

- [ ] **Step 2: Update `scripts/new_product.py` to generate `_documentation`**

Find the `render_agents_md` or config generation code in `scripts/new_product.py`. Add the new `_documentation` block to the generated `cohort_corpus.json` template. If the script copies `example_data/cohort_corpus.example.json`, then Step 1 already covers it.

Verify in `scripts/new_product.py` that `scaffold_config_templates` copies `example_data/cohort_corpus.example.json` (line 1282). Since it copies the file, updating the example is sufficient.

- [ ] **Step 3: Verify scaffolded product gets new docs**

Run:

```bash
python scripts/new_product.py test-product --output-dir /tmp/test-product-scaffold
```

Then check:

```bash
cat /tmp/test-product-scaffold/config/cohort_corpus.json | python -m json.tool | grep -A5 "tab_selection_overrides"
```

Expected: The `_documentation.tab_selection_overrides` block is present.

- [ ] **Step 4: Update existing test**

In `examples/tests/test_new_product_scaffold.py`, add:

```python
def test_scaffolded_cohort_corpus_has_override_docs():
    # After running new_product scaffold...
    config = json.loads((output_dir / "config" / "cohort_corpus.json").read_text())
    docs = config.get("_documentation", {})
    assert "tab_selection_overrides" in docs
    assert "common_mistakes" in docs["tab_selection_overrides"]
    assert "include" in docs["tab_selection_overrides"]["common_mistakes"]
```

- [ ] **Step 5: Run test**

```bash
.venv/bin/python -m pytest examples/tests/test_new_product_scaffold.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add example_data/cohort_corpus.example.json examples/tests/test_new_product_scaffold.py
git commit -m "feat: document tab_selection_overrides schema in cohort_corpus template"
```

---

## Task 4: Tiered Audit Catalog

**Files:**
- Create: `docs/discoverability-audit.md`

- [ ] **Step 1: Create the living catalog**

```markdown
# Discoverability Audit

Living tiered catalog of user-facing error sites across migration-workbench.

## Tier definitions

| Tier | Name | Criteria |
|------|------|----------|
| 1 | Critical | Forces the user to read source code. Missing valid-values hints, missing action guidance, or cryptic one-liners. |
| 2 | Enhance | Technically correct but lacks context. Tells the user *what* failed without *how* to fix it. |
| 3 | Good | Follows the full contract (message + valid values + action + check_id). |

## Current catalog

### Profiler

| check_id | File | Error site | Tier | Notes |
|----------|------|------------|------|-------|
| PROFILER-OVERRIDE-001 | `profiler/tools/cohort_corpus.py` | `apply_tab_selection_overrides` unknown keys | 3 | Message + valid_values + action |
| PROFILER-CONFIG-001 | `profiler/tools/cohort_corpus.py` | missing `in_scope_workbooks` | 3 | Message + action |
| PROFILER-CONFIG-002 | `profiler/tools/cohort_corpus.py` | missing `folder_id` | 3 | Message + action |
| PROFILER-CODA-001 | `profiler/tools/coda_corpus.py` | `apply_table_selection_overrides` unknown keys | 3 | Message + valid_values + action |
| PROFILER-CODA-002 | `profiler/tools/coda_corpus.py` | missing `docs` list | 3 | Message + action |

### Connectors

| check_id | File | Error site | Tier | Notes |
|----------|------|------------|------|-------|
| CONNECTOR-ROUTER-001 | `connectors/router.py` | unsupported provider | 3 | Message + valid_values + action |

### Workbook

| check_id | File | Error site | Tier | Notes |
|----------|------|------------|------|-------|
| WORKBOOK-CONTRACT-001 | `workbook/codegen/contract.py` | cyclic `!include` | 3 | Message + action |
| WORKBOOK-CONTRACT-002 | `workbook/codegen/contract.py` | missing include file | 3 | Message + action |
| SCAFFOLD_PARTIAL-001 | `workbook/management/commands/scaffold_workbook_schema.py` | hard-fail on first error | 3 | Mitigated by `--continue-on-error` (Plan A) |
| SCAFFOLD_NULL_MODEL_NAME | `workbook/management/commands/scaffold_workbook_schema.py` | empty `model_name` | 2 | Has action, lacks check_id in current code; fixed in Plan A |
| SCAFFOLD_PIVOT_TABLE | `workbook/management/commands/scaffold_workbook_schema.py` | numeric headers > threshold | 2 | Has action, lacks check_id in current code; fixed in Plan A |
| SCAFFOLD_INVALID_IDENTIFIER | `workbook/management/commands/scaffold_workbook_schema.py` | invalid Python identifier | 2 | Has action, lacks check_id in current code; fixed in Plan A |

### Importer

| check_id | File | Error site | Tier | Notes |
|----------|------|------------|------|-------|
| IMPORTER-SETUP-001 | `importer/base.py` | missing data directory | 3 | Message + action |

## Adding a new entry

When you add or refactor an error site:
1. Pick the next sequential `check_id` in the app's namespace.
2. Ensure the message includes: what failed, valid values (if applicable), and a concrete action.
3. Update this table.
```

- [ ] **Step 2: Commit**

```bash
git add docs/discoverability-audit.md
git commit -m "docs: add tiered discoverability audit catalog"
```

---

## Task 5: Regression Guard

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
   - `UserFacingError` base class + `command_error()` factory: ✅ Task 1
   - Management commands raise enriched `CommandError`: ✅ Task 2
   - Library code raises `UserFacingError` directly: ✅ Task 2 (`contract.py`)
   - Config self-documentation (`_documentation` block): ✅ Task 3
   - Tiered audit catalog: ✅ Task 4
   - No new dependencies: ✅ (uses existing Django, stdlib)
   - `workbench` never imports Django or app modules: ✅ Task 1

2. **Placeholder scan:** No TBD, TODO, or vague steps found.

3. **Type consistency:** `UserFacingError` fields (`action`, `valid_values`, `check_id`) match usage in all refactored sites.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-21-pipeline-discoverability.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session, batch execution with checkpoints.

**Which approach?**
