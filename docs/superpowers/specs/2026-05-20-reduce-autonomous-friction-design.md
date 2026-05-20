# Design: Reduce Autonomous Pipeline Friction — Fail-Fast Guardrails

**Date:** 2026-05-20  
**Status:** Approved  
**Scope:** `migration-workbench` upstream — profiler, scaffold, contract validation, codegen, and autonomous-run documentation.

---

## Problem Statement

A recent autonomous run encountered six cascading friction points that produced a broken contract, invalid generated Python, and confusing error messages. The root cause in every case was missing or unvalidated upstream data (empty domain context, pivot tables, invalid identifiers). The pipeline did not stop early; it emitted bad artifacts and failed later with opaque errors.

**Design goal:** Make the autonomous pipeline **fail fast at the exact point of data failure**, with **actionable, structured error messages** that tell the operator what to fix and where.

---

## Guiding Principles

1. **Fail fast, explain why.**  Do not silently degrade, skip, or “best-effort” repair bad upstream data.
2. **Validation at the point of production.**  The command that produces an artifact is responsible for validating it before writing.
3. **Validation at the point of consumption.**  The command that consumes an artifact validates it before reading.
4. **Structured error contract.**  Every fatal check emits a machine-readable `FAIL[<check_id>]` line followed by a human message and a concrete action.
5. **No new dependencies.**  Re-use existing Django management command, Makefile, and `workbook.codegen` infrastructure.

---

## Design Sections

### Section 1 — Environment Pre-Flight Gate

A new script `scripts/preflight.py` is invoked at the top of the autonomous prompt (and optionally via `make preflight`). It checks:

- `.venv` exists and `manage.py check` passes (catches friction #6).
- `wb` CLI is accessible either on PATH or at `.venv/bin/wb` (catches friction #3).
- `domain_context.yaml` exists and has non-empty `domain`, `year_scope.active`, and at least one token in `vocabulary.operational` or `vocabulary.reference` (catches friction #1).

On failure it prints a structured message and exits non-zero so the autonomous prompt stops immediately:

```text
FAIL[PREFLIGHT_DOMAIN_EMPTY]: domain_context.yaml has empty "domain"
  → Action: Edit config/domain_context.yaml and set domain (e.g. "farm_management")
```

**File additions:**
- `scripts/preflight.py`
- `make preflight` target in `Makefile`

---

### Section 2 — Domain Context Population Enforcement

The profiler commands (`profile_cohort_corpus` phase 1) will check the loaded `DomainContext`. If vocabulary lists are empty, the command exits with:

```text
FAIL[PROFILER_EMPTY_VOCABULARY]: Domain context vocabulary is empty
  → Action: Populate vocabulary.operational / vocabulary.reference in domain_context.yaml
     and re-run phase 1.
```

This prevents the silent “first-alphabetical tab wins” behaviour observed when no operational/reference tokens are available for tab scoring.

**File changes:**
- `profiler/management/commands/profile_cohort_corpus.py`
- `profiler/tools/domain_context.py` — add helper `has_meaningful_vocabulary()`

---

### Section 3 — Scaffold Guardrails

`scaffold_workbook_schema` gains three validation rules that cause **hard failures** instead of emitting broken YAML.

#### 3.1 Null `model_name` guard
After `_build_cohort_contract`, every table must have a non-empty `model_name`. Tables derived from duplicate tabs (same title across year workbooks) without a unique slug are rejected with a message naming the duplicate tab title.

```text
FAIL[SCAFFOLD_NULL_MODEL_NAME]: Tab "Final Report" produced empty model_name
  → Action: Deduplicate the tab across year workbooks or set a unique suggested_model_name
  (File: build/schema-contract.yaml, Table: ?, Field: model_name)
```

#### 3.2 Pivot-table detection
If a tab’s column headers are >50 % numeric strings (e.g. “1”, “6”, “7”), the scaffold fails with:

```text
FAIL[SCAFFOLD_PIVOT_TABLE]: Tab "Irrigation" appears to be a pivot table (numeric headers: 1, 6, 7, ...)
  → Action: Add it to vocabulary.derived or exclude it from the corpus config.
```

#### 3.3 Invalid identifier pre-check
Before writing the contract, every `suggested_field_name` and `model_name` is checked with `str.isidentifier()` and `keyword.iskeyword()`. If any fail, the scaffold lists the offending names and exits.

```text
FAIL[SCAFFOLD_INVALID_IDENTIFIER]: Field name "201_unit" is not a valid Python identifier
  → Action: Rename the source column header or add a column alias in the bundle config.
  (Table: unit, Field: 201_unit)
```

**File changes:**
- `workbook/management/commands/scaffold_workbook_schema.py`
- `workbook/field_mapping.py` — add `is_valid_python_identifier(name)` helper

---

### Section 4 — Contract Validation Enhancement

The existing `wb validate contract` (and `make validate-contract`) is enhanced with a **strict mode** (`--strict`) that adds identifier-level checks on top of the current structural checks.

Strict checks:
- No `model_name` is null or empty.
- Every `suggested_field_name` is a valid Python identifier and not a keyword.
- No duplicate `model_name` values exist across tables.
- No `suggested_field_name` starts with a digit.

If validation fails, the autonomous prompt stops before `make generate-models` is invoked, preventing the chicken-and-egg loop where a broken contract breaks generation.

```text
FAIL[VALIDATE_DUPLICATE_MODEL]: Duplicate model_name "FinalReport" (2 tables)
  → Action: Merge the duplicate tables or give them distinct model_name values.
```

**File changes:**
- `workbook/management/commands/validate_contract.py`
- `workbook/codegen/contract.py` — add strict helpers
- `deployment/wb_cli.py` — pass `--strict` through `wb validate contract`

---

### Section 5 — Identifier Sanitization in Generation (Defense in Depth)

`generate_models`’s `render_field` already uses `to_python_identifier` from `python_render.py`. We tighten this so that if the contract validator was bypassed, the generator still emits valid Python — but it logs a loud warning for every sanitized identifier, making the issue visible in CI logs.

```text
WARNING[GEN_SANITIZED_FIELD]: Field "201_unit" sanitized to "f_201_unit" in model "Unit"
  → Action: Fix the source column name in the contract and re-generate.
```

**File changes:**
- `workbook/codegen/python_render.py` — add warning emission in `render_field`
- `workbook/codegen/model_generator.py` — propagate warnings to stdout

---

### Section 6 — Scaffold vs Generate Clarity

Eliminate the confusion between `scaffold_workbook_schema --models-stub-out` and `make generate-models`.

- Update `AUTONOMOUS_RUN_PROMPT.md`:
  - `scaffold_workbook_schema` produces the **contract YAML** only.
  - `make generate-models` reads the contract and writes `models_auto.py`.
  - The stub is never required for Django to load.
- Add a comment block at the top of generated `models_auto.py`:
  ```python
  # Generated by: wb generate models
  # Source contract: build/schema-contract.yaml
  # Do not edit directly — edit the contract and re-run make generate-models
  ```

**File changes:**
- `AUTONOMOUS_RUN_PROMPT.md`
- `workbook/codegen/python_render.py` — `render_import_block`

---

### Section 7 — AUTONOMOUS_RUN_PROMPT.md Redesign

Restructure the prompt into explicit phases with gates. Each phase’s shell block is preceded by a **Gate** comment explaining what failure looks like and what the operator should do.

```markdown
## Phase 0: Pre-Flight
```bash
make install          # idempotent; runs first
scripts/preflight.py  # fails fast with actionable messages
```

## Phase 1: Orient
...

## Phase 2: Profiling
...

## Phase 3: Schema Contract
```bash
make scaffold-contract  # stops on pivot/duplicate/identifier errors
make validate-contract CONTRACT=build/schema-contract.yaml  # strict gate
```

## Phase 4: Code Generation
...
```

**File changes:**
- `AUTONOMOUS_RUN_PROMPT.md`

---

### Section 8 — Error Message Contract

All new validation failures follow a common format so the autonomous runner (or a human) can parse them:

```text
FAIL[<check_id>]: <human message>
  → Action: <what to do>
  (File: <path>, Table: <name>, Field: <name>)
```

Check-ID registry (new IDs):

| ID | Owner | Meaning |
|----|-------|---------|
| `PREFLIGHT_DOMAIN_EMPTY` | `scripts/preflight.py` | `domain_context.yaml` missing `domain` |
| `PREFLIGHT_VENV_MISSING` | `scripts/preflight.py` | `.venv` not found |
| `PREFLIGHT_WB_NOT_FOUND` | `scripts/preflight.py` | `wb` CLI not on PATH or in `.venv/bin` |
| `PROFILER_EMPTY_VOCABULARY` | `profile_cohort_corpus` | No operational/reference tokens |
| `SCAFFOLD_NULL_MODEL_NAME` | `scaffold_workbook_schema` | Empty `model_name` after dedup |
| `SCAFFOLD_PIVOT_TABLE` | `scaffold_workbook_schema` | Numeric headers > 50 % |
| `SCAFFOLD_INVALID_IDENTIFIER` | `scaffold_workbook_schema` | Field/model name not a valid identifier |
| `VALIDATE_DUPLICATE_MODEL` | `validate_contract` | Duplicate `model_name` across tables |
| `VALIDATE_INVALID_FIELD_NAME` | `validate_contract` | Field name not a valid identifier |
| `GEN_SANITIZED_FIELD` | `generate_models` | Identifier was auto-sanitized |

---

## Testing Plan

1. **Unit tests** for each new check in the app’s `tests/` directory:
   - `profiler/tests/test_domain_context.py` — `has_meaningful_vocabulary()`
   - `workbook/tests/test_scaffold_workbook_schema.py` — pivot table, null model_name, invalid identifier guards
   - `workbook/tests/test_validate_contract.py` — strict-mode duplicate / identifier checks
   - `scripts/tests/test_preflight.py` — environment gate checks
2. **Integration test** via `make chassis-gate` smoke path:
   - The existing smoke contract in `chassis-gate` already exercises `scaffold_workbook_schema` → `validate_contract` → `generate_models`. After these changes it must still pass.
3. **Manual verification** by running the autonomous prompt against an empty domain context and confirming it stops at `PREFLIGHT_DOMAIN_EMPTY`.

---

## Rollout / Backwards Compatibility

- `scripts/preflight.py` is additive; existing workflows that do not call it are unchanged.
- `scaffold_workbook_schema` guardrails are **breaking** for downstream repos that currently rely on silent bad-data handling. Because `migration-workbench` is on `0.x` semver, breaking changes are acceptable. Downstream repos can pin an older version if they need the old permissive behaviour.
- `validate_contract --strict` is additive; the default behaviour remains unchanged unless `--strict` is passed. The autonomous prompt will pass `--strict`.
- `generate_models` warnings are additive and do not change exit codes.

---

## Files to Modify

| File | Section |
|------|---------|
| `scripts/preflight.py` | 1 (new) |
| `Makefile` | 1, 4 |
| `profiler/management/commands/profile_cohort_corpus.py` | 2 |
| `profiler/tools/domain_context.py` | 2 |
| `workbook/management/commands/scaffold_workbook_schema.py` | 3 |
| `workbook/field_mapping.py` | 3 |
| `workbook/management/commands/validate_contract.py` | 4 |
| `workbook/codegen/contract.py` | 4 |
| `deployment/wb_cli.py` | 4 |
| `workbook/codegen/python_render.py` | 5, 6 |
| `workbook/codegen/model_generator.py` | 5 |
| `AUTONOMOUS_RUN_PROMPT.md` | 6, 7 |
| `profiler/tests/test_domain_context.py` | Testing (new or extend) |
| `workbook/tests/test_scaffold_workbook_schema.py` | Testing (new or extend) |
| `workbook/tests/test_validate_contract.py` | Testing (new or extend) |
| `scripts/tests/test_preflight.py` | Testing (new) |

---

*Spec written and committed. Ready for implementation planning.*
