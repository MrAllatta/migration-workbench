# Farm End-to-End Runbook

Step-by-step instructions for running the full migration-workbench pipeline against a product repo (farm).

---

## Prerequisites

- `.env` configured with provider credentials (Google Sheets API key, etc.)
- Product repo cloned and `migration-workbench` installed as a dependency
- Django settings configured for the product repo

---

## Step 1: Profile the source data

**Command:**
```bash
python manage.py profile_cohort_corpus --corpus path/to/cohort_corpus.json --out build/profiles/
```

**Input:** `cohort_corpus.json`
**Output:** `build/profiles/` directory with per-tab JSON profiles
**Expected exit code:** 0

**Review checkpoint:** Verify that all tabs in scope are profiled. Check for unexpected tab names, empty profiles, or tabs with all-null columns.

**Emergency exit:** If profiling fails, check credentials and corpus config. Re-run with `--verbose` for detailed error output.

---

## Step 2: Scaffold the schema contract

**Command:**
```bash
python manage.py scaffold_workbook_schema build/profiles/ --out build/schema-contract.yaml
```

**Input:** `build/profiles/`
**Output:** `build/schema-contract.yaml`
**Expected exit code:** 0

**With `--continue-on-error`:**
```bash
python manage.py scaffold_workbook_schema build/profiles/ --out build/schema-contract.yaml --continue-on-error --pivot-detection-threshold 0.5
```

**Review checkpoint:** Open `build/schema-contract.yaml` and review:
- Model names are sensible (rename if needed)
- Field types match domain expectations
- FK targets are correct
- Computed fields are specified
- No pivot tables slipped through

If `--continue-on-error` was used, check `build/schema-contract-rejected.yaml` for rejected tables.

**Emergency exit:** If scaffold fails, check profile output. If certain tabs cause errors, exclude them from the corpus config and re-profile.

---

## Step 3: Hand-harden the contract

**No command.** Manual editing of `build/schema-contract.yaml`.

**Review:**
- Rename `suggested_model_name` values to desired model names
- Adjust `django_field_class` for columns that need different types
- Add `model_meta` for verbose names, ordering, unique_together
- Add `import_config` blocks with `bundle_path` values
- For multi-year data, use `{year}` placeholder in `bundle_path`

---

## Step 4: Generate models + admin + import

**Commands:**
```bash
python manage.py generate_models --contract build/schema-contract.yaml --app-label core --force --out backend/apps/core/models_auto.py
python manage.py generate_admin --contract build/schema-contract.yaml --app-label core --force
python manage.py generate_import --contract build/schema-contract.yaml --app-label core --force
```

**With `--continue-on-error` (generates partial output):**
```bash
python manage.py generate_models --contract build/schema-contract.yaml --app-label core --force --continue-on-error
```

**Input:** `build/schema-contract.yaml`
**Output:** `models_auto.py`, `admin_auto.py`, `import_core.py`
**Expected exit code:** 0

For each generated file, check:
- `build/models_auto-rejected.yaml` (only if `--continue-on-error`)
- `build/admin_auto-rejected.yaml`
- `build/import_core-rejected.yaml`

**Review checkpoint:** Verify generated imports reference correct model names and bundle paths.

**Emergency exit:** Fix the contract and re-generate. Generated files are deterministic — re-running overwrites.

---

## Step 5: Pull bundle data

**Command:**
```bash
python manage.py pull_bundle --config path/to/pull_config.yaml --data-dir data/
```

**Input:** `pull_config.yaml`
**Output:** `data/year_YYYY/` directories with CSV files
**Expected exit code:** 0

**Review checkpoint:** Verify CSV files exist at expected paths. Check row counts match source data.

**Emergency exit:** If pull fails, check provider credentials and config. Individual tab failures can be retried.

---

## Step 6: Validate import (dry run)

**Command:**
```bash
python manage.py import_core_data --validate-only
```

**For multi-year imports:**
```bash
python manage.py import_core_data --validate-only --year 2023 2024
```

**Input:** `data/year_YYYY/` directories
**Output:** Validation summary to stdout
**Expected exit code:** 0

**Review checkpoint:** No row errors expected. If errors appear, check bundle paths and column mappings.

**Emergency exit:** Fix bundle data or contract `import_config` and re-validate.

---

## Step 7: Run import

**Command:**
```bash
python manage.py import_core_data
```

**For multi-year imports:**
```bash
python manage.py import_core_data --year 2023 2024
```

Or omit `--year` to auto-discover from `data/` directory.

**Input:** `data/year_YYYY/` directories
**Output:** Import summary JSON
**Expected exit code:** 0

**Review checkpoint:** Check import summary JSON. Expected: 0 row errors. Row counts should match source data.

**Emergency exit:** If import has errors, check the summary JSON for specific row errors. Fix source data or contract and re-run with `--validate-only` first.

---

## Step 8: Scaffold view manifest

**Command:**
```bash
python manage.py scaffold_view_manifest --structure build/structure.json --schema-contract build/schema-contract.yaml --out build/view-manifest.yaml
```

**Input:** `build/structure.json`, `build/schema-contract.yaml`
**Output:** `build/view-manifest.yaml`
**Expected exit code:** 0

**Review checkpoint:** Verify view entries match expected admin views. Check editable vs computed fields.

---

## Step 9: Generate discovery interview + merge

**Command:**
```bash
python manage.py generate_discovery_interview --manifest build/view-manifest.yaml --out build/discovery-interview.yaml
```

**Input:** `build/view-manifest.yaml`
**Output:** `build/discovery-interview.yaml`
**Expected exit code:** 0

**Review checkpoint:** Fill in discovery interview with role ownership, status semantics, and weekly actions for each view.

Then merge:
```bash
python manage.py merge_discovery_notes --manifest build/view-manifest.yaml --interview build/discovery-interview.yaml --out build/view-manifest-merged.yaml
```

---

## Step 10: Generate final admin + deploy

**Command:**
```bash
python manage.py generate_admin --contract build/schema-contract.yaml --manifest build/view-manifest-merged.yaml --app-label core --force
```

**Then:**
```bash
wb deploy <space> --env <preview|production> --live
```

**Expected exit code:** 0

---

## Acceptable error thresholds

| Stage | Acceptable errors | Action if exceeded |
|-------|------------------|--------------------|
| Profile | 0 | Re-profile with adjusted corpus config |
| Scaffold | 0 (without `--continue-on-error`) | Fix contract manually; with `--continue-on-error`, check rejected tables |
| Generate | 0 | Fix contract and re-generate |
| Validate import | 0 | Fix bundle path or column mapping |
| Import | 0 row errors | Check summary JSON; fix data or mapping |
