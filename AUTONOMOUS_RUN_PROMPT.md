# Autonomous Run Prompt: Execute End-to-End Pipeline

> **For agents working in a scaffolded product repo.** This prompt runs the migration-workbench pipeline based on current state. It checks what exists, runs the next appropriate phase, and reports progress.
>
> **Do not duplicate AGENTS.md content.** Use the Makefile commands directly. Only pause for human decisions at documented judgment points.

---

## Pre-Flight

```bash
# Verify environment is configured
make check-env || { echo "ERROR: .env not configured"; exit 1; }

# Verify Django can start (check for models_auto.py stub)
cd backend && .venv/bin/python manage.py check || { echo "ERROR: Django check failed — is models_auto.py missing?"; exit 1; }
cd ..
```

---

## State Machine: Run Next Phase

Execute the following checks and run the appropriate command for each phase:

### Phase 0: Orient (if domain_context.yaml exists)

```bash
# Validate domain context
make validate-domain-context DOMAIN_CONTEXT=config/domain_context.yaml

# If no drive tree yet, draft it (Makefile reads DRIVE_FOLDER_ID from .env;
# if missing, the target fails with a clear error.)
if [ ! -f data/profile_snapshots/drive_tree.json ]; then
    make profile-drive-folder
fi

# Extract workbook codes
make extract-workbook-codes DRIVE_TREE=data/profile_snapshots/drive_tree.json COHORT_CORPUS_CONFIG=config/cohort_corpus.json
```

### Phase 1-3: Profiling (if cohort_corpus.json configured)

```bash
# Run Phase 1: discovery + tab selection
make profile-cohort-corpus-phase1

# Phase 2: heuristic refinement (re-run without API calls)
make profile-cohort-corpus-phase2

# Phase 3: deep profiling
make profile-cohort-corpus-phase3
```

### Phase: Schema Contract (if profiler output exists)

```bash
# If config/contract.yaml doesn't exist, scaffold from profiler output
if [ ! -f config/contract.yaml ]; then
    python manage.py scaffold_workbook_schema \
        --bundle-config config/bundle.json \
        --table-profile build/bundle/structure.json \
        --out config/contract.yaml
fi

# Validate contract
make validate-contract CONTRACT=config/contract.yaml
```

### Phase: Code Generation (if contract exists)

```bash
# Generate models, admin, import
make generate-models CONTRACT=config/contract.yaml OUT=backend/apps/core/models_auto.py
make generate-admin CONTRACT=config/contract.yaml OUT=backend/apps/core/admin_auto.py
make generate-import CONTRACT=config/contract.yaml OUT=backend/apps/core/imports.py
```

### Phase: Migration (if generated code exists)

```bash
make migrate
make check
```

### Phase: View Manifest (if bundle exists)

```bash
# Pull bundle if not exists
if [ ! -d build/bundle ]; then
    make pull-bundle SOURCE_CONFIG=config/bundle.json
fi

# Generate view manifest
make generate-view-manifest CONTRACT=config/contract.yaml
```

### Phase: Import

```bash
# Preflight (validate-only)
make import-preflight IMPORT_DATA_DIR=build/bundle IMPORT_COMMAND=import_reference_example SUMMARY_JSON=build/preflight-summary.json

# Review SUMMARY_JSON — if errors > 0, stop and report to human

# Apply
make import-apply IMPORT_DATA_DIR=build/bundle IMPORT_COMMAND=import_reference_example SUMMARY_JSON=build/apply-summary.json
```

---

## Summary Report

After running, output a summary:

```
## Pipeline Status

| Phase | Status | Notes |
|-------|--------|-------|
| Pre-flight | ✅/❌ | |
| Orient | ✅/⏭️/❌ | domain_context.yaml exists: yes/no |
| Profiling | ✅/⏭️/❌ | cohort_corpus.json configured: yes/no |
| Schema Contract | ✅/⏭️/❌ | config/contract.yaml exists: yes/no |
| Code Gen | ✅/⏭️/❌ | models_auto.py populated: yes/no |
| Migration | ✅/⏭️/❌ | migrations applied: yes/no |
| View Manifest | ✅/⏭️/❌ | config/view-manifest.yaml exists: yes/no |
| Import | ✅/⏭️/❌ | build/bundle exists: yes/no |

## Human Decision Points Needed

- [ ] Review profiler output (Phase 1-3)
- [ ] Review schema contract draft
- [ ] Review generated code before migrating
- [ ] Review view manifest before admin regen
- [ ] Review import preflight summary
```

---

## End of Prompt