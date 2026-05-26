# Track A: PipelineState Skeleton

> **Goal:** Implement the `PipelineState` dataclass and checkpoint machinery as a non-invasive wrapper around the existing artifact-based pipeline.  
> **Duration:** Week 1  
> **Risk:** Low  
> **Worktree:** `.worktrees/track-a-pipeline-state/`  
> **Branch:** `0-2-0/track-a-pipeline-state`

---

## Worktree Setup

```bash
# From repo root
git branch 0-2-0/track-a-pipeline-state master
git worktree add .worktrees/track-a-pipeline-state 0-2-0/track-a-pipeline-state
cd .worktrees/track-a-pipeline-state
```

**Agent rules:** Only touch files listed in this track. Do not edit files in other tracks' scopes. Commit to `0-2-0/track-a-pipeline-state` branch only.

---

## Context

The profiler currently scatters state across date-stamped JSON artifacts. The `PipelineState` design doc (`docs/pipeline-state.md`) defines a layered checkpoint model. This track implements the runtime skeleton without replacing the existing `run_cohort_corpus()` function — it wraps it.

---

## Files

**New:**
- `profiler/tools/pipeline_state.py` — `PipelineState` dataclass, `DiscoveryState`, `DomainKnowledge`
- `profiler/management/commands/run_pipeline_state.py` — Management command wrapper
- `profiler/tests/test_pipeline_state.py` — Unit + integration tests

**Modified:**
- `profiler/tools/cohort_corpus.py` — Add `save_checkpoint()` calls at phase boundaries (behind feature flag)

---

## Design Decisions

1. **Checkpoint file is `build/pipeline-state.yaml`.** External artifacts referenced via `_artifact` keys. Raw grid data never inlined.
2. **Storage backend is YAML for now.** SQLite migration is a future optimization, not this track.
3. **Resume logic stays in `run_cohort_corpus()`.** PipelineState wraps the existing function; replacement is a future track.
4. **The checkpoint is human-reviewable.** A consultant opens it between phases, edits `approved_tabs`, and resumes.

---

## Acceptance Criteria

- [ ] `PipelineState.load("build/pipeline-state.yaml")` parses a checkpoint with discovery + domain_knowledge layers
- [ ] `state.save_checkpoint("build/pipeline-state.yaml")` writes a checkpoint readable by `load()`
- [ ] Checkpoint contains `_artifact` references, not inline grid data
- [ ] `run_pipeline_state --phase discover --checkpoint build/pipeline-state.yaml` runs Phase 0/1 and saves checkpoint
- [ ] `run_pipeline_state --phase score_and_select --checkpoint build/pipeline-state.yaml` loads checkpoint, runs Phase 2, saves updated checkpoint
- [ ] Test: load → modify `approved_tabs` → save → reload preserves modification
- [ ] Test: checkpoint without `domain_knowledge` loads successfully (backward-compatible)

---

## Tasks (Atomic)

### Task A1: Define dataclasses
**Where:** `profiler/tools/pipeline_state.py`  
**What:** Define `PipelineState`, `DiscoveryState`, `DomainKnowledge` dataclasses matching the spec in `docs/pipeline-state.md`.

```python
@dataclass
class DiscoveryState:
    source_tree: dict = field(default_factory=dict)
    workbook_index: list[dict] = field(default_factory=list)
    broad_inventory: list[dict] = field(default_factory=list)
    shortlist: list[dict] = field(default_factory=list)
    approved_tabs: dict[str, list[str]] = field(default_factory=dict)

@dataclass
class PipelineState:
    version: str = "0.2.0"
    discovery: DiscoveryState = field(default_factory=DiscoveryState)
    domain_knowledge: DomainKnowledge = field(default_factory=DomainKnowledge)
    schema_contract: dict | None = None
    interaction_contract: dict | None = None
```

**Verify:** Import succeeds, dataclass fields are accessible.

### Task A2: Implement YAML serialization
**Where:** `profiler/tools/pipeline_state.py`  
**What:** Implement `load()` and `save_checkpoint()` with `_artifact` reference resolution.

**Rules:**
- On save: fields with large data (inventory, shortlist) write `_artifact: "path/to/file.json"` instead of inline data
- On load: resolve `_artifact` paths to actual data; missing files = empty list
- Missing checkpoint file → return empty `PipelineState()`
- Corrupted checkpoint → raise `CommandError` with path and error details

**Verify:** Round-trip test: create state → save → load → compare.

### Task A3: Add management command
**Where:** `profiler/management/commands/run_pipeline_state.py`  
**What:** New management command with `--phase`, `--checkpoint`, `--config` arguments.

**Phases:**
- `discover` — Phase 0/1: calls `run_cohort_corpus` with `fresh` flag
- `score_and_select` — Phase 2: loads checkpoint, runs scoring, saves
- `deep_profile` — Phase 3: loads checkpoint, runs deep profile, saves
- `all` — Runs all phases sequentially

**Resume logic:**
- If checkpoint exists and phase is `discover`, skip discovery (use checkpoint)
- If checkpoint has `approved_tabs`, skip `score_and_select` (use checkpoint)

**Verify:** Run against example data, verify checkpoint file exists and is reviewable.

### Task A4: Wire into cohort_corpus
**Where:** `profiler/tools/cohort_corpus.py`  
**What:** Add optional `pipeline_state: PipelineState | None` parameter to `run_cohort_corpus()`. When provided, save checkpoint at phase boundaries instead of/in addition to JSON artifacts.

**Verify:** Existing tests pass with `pipeline_state=None` (default). Integration test passes with `pipeline_state=PipelineState()`.

### Task A5: Integration test
**Where:** `profiler/tests/test_pipeline_state.py`  
**What:** End-to-end test using example data.

```python
def test_pipeline_state_round_trip():
    state = PipelineState()
    state.discovery.approved_tabs = {"101": ["Crop Planner"]}
    state.save_checkpoint("/tmp/test-pipeline-state.yaml")
    loaded = PipelineState.load("/tmp/test-pipeline-state.yaml")
    assert loaded.discovery.approved_tabs == {"101": ["Crop Planner"]}
```

**Verify:** Test passes.

---

## Non-Goals (Out of Scope)

- Replacing `run_cohort_corpus()` with pure PipelineState methods
- SQLite backend migration
- Real-time checkpoint syncing during long-running phases
- GUI for checkpoint editing
