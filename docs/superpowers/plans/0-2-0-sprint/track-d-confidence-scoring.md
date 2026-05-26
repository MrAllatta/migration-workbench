# Track D: Confidence Scoring

> **Goal:** Add confidence scores to all existing profiler and scaffold heuristics. No behavioral changes unless thresholds are explicitly tuned.  
> **Duration:** Week 1-2 (background, parallel with other tracks)  
> **Risk:** Low  
> **Worktree:** `.worktrees/track-d-confidence-scoring/`  
> **Branch:** `0-2-0/track-d-confidence-scoring`

---

## Worktree Setup

```bash
# From repo root
git branch 0-2-0/track-d-confidence-scoring master
git worktree add .worktrees/track-d-confidence-scoring 0-2-0/track-d-confidence-scoring
cd .worktrees/track-d-confidence-scoring
```

**Agent rules:** Only touch files listed in this track. Do not edit files in other tracks' scopes. Commit to `0-2-0/track-d-confidence-scoring` branch only.

---

## Context

The agent harness design (`docs/agent-harness.md`) defines a confidence taxonomy: autonomous (>0.90), alert (0.50–0.90), blocking (<0.50). This track adds confidence scoring to existing heuristics so the taxonomy has data to act on.

This is purely additive. No function changes its return type or behavior. Confidence is an additional field that downstream tools can use for gating or display.

---

## Files

**Modified:**
- `profiler/tools/cohort_corpus.py` — `score_tab()` returns confidence
- `workbook/view_manifest.py` — `_infer_status_field()` returns confidence
- `workbook/management/commands/scaffold_workbook_schema.py` — `_flag_fk_columns()`, `_flag_computed_fields()` return confidence

**New:**
- `profiler/tests/test_confidence_scoring.py` — Determinism + threshold tests

---

## Design Decisions

1. **Confidence is 0.0–1.0 float.** Higher = more certain.
2. **Default threshold is 0.0 (no gating).** Commands must explicitly pass `--confidence-threshold` to filter.
3. **Confidence formulas are deterministic.** Same input always produces same score.
4. **Confidence scores are additive metadata.** No existing function changes its primary output.

---

## Confidence Formulas

### score_tab() — Tab Scoring

**Signals:**
- Keyword match count (operational/reference/support tokens)
- Coverage bonus (appears in multiple years)
- Formula density penalty
- Row count appropriateness

**Formula:**
```python
confidence = (
    keyword_match_ratio * 0.4 +
    coverage_bonus * 0.3 +
    (1 - formula_density_penalty) * 0.2 +
    row_count_appropriateness * 0.1
)
```

Where:
- `keyword_match_ratio` = matched_keywords / total_keywords
- `coverage_bonus` = 1.0 if tab appears in >=2 active years, else 0.5
- `formula_density_penalty` = formula_cell_count / total_cells
- `row_count_appropriateness` = 1.0 if 10 < rows < 10000, else 0.5

### _infer_status_field() — Status Field Detection

**Signals:**
- Header name match (status/state/stage)
- Data validation presence
- Value distinctness

**Formula:**
```python
header_match = 1.0 if regex_matches else 0.0
data_validation = 1.0 if dv_type else 0.5
distinctness = min(1.0, distinct_values / 10)  # 10+ values = 1.0

confidence = header_match * 0.5 + data_validation * 0.3 + distinctness * 0.2
```

### _flag_fk_columns() — FK Detection

**Signals:**
- `_id` suffix (strong signal)
- Entity keyword match (moderate signal)
- Profiler enrichment (strongest signal)

**Formula:**
```python
if profiler_enrichment:
    confidence = 1.0
elif name.endswith("_id"):
    confidence = 0.9
elif name.lower() in ENTITY_KEYWORDS:
    confidence = 0.7
else:
    confidence = 0.0
```

### _flag_computed_fields() — Computed Field Detection

**Signals:**
- Formula pattern (row_formula, expansion_formula)
- `is_computed` flag from profiler enrichment

**Formula:**
```python
if is_computed:
    confidence = 1.0
elif pattern == "expansion_formula":
    confidence = 0.95
elif pattern == "row_formula":
    confidence = 0.9
else:
    confidence = 0.0
```

---

## CLI Integration

### --confidence-threshold Flag

Added to commands that use these heuristics:

```bash
python manage.py scaffold_workbook_schema \
  --bundle-config config.json \
  --confidence-threshold 0.85

python manage.py scaffold_view_manifest \
  --structure structure.json \
  --confidence-threshold 0.85
```

**Behavior:**
- `--confidence-threshold 0.85`: Only include heuristics with confidence >= 0.85
- Default (no flag): Include all heuristics, confidence is informational only

---

## Acceptance Criteria

- [ ] All heuristic functions return `(result, confidence)` tuple or add `confidence` field to result dict
- [ ] Default behavior unchanged (confidence scores are additive, not gatekeeping)
- [ ] `--confidence-threshold` CLI argument exists on `scaffold_workbook_schema` and `scaffold_view_manifest`
- [ ] Test: confidence scores are deterministic for same input
- [ ] Test: threshold 0.85 filters out low-confidence heuristics
- [ ] Test: threshold 0.0 includes all heuristics
- [ ] Test: confidence scores are monotonic (stronger signals → higher confidence)

---

## Tasks (Atomic)

### Task D1: score_tab() confidence
**Where:** `profiler/tools/cohort_corpus.py`  
**What:** Modify `score_tab()` to return `(score_dict, confidence)`.

**Implementation:**
1. Extract signals used in scoring
2. Apply confidence formula
3. Return confidence alongside existing score dict

**Verify:** Unit test with known tab data, verify confidence is deterministic.

### Task D2: _infer_status_field() confidence
**Where:** `workbook/view_manifest.py`  
**What:** Modify `_infer_status_field()` to return `(field_name, confidence)`.

**Implementation:**
1. Check header match, data validation, distinctness
2. Apply confidence formula
3. Return confidence alongside field name

**Verify:** Unit test with columns that have varying signal strength.

### Task D3: _flag_fk_columns() confidence
**Where:** `workbook/management/commands/scaffold_workbook_schema.py`  
**What:** Modify `_flag_fk_columns()` to add `confidence` field to column dict.

**Implementation:**
1. Check profiler enrichment, `_id` suffix, entity keywords
2. Apply confidence formula
3. Set `col["fk_confidence"] = confidence`

**Verify:** Unit test with columns of varying FK likelihood.

### Task D4: _flag_computed_fields() confidence
**Where:** `workbook/management/commands/scaffold_workbook_schema.py`  
**What:** Modify `_flag_computed_fields()` to add `confidence` field.

**Implementation:**
1. Check `is_computed` flag and formula pattern
2. Apply confidence formula
3. Set `computed[field]["confidence"] = confidence`

**Verify:** Unit test with columns of varying computed likelihood.

### Task D5: Add --confidence-threshold CLI arguments
**Where:** `workbook/management/commands/scaffold_workbook_schema.py` and `scaffold_view_manifest.py`  
**What:** Add `--confidence-threshold` argument to both commands.

**Behavior:**
- Default: 0.0 (include all)
- When > 0.0: Filter out heuristics with confidence < threshold
- Log filtered heuristics at INFO level

**Verify:** Test that threshold filters correctly.

### Task D6: Confidence determinism tests
**Where:** `profiler/tests/test_confidence_scoring.py` and `workbook/tests/`  
**What:** Tests for determinism and threshold behavior.

```python
def test_score_tab_confidence_determinism():
    tab = {"title": "Crop Planner", "columns": [...]}
    _, confidence1 = score_tab(tab, heuristics)
    _, confidence2 = score_tab(tab, heuristics)
    assert confidence1 == confidence2

def test_confidence_threshold_filters_low_confidence():
    columns = [
        {"suggested_field_name": "maybe_fk", "confidence": 0.3},
        {"suggested_field_name": "definitely_fk", "confidence": 0.95},
    ]
    filtered = apply_threshold(columns, threshold=0.85)
    assert len(filtered) == 1
    assert filtered[0]["suggested_field_name"] == "definitely_fk"
```

**Verify:** All tests pass.

---

## Non-Goals (Out of Scope)

- Machine learning for confidence calibration
- Confidence scores for non-heuristic decisions (e.g., human overrides)
- Real-time confidence updating
- Confidence visualization UI
