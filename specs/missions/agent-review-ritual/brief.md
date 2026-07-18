# brief: agent-review-ritual

Data engineer feedback on the migration-workbench architecture.
Source: simulated data engineer review, 2026-07-17.

## Context

The workbench is maintained by one human plus an AI agent. The agent writes
code, runs tests, makes commits. The human owns the roadmap. `make
chassis-gate` is the mechanical quality gate (tests pass, lint clean,
docstrings at 80%).

But mechanical gates don't catch:
- Specification drift (agent changed the test to match the code).
- Behavioral changes (refactor that subtly alters semantics).
- Trade-off decisions (agent chose approach A over B without documenting
  why).
- Missing requirements (agent implemented what was asked, not what was
  needed).

The agent's output volume will eventually exceed a human's review capacity.
Without a structured review ritual, the human becomes a bottleneck or —
worse — a rubber stamp.

The existing `receiving-code-review` and `requesting-code-review` skills
are a start, but they're optional. The review ritual needs to be wired
into the workflow, not a best-effort add-on.

## Goal

Design an agent review ritual that:
1. Produces a review artifact for every significant change.
2. Captures what changed, what didn't, what assumptions were made, and
   what was explicitly not changed.
3. Detects specification drift (test-of-tests or test-of-requirements).
4. Makes the human's review efficient (structured output, not raw diff).
5. Accumulates review patterns across sessions (what kinds of issues
   recur?).

This is a process design mission, not a code mission. The output is a
documented ritual and the tooling to support it.

## Scope

### In-scope
- Review artifact format: what goes into the artifact (diff summary,
  test results, assumption log, decision record).
- Specification drift detection: mechanism to verify that test changes
  are intentional and not drift (e.g., snapshot comparison, requirement
  traceability matrix).
- Review workflow: when does the human review? Before merge? After gate
  passes? Both?
- Review tooling: management commands or CLI subcommands that produce
  the review artifact.
- Recurring issue tracking: pattern log that accumulates across sessions
  (e.g., "agent frequently misses edge cases in FK resolution").

### Out-of-scope
- Changing the agent's autonomy model (that's a human decision).
- Implementing a code review UI (terminal-based artifacts only).
- Modifying the chassis-gate (that stays mechanical).
- Agent self-review (the agent reviews its own work; that's circular).

## Success Criteria
- [ ] A review ritual document exists describing the step-by-step process.
- [ ] `wb review-artifact --since <commit>` produces a structured artifact
      listing: files changed, tests added/modified/removed, assumptions
      made, decisions recorded, requirements traced.
- [ ] Snapshot comparison detects when a test was modified (not just added)
      and flags it for human review.
- [ ] The review artifact is consumable in <5 minutes for a typical change
      (not a wall of text).
- [ ] A recurring-issue log exists with at least 3 entries from past sessions
      (retroactive analysis of recent commits).

## Constraints
- Must not slow down the agent's development loop (review is post-hoc,
  not blocking).
- Must work with the existing commit style (conventional commits).
- Must not require new dependencies (use existing tooling).
- The ritual must be documented in `docs/contributing.md` or a new
  `docs/review-ritual.md`.

## Reference
- Agent harness: `docs/agent-harness.md`
- Contributing guide: `docs/contributing.md`
- Chassis gate: `Makefile` (`chassis-gate` target)
- Commit conventions: `AGENTS.md` (conventional commits)
- Existing review skills: `receiving-code-review`, `requesting-code-review`
- Portfolio/journal: `.pi/` directory

## Open Questions
1. Should the review artifact be per-commit or per-PR (per branch)?
   The solo-operator model means PRs are rare; per-commit may be more
   practical.
2. How should specification drift be detected without a formal
   requirements document? The brief is the closest thing, but it's
   not machine-readable.
3. Should the recurring-issue log be in `.pi/journal.md`, a separate
   file, or part of the portfolio?
4. Is "test-of-tests" feasible, or is it overkill for a solo-operator
   project? Snapshot testing (`make check-snapshots`) already covers
   codegen output — does that suffice?

## Related Feedback
> "Who watches the watcher? If the agent is running the gate and the
> agent wrote the tests, you need a way to detect specification drift —
> cases where the agent changed the test to match the code instead of
> the other way around."
>
> "Every significant change should produce a review artifact: what was
> the before, what's the after, what assumptions were made, what was
> explicitly not changed. The human reviews that artifact, not the code."
