# Story e06s04: Wire phases into a PipelineState checkpoint pattern

Epic: e06 — pipeline-state-decoupling
Split profiler/tools/pipeline_state.py into a thin PipelineState
checkpoint object plus phase modules under profiler/pipeline/phases/.

## Your job
Execute story e06s04. Work in small, tested steps.

## Tasks
1. Each phase reads from and writes to PipelineState
   Verify: `make chassis-gate`

## Constraints
- Work on the active feature branch, NOT on master.
- Run the verification command for each task before moving on.
- When the story is complete, update specs/execution-status.yaml:
  - Set active.epic_id to e06
  - Set active.story_id to e06s04
  - Set active.status to done
  - Set active.completed_at to the current ISO timestamp.
- Do NOT start another story in this session.
- Commit all changes to the worktree before marking the story done.
  Use a conventional commit message: `e06s04: <short description>`.
  Include `last-prompt.md` in the commit — it records the original intent.

Begin.