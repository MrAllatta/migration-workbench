# brief: platform-transition-missions (placeholder)

Eight missions were created on 2026-07-17 in an opencode session but were
lost (corrupted path, deleted with typo directory). This placeholder
captures the reconstructed intent of each for future recreation.

**Status**: Skeleton only. Each needs a dedicated brief with full context.

## 1. archetype-classifier-refinement

Refine the archetype classifier (currently fixed heuristics in
`workbook/tools/archetype_matrix.py`) to absorb learnings from the farm
and Vizcarra engagements. Force-frame analysis of classifier precision on
known-good archetype assignments. Proposal for an optional feedback
pipeline (design doc only, no ML). Goal: determine whether the static
heuristic approach is already >90% accurate or needs a learning loop.

## 2. consultant-playbook

Create a playbook for consultants engaging with migration-workbench.
Covers: how to start an engagement, what the pipeline produces at each
stage, how to review and override YAML contracts, how to validate
generated views, when to escalate to the human operator. The consultant
is mandatory until the judgment taxonomy is dense enough — this playbook
is their reference.

## 3. engagement-metrics-system

Define and implement a system for tracking metrics across engagements:
time-to-comple, schema contract accuracy, import success rates, view
codegen coverage, formula parity scores, consultant override frequency.
Goal: quantitative evidence of whether the platform improves with each
engagement.

## 4. judgment-taxonomy-validation

Validate the judgment taxonomy (confidence-gated autonomy model) across
engagements. Currently the taxonomy accumulates decisions but has no
validation mechanism. Goal: verify that low-confidence decisions
correctly identify the right cases, and that high-confidence decisions
don't produce surprises. Compare classifier confidence against consultant
overrides.

## 5. platform-philosophy-docs

Document the platform philosophy: core architectural bets (YAML
contracts as consultant interface, archetypes as platform primitives,
behavioral specs drive codegen, confidence-gated autonomy), design
decisions and their rationale, what the platform is and isn't. Goal:
make the "why" legible to new contributors and to the consultant
workflow.

## 6. platform-readiness-definition

Define what "platform readiness" means: when does migration-workbench
stop being a tool for two specific engagements and become a platform that
new engagements can adopt? Success criteria, maturity signals, blocking
gaps. Goal: a concrete checklist that answers "are we there yet?"

## 7. roadmap-fork-appendix

Appendix documenting how the roadmap forks from tool-specific to
platform-generic. Currently the roadmap tracks farm and Vizcarra
specifics. After e05 and the platform-transition missions, the roadmap
needs a fork: tool-hardening track vs. platform-breadth track. Goal:
plan the fork without disrupting current delivery.

## 8. third-engagement-validation

Validate the platform with a third engagement (beyond farm and
Vizcarra). This is the proof-of-generality: if the pipeline works on a
third spreadsheet source with zero engagement-specific code changes, the
platform bet is validated. Goal: identify what a third engagement would
need to prove, and what to measure.

## Recreation Notes

These missions were likely created during a session simulating platform
maturity thinking — possibly triggered by the data engineer review
feedback. The names suggest a coherent "post-1.0.0 platform transition"
theme. When recreating, each should get its own brief.md with:

- Context tied to the current project state
- Specific in-scope / out-of-scope boundaries
- Measurable success criteria
- References to relevant code paths and existing docs
- Related feedback quotes where applicable

The surviving `archetype-classifier-refinement` brief (recovered from
corrupted path) can serve as the quality template.
