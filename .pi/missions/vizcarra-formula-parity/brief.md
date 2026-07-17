# brief: vizcarra-formula-parity (Track A, 0.8.3)

## Context
Coda is full of business logic encoded as formulas. In the Work Orders table
alone there are formulas for `Amount Due`, `Paid?`, `Total`, `Tax`, `Labor
Price`, `Job Subtotal`, etc. These drive invoices, scheduling, and status.

The workbench already classifies Coda formulas (0.5.3) and emits computed
fields, but the classifications were unit-tested only. No one has proven that
the generated computed fields produce the **same numeric/text output as Coda**
for real Vizcarra records.

Before the team can rely on the Django app for billing and work-order status
(1.0.0), the business-critical formulas must match Coda output within the
product repo.

## Goal
Select the business-critical Coda formulas in the Work Orders table,
generate computed fields for them, import real Coda records, and assert that
the Django-computed values match the original Coda values.

## Repo
migration-workbench (computed-field codegen improvements if needed) +
vizcarra-guitars (formula selection, comparison tests, import command tweaks)

## Starting State
- Work Orders table has ~40 formulas; most are currently ignored or mapped
  to `TextField`.
- Formula classifier exists in workbench (0.5.3).
- Computed-field codegen exists but may not handle all Vizcarra formula
  shapes.
- Real Coda data is available via `import_domain`.

## Scope

### In-scope
1. **Identify critical formulas**
   - From the Coda doc profile, select formulas that affect day-to-day
     operations:
     - `Amount Due` = `Total - Total Paid`
     - `Paid?` = `And(Amount Due <= 0, Total != 0)`
     - `Total` = subtotal + tax
     - `Tax` and `Taxable?`
     - `Labor Price` = `[Labor Hours] * shop_rate * 24`
   - Document which formulas are in scope (others can be deferred).

2. **Computed field generation**
   - For each in-scope formula, ensure the schema contract represents it as
     a computed field.
   - Improve workbench computed-field codegen if the existing renderer fails
     on a Vizcarra formula shape.
   - Fallback: hand-write the computed expression in the product repo and
     document the gap.

3. **Coda export for ground truth**
   - Export a sample of real Work Orders rows with the original formula
     values from Coda (or use an existing Coda export artifact).
   - Store the ground-truth CSV/JSON in `vizcarra-guitars/build/_out/`.

4. **Parity tests**
   - Import the same rows into Django.
   - For each critical formula, assert Django-computed value == Coda value
     (or explain discrepancy).
   - Tests must exercise edge cases: zero totals, discounts, out-of-state tax.

### Out-of-scope
- Every formula in the doc (focus on business-critical ones).
- Live two-way sync with Coda.
- Charts/graphs produced by Coda formulas.

## Success Criteria
- [ ] Critical Work Orders formulas identified and documented
- [ ] Schema contract marks them as computed fields
- [ ] Generated models compute the fields correctly
- [ ] Ground-truth Coda export exists
- [ ] Parity tests pass against real Coda records
- [ ] Workbench `make chassis-gate` green
- [ ] vizcarra-guitars tests pass
- [ ] Merge to master, tag v0.8.3

## Earns
0.8.3 — Business-critical Coda formulas validated against real Vizcarra data;
generated computed fields produce the same results as Coda.
