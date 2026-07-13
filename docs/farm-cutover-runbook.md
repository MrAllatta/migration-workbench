# Farm Cutover Runbook

> **Cutover:** Replace Google Sheets spreadsheet with generated Django views as system of record.
> **Prepared:** 2026-07-13
> **Planned release:** 1.0.0

## Preconditions

- [ ] Readiness checklist green (see `build/_out/cutover-readiness.md`)
- [ ] **Pre-cutover patches (0.9.x):**
  - [ ] Fix 4 pre-existing CropConfig test failures (model drift)
  - [ ] Fix `test_bprs_scaffold.py` syntax error
  - [ ] Wire generated list views into `generated/urls_auto.py`
- [ ] All 204+ tests pass on farm `main`
- [ ] Workbench `make chassis-gate` green
- [ ] Team notified of cutover window (recommend end-of-week)

## Step 1: Export Spreadsheet to Read-Only Archive

```bash
cd /home/teacher/projects/farm
source .env

# Pull latest from Google Sheets (requires Google API credentials)
make pull-bundle SOURCE_CONFIG=config/source_config.json BUNDLE_OUTPUT_DIR=build/bundle-final

# Verify data
python backend/manage.py import_core build/bundle-final --validate-only

# Archive
tar czf build/sheets-archive-$(date +%Y%m%d).tgz build/bundle-final/
```

**Success check:** Archive file created, validate-only reports 0 errors.

## Step 2: Wire Generated List Views

```bash
# Copy generated views from staging to the running app
cp build/_out/generated_views/views_auto.py backend/apps/generated/views_auto.py
cp build/_out/generated_views/urls_auto.py backend/apps/generated/urls_auto.py

# Or regenerate fresh with the bundle
python backend/manage.py generate_views \
  --contract config/contract.yaml \
  --out-dir build/_out/generated_views \
  --archetype-list-from-manifest config/view-manifest.yaml \
  --force
```

**Success check:** `generated/urls_auto.py` contains all 14 entity URL patterns.

## Step 3: Final Data Import

```bash
# Run the import
python backend/manage.py import_core build/bundle-final
```

**Success check:** `TOTALS: created=NNNN updated=0 skipped=0 error=0`

## Step 4: Validate

```bash
# Run full test suite
python -m pytest -q --ignore=backend/apps/core/tests/test_bprs_scaffold.py

# Run workforce-wide views (if platform supports smoke testing)
python backend/manage.py smoke_tests
```

**Success check:** All tests pass.

## Step 5: Switch Default Landing Page

```bash
# Update the root URL conf to prefer generated views over the spreadsheet
# Edit backend/config/urls.py: reorder app/ include

# Commit
git add -A
git commit -m "cutover: farm spreadsheet → generated Django views"
git tag v1.0.0
```

**Success check:** Farm team can access all data views via the Django app.

## Step 6: Notify Team

- Remove spreadsheet from daily-use rotation
- Point team to Django app URL
- Train any team members unfamiliar with the app
- Schedule office-hours for the first week

## Rollback Plan

If something goes wrong within 48 hours:

```bash
# 1. Revert git changes
git revert HEAD

# 2. Restore spreadsheet access (if permissions were changed)

# 3. Notify team of rollback
```

**Rollback time estimate:** < 5 minutes.

## Post-Cutover (Week 1-2)

- Monitor for data sync gaps
- Resolve any parity issues the team finds
- Move the spreadsheet to a read-only archive folder
- Celebrate 🎉
