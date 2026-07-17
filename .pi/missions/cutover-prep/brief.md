# brief: cutover-prep (Joint, 0.9.4)

## Context

`cutover` (1.0.0) is the moment both product teams stop using their
tabular systems and start using the generated Django apps as their system
of record:

- **Vizcarra Guitars** stops using their Coda doc.
- **farm** stops using their Google Sheets spreadsheet.

Before that can happen safely, every readiness gate must be checked for
both engagements and a runbook must exist for each. This mission is the
final validation and planning gate. It does **not** switch either team; it
proves both apps are ready to replace their tabular systems and documents
exactly how the switches will happen.

## Goal

Run a dry-run cutover end-to-end on both engagements: import all in-scope
data, run all generated UI tests, verify formula parity (Vizcarra) and
data migration (farm), and produce a signed-off runbook for each. Earn the
go/no-go decision for 1.0.0.

## Preconditions (all shipped)

### Track A — Vizcarra (Coda engagement)
- `vizcarra-generated-ui` (0.8.1): views generated and tested.
- `vizcarra-people-type` (0.8.2): users mapped.
- `vizcarra-formula-parity` (0.8.3): critical formulas validated.
- `vizcarra-import-pipeline` (0.8.4): repeatable, reconciled import.

### Track B — farm (Sheets engagement)
- `farm-behavioral-codegen` (0.8.5): views from MWBS spec.
- `farm-workflow-coverage` (0.8.6): manifest → views.
- `farm-data-migration` (0.8.7): real bundle import, 0 errors.

## Repos

- **vizcarra-guitars**: direct commits to `main`.
- **farm**: direct commits to `main`.
- **migration-workbench**: only if codegen gaps surface.

## Scope

### In-scope

1. **Readiness checklist (both engagements)**
   - Data: all in-scope tables imported and reconciled.
   - Users (Vizcarra): all Coda people have Django accounts; roles documented.
   - UI: generated views load and display real data; no broken URLs.
   - Business logic:
     - Vizcarra: formula parity tests pass on real records.
     - farm: data migration tests show 0 errors against real bundle.
   - Backup: each tabular system can be exported/read-only before switch.

2. **Dry-run cutover (both engagements)**
   - Run the import pipeline on a fresh database.
   - Run the full test suite.
   - Smoke-test every generated view with real data.
   - Record timings and any warnings.

3. **Runbook (one per engagement)**
   - Exact cutover steps:
     1. Notify team.
     2. Export tabular system to read-only archive.
     3. Final data import.
     4. Validate reconciliation.
     5. Switch login/landing page.
     6. Post-cutover smoke tests.
   - Rollback plan.

4. **Go/no-go decision record**
   - Open questions / risks from prior missions.
   - Decision: ready for 1.0.0 or need more patches.

### Out-of-scope
- Actually switching either team (that's 1.0.0).
- Production hosting changes (assumed in place from earlier deploy).
- New feature development.

## Success Criteria

- [ ] Readiness checklist complete and green for **both** engagements.
- [ ] Dry-run cutover succeeds end-to-end for **both** engagements.
- [ ] Two runbooks written and reviewed.
- [ ] Go/no-go decision recorded.
- [ ] vizcarra-guitars full test suite passes.
- [ ] farm full test suite passes.
- [ ] Workbench `make chassis-gate` green.
- [ ] Merge to workbench master, tag v0.9.4.

## Earns

0.9.4 — Cutover readiness proven and documented for both engagements.
The teams have signed-off runbooks and green dry-runs, satisfying all
preconditions for 1.0.0.
