# Vizcarra Guitars Cutover Runbook

> **Cutover:** Replace Coda doc with generated Django app as system of record.
> **Prepared:** 2026-07-13
> **Planned release:** 1.0.0

## Preconditions

- [ ] Readiness checklist green (see `build/_out/cutover-readiness.md`)
- [ ] All 81 tests pass on vizcarra-guitars `main`
- [ ] Workbench `make chassis-gate` green
- [ ] Team notified of cutover window (recommend Friday afternoon)

## Step 1: Export Coda to Read-Only Archive

```bash
cd /home/teacher/projects/vizcarra-guitars
source .env

# Pull latest data from Coda
make pull-bundle SOURCE_CONFIG=config/source_config.json BUNDLE_OUTPUT_DIR=build/bundle-final

# Verify data matches earlier runs
python backend/manage.py import_domain build/bundle-final --validate-only

# Archive the Coda export
tar czf build/coda-archive-$(date +%Y%m%d).tgz build/bundle-final/
```

**Success check:** Archive file created, validate-only reports 0 errors.

## Step 2: Final Data Import

```bash
# Run the import against a fresh database (or truncate existing data)
python backend/manage.py import_domain build/bundle-final
```

**Success check:** `TOTALS: created=NNNN updated=0 skipped=0 error=0`

## Step 3: Validate Reconciliation

```bash
# Re-run validate-only to confirm
python backend/manage.py import_domain build/bundle-final --validate-only

# Run the full test suite
python -m pytest -q --tb=short
```

**Success check:** All 81 tests pass, 0 errors in validate-only.

## Step 4: Switch Landing Page

```bash
# Update the root URL conf to point at the generated app
# Edit backend/config/urls.py: uncomment the `domain/` include
# git commit the URL change
```

**Success check:** `curl http://localhost:8000/instruments/` returns 200.

## Step 5: Post-Cutover Smoke Tests

```bash
# Verify all non-admin URLs serve 200
python backend/manage.py smoke_tests

# Run full suite one more time
python -m pytest -q --tb=short
```

**Success check:** Smoke tests pass, full suite passes.

## Step 6: Notify Team

- Send notification that the app is live
- Coda doc is now read-only (point team to Django app)
- Schedule office-hours session for questions

## Rollback Plan

If something goes wrong within 24 hours:

```bash
# 1. Revert the URL change
git revert HEAD

# 2. Restore Coda doc access (if you changed permissions)
#    → Update Coda doc permissions back to editable

# 3. Notify team of rollback
```

**Rollback time estimate:** < 5 minutes (git revert + notification).

## Post-Cutover (Week 1)

- Monitor for data discrepancies
- Collect team feedback
- Consider resolving any remaining parity gaps
