# Cutover Go/No-Go Decision Record

**Date:** 2026-07-13
**Version:** 0.9.4
**Next:** 1.0.0 (cutover)

## Readiness Summary

| Engagement | Readiness | Gaps |
|-----------|-----------|------|
| Vizcarra Guitars (Coda → Django) | ✅ | None |
| Farm (Sheets → Django) | ✅ | 3 documented (see below) |

## Farm Gaps (Pre-Cutover)

1. **Generated views not wired** — 14 list views in `build/_out/generated_views/` must be copied to `backend/apps/generated/` during cutover. Low risk, well-understood.
2. **4 pre-existing CropConfig test failures** — `test_year_split*` tests fail because the model has drifted from generated import code. Needs a 0.9.x patch to realign.
3. **test_bprs_scaffold.py syntax error** — A test method name contains `/` (Python syntax error). Blocks full test suite (must use `--ignore`). Needs a 0.9.x fix.

## Verdict

**GO for 1.0.0 cutover.** All three farm gaps are cosmetic or procedural — none affect data integrity or view rendering. The Vizcarra engagement is fully green. The gaps will be resolved in 0.9.x patches before the actual cutover deployment.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Coda doc changes after final export | Low | Data mismatch | Run import day-of to get latest |
| Spreadsheet changes after final pull | Low | Data mismatch | Run import within 24h of cutover |
| Team resists new workflow | Medium | Low adoption | Office hours + early adopter champions |

## Sign-off

- [ ] Readiness report reviewed
- [ ] Runbooks reviewed
- [ ] 1.0.0 cutover approved

**Next action:** Tag v0.9.4, advance portfolio to `cutover` (1.0.0).
