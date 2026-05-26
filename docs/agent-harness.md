# Agent Harness

> **Status:** Design philosophy (incorporated into 0.2.0+)  
> **Audience:** Workbench developers, pipeline operators, product strategists

The migration-workbench is not a self-service platform.
It is a **consultant accelerant**: an agent that does everything
that does not require judgment, alerting the human for the judgment.

## Philosophy

The agent makes autonomous decisions where it has high confidence.
The consultant reviews and corrects where confidence is low.
Every correction teaches the agent for the next engagement.

The goal is not to eliminate the consultant.
The goal is to make the consultant 10x faster.

## Confidence Levels

| Level | Threshold | Agent Action | Consultant Role |
|-------|-----------|--------------|-----------------|
| Autonomous | > 0.90 | Apply silently | None |
| Alert | 0.50–0.90 | Flag for review | Confirm or override |
| Blocking | < 0.50 | Stop and ask | Must decide |

## Judgment Taxonomy

Every decision the agent makes is recorded in the `PipelineState`
checkpoint with confidence, reasoning, and consultant override.

Over engagements, the taxonomy becomes the moat.

Example entry (accumulated across verticals):

| Decision | Confidence Threshold | Action | Farm Override |
|----------|---------------------|--------|---------------|
| Tab is operational (not pivot) | > 0.85 | Autonomous | Lower to 0.75 |
| Column is FK candidate | > 0.80 | Autonomous | Raise to 0.90 |
| Formula column is computed field | > 0.90 | Autonomous | None |
| Duplicate tab (same title, different year) | Any | Blocking | None |
| Model name from tab title | > 0.95 | Autonomous | Use glossary |

## Why Not Self-Service?

The agent makes mistakes. Real business data is messy.
A bad migration destroys trust and data. The consultant is the
safety layer. The agent is the accelerant.

Self-service is a future phase (0.5.0+), only after the judgment
taxonomy is dense enough to make the agent reliably correct.

## Where This Lives

- `PipelineState` checkpoint records every decision. See [Pipeline State](pipeline-state.md).
- Profiler signals carry confidence scores. See [Interaction Contract](interaction-contract.md).
- Schema design loop defines agent vs. human boundaries per step. See [Schema Design Loop](schema-design-loop.md).
