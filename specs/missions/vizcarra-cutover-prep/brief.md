# brief: vizcarra-cutover-prep (Track A, 0.9.4)

## Context
`vizcarra-cutover` (1.0.0) is the moment the Vizcarra Guitars team stops
using their Coda doc and starts using the generated Django app as their
system of record. Before that can happen safely, every readiness gate must be
checked and a runbook must exist.

This mission is the final validation and planning gate. It does **not**
replace Coda yet; it proves the app is ready to replace Coda and documents
exactly how the switch will happen.

## Goal
Run a dry-run cutover end-to-end in vizcarra-guitars: import all in-scope
Coda data, run all generated UI tests, verify formula parity, verify user
mapping, and produce a signed-off runbook. Earn the go/no-go decision for
1.0.0.

## Repo
vizcarra-guitars (primary) + migration-workbench (only if codegen gaps
surface)

## Starting State
- `vizcarra-generated-ui` (0.8.1): views generated and tested.
- `vizcarra-people-type` (0.8.2): users mapped.
- `vizcarra-formula-parity` (0.8.3): critical formulas validated.
- `vizcarra-import-pipeline` (0.8.4): repeatable, reconciled import exists.
- All four prior missions merged and tagged.

## Scope

### In-scope
1. **Readiness checklist**
   - Data: all in-scope tables imported and reconciled.
   - Users: all Coda people have Django accounts; roles documented.
   - UI: generated views load and display real data; no broken URLs.
   - Business logic: formula parity tests pass.
   - Backup: Coda doc can be exported/read-only before switch.

2. **Dry-run cutover**
   - Run the import pipeline on a fresh database.
   - Run the full test suite.
   - Smoke-test every generated view with real data.
   - Record timings and any warnings.

3. **Runbook**
   - Document the exact cutover steps:
     1. Notify team.
     2. Export Coda to read-only archive.
     3. Final data import.
     4. Validate reconciliation.
     5. Switch DNS/login page.
     6. Post-cutover smoke tests.
   - Include rollback plan.

4. **Go/no-go decision record**
   - Open questions / risks from prior missions.
   - Decision: ready for 1.0.0 or need more patches.

### Out-of-scope
- Actually switching the team (that's 1.0.0).
- Production hosting changes (assumed already in place from earlier deploy).
- New feature development.

## Success Criteria
- [ ] Readiness checklist complete and green
- [ ] Dry-run cutover succeeds end-to-end
- [ ] Runbook written and reviewed
- [ ] Go/no-go decision recorded
- [ ] vizcarra-guitars full test suite passes
- [ ] Workbench `make chassis-gate` green
- [ ] Merge to master, tag v0.9.4

## Earns
0.9.4 — Cutover readiness proven and documented. The team has a signed-off
runbook and a green dry-run, satisfying all preconditions for 1.0.0.
