# Schema Design Loop

This loop keeps spreadsheet-driven importer work in product-owned configuration and schema docs, not ad hoc patches in importer internals.

## Loop Steps

1. **Profile**  
   Run `profile_tab` and `scan_formula_patterns` to capture sheet structure and formula behavior into `data/profile_snapshots/`.
2. **Observe**  
   Read profile output and identify entities, attributes, relations, and formula-derived semantics as they exist in sheets.
3. **Draft contract**  
   Update `docs/schema-contract.md` with entity sections that cite tab, header row, source columns, and formula skeletons.
4. **Decide per app**  
   For each app area, choose `lift`, `modify`, or `rebuild` using contract evidence.
5. **Author tab config**  
   Encode import mappings in `bundles/<tier>.yaml` (`required_headers`, `aliases`, `column_map`, `default_values`, `row_transforms`).
6. **Author importer**  
   Keep importer commands thin `BaseImportCommand` subclasses that delegate to configured tiers.
7. **Gate**  
   Run validate-only before apply; keep chassis and product gates green.
8. **Drift check**  
   Re-profile periodically and diff against checked-in snapshots; treat column/formula changes as explicit contract updates.

## Are We Patching?

Use this quick diagnostic when deciding where a change belongs.

- Changes in loop steps 4-6 are expected design work.
- Changes in `importer/*` command body logic are workbench-level changes and should be rare.
- If an importer bug fix requires code edits outside bundle config and thin importer subclasses, treat it as a smell and revisit the schema contract/config first.
