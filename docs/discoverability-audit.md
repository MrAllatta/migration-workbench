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
| IMPORTER-SETUP-001 | `importer/base.py` | missing data directory | 3 | Message + action |

## Adding a new entry

When you add or refactor an error site:
1. Pick the next sequential `check_id` in the app's namespace.
2. Ensure the message includes: what failed, valid values (if applicable), and a concrete action.
3. Update this table.