# Design: Pipeline Discoverability — Four-Dimensional Enhancement

**Date:** 2026-05-20  
**Status:** Draft — pending user review  
**Scope:** `migration-workbench` upstream — profiler, workbook, importer, connectors, and deployment. Covers error messages, config self-documentation, partial-output modes, and contract-validation diagnostics.

---

## Problem Statement

A recent autonomous run produced five cascading friction points that blocked the entire pipeline. The root causes were not individual bugs; they were **systemic discoverability failures** across four dimensions:

1. **Error messages** — `tab_selection_overrides['201'] has unknown keys: ['include']` gave no hint about valid keys (`add`, `remove`, `replace`, `tabs`). The operator had to read source code.
2. **Config self-documentation** — `cohort_corpus.json` contains a `_documentation` block, but it does not describe the `tab_selection_overrides` schema. The operator guessed the key name.
3. **Partial-output modes** — `scaffold_workbook_schema` exits on the first error and writes nothing. A `--continue-on-error` or `--write-partial` flag would let the operator review what worked, iterate, and proceed.
4. **Contract-validation messages** — Deep-profile files store `tab_title` under `summary.tab_title`, but the scaffold code reads `result['tab_title']`. The error was a null `model_name` with no explanation of the **expected vs actual data shape**.

Additional data-quality blockers emerged:
- Pivot-table detection (0.5 numeric-header ratio) classified operational tabs like "Irrigation" and "Mulch" as pivot tables and hard-failed.
- Invalid Python identifiers (numeric column headers like `"201"`) produced hundreds of `FAIL[SCAFFOLD_INVALID_IDENTIFIER]` errors that blocked the entire scaffold.

The pipeline should be **self-documenting at failure time**. No source code should be required to understand an error, fix a config, or recover from a partial failure.

---

## Guiding Principles

1. **Fail fast, explain why.** Do not silently degrade, skip, or “best-effort” repair bad upstream data.
2. **Allow human review on partial failure.** A command that validates data should still emit *valid* artifacts so the operator can inspect, understand, and iterate.
3. **Validation at the point of production.** The command that produces an artifact is responsible for validating it before writing.
4. **Validation at the point of consumption.** The command that consumes an artifact validates it before reading, and explains **expected vs actual** data shapes.
5. **Config files document themselves.** Every JSON/YAML config should contain a `_documentation` block describing the schema, valid keys, and examples.
6. **Structured error contract.** Every fatal check emits a message, a list of valid values (when applicable), a concrete action, and a stable `check_id`.
7. **No new dependencies.** Re-use existing Python standard library and Django infrastructure.
8. **Idiomatic Django preserved.** Management commands continue to raise `CommandError`. Library code continues to raise `ValueError` or custom exceptions. The enrichment happens in the message payload, not the exception type.

---

## Dimension 1 — The `UserFacingError` Contract

### Base class

A lightweight exception base in `workbench/exceptions.py`:

```python
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
```

### Django management-command wrapper

Management commands use a thin helper so they can still `raise CommandError(...)`:

```python
def command_error(
    message: str,
    *,
    action: str | None = None,
    valid_values: list[str] | None = None,
    check_id: str | None = None,
) -> CommandError:
    """Return a Django CommandError with a fully-explained message."""
    err = UserFacingError(message, action=action, valid_values=valid_values, check_id=check_id)
    return CommandError(str(err))
```

### Usage split

- **Management commands** (`profiler/management/commands/*.py`, `workbook/management/commands/*.py`) → `raise command_error(...)`
- **Library/util code** (`profiler/tools/*.py`, `workbook/codegen/*.py`, `importer/*.py`, `connectors/*.py`) → `raise UserFacingError(...)` directly, or wrap in `CommandError` at the call site if the caller is a command.

### Output example

```
CommandError: tab_selection_overrides['201'] has unknown keys: ['include'].
Valid values: add, remove, replace, tabs.
Action: Replace the key 'include' with 'replace: true' and a 'tabs' list.
```

---

## Dimension 2 — Config Self-Documentation

### Problem

`cohort_corpus.json` ships with a `_documentation` block, but it does not describe the `tab_selection_overrides` schema. The operator guessed `include: [...]` instead of `replace: true` + `tabs: [...]`.

### Solution

Every config file that defines a user-editable schema must contain a `_documentation` object that describes:
1. The purpose of the file.
2. The schema of each top-level key, with valid values and examples.
3. Common mistakes and their corrections.

### Example: `cohort_corpus.json` `_documentation` addition

```json
{
  "_documentation": {
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
    }
  }
}
```

### Enforcement

- **Validation command** — `validate_cohort_corpus` (new or existing) checks that every user-supplied key exists in the documented schema. Undocumented keys raise `WARN[CONFIG_UNDOCUMENTED_KEY]` but do not fail, so we can iterate the docs.
- **Agent notes** — `AGENTS.md` updated to instruct agents: "When generating or editing a config file, always check the `_documentation` block for the correct schema before guessing key names."

### Scope

- This PR updates `cohort_corpus.json` (the example/template) and the `new_product.py` scaffold to generate `_documentation` blocks.
- Future PRs extend this to `bundle_config.json`, `domain_context.yaml`, and other config files.

---

## Dimension 3 — Partial-Output Modes

### Problem

`scaffold_workbook_schema` exits on the first error and writes nothing. The operator cannot review what worked, cannot see which tabs passed validation, and cannot proceed to downstream phases (codegen, migration, import) until every single data issue is fixed.

### Solution

`scaffold_workbook_schema` gains a `--continue-on-error` flag (and an alias `--write-partial`). When enabled:

1. **Validation errors are collected**, not raised immediately.
2. **Valid tables are written** to the output YAML.
3. **Invalid tables are written** to a companion file (e.g., `schema-contract-rejected.yaml`) with their error annotations.
4. **A summary is printed** to stdout:

```
WARN[SCAFFOLD_PARTIAL_OUTPUT]: scaffold_workbook_schema wrote partial output.
  Tables written: 12
  Tables rejected: 5
  Rejections written to: data/schema-contract-rejected.yaml
  Action: Review rejected tables, fix upstream data, and re-run without --continue-on-error.
```

### Rejection file format (`schema-contract-rejected.yaml`)

```yaml
rejected_tables:
  - table:
      source_tab_title: "Irrigation"
      source_workbook_code: "301"
    error:
      check_id: "SCAFFOLD_PIVOT_TABLE"
      message: "Tab 'Irrigation' appears to be a pivot table (numeric headers: 1, 6, 7)."
      action: "Add to vocabulary.derived or exclude from corpus config."
  - table:
      source_tab_title: "Final Report"
      source_workbook_code: "201"
    error:
      check_id: "SCAFFOLD_NULL_MODEL_NAME"
      message: "Tab 'Final Report' produced empty model_name."
      action: "Check deep profile data shape; expected result['tab_title'], found summary.tab_title."
```

### Scope of partial-output mode

- **This PR:** `scaffold_workbook_schema` only.
- **Future PRs:** Extend to `generate_models`, `generate_admin`, and `generate_import` if similar blocking behavior is observed.

### Interaction with existing hard-fail checks

- `--continue-on-error` does **not** bypass **environment pre-flight** (missing `--bundle-config`, missing `--cohort-corpus-out-dir`). Those still fail fast.
- `--continue-on-error` **does** bypass **data-quality checks** (null model_name, pivot table, invalid identifier) and writes partial output.

---

## Dimension 4 — Contract Validation Messages (Expected vs Actual)

### Problem

Deep-profile files store `tab_title` under `summary.tab_title`, but `scaffold_workbook_schema` reads `result['tab_title']`. The error was a null `model_name` with no explanation of the **expected vs actual data shape**.

### Solution

When a command consumes an artifact and finds a missing or malformed field, the error message must name:
1. The **expected path** in the data structure.
2. The **actual path** where the data was found (or `not found`).
3. The **consuming command** and the **producing command** so the operator knows which end to fix.

### Example rewrite

**Before:**
```
CommandError: Tab "Final Report" produced empty model_name
```

**After:**
```
CommandError: SCAFFOLD_NULL_MODEL_NAME: Tab "Final Report" produced empty model_name.
  Expected path: result['tab_title']
  Actual path: summary['tab_title'] (value: "Final Report")
  Producing command: profile_cohort_corpus (deep profile output)
  Consuming command: scaffold_workbook_schema
  Action: Update profile_cohort_corpus to write tab_title at result['tab_title'],
          or update scaffold_workbook_schema to read from summary['tab_title'].
```

### Additional data-shape mismatch sites

| Producer | Consumer | Expected path | Actual path | check_id |
|----------|----------|---------------|-------------|----------|
| `profile_cohort_corpus` deep | `scaffold_workbook_schema` | `result['tab_title']` | `summary['tab_title']` | `SCAFFOLD_SHAPE_MISMATCH-001` |
| `profile_cohort_corpus` broad | `scaffold_workbook_schema` | `result['inventory_rows']` | `inventory_rows` (top-level) | `SCAFFOLD_SHAPE_MISMATCH-002` |
| `snapshot_bundle` | `generate_import` | `bundle['tables'][0]['columns']` | `bundle['tables'][0]['fields']` | `IMPORTER_SHAPE_MISMATCH-001` |

### Upstream fix responsibility

The deep-profile data-shape mismatch is an **upstream bug** in the profiler. The `UserFacingError` contract must still explain the mismatch clearly, but the fix belongs in `profiler/tools/cohort_corpus.py` (write `tab_title` to the path the scaffold expects) or in `scaffold_workbook_schema` (read from `summary.tab_title` if that is the canonical path).

**Decision needed:** Is `summary.tab_title` the canonical path going forward, or should the profiler write `tab_title` at the top level? (The spec recommends aligning on `summary.tab_title` because it already contains other metadata, but either choice is fine as long as both ends agree.)

---

## Tiered Audit Catalog

The audit lives at `docs/discoverability-audit.md` and is updated when new commands or error sites are added.

### Tier definitions

| Tier | Name | Criteria |
|------|------|----------|
| 1 | Critical | Forces the user to read source code. Missing valid-values hints, missing action guidance, missing expected-vs-actual paths, or cryptic one-liners. |
| 2 | Enhance | Technically correct but lacks context. Tells the user *what* failed without *how* to fix it or where the data came from. |
| 3 | Good | Follows the full contract (message + valid values + action + expected/actual paths). Catalogued for reference. |

### Example rewrite (Tier 1 → Tier 3)

**Before (Tier 1):**
```
CommandError: tab_selection_overrides['201'] has unknown keys: ['include']
```

**After (Tier 3):**
```
CommandError: tab_selection_overrides['201'] has unknown keys: ['include'].
Valid values: add, remove, replace, tabs.
Action: Replace 'include' with 'replace: true' and a 'tabs' list.
```

### Current Tier 1 targets by dimension

| Dimension | App | File | Error site | check_id |
|-----------|-----|------|------------|----------|
| Error messages | profiler | `tools/cohort_corpus.py` | `apply_tab_selection_overrides` unknown keys | `PROFILER-OVERRIDE-001` |
| Error messages | profiler | `tools/cohort_corpus.py` | missing `in_scope_workbooks` | `PROFILER-CONFIG-001` |
| Error messages | profiler | `tools/cohort_corpus.py` | missing `folder_id` | `PROFILER-CONFIG-002` |
| Error messages | profiler | `tools/coda_corpus.py` | `apply_table_selection_overrides` unknown keys | `PROFILER-CODA-001` |
| Error messages | workbook | `codegen/contract.py` | cyclic include | `WORKBOOK-CONTRACT-001` |
| Error messages | workbook | `codegen/contract.py` | missing include file | `WORKBOOK-CONTRACT-002` |
| Error messages | importer | `base.py` | missing data directory | `IMPORTER-SETUP-001` |
| Error messages | connectors | `router.py` | unsupported provider | `CONNECTOR-ROUTER-001` |
| Config docs | profiler | `cohort_corpus.json` template | `_documentation` missing override schema | `CONFIG-DOCS-001` |
| Partial output | workbook | `scaffold_workbook_schema.py` | hard-fail on first error | `SCAFFOLD_PARTIAL-001` |
| Contract validation | profiler/workbook | `cohort_corpus.py` / `scaffold_workbook_schema.py` | deep profile `tab_title` path mismatch | `SCAFFOLD_SHAPE_MISMATCH-001` |
| Contract validation | workbook | `scaffold_workbook_schema.py` | null model_name without expected/actual | `SCAFFOLD_NULL_MODEL_NAME` |
| Contract validation | workbook | `scaffold_workbook_schema.py` | pivot table without numeric header list | `SCAFFOLD_PIVOT_TABLE` |
| Contract validation | workbook | `scaffold_workbook_schema.py` | invalid identifier without source column name | `SCAFFOLD_INVALID_IDENTIFIER` |

---

## Implementation Boundary

### New files

- `workbench/exceptions.py` — `UserFacingError` + `command_error()`.
- `docs/discoverability-audit.md` — Living tiered catalog.

### Files to modify (Tier 1 → Tier 3)

- `profiler/tools/cohort_corpus.py`
- `profiler/tools/coda_corpus.py`
- `connectors/router.py`
- `workbook/codegen/contract.py`
- `importer/base.py`
- `workbook/management/commands/scaffold_workbook_schema.py`
- `profiler/management/commands/profile_cohort_corpus.py`
- `profiler/tests/test_cohort_corpus_tools.py`
- `profiler/tests/test_coda_corpus.py`
- `scripts/new_product.py` — generate `_documentation` blocks in config templates

### Files intentionally NOT touched

- `deployment/wb_cli.py` — Already has a clean `ERROR_CODES` + `details` pattern. Treated as Tier 3.
- Internal `assert` statements, test-only helper messages, and logging-only strings.

### Architecture rule

`workbench.exceptions` must never import Django or any app-specific module. It stays a pure-Python leaf so every app can import it without circular dependencies.

---

## Testing Strategy

1. **Unit tests** — Every rewritten error site is covered by an existing test; update the `match=` pattern to assert the new substring appears in the raised exception message (`match="Valid values:"`, `match="Action:"`, `match="Expected path:"`).
2. **Partial-output test** — New test for `scaffold_workbook_schema --continue-on-error`: verify valid tables are written, rejected tables are written to companion file, and stdout contains the summary.
3. **Regression guard** — The existing `make chassis-gate` must pass after string updates.
4. **No new test dependencies** — Tests continue to use `pytest.raises(CommandError, match=...)`. Partial-output test uses `tmp_path` and YAML parsing (already in test suite).

---

## Rollback & Compatibility

- This is a **string-only and CLI-flag change** for user-facing messages. No APIs, no file formats change.
- The `--continue-on-error` flag is additive; existing behavior is unchanged when the flag is absent.
- Product repos that screen-scrape exact error strings may need minor updates, but the workbench is upstream and Semver allows minor string changes on `0.x`.
- If a message rewrite introduces ambiguity, we revert the single string in a follow-up PR.

---

## Decisions (Resolved)

1. **Data-shape canonical path:** `tab_title` is written at the **top level** of deep-profile output. The scaffold reads `result['tab_title']` as the canonical path. The profiler is updated to write `tab_title` at the top level.
2. **Pivot-table threshold:** The numeric-header ratio is configurable via `pivot_detection_threshold` in `cohort_corpus.json` (default: 0.5). Product repos can tune or disable (set to `null` or `1.0`) for idiosyncratic data.
3. **Scope of partial-output:** `--continue-on-error` is added to `scaffold_workbook_schema`, `generate_models`, `generate_admin`, and `generate_import` in this PR.

---

## References

- Existing design: `docs/superpowers/specs/2026-05-20-reduce-autonomous-friction-design.md` (introduced `FAIL[CHECK_ID]` contract)
- Agent notes: `AGENTS.md` — interface contract, patching boundary, human judgment points
