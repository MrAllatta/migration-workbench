# journal: farm-data-migration

Track B 0.8.7 — Import and reconcile real farm spreadsheet data.

## Status
Active.

## Branch
Workbench: `master` (farm changes on `farm/main`, workbench changes only if needed).
Farm: direct commits to `main`.

## Log

### 2026-07-13 — Booted
- Brief written based on existing `build/bundle/` (121 CSVs, 11 MB).
- Initial dry-run: `import_core build/bundle --dry-run` → 26,854 rows
  processed, 674 FieldEvent errors, all `stale_fk` for crop names.
- Root cause: 30 crop names in `harvest_pack/harvest_list_*.csv` do not
  match canonical names in `reference/crop_info.csv`.

### 2026-07-13 — Slice 1: Crop alias resolution

- Created `config/crop_aliases.csv` mapping 30 harvest-list crop names to
  canonical Crop records from `reference/crop_info.csv`.
- Added `_load_crop_aliases`, `_resolve_crop_name`, and
  `_get_or_create_crop_by_alias` to `imports_auto.py`.
- Wired into `_import_storage_crop` and `_import_harvest_forecast_2023`.
- **674 stale_fk errors → 0** in live import mode.
- 4 new unit tests for alias resolution.

### 2026-07-13 — Slice 2: Reconciliation tests

- `test_crop_aliases.py`: 4 unit tests for alias loading and resolution.
- `test_import_reconciliation.py`: 2 real-data integration tests:
  - Validate-only completes without crash.
  - Key models (Crop, FieldBlock, SalesPlan, FieldEvent, etc.) have
    expected minimum row counts.
- Live import produces 0 errors with alias resolution.
- Dry-run reveals 362 expected errors (placeholder crops not yet in DB).

## Next

- Final verification: run `make chassis-gate`, release v0.8.7.
