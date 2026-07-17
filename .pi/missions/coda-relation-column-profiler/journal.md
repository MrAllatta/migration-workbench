# Journal: coda-relation-column-profiler

## 2026-07-10 — Session 1

### What was done
- Added `extract_relation_columns()` to `connectors/coda_source.py` — scans Coda API column format blocks and extracts `lookup`, `linked_relation`, and `person` column metadata with target table resolution.
- Updated `connectors/coda.py` — `shape_coda_table_structure()` now includes `relation_columns` in the structure output.
- Updated `profiler/management/commands/profile_coda_table.py` — `summarize_coda_table()` emits a `relation_columns` array in the profile JSON.
- Updated `workbook/schema_contract.py` — `build_contract()` consumes Coda relation columns and:
  - Upgrades lookup columns from `TextField` to `ForeignKey`
  - Resolves target model names from Coda's `format.table` metadata (PascalCase)
  - Falls back to `TODO_<ColumnName>` when the API does not expose the target table
  - Adds `fk_resolutions` entries to the contract table
- Added 5 connector tests for `extract_relation_columns` and `shape_coda_table_structure` with relations.
- Added 2 workbook tests for `build_contract` with Coda relation columns (resolved target and TODO fallback).
- Updated `.gitignore` to ignore `.pi/orchestration/session-logs/`.

### Files changed
- `connectors/coda_source.py` (+86 lines)
- `connectors/coda.py` (+3 lines)
- `profiler/management/commands/profile_coda_table.py` (+3 lines)
- `workbook/schema_contract.py` (+108 lines, -6 lines)
- `connectors/tests/test_coda_provider.py` (+77 lines)
- `workbook/tests/test_schema_contract.py` (+113 lines)
- `.gitignore` (+3 lines)

### Decisions made
- Target table resolution uses `_to_pascal_case()` on the normalised table name from Coda's `format.table` dict. If the resolved name matches another bundle tab's model name, it is used directly.
- Person columns are flagged as `person` relation type but are NOT upgraded to `ForeignKey` — they get a note saying "person_reference_not_resolved_to_fk". This preserves the human judgment point.
- Linked relations (bidirectional) are detected and marked `is_bidirectional: true`, with source table notes preserved.

### Gate result
- `make chassis-gate`: **1610 passed, 1 warning** ✅

### Blockers / Gaps
- None.
