# journal: vizcarra-formula-parity

Track A 0.8.3 — Validate business-critical Coda formulas against generated
computed fields on real Vizcarra data.

## Status
Planned.

## Branch
`feat/vizcarra-formula-parity`

## Log

### 2026-07-12 — Designed
- Brief written: identify critical Work Orders formulas, generate computed
  fields, compare against Coda ground truth, real-data parity tests.
- Precondition: `vizcarra-people-type` (0.8.2) complete.

### 2026-07-12 — Booted
- `master` chassis-gate: 1747 passed, exit code 0.
- Worktree `../migration-workbench-vizcarra-formula-parity` created on branch `feat/vizcarra-formula-parity`.
- Portfolio marked Active: `vizcarra-formula-parity` (Track A, 0.8.3).

### 2026-07-13 — Implemented
- Pulled Work Orders bundle from Coda (552 rows, `value_format=simple`).
- Identified 7 business-critical formulas from the Work Orders table.
- Implemented 5 `compute_*` methods on the WorkOrders model:
  - `compute_taxable()` — `Home State is "NM" or ""` (100% parity)
  - `compute_paid()` — `Amount Due <= 0 AND Total != 0` (83% parity, 94 rows with manual overrides)
  - `compute_top_5()` — `Now Serving < 6` (100% parity)
  - `compute_tax()` — conditional tax_rate multiplication with $ parsing (100% parity)
  - `compute_total()` — subtotal + tax with $ parsing (100% parity)
- Added `_parse_decimal()` helper for Coda currency format strings.
- 17 unit tests for formula edge cases (nulls, boundaries, booleans).
- 6 real-data tests: 1 summary + 5 per-formula against all 552 rows.
- Remaining formulas deferred:
  - `Amount Due` — blocked by `total_paid` not being a model field on WorkOrders
  - `Labor Price` — needs duration parsing for `Labor Hours` (`"1 hr"`)
  - `Job Subtotal (before discounts)` — needs related-table joins
  - `Storage Fee` — needs duration parsing for `Length of Storage`
- vizcarra-guitars: 78 tests pass.
- Workbench: 1747 pass, chassis-gate green.
