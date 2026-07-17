# journal: cutover-prep

Joint 0.9.4 — Final readiness gate and runbooks before `cutover` (1.0.0).

## Status
Active.

## Branch
Workbench: `master` (this is a coordination mission, not a code mission).
vizcarra-guitars: direct commits to `main`.
farm: direct commits to `main`.

## Log

### 2026-07-13 — Booted
- Supersedes the old `vizcarra-cutover-prep` Track A brief — now joint
  for both Vizcarra and farm engagements.
- Both track-specific sequences (Vizcarra 0.8.1–0.8.4, farm 0.8.5–0.8.7)
  are shipped. All preconditions met.
- Roadmap defines 0.9.4 as the joint dry-run + runbook + go/no-go gate
  before 1.0.0 cutover.

## Next

1. Verify Vizcarra readiness — run full test suite, list generated views.
2. Verify farm readiness — run full test suite, list generated views.
3. Write two runbooks (one per engagement).
4. Record go/no-go decision.
5. Tag v0.9.4 on workbench.
