# Journal: coda-formula-classification

## 2026-07-11 — Session 1

### What was done
- Mission capsule created from template.
- Brief written based on successor suggestion from `coda-relation-column-profiler`.
- **Plan phase exploration**: read current implementation of:
  - `connectors/coda_source.py` — `column_has_formula()`, `formula_text()`, `extract_relation_columns()`
  - `connectors/coda.py` — `shape_coda_table_structure()`
  - `profiler/management/commands/profile_coda_table.py` — `summarize_coda_table()`
  - `profiler/tools/formula_dependency.py` — Sheets-only cell-level graph builder (not reusable for Coda)
  - `workbook/schema_contract.py` — `build_contract()`, `index_table_profile()`
  - `connectors/tests/test_coda_provider.py` — existing test patterns
  - `workbook/tests/test_schema_contract.py` — existing contract test patterns

### Key findings
- Coda formulas are **column-level** (not cell-level like Sheets), so we classify per-column, not per-cell.
- `summarize_coda_table()` already emits `formula_columns` as `{name, formula_text}` but has no taxonomy.
- `build_contract()` already consumes `relation_columns` from `index_table_profile()`; we will extend the same pattern for `formula_classifications`.
- The Sheets `formula_dependency.py` is entirely cell-coordinate-based and uses networkx — not applicable to Coda's named-object formula language.

### Implementation plan (approved)
1. Add `classify_formula_columns()` to `connectors/coda_source.py` — heuristic classifier using regex patterns on formula text.
2. Wire `formula_classifications` into `shape_coda_table_structure()` in `connectors/coda.py`.
3. Wire `formula_classifications` into `summarize_coda_table()` in `profiler/management/commands/profile_coda_table.py`.
4. Update `index_table_profile()` in `workbook/schema_contract.py` to return formula classifications.
5. Update `build_contract()` to mark `expansion_formula` columns as `is_computed: true` with a note; leave `row_formula` as normal fields.
6. Add tests in `connectors/tests/test_coda_provider.py` and `workbook/tests/test_schema_contract.py`.

### Decisions made
- Heuristic classification rather than full AST parsing. Keeps scope bounded and avoids building a Coda formula parser.
- Confidence scoring (`high`/`medium`/`low`) so the human judgment point at schema contract review has signal.
- `expansion_formula` = table-wide / aggregation logic (contains `Filter`, `Count`, `Sum`, `Average`, `Max`, `Min`, `Lookup`, `Table.` without `thisRow`).
- `row_formula` = per-row logic (contains `thisRow`, simple arithmetic, string ops without aggregation).
- `hybrid` = contains both patterns.
- `unknown` = formula present but no recognizable pattern.

## 2026-07-11 — Session 2

### What was done
- **Build phase**: implemented all 6 planned changes.
- Added `classify_formula_columns()` to `connectors/coda_source.py` with heuristic rules and confidence scoring.
- Wired `formula_classifications` into `shape_coda_table_structure()` in `connectors/coda.py`.
- Wired `formula_classifications` into `summarize_coda_table()` in `profiler/management/commands/profile_coda_table.py`.
- Updated `index_table_profile()` in `workbook/schema_contract.py` to return `formula_classifications` as fourth tuple element.
- Updated `build_contract()` to consume formula classifications: `expansion_formula` → `is_computed: true` + note; `row_formula`/`hybrid` → note only.
- Added 10 new tests:
  - 6 in `connectors/tests/test_coda_provider.py` (row, expansion, hybrid, unknown, skip non-formula, shape structure includes classifications)
  - 4 in `workbook/tests/test_schema_contract.py` (index_table_profile returns fcs, expansion → computed, row → note not computed, hybrid → note)

### Files changed
- `connectors/coda_source.py` (+55 lines)
- `connectors/coda.py` (+4 lines)
- `profiler/management/commands/profile_coda_table.py` (+4 lines)
- `workbook/schema_contract.py` (+26 lines, -1 line)
- `connectors/tests/test_coda_provider.py` (+58 lines)
- `workbook/tests/test_schema_contract.py` (+105 lines)

### Decisions made
- Kept `formula_columns` (simple name+text list) in profiler output alongside the new `formula_classifications` for backward compatibility.
- `index_table_profile()` now returns a 4-tuple instead of 3-tuple. This is a breaking change for direct callers, but `build_contract()` is the only consumer in the repo and was updated.
- Table-qualified references without `thisRow` are treated as expansion signals (e.g., `Table.Column` references).

### Gate result
- `make chassis-gate`: **1620 passed, 1 warning** ✅

### Blockers / Gaps
- None.

## 2026-07-11 — Session 3

### What was done
- Moved implementation from master to feature branch `feat/coda-formula-classification`.
- Re-ran `make chassis-gate` on the branch: 1620 passed.
- Squash-merged branch to master.
- Deleted feature branch.
- Updated `.pi/portfolio.md` to mark mission done.
- Deleted stale `feat/coda-relation-column-profiler` branch.

### Final master commits
- `0c90325` feat(connectors): classify Coda formulas into row/expansion/hybrid taxonomy
- `7ae7c02` docs: mark coda-formula-classification done in portfolio

### Gate result
- `make chassis-gate` on master: **1620 passed, 1 warning** ✅

### Blockers / Gaps
- None. Ready for version bump, changelog, tag, and release.
