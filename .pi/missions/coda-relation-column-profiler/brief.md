# brief: coda-relation-column-profiler

## Context
Track C (workbench platform). Vizcarra Guitars is the second real engagement and the first Coda-sourced project. The Coda profiler (`connectors/coda.py`, `connectors/coda_source.py`) can list docs, tables, and rows, but it does not surface Coda's native relationship primitives. In a Coda doc, relation columns explicitly declare which table they point to — this is structurally richer than Google Sheets, where FKs must be inferred from cross-sheet formula references or text matching.

If the profiler does not extract relation metadata, the schema contract scaffolder will emit `CharField` or `TextField` for relation columns, and the human operator must manually upgrade them to `ForeignKey`. This undermines the accelerant value for Coda engagements.

## Goal
Extend the Coda profiling pipeline to detect and emit relation-column metadata, comparable to how the Sheets profiler's formula dependency graph suggests FK targets. The output should feed into `scaffold_workbook_schema` so that Coda-sourced contracts propose `ForeignKey` fields with resolved `to` targets where Coda's schema makes that possible.

## Repo
migration-workbench

## Starting State
- `connectors/coda_source.py` — CodaProvider, basic table/row reading
- `connectors/coda.py` — Coda doc/table profiling commands (`profile_coda_doc`, `profile_coda_table`, `scan_coda_formula_columns`)
- `profiler/tools/formula_dependency.py` — Sheets-only formula graph logic
- `profiler/tools/enrichment_utils.py` — enrichment functions for Sheets profiles, no Coda equivalent
- `workbook/tools/vertical_registry.py` — vertical template system, currently farm-only
- 1280+ tests pass; `make chassis-gate` is green

## Scope
### In-scope
1. Coda API `listColumns` response parsing: detect `format.type == "lookup"` and `format.type == "person"`
2. For lookup columns, extract `formula` or `displayColumn` metadata that reveals the target table
3. For person columns, note the column as a `PersonReference` type (not yet FK, but flagged)
4. For linked relations (bidirectional / reverse lookup), detect and record `related_table` + `related_column`
5. Profile output augmentation: add `relation_columns[]` array to the table profile JSON
6. Schema contract enrichment: wire `relation_columns` into `scaffold_workbook_schema` so that lookup columns emit `ForeignKey` with `to: TODO_<TargetModel>` (or resolved if table name maps cleanly)
7. Add/update tests in `connectors/tests/test_coda_provider.py` or `workbook/tests/`

### Out-of-scope
- Cross-doc sync table resolution (docs outside the current doc)
- Canvas or attachment column handling
- Bidirectional sync or two-way relation mutation
- Admin or UI codegen changes

## Success Criteria
- [x] `profile_coda_table` for a doc containing relation columns produces JSON with a `relation_columns` array
- [x] Each relation entry has: `column_name`, `column_type` (`lookup` | `linked_relation` | `person`), `target_table_name` (if known), `target_table_id` (if known), `is_bidirectional` (boolean)
- [x] `scaffold_workbook_schema` run on a Coda profile with relation columns emits `ForeignKey` fields for lookup columns, with `to` set to the PascalCase table name if resolvable, else `TODO_<TargetModel>`
- [x] `make chassis-gate` passes after changes
- [x] Existing Coda profile tests still pass (backward compatibility)

## Constraints
- Do NOT modify the Google Sheets profiler or formula dependency graph modules.
- Do NOT change the schema contract YAML format version.
- Do NOT commit to master. Work in a feature branch per AGENTS.md.
- If the Coda API does not expose target table names cleanly, document the limitation in the profile JSON's `notes` field rather than guessing.

## Reference
- Coda API column format types: `text`, `person`, `lookup`, `number`, `percent`, `currency`, `date`, `dateTime`, `time`, `duration`, `email`, `link`, `slider`, `scale`, `image`, `imageReference`, `attachments`, `button`, `checkbox`, `select`, `packObject`, `reaction`, `canvas`, `other`
- Coda relation docs: https://help.coda.io/hc/en-us/articles/39555878926861-Connect-tables-with-relation-columns
- Coda cross-doc docs: https://help.coda.io/hc/en-us/articles/39555763704461-Set-up-Cross-doc-sync-tables

## Next Brief (suggested)
`coda-formula-classification` — Coda formulas use named-object references (not cell coordinates). The current `scan_coda_formula_columns` command does not classify formulas into `row_formula`, `expansion_formula`, `hybrid` the way the Sheets profiler does. A follow-up brief should add formula taxonomy parity for Coda.
