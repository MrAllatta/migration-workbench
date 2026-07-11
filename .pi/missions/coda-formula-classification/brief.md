# brief: coda-formula-classification

## Context
Track C (workbench platform). The Coda profiler now detects relation columns (`coda-relation-column-profiler`), but formula classification remains a gap. Coda formulas use named-object references (not cell coordinates like Sheets), and the current `scan_coda_formula_columns` command does not classify formulas into the taxonomy the workbench expects: `row_formula`, `expansion_formula`, `hybrid`.

In the Sheets profiler, `formula_dependency.py` uses the formula graph to tag columns by how they compute: row-level (per-row logic), expansion (spill/array logic), or hybrid. Without this taxonomy, the schema contract scaffolder cannot hint at computed fields versus stored fields, and the import pipeline cannot decide whether a column should be imported or derived.

## Goal
Add formula taxonomy parity for Coda. The `scan_coda_formula_columns` command (or equivalent Coda profiling step) should classify each formula column into `row_formula`, `expansion_formula`, `hybrid`, or `unknown`, and emit this classification into the profile JSON. The schema contract builder should consume the classification to decide whether a column is a candidate for a model field (imported) or a view-level computed value (derived).

## Repo
migration-workbench

## Starting State
- `connectors/coda_source.py` — CodaProvider, now with `extract_relation_columns()`
- `connectors/coda.py` — `scan_coda_formula_columns` exists but does not classify
- `profiler/tools/formula_dependency.py` — Sheets-only formula graph and taxonomy logic
- `profiler/management/commands/profile_coda_table.py` — emits profile JSON, now includes `relation_columns`
- 1610 tests pass; `make chassis-gate` is green
- Coda relation column support is on `master` (merged from `feat/coda-relation-column-profiler`)

## Scope
### In-scope
1. Parse Coda column metadata for `format.type == "formula"` and extract the formula string
2. Classify formula strings by pattern:
   - `row_formula` — per-row logic (e.g., `thisRow.Price * thisRow.Quantity`)
   - `expansion_formula` — table-wide or aggregation (e.g., `Table.Filter(...).Count()`)
   - `hybrid` — mixed references or conditional expansion
   - `unknown` — formula present but not parseable
3. Emit `formula_classifications[]` array in the Coda table profile JSON alongside `relation_columns`
4. Wire classification into `workbook/schema_contract.py` so that `row_formula` columns are treated as regular fields (importable) and `expansion_formula` columns are flagged as `computed: true` in the contract
5. Add tests in `connectors/tests/test_coda_provider.py` or `workbook/tests/test_schema_contract.py`

### Out-of-scope
- Full formula dependency graph (who references whom) — that is Sheets-level complexity
- Cross-doc formula resolution
- Canvas or button formula handling
- Admin or UI codegen changes

## Success Criteria
- [ ] `profile_coda_table` emits a `formula_classifications` array for tables with formula columns
- [ ] Each entry has: `column_name`, `formula_text` (truncated to 200 chars), `classification` (`row_formula` | `expansion_formula` | `hybrid` | `unknown`), `confidence` (`high` | `medium` | `low`)
- [ ] `scaffold_workbook_schema` treats `expansion_formula` columns as computed (not imported) and `row_formula` as normal fields
- [ ] `make chassis-gate` passes
- [ ] Existing Coda profile tests still pass

## Constraints
- Do NOT modify the Google Sheets profiler or formula dependency graph modules.
- Do NOT change the schema contract YAML format version.
- Do NOT commit to master. Work in a feature branch per AGENTS.md.
- Classification is heuristic. If uncertain, mark `classification: unknown`, `confidence: low`, and document the formula text so the human can decide at the judgment point.

## Reference
- Coda formula docs: https://help.coda.io/hc/en-us/articles/223425786-Formulas-in-Coda
- Sheets formula taxonomy in `profiler/tools/formula_dependency.py` — read for pattern inspiration, do not reuse code directly
- `connectors/coda_source.py` — `extract_relation_columns()` shows how to parse Coda column format blocks

## Next Brief (suggested)
`vizcarra-profile-clients` — Run the now-enhanced profiler on the Vizcarra Guitars Coda doc, verify relation columns and formula classifications are captured correctly, and produce a schema contract for review.
