# brief: vizcarra-import-pipeline (Track A, 0.8.4)

## Context
Cutover (1.0.0) requires a **reliable, repeatable data migration** from Coda
to Django. Today, imports are run ad-hoc and may not be idempotent. If the
Vizcarra team is going to rely on the Django app, they must be confident that:

- All required Coda rows are imported.
- Re-running the import does not duplicate or corrupt data.
- Row counts and key totals reconcile with Coda.
- The import can be rehearsed safely before the final cutover.

This mission builds the import pipeline that the cutover runbook will use.

## Goal
Make the vizcarra-guitars import command idempotent, preflight-capable, and
reconcilable against Coda row counts and key totals. Prove it by running a
full import and validating counts against the real Coda doc.

## Repo
migration-workbench (BaseImportCommand improvements if needed) +
vizcarra-guitars (import command + reconciliation + tests)

## Starting State
- `import_domain.py` exists and can import the four migrated tables.
- Dry-run mode exists but may not be exhaustive.
- No systematic reconciliation against Coda totals.
- `vizcarra-formula-parity` (0.8.3) has validated critical computed fields.
- `vizcarra-people-type` (0.8.2) has mapped users.

## Scope

### In-scope
1. **Idempotent import**
   - Determine a stable natural key for each table (e.g., `Work Order ID`,
     `oldClient ID`, `instrument_id`).
   - Update existing rows on re-import instead of creating duplicates.
   - Log created/updated/skipped counts.

2. **Preflight / apply split**
   - `--dry-run` reports what would change without writing.
   - `--apply` executes the import.
   - Both modes produce a JSON summary compatible with the workbench
     importer summary format.

3. **Reconciliation report**
   - After apply, compare row counts per table against Coda source counts.
   - Compare key totals: number of Clients, open Work Orders, Instruments,
     total revenue (if formula parity allows).
   - Fail the command (exit non-zero) if reconciliation differs beyond a
     configurable tolerance.

4. **Scope discovery**
   - Document which Coda tables are in scope for 1.0.0 and which are
     out-of-scope (e.g., `Fret Placement`, `VGPO` if not day-to-day).
   - For in-scope tables not yet migrated, either migrate them here or file
     explicit follow-up missions.

5. **Real-data test**
   - Run full import against real Coda data.
   - Assert reconciliation passes for all in-scope tables.

### Out-of-scope
- Migrating every Coda table (only day-to-day tables).
- Scheduled/recurring sync (one-shot, repeatable import is the gate).
- Two-way sync back to Coda.

## Success Criteria
- [ ] Natural keys identified for each in-scope table
- [ ] Re-import does not duplicate records
- [ ] `--dry-run` and `--apply` produce JSON summaries
- [ ] Reconciliation report compares row counts and key totals to Coda
- [ ] Full real-data import passes reconciliation
- [ ] Workbench `make chassis-gate` green
- [ ] vizcarra-guitars tests pass
- [ ] Merge to master, tag v0.8.4

## Earns
0.8.4 — Repeatable, reconciled Coda→Django import pipeline; the data
migration process is trustworthy enough for cutover rehearsal.
