# 0.2.0 Sprint Plan: PipelineState & Interaction Contract Foundation

> **Sprint goal:** Build the runtime foundation for 0.2.0 while keeping the 0.1.0 farm path stable.  
> **Duration:** 2 weeks  
> **Team:** 4 parallel agents (1 per track)

---

## Context

The farm project has been scaffolded and the 0.1.0 pipeline is running on real data. The strategic design docs for 0.2.0 are written (`pipeline-state.md`, `interaction-contract.md`, `agent-harness.md`). This sprint implements the runtime skeleton that makes those designs executable without perturbing the existing artifact-based pipeline.

---

## Parallel Development Model

Each track is implemented in a **dedicated git worktree** under `.worktrees/`. This enables true parallel development without branch contention or working-directory conflicts.

### Worktree Layout

```
migration-workbench/                    (master branch — stable)
├── .worktrees/
│   ├── track-a-pipeline-state/      (branch: 0-2-0/track-a-pipeline-state)
│   ├── track-b-profiler-signals/     (branch: 0-2-0/track-b-profiler-signals)
│   ├── track-c-merge-tool/           (branch: 0-2-0/track-c-merge-tool)
│   └── track-d-confidence-scoring/   (branch: 0-2-0/track-d-confidence-scoring)
```

### Agent Workflow

1. **Setup:** Agent creates worktree and branch from latest master
2. **Implement:** Agent works in their worktree, committing to their branch
3. **Verify:** Agent runs `make chassis-gate` in their worktree
4. **Merge:** When done, branch is merged back to master via PR or direct merge

### Worktree Setup Commands (per track)

```bash
# From repo root
TRACK=track-a-pipeline-state
BRANCH=0-2-0/$TRACK

# Create branch and worktree
git branch $BRANCH master
git worktree add .worktrees/$TRACK $BRANCH

# Agent works in worktree
cd .worktrees/$TRACK

# When done, merge back
cd /home/teacher/projects/migration-workbench
git merge $BRANCH
```

### Isolation Rules

- **No cross-worktree file edits.** Each agent only touches files in their track's scope.
- **Shared read-only access.** Agents can read design docs and existing code from any worktree.
- **Merge conflicts resolved at integration.** If two tracks touch the same file, the integration owner resolves.
- **No force-push to shared branches.** Each agent owns their branch.

---

## Tracks

| Track | Focus | Week | Risk | Worktree |
|-------|-------|------|------|----------|
| [A: PipelineState Skeleton](track-a-pipeline-state.md) | Layered checkpoint dataclass + YAML load/save | 1 | Low | `.worktrees/track-a-pipeline-state/` |
| [B: Profiler Signals](track-b-profiler-signals.md) | Archetype classification + dependency graph | 1-2 | Medium | `.worktrees/track-b-profiler-signals/` |
| [C: Merge Tool](track-c-merge-tool.md) | Signals + human contract → codegen manifest | 2 | Medium | `.worktrees/track-c-merge-tool/` |
| [D: Confidence Scoring](track-d-confidence-scoring.md) | Add confidence to all heuristics | 1-2 | Low | `.worktrees/track-d-confidence-scoring/` |

---

## Dependencies

```
Track A ──→ wraps existing run_cohort_corpus() (no new deps)
Track B ──→ depends on existing structure.json format (stable)
Track C ──→ depends on Track B (needs signals format) + existing merge_discovery_notes
Track D ──→ no deps; additive to existing heuristics
```

**Cross-track dependency:** Track C depends on Track B's output format. Track C agent should read Track B's design doc but not block on implementation. If Track B's format changes, Track C adapts at merge time.

---

## Integration Gates

### Week 1 Gate
- PipelineState checkpoint loads/saves correctly
- Profiler signals command produces valid YAML
- Confidence scores are deterministic
- All existing tests pass (zero regressions)

### Week 2 Gate
- Merge tool produces correct codegen manifest
- `generate_admin` consumes new manifest format
- End-to-end round-trip: structure.json → signals → human contract → codegen manifest → admin.py
- All existing tests pass; new tests cover merge semantics

### Final Gate
- `make chassis-gate` — zero failures
- Farm profiling with PipelineState checkpoint — checkpoint is reviewable YAML
- Makefile targets still route to real commands

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| PipelineState checkpoint grows too large | Raw grid data stays external; checkpoint only metadata |
| Archetype classification is wrong for farm tabs | Confidence score flags low-certainty; human override always wins |
| Merge tool breaks existing view manifest flow | Backward-compatible: old `--manifest` path still works |
| Confidence scoring changes behavior | Default threshold 0.0 (no gating); explicit `--confidence-threshold` required |
| Worktree merge conflicts | Each track touches different files by design; integration owner resolves if needed |

---

## Definition of Done

1. All acceptance criteria met for all four tracks
2. `make chassis-gate` passes with zero failures in every worktree
3. All four branches merged to master with clean history
4. Documentation updated: `pipeline-state.md` and `interaction-contract.md` marked "implemented in 0.2.0"
5. Farm project can run `run_pipeline_state --phase discover --checkpoint build/pipeline-state.yaml` successfully
6. No breaking changes to 0.1.0 command surface
