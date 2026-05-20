# Autonomous Run Prompt: Execute End-to-End Pipeline

> **For agents working in a scaffolded product repo.** This prompt runs the migration-workbench pipeline based on current state. It checks what exists, runs the next appropriate phase, and reports progress.
>
> **Do not duplicate AGENTS.md content.** Use the Makefile commands directly. Only pause for human decisions at documented judgment points.

---

## Phase 0: Pre-Flight

```bash
# Gate: If any check fails, the script prints a FAIL[<id>] message and exits.
# Action: Follow the printed instructions and re-run this phase.
make install          # idempotent; creates venv if missing
scripts/preflight.py  # checks venv, wb CLI, and domain_context.yaml population
```

---

## Phase 1: Orient (if domain_context.yaml exists)

```bash
# Gate: validate-domain-context fails if the YAML is malformed.
make validate-domain-context DOMAIN_CONTEXT=config/domain_context.yaml

# If no drive tree yet, draft it (Makefile reads DRIVE_FOLDER_ID from .env;
# if missing, the target fails with a clear error.)
if [ ! -f data/profile_snapshots/drive_tree.json ]; then
    make profile-drive-folder
fi

# Extract workbook codes
make extract-workbook-codes DRIVE_TREE=data/profile_snapshots/drive_tree.json COHORT_CORPUS_CONFIG=config/cohort_corpus.json
```

---

## Phase 2: Profiling (if cohort_corpus.json configured)

```bash
# Gate: If domain vocabulary is empty, phase 1 fails with FAIL[PROFILER_EMPTY_VOCABULARY].
# Action: Populate vocabulary.operational / vocabulary.reference in domain_context.yaml.

# Run Phase 1: discovery + tab selection
make profile-cohort-corpus-phase1

# Phase 2: heuristic refinement (re-run without API calls)
make profile-cohort-corpus-phase2

# Phase 3: deep profiling
make profile-cohort-corpus-phase3
```

---

## Phase 3: Schema Contract (if profiler output exists)

```bash
# Gate: scaffold_workbook_schema fails if it detects:
#   - duplicate tabs producing empty model_name  (FAIL[SCAFFOLD_NULL_MODEL_NAME])
#   - pivot tables with numeric column headers    (FAIL[SCAFFOLD_PIVOT_TABLE])
#   - invalid Python identifiers in field names   (FAIL[SCAFFOLD_INVALID_IDENTIFIER])
# Action: Exclude bad tabs from the corpus config or fix source headers.

# If config/contract.yaml doesn't exist, scaffold from profiler output
if [ ! -f config/contract.yaml ]; then
    python manage.py scaffold_workbook_schema \
        --bundle-config config/bundle.json \
        --table-profile build/bundle/structure.json \
        --out config/contract.yaml
fi

# Gate: validate-contract --strict fails on duplicate models or bad identifiers.
# Action: Edit config/contract.yaml to fix the listed issues.
make validate-contract CONTRACT=config/contract.yaml STRICT=1
```

---

## Phase 4: Code Generation (if contract passes strict validation)

```bash
# scaffold_workbook_schema produces the contract YAML.
# make generate-models reads the contract and writes models_auto.py.
# The contract is the single source of truth; no stub is required.
make generate-models CONTRACT=config/contract.yaml OUT=backend/apps/core/models_auto.py
make generate-admin CONTRACT=config/contract.yaml OUT=backend/apps/core/admin_auto.py
make generate-import CONTRACT=config/contract.yaml OUT=backend/apps/core/imports.py
```

---

## Phase 5: Migration (if generated code exists)

```bash
make migrate
make check
```

---

## Phase 6: View Manifest (if bundle exists)

```bash
# Pull bundle if not exists
if [ ! -d build/bundle ]; then
    make pull-bundle SOURCE_CONFIG=config/bundle.json
fi

# Generate view manifest
make generate-view-manifest CONTRACT=config/contract.yaml
```

---

## Phase 7: Import

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