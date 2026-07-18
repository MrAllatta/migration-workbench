# brief: farm-data-migration

Track B 0.8.7 — Import and reconcile real farm spreadsheet data.

## Goal

Run the existing `import_core` management command against the real farm
bundle in `build/bundle/` (121 CSVs, 11 MB) and make it reconcile cleanly:
zero unresolved FK errors, CSV row counts match processed row counts, and
DB counts match expectations for every tier.

## Success criteria

1. `import_core build/bundle --dry-run` reports **0 errors**.
2. `import_core build/bundle --validate-only` reports **0 errors** and a
   summary JSON is produced.
3. Reconciliation: for each imported CSV the command compares source row
   count to `created + updated + skipped + error` and fails the command on
   mismatch (unless the mismatch is explained by duplicate collapsing).
4. A crop alias map resolves harvest-list crop names (e.g. `Cabbage`,
   `Tomato Cherry`) that do not exactly match `reference/crop_info.csv`
   canonical names.
5. Farm real-data tests assert the import command succeeds and that key
   model counts are non-zero / match expected CSV counts.
6. Workbench `make chassis-gate` remains green; farm test suite grows.

## Scope

**In scope:**
- Crop alias resolution for FieldEvent harvest imports.
- Reconciliation hook in `imports_auto.py` / `BaseImportCommand`.
- Summary JSON validation and test coverage.

**Out of scope:**
- Pulling new CSVs from Google Sheets (bundle already exists).
- Changing model schemas (no migrations unless unavoidable).
- Re-importing already-loaded operational data idempotently beyond what
  `update_or_create` already provides.

## Repos

- **farm**: direct commits to `main` (per `farm/AGENTS.md`).
- **migration-workbench**: if `BaseImportCommand` reconciliation hooks need
  extension, use a feature worktree.

## Test targets

- Farm: `backend/apps/core/tests/test_import_reconciliation.py` (new).
- Existing farm test suites must not regress.
