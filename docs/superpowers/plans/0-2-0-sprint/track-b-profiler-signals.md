# Track B: Profiler Signals

> **Goal:** Make `scaffold_view_manifest` emit the new profiler-signals format. Add archetype classification and dependency graph extraction from existing profiler metadata.  
> **Duration:** Week 1-2  
> **Risk:** Medium  
> **Worktree:** `.worktrees/track-b-profiler-signals/`  
> **Branch:** `0-2-0/track-b-profiler-signals`

---

## Worktree Setup

```bash
# From repo root
git branch 0-2-0/track-b-profiler-signals master
git worktree add .worktrees/track-b-profiler-signals 0-2-0/track-b-profiler-signals
cd .worktrees/track-b-profiler-signals
```

**Agent rules:** Only touch files listed in this track. Do not edit files in other tracks' scopes. Commit to `0-2-0/track-b-profiler-signals` branch only.

---

## Context

The interaction contract design (`docs/interaction-contract.md`) defines three layers: profiler signals (machine-generated), human interaction contract (operator-authored), and codegen manifest (derived merge). This track implements Layer 1: the profiler signals.

The profiler already extracts formula patterns, data validation types, cross-sheet refs, and null rates. These signals are sufficient to classify UI archetype (form/list/dashboard/reference) and build a dependency graph. No new API calls are needed.

---

## Files

**Modified:**
- `workbook/view_manifest.py` — `_build_view_entry()` gains archetype classification + confidence
- `workbook/view_manifest.py` — `_build_workflow_hints()` gains dependency graph
- `workbook/management/commands/scaffold_view_manifest.py` — Add `--signals-only` flag
- `workbook/tests/test_view_manifest.py` — New tests for archetype + graph

---

## Design Decisions

1. **Archetype classification uses existing profiler metadata.** Formula density, data validation columns, row count, cross-sheet refs — all already in `structure.json`.
2. **Confidence is 0.0–1.0 based on signal strength.** Strong convergence = high confidence; ambiguous signals = low confidence (triggers human review in the agent harness).
3. **Dependency graph built from `cross_sheet_refs` across all tabs.** Already extracted by profiler; just needs cross-tab aggregation.
4. **Backward-compatible:** Without `--signals-only`, output remains `view-manifest-draft-1` format.

---

## Archetype Classification

### Signals Used

| Signal | Source in structure.json | Meaning |
|--------|-------------------------|---------|
| `data_validation_columns` | `columns[].data_validation_type` | Dropdowns, ranges, constraints |
| `formula_density` | `formula_cell_count / total_cells` | Computed vs raw ratio |
| `row_count` | `dimensions.row_count` | Tab size |
| `cross_sheet_refs` | `columns[].cross_sheet_refs` | Upstream dependencies |
| `null_rates` | `columns[].null_rate` | Data completeness |
| `status_column` | Header matches `status/state/stage` + has data validation | Workflow state machine |

### Classification Rules

| Archetype | Primary Signals | Confidence Formula |
|-----------|----------------|-------------------|
| **form** | >3 data_validation columns, non_null_rate >0.8, formula_density <0.05 | `min(1.0, (dv_count/5)*0.4 + (1-formula_density)*0.3 + non_null_rate*0.3)` |
| **list** | 1-3 data_validation columns, moderate null rate (0.2-0.6), status column present | `min(1.0, (dv_count/3)*0.3 + (1-null_rate)*0.3 + status_present*0.4)` |
| **dashboard** | formula_density >0.5, expansion_formula present, merged_spans >2 | `min(1.0, formula_density*0.4 + expansion_present*0.3 + merged_spans/5*0.3)` |
| **reference** | row_count <50, uniqueness >0.9, formula_density <0.01, glossary match | `min(1.0, (1-row_count/50)*0.3 + uniqueness*0.3 + (1-formula_density)*0.2 + glossary_match*0.2)` |

### Confidence Thresholds

- `confidence >= 0.90`: Autonomous — agent classifies without human review
- `0.50 <= confidence < 0.90`: Alert — flags for consultant confirmation
- `confidence < 0.50`: Blocking — consultant must decide

---

## Dependency Graph

### Edge Extraction

For each tab, examine `columns[].cross_sheet_refs`:

```python
for col in columns:
    for ref in col.get("cross_sheet_refs", []):
        edges.append({
            "from": current_tab_title,
            "to": ref["target_tab"],
            "ref_type": ref["ref_type"],  # VLOOKUP, IMPORTRANGE, SUM_range, etc.
            "column": col["header_label"],
        })
```

### Graph Structure

```yaml
workflow_graph:
  tabs:
    CropPlanner: {archetype: form, role_owner: null}
    HarvestRecord: {archetype: list, role_owner: null}
  edges:
    - from: CropPlanner
      to: HarvestRecord
      ref_type: VLOOKUP
      column: Crop
```

---

## Acceptance Criteria

- [ ] `scaffold_view_manifest --signals-only` produces `profiler-signals-1` format YAML
- [ ] Each view entry has `signals.ui_archetype` with `confidence` 0.0–1.0
- [ ] Dependency graph lists all cross-sheet refs as edges with `ref_type`
- [ ] Without `--signals-only`, output remains backward-compatible `view-manifest-draft-1`
- [ ] Test: archetype classification matches expected for all four archetypes
- [ ] Test: confidence scores are deterministic for same input
- [ ] Test: dependency graph includes all cross-sheet refs, no duplicates

---

## Tasks (Atomic)

### Task B1: Archetype classification function
**Where:** `workbook/view_manifest.py`  
**What:** Add `_classify_archetype(tab: dict) -> tuple[str, float]`.

**Implementation:**
1. Extract signals from tab metadata (formula density, DV columns, null rates, etc.)
2. Score each archetype using classification rules above
3. Return `(winning_archetype, confidence)`

**Verify:** Unit test with synthetic tab data for each archetype.

### Task B2: Dependency graph builder
**Where:** `workbook/view_manifest.py`  
**What:** Add `_build_dependency_graph(tabs: list[dict]) -> dict`.

**Implementation:**
1. Iterate all tabs and their columns
2. Collect `cross_sheet_refs` into edges
3. Deduplicate edges by `(from, to, ref_type)`
4. Return graph dict with `tabs` and `edges` keys

**Verify:** Unit test with synthetic tabs containing cross-sheet refs.

### Task B3: Signals namespace in build_view_manifest
**Where:** `workbook/view_manifest.py`  
**What:** Extend `build_view_manifest()` to include `signals:` namespace when `include_signals=True`.

**Output format:**
```yaml
views:
  CropPlanner:
    signals:
      ui_archetype: form
      confidence: 0.87
      formula_density: 0.02
      data_validation_columns: [Crop, Quantity, Block]
      cross_sheet_refs:
        - target_tab: HarvestRecord
          ref_type: VLOOKUP
      null_rates:
        notes: 0.45
```

**Verify:** Output validates against expected schema.

### Task B4: Add --signals-only flag
**Where:** `workbook/management/commands/scaffold_view_manifest.py`  
**What:** Add `--signals-only` argument. When set, emit `profiler-signals-1` format instead of `view-manifest-draft-1`.

**Behavior:**
- `--signals-only` → output has `version: profiler-signals-1`, includes `signals` namespace, excludes `workflow_hints`
- Without flag → backward-compatible `view-manifest-draft-1`

**Verify:** Test both paths with same input, verify formats differ as expected.

### Task B5: Integration tests
**Where:** `workbook/tests/test_view_manifest.py`  
**What:** Comprehensive tests.

```python
def test_archetype_form_classification():
    tab = {"columns": [...], "formula_density": 0.02, ...}
    archetype, confidence = _classify_archetype(tab)
    assert archetype == "form"
    assert confidence >= 0.85

def test_archetype_dashboard_classification():
    tab = {"columns": [...], "formula_density": 0.78, ...}
    archetype, confidence = _classify_archetype(tab)
    assert archetype == "dashboard"
    assert confidence >= 0.85

def test_dependency_graph_extraction():
    tabs = [...]
    graph = _build_dependency_graph(tabs)
    assert len(graph["edges"]) == expected_count
    assert graph["edges"][0]["ref_type"] in ("VLOOKUP", "IMPORTRANGE", "SUM_range")
```

**Verify:** All tests pass.

---

## Non-Goals (Out of Scope)

- Adding new profiler API calls to collect more signals
- Machine learning for archetype classification (rules-based only)
- Real-time signal updating during profiling
- Role boundary inference (human provides this in interaction contract)
