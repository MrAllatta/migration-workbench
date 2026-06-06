# Ecosystem Protocol

**Status:** Living document
**Date:** 2026-06-03
**Audience:** Meta, Workbench, and Product agents
**Note:** Milestone labels revised 2026-06-05. The "app replaces spreadsheet" quality gate name is under review (issue #04). v0.2.0 is now "Admin generation maturity", v0.3.0 is "User-facing UI codegen", v0.4.0 is "Role-based interfaces", v0.5.0+ is "Consultant accelerant (platform)". This document uses the quality gate's current filename.

## Three-Agent Architecture

The migration-workbench ecosystem coordinates three agent types through a filesystem-based protocol. Each agent has a single, well-defined role and never crosses boundaries.

### Meta agent

Orchestrates from this checkout. Merges worktree features to `exercise`, signals product repos to validate, proposes squashes to human. Never switches branches.

### Workbench agent

Builds features in isolated worktrees (`git worktree add .worktrees/wt-<feature> exercise -b feat/<feature>`), runs `make chassis-gate`, writes `.omo/ready/<feature>.yaml`. Never merges.

### Product agent

Owns a product repo (e.g., farm). Consumes workbench as a PyPI dependency. Drives quality through an issue-driven hardening loop — no longer a passive validator of workbench features.

## Branch Model

```
worktrees ──merge to──▶ exercise ──squash to──▶ master
```

- Main checkout lives on `exercise` permanently. Never switch branches.
- Each feature gets a worktree branched from `exercise`: `git worktree add .worktrees/wt-<feature> exercise -b feat/<feature>`
- Meta merges completed worktrees into `exercise`. Workbench agents never merge.
- Human reviews squash proposal, then: `git branch -f exercise master` after squash.

## Queue Protocol (Farm-Led Hardening)

### Queue Semantics

| Queue | Writer → Reader | Purpose | Lifecycle |
|-------|----------------|---------|-----------|
| `.omo/next/<feature>.yaml` | Meta → Workbench | "Build or repair this feature" | created → active → consumed |
| `.omo/ready/<feature>.yaml` | Workbench → Meta | "Feature built, chassis-gate passed" | created → active → consumed |
| `.omo/exercise/<feature>.yaml` | Meta → Product | "New feature on exercise — integrate and validate" | created → active → consumed |
| `.omo/results/<feature>.yaml` | Product → Meta | "Ran smoke tests. PASS/FAIL on admin usability, not just command exit codes" | created → active → consumed |
| `.omo/issues/<NN>-<slug>.md` | Product → Meta | "Found concrete problem. Here's the error, expected behavior, and which design doc it violates" | created → active → consumed |
| `.omo/quality-gates/<milestone>.yaml` | Product → Human | "Deterministic test spec for milestone readiness. Product certifies go/nogo" | created → active → consumed |
| `.omo/proposals/squash-<milestone>.md` | Meta → Human | "All quality gates green. Proposed squash message." | created → active → consumed |

Product repos reach these files via the relative path `../migration-workbench/.omo/` (or `../platform/.omo/` through workspace symlinks).

## Queue Entry Lifecycle

Every queue entry follows a three-state lifecycle tracked via a ``lifecycle``
block in the entry YAML (or front matter for Markdown issues):

```
created ──▶ active ──▶ consumed
```

| State | Meaning | Set by |
|-------|---------|--------|
| ``created`` | Entry written to queue, not yet read | Writer |
| ``active`` | Entry has been read, processing in progress | Reader (via ``wb ecosystem ack --status active``) |
| ``consumed`` | Entry fully processed, resolved | Reader/consumer (via ``wb ecosystem ack``) |

### Lifecycle block format

```yaml
lifecycle:
  status: created           # created | active | consumed
  created_at: "2026-06-04T00:00:00Z"   # ISO 8601 UTC
  activated_at: null                    # populated on ack --status active
  consumed_at: null                     # populated on ack --status consumed
  actor: null                           # who changed the state
```

Entries written before this lifecycle requirement (v0.3.0 and earlier) are
backward-compatible — the reader assumes ``active`` status when no lifecycle
block is present.

### Validation gates

Before writing to any queue, call ``validate_queue_entry()`` to check:

- Required fields are present per queue type (see ``QUEUE_REQUIRED_FIELDS``)
- ``lifecycle.status`` is a valid value
- ``lifecycle.created_at`` is present for entries that include lifecycle

Malformed entries are rejected at write time, not discovered at read time.

### Staleness timeouts

If an entry remains ``created`` or ``active`` past its timeout, it is flagged
as stale by the health check:

| Queue | ``created`` timeout | ``active`` timeout |
|-------|---------------------|--------------------|
| ``next/`` | 72h (3d) | 168h (7d) |
| ``ready/`` | 72h (3d) | 168h (7d) |
| ``exercise/`` | 72h (3d) | 168h (7d) |
| ``results/`` | 168h (7d) | 336h (14d) |
| ``issues/`` | 336h (14d) | 672h (28d) |
| ``quality-gates/`` | 336h (14d) | 672h (28d) |
| ``proposals/`` | 72h (3d) | 168h (7d) |

Timeouts are configured in ``workbook/tools/queue_protocol.py``
(``DEFAULT_TIMEOUTS``).

### Health monitoring

Run ``wb ecosystem health`` to inspect all queues:

```bash
$ wb ecosystem health
next          created: 1
  Meta → Workbench: build or repair
  1 total
  Oldest unconsumed: v0.4.0-phase1-archetype-matrix.yaml (2.3h)

ready         empty
  Workbench → Meta: feature built, gate passed
  0 total

exercise      active: 1
  Meta → Product: integrate and validate
  1 total
...
```

Use ``--json`` for machine-readable output suitable for CI monitoring.

### Consumption acknowledgement

After processing a queue entry, the consumer acknowledges it:

```bash
wb ecosystem ack <queue> <filename>          # mark as consumed (default)
wb ecosystem ack <queue> <filename> --status active  # mark as active
```

For example, after a workbench agent completes a feature:

```bash
wb ecosystem ack next v0.4.0-phase1-archetype-matrix.yaml --status consumed
```

This updates the lifecycle block in-place. The file remains in the queue
directory (not moved to archive), allowing audit trail.

### Cross-queue consistency

The health check verifies:

- Every ``results/`` entry references a feature that has a corresponding
  ``exercise/`` signal. Results referencing unknown features are flagged.

### Farm-Led Hardening Loop

1. **Product generates admin** from workbench tools
2. **Product runs** "app replaces spreadsheet" smoke test suite
3. **If PASS:** product writes `.omo/results/<feature>.yaml` with `status: pass`
4. **If FAIL:** product writes structured issue to `.omo/issues/` with:
   - Exact error (stack trace, admin crash, wrong output)
   - Expected behavior (what should happen instead)
   - Design doc reference (which design doc this violates, e.g., `status-workflow.md` or `ui-archetypes.md`)
   - Severity (blocking / non-blocking)
5. **Meta reads issues**, signals workbench via `.omo/next/<fix>.yaml`
6. **Workbench fixes**, writes `.omo/ready/<fix>.yaml`
7. **Meta merges** to exercise, signals product via `.omo/exercise/<fix>.yaml`
8. **GOTO step 1**
9. **Exit condition:** product reports N consecutive clean passes of the smoke test suite

### Agent Launch Prompts

**Meta:**

> "You are Meta. Orchestrate the workbench development ecosystem. Read AGENTS.md and `.omo/design/ecosystem.md` for your protocol. Start by checking `.omo/ready/` for completed features, `.omo/issues/` for unresolved defects, and `.omo/quality-gates/` for milestone certification.
>
> **You never create worktrees.** You write `.omo/next/` to signal workbench agents. You merge completed worktrees to `exercise` and write `.omo/exercise/` to signal product agents."

**Workbench:**

> "You are a workbench agent. Read `.omo/next/<feature>.yaml` for your assignment.
>
> **Your workflow:**
> 1. Create your own worktree: `git worktree add .worktrees/wt-<feature> exercise -b feat/<feature>`
> 2. `cd .worktrees/wt-<feature>`
> 3. Implement the feature. Commit freely on your branch with conventional commits.
> 4. Run `make chassis-gate` — must pass.
> 5. Write `.omo/ready/<feature>.yaml` on the **main checkout** (not the worktree), signaling completion.
> 6. Stop. Do not merge, push, tag, or rebase."

**Product:**

> "You are a product agent. Build your product repo using the latest workbench tools. If `.omo/exercise/<feature>.yaml` exists, integrate and validate it. Run the 'app replaces spreadsheet' smoke test suite. PASS → write `.omo/results/`. FAIL → write `.omo/issues/` with structured error, expected behavior, and design doc reference."

### Worktree Ownership

- **Workbench agents** create, own, and commit in worktrees. Meta never touches them.
- **Meta** merges completed worktrees to `exercise`. Workbench agents never merge.
- **Branch rule:** each feature gets its own branch (`feat/<feature>`) branched from `exercise`.
  Workbench agents commit freely on this branch. Conventional commits only.

## Quality Gate: App Replaces Spreadsheet

The deterministic test spec lives at `.omo/quality-gates/app-replaces-spreadsheet.yaml`. Product agents run this to certify readiness. See that file for the 10-test suite.

## Patching Boundary

| Situation | Where to fix |
|-----------|-------------|
| Bug in workbench command, template, or utility | **Workbench repo** |
| Missing feature another product would also need | **Workbench repo** |
| Product-specific display logic or admin config | **Product repo** |
| Product-specific data validation or business rules | **Product repo** |

Never vendor workbench code into product repos. Fix upstream, release to PyPI.

## Worktree Commit Rules

On worktree branches only: agents **may commit** with conventional commit messages as checkpoints. Agents must not push, tag, merge, or rebase. Each commit captures a working state.
