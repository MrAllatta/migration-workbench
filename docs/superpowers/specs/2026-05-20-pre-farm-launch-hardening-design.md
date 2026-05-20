# Design: Pre-farm Launch Hardening — Comprehensive Profiler & Agent Bridge

**Date:** 2026-05-20  
**Approach:** Comprehensive (Approach 3)  
**Status:** Approved  
**Scope:** migration-workbench profiler, scaffold, and autonomous agent integration  

---

## 1. Background

The farm product test is intended to exercise the full migration-workbench pipeline toward v1.0. The recent `domain_context` / Phase 0 orientation feature (commits `09779a1` through `28af6cd`) introduced a critical deduplication bug and left the autonomous agent unable to self-configure between Phase 0 (orient) and Phase 1 (discovery). This spec hardens every layer before the live end-to-end run.

## 2. Goals

1. Fix all launch-blocking bugs in the profiler deduplication and enrichment paths.
2. Enable the autonomous agent to execute Phase 0 without human manual extraction.
3. Close every gap between scaffold instructions and executable commands.
4. Improve observability so operators (human or agent) can trace why tabs were included or excluded.
5. Add `--dry-run` preview capability to avoid expensive API calls during agent self-check.

## 3. Non-Goals

- NLP/ML parsing of raw notes (B3 uses naive keyword frequency only).
- Automatic contract/schema generation from domain context.
- Changes to importer, deployment, or workbook codegen logic.
- UI/admin visual changes.

## 4. Detailed Design

### 4.1 Critical Bug Fix — `deduplicate_index_records` (A1)

**Current behavior (buggy):**
- `deduplicate_index_records` groups by `workbook_code`, iterates over `approved_tabs[workbook_code]` tab titles, but index records lack `tab_title`.
- `max()` selects the latest record across the *entire workbook*, not per tab.
- Exception branch adds *all* workbook records, not just the exception tab.

**Fixed behavior:**
1. **Simplify `deduplicate_index_records`** to filter archived years only. Remove all tab-level logic from this function.
2. **Move tab-level deduplication into `run_cohort_corpus`** deep-profiling loop (around line 1509), where `record` and `tab_title` are both in scope.

**Pseudocode for deep-loop dedup:**

```python
latest_year_by_workbook = {}
for rec in index_records:
    wb = rec["workbook_code"]
    yr = rec.get("year") or 0
    if yr > latest_year_by_workbook.get(wb, 0):
        latest_year_by_workbook[wb] = yr

for record in index_records:
    wb = record["workbook_code"]
    yr = record.get("year") or 0
    for tab_title in approved_tabs.get(wb, []):
        if domain_context is not None:
            is_exception = domain_context.is_deduplication_exception(tab_title)
            if not is_exception and yr != latest_year_by_workbook.get(wb):
                continue
        # Proceed to deep profile
```

**Impact:** Tab-level deduplication now correctly respects per-tab exceptions and per-year filtering.

### 4.2 Autonomous Agent Bridge (B1-B4)

#### B1 — `extract_workbook_codes` Management Command

```bash
python manage.py extract_workbook_codes \
  --drive-tree data/profile_snapshots/drive_tree.json \
  --config config/cohort_corpus.json \
  [--update-config] \
  [--smoke]
```

- Reads `drive_tree.json` (output of `profile_drive_folder`).
- Applies `workbook_id_regex` from `cohort_corpus.json`.
- Prints sorted unique codes and count.
- `--update-config`: rewrites `in_scope_workbooks` in `cohort_corpus.json` in place. Uses `json.dump` with `indent=2` and `sort_keys=True` for stability. Any comments or custom key order in the original file are lost; a `.bak` copy is written alongside.
- `--smoke`: validates argument parsing and writes a smoke artifact.

#### B2 — `validate_domain_context` Management Command

```bash
python manage.py validate_domain_context \
  --config config/domain_context.yaml
```

Validates:
- `year_scope.active` is a list of integers.
- `year_scope.archived` and `forward` are lists of integers.
- `vocabulary` sub-keys (`operational`, `reference`, `support`, `derived`) are lists of strings.
- `deduplication.strategy` is `"latest_year"` or `"none"`.
- `glossary` is a mapping of strings to strings.

Warnings:
- `year_scope.active` is empty.
- `vocabulary` has no tokens.

Exit codes:
- `0` on valid.
- `1` on structural error.
- `2` on warning only (when `--strict`).

#### B3 — `draft_domain_context` Management Command

```bash
python manage.py draft_domain_context \
  --drive-tree data/profile_snapshots/drive_tree.json \
  [--raw-notes-dir data/raw_notes/] \
  [--out config/domain_context.yaml]
```

Heuristics:
1. Scan folder/file names for `\b(20\d{2})\b`.
   - Most recent 2 years (or fewer if only 1–2 exist) → `year_scope.active`
   - All remaining older years → `year_scope.archived`
   - `year_scope.forward` left empty (requires human judgment)
2. Extract workbook codes via regex → empty `entities` stubs per code.
3. If `--raw-notes-dir` provided:
   - Naive word frequency on `.md` and `.txt` files.
   - Cross-reference against a small built-in starter keyword list (`planting`, `harvest`, `variety`, `crop`, `order`, `inventory`, `price`, `index`, `summary`, `pivot`, `rollup`).
   - Populate `vocabulary` with top 5 hits per category (operational, reference, support, derived).
4. Output YAML with `_documentation` header and comment `generated: draft — review required`.

#### B4 — `make orient` Target and Sub-targets

New Makefile targets in `workbook/makefile_targets.py`:

```makefile
draft-domain-context:
	$(MANAGE) draft_domain_context \
	  --drive-tree "$${DRIVE_FOLDER_OUT:-data/profile_snapshots/drive_tree.json}" \
	  --out config/domain_context.yaml

validate-domain-context:
	$(MANAGE) validate_domain_context --config config/domain_context.yaml

extract-workbook-codes:
	$(MANAGE) extract_workbook_codes \
	  --drive-tree "$${DRIVE_FOLDER_OUT:-data/profile_snapshots/drive_tree.json}" \
	  --config config/cohort_corpus.json \
	  --update-config

orient: validate-domain-context profile-drive-folder extract-workbook-codes
```

The `orient` target chains validation, drive folder profiling, and code extraction into one operator-facing step.

### 4.3 Scaffold & Workflow Integration (C1-C3)

#### C1 — Chassis Gate Additions

Add to root `Makefile` `chassis-gate` target after existing profiler smoke tests:

```makefile
	# Domain context integration smoke
	DB_ENGINE=sqlite $(MANAGE) validate_domain_context --config example_data/domain_context.example.yaml
	DB_ENGINE=sqlite $(MANAGE) draft_domain_context --drive-tree example_data/drive_tree.example.json --smoke
	DB_ENGINE=sqlite $(MANAGE) extract_workbook_codes --drive-tree example_data/drive_tree.example.json --config example_data/cohort_corpus.example.json --smoke
```

Also add `example_data/drive_tree.example.json` (a minimal synthetic tree) and verify existing `example_data/domain_context.example.yaml` passes validation.

#### C2 — AGENTS.md Template Updates

Replace the static Phase 0 paragraph in `scripts/new_product.py` (`render_agents_md`) with an executable checklist:

```markdown
#### Phase 0 — Orient

Run these commands in order. Each is safe to re-run.

1. **Draft domain context** (optional seed from drive tree):
   ```bash
   make draft-domain-context
   ```
2. **Edit** `config/domain_context.yaml` — set year scope, vocabulary, glossary.
3. **Validate** the domain context file:
   ```bash
   make validate-domain-context
   ```
4. **Profile the drive folder**:
   ```bash
   make profile-drive-folder
   ```
5. **Extract workbook codes** into `config/cohort_corpus.json`:
   ```bash
   make extract-workbook-codes
   ```
6. Review `config/cohort_corpus.json` — adjust heuristics before Phase 1.
```

#### C3 — `domain_context.example.yaml` Improvements

Update `example_data/domain_context.example.yaml`:

```yaml
_documentation:
  domain: "Short slug for the business domain"
  year_scope.active: "Years to profile in full (list of ints)"
  deduplication.strategy: "latest_year | none"
  deduplication.exceptions: "Tabs that should be profiled across all years"

domain: ""
description: ""

year_scope:
  active: []
  archived: []
  forward: []

deduplication:
  strategy: latest_year
  exceptions:
    - tab_title: "Sales Actuals"
      reason: "Structure changes yearly; profile all years"

entities: []

vocabulary:
  operational: []
  reference: []
  support: []
  derived: []

glossary: {}

scope_notes: ""
```

### 4.4 Observability & Operator Experience (D1-D3, E1-E2)

#### D1 — Deduplication Trace in Artifacts

The dedup trace is appended to `deep_profile_coverage_<date>.json` after the deep-profiling loop completes (the trace is only knowable after the loop runs):

```json
{
  "job_count": 12,
  "success_count": 12,
  "failure_count": 0,
  "results": [...],
  "dedup_trace": {
    "402": {
      "latest_year": 2026,
      "profiled_all_years": ["Sales Actuals"],
      "profiled_latest_only": ["Crop Planner", "Harvest Log"]
    }
  }
}
```

This is computed as the loop iterates: for each `(workbook_code, tab_title)`, record whether the current year was the latest or an exception.

#### D2 — Coverage Bonus Normalization

Change legacy mode (no domain context) in `select_tabs_from_inventory` from `>=3` years to `>=2` years, matching domain-context mode.

```python
# Legacy mode (domain_context is None)
coverage_bonus = 1 if len(bucket["years"]) >= 2 else 0
```

Rationale: consistency and utility. `>=2` years is the more useful threshold for identifying stable tabs.

#### D3 — `known_tabs` Population in Full Mode

Currently `known_tabs` is only populated when `resume_from_tab_selection=True`. In full mode, `inventory_rows` is freshly generated from broad coverage. Populate `known_tabs` from it unconditionally:

```python
for inventory_row in broad_payload.get("inventory_rows", []):
    known_tabs.add((inventory_row["spreadsheet_id"], inventory_row["tab_title"]))
```

This ensures the year-aware tab skip at line 1513 works in all modes, avoiding wasted API calls for tabs that don't exist in a given year's workbook.

#### E1 — Glossary Expansion Substring Safety

In `score_tab`, replace string concatenation with set-based matching:

```python
match_texts = {lowered}
if domain_context is not None and domain_context.glossary:
    title_expansions = glossary_expand(lowered, domain_context.glossary)
    if title_expansions:
        match_texts.update(title_expansions)
```

Then check token membership against the set rather than substring of a concatenated string:

```python
for token in tokens:
    if any(_token_match(token, text, match_mode) for text in match_texts):
        # ...
```

This prevents false substring matches across expansion boundaries.

### 4.5 `--dry-run` Mode for `profile_cohort_corpus`

New CLI flag for `profile_cohort_corpus`:

```bash
python manage.py profile_cohort_corpus \
  --config config/cohort_corpus.json \
  --out-dir data/profile_snapshots/cohort_corpus \
  --dry-run
```

Behavior by mode:

| Mode | `--dry-run` Behavior |
|------|---------------------|
| Full (no resume) | Walks Drive, counts workbooks/tabs, validates domain context, estimates API calls, prints preview, exits 0. No Sheets grid fetches. No deep writes. |
| `resume_from_broad` | Reads broad coverage, previews tab selection and estimated deep jobs, exits 0. |
| `resume_from_tab_selection` | Reads tab selection, counts deep jobs that would run, previews known_tab skips, exits 0. |

Output format: JSON to stdout or `--dry-run-out` with keys:
- `mode`: `"dry_run"`
- `estimated_api_calls`: int
- `estimated_deep_jobs`: int
- `workbooks`: list of `{code, year_list, tab_count}` where `year_list` is sorted unique years
- `warnings`: list of strings

## 5. Testing Strategy

| Component | Test Type | Location |
|-----------|-----------|----------|
| `deduplicate_index_records` simplification | Unit | `profiler/tests/test_domain_context.py` |
| Deep-loop dedup logic | Unit | `profiler/tests/test_cohort_corpus_tools.py` |
| `extract_workbook_codes` | Unit + CLI smoke | New: `profiler/tests/test_extract_workbook_codes.py` |
| `validate_domain_context` | Unit + CLI smoke | New: `profiler/tests/test_validate_domain_context.py` |
| `draft_domain_context` | Unit + CLI smoke | New: `profiler/tests/test_draft_domain_context.py` |
| `--dry-run` | Integration (mocked services) | `profiler/tests/test_cohort_corpus_tools.py` |
| Chassis gate additions | Integration | `Makefile` |
| AGENTS.md rendering | Snapshot | `scripts/tests/test_new_product.py` (if exists) or manual review |

All new tests must pass with `pytest -x` and `ruff check`.

## 6. Rollout & Verification

1. Implement in feature branch `feat/pre-farm-hardening`.
2. Run `make chassis-gate` locally.
3. Run `make new-product PRODUCT=farm-test` and exercise `make orient` on a real Drive folder.
4. Merge to `master` after green CI.
5. Cut v0.9.4 with changelog entry documenting all changes.
6. Update farm product repo's `pyproject.toml` lower bound to `>=0.9.4`.

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| `deduplicate_index_records` refactor breaks existing tests | Update all test expectations; add new deep-loop dedup tests |
| `--update-config` corrupts user JSON | Use `json.dump` with `indent=2`, sort keys for stability; back up original to `.bak` |
| `draft_domain_context` produces poor vocabulary suggestions | Label output as draft; agent instructions require human review |
| `--dry-run` output format changes later | Mark as experimental in docs; pin format version in JSON |

## 8. References

- `README.md` v0.9.3 roadmap (product test repo = farm)
- `profiler/tools/domain_context.py` (A1, D1, D2)
- `profiler/tools/cohort_corpus.py` (A1, D3, E1)
- `scripts/new_product.py` (C2)
- `example_data/domain_context.example.yaml` (C3)
- `workbook/makefile_targets.py` (B4)
