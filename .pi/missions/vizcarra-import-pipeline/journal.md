# journal: vizcarra-import-pipeline

Track A 0.8.4 — Build a repeatable, reconciled Coda→Django import pipeline
for vizcarra-guitars.

## Status
Planned.

## Branch
`feat/vizcarra-import-pipeline`

## Log

### 2026-07-12 — Designed
- Brief written: idempotent import, preflight/apply split, reconciliation
  report, scope discovery, real-data validation.
- Precondition: `vizcarra-formula-parity` (0.8.3) complete.

### 2026-07-13 — Booted
- `master` chassis-gate: 1747 passed, exit code 0.
- Worktree `../migration-workbench-vizcarra-import-pipeline` created on branch `feat/vizcarra-import-pipeline`.
- Portfolio marked Active: `vizcarra-import-pipeline` (Track A, 0.8.4).

### 2026-07-13 — Implemented

**Import pipeline fixes:**
- Compound unique key `(first, last)` for Clients (was `first` only — 11 duplicates).
- `_prepare_row` nullifies FK string values; per-tier FK field set (ArchivedWorkOrders TextField fix).
- Date parsing tolerance (corrupted birthdays → None).
- `instrument_id` → `instrument_id_value` (WorkOrders FK bug).

**Tables imported (0 errors, 0 warnings):**
- Clients: 540 created + 27 updated = 567 rows ✅
- WorkOrders: 552 created ✅
- Instruments: 819 created ✅
- ArchivedWorkOrders: 294 created ✅

**Reconciliation:**
- Post-import CSV-vs-DB count check; exits 1 on mismatch.
- All 4 tables pass: 2232 records, 0 errors.

**Gates:**
- Workbench: 1747 passed.
- Vizcarra: 81 passed.
