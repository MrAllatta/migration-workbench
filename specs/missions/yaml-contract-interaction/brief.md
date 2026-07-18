# brief: yaml-contract-interaction

Data engineer feedback on the migration-workbench architecture.
Source: simulated data engineer review, 2026-07-17.

## Context

The workbench uses YAML as the consultant interface for schema contracts,
interaction contracts, and PipelineState checkpoints. YAML is human-editable
and diffable, which was the original motivation.

But at scale (18 tables, 46 columns each, with FK resolutions, computed
fields, import configs, and admin blocks), a YAML contract is not a file
you read top-to-bottom. It's a data structure you search, filter, and
validate. No consultant is reading a 500-line YAML contract — they're
searching for specific patterns, checking specific fields, validating
specific relationships.

The `_artifact` key pattern (referencing external JSON files) keeps the
checkpoint small, but the interaction model is still "open a YAML file in
an editor." That doesn't scale.

The planned SQLite migration for PipelineState storage is the right
instinct, but "the interface stays YAML-like" is vague. The question is:
what does the consultant actually *do* with the contract, and how should
the tooling support that workflow?

## Goal

Design a consultant-centric contract review workflow:
1. Map the consultant's actual review tasks (what do they search for,
   what do they edit, what do they validate).
2. Build CLI surfaces that support those tasks (not just "open YAML").
3. Make the contract reviewable table-by-table, not all-at-once.
4. Produce review artifacts that capture the consultant's decisions.

This replaces "edit YAML" with "review and approve through a structured
workflow" — the same pattern the delta-import and formula-validation
missions use.

## Scope

### In-scope
- Contract review CLI: `wb contract review --interactive` that presents
  one table at a time, shows fields/FKs/computed, and lets the consultant
  approve or flag each.
- Contract diff surface: `wb contract diff v1.yaml v2.yaml` already exists;
  enhance it to show per-field changes with context (not just additions/
  removals).
- Unresolved FK dashboard: `wb contract review --unresolved` lists all
  `TODO_*` FK targets with the tables that reference them, so the
  consultant can resolve them in bulk.
- Review artifact: JSON recording which tables were reviewed, which fields
  were flagged, and what decisions were made.
- PipelineState integration: review artifacts feed into the checkpoint
  so downstream phases know what's been approved.

### Out-of-scope
- GUI for contract authoring (explicitly a non-goal today).
- SQLite storage migration (that's a separate infrastructure mission).
- Contract composition / `!include` changes.
- Schema contract format changes (v1.3 is current).

## Success Criteria
- [ ] `wb contract review --interactive build/schema-contract.yaml` presents
      tables one at a time with field summaries and FK status.
- [ ] `wb contract review --unresolved build/schema-contract.yaml` lists all
      TODO_* FK targets with reference counts.
- [ ] `wb contract review --record build/schema-contract.yaml` produces a
      review artifact JSON with per-table approval status.
- [ ] `wb contract diff old.yaml new.yaml --context` shows changed fields
      with surrounding context (not just +/- lines).
- [ ] Review artifact integrates with PipelineState (recorded in checkpoint).
- [ ] Existing contract review/diff tests pass; new tests cover interactive
      review, unresolved listing, and review artifact generation.

## Constraints
- Must not change the schema contract YAML format (v1.3).
- Must not break `wb contract review`, `wb contract diff`, or `wb contract safety`.
- Interactive review must work in a terminal (no web UI).
- Review artifacts must be provider-agnostic (same format for Sheets and
  Coda contracts).

## Reference
- Schema contract format: `docs/schema-contract.md`
- Contract review: `workbook/contract/review.py` (post e04 split)
- Contract diff: `workbook/contract/diff.py` (post e04 split)
- PipelineState: `profiler/tools/pipeline_state.py`
- Interaction contract: `docs/interaction-contract.md`

## Open Questions
1. Should `--interactive` mode be a readline-based TUI, or a structured
   JSON output that a wrapper script presents?
2. How should the review artifact relate to PipelineState? New field in
   `domain_knowledge`? Separate `_artifact` reference?
3. For 18 tables × 46 columns, is per-field review too granular? Should
  the default be per-table (approve all fields) with per-field override?
4. Should unresolved FK resolution be a separate command, or part of
   the interactive review flow?

## Related Feedback
> "YAML is terrible for structured review. If I'm a consultant reviewing
> a schema contract with 18 tables, 46 columns each, FK resolutions,
> computed fields, import configs, and admin blocks — that's not a YAML
> file, that's a codebase. No human is reading that top-to-bottom."
>
> "The storage backend doesn't matter if the interaction model is still
> 'read a YAML file.' I'd want to see the consultant workflow mapped out:
> what do they open, what do they search for, what do they edit, and what
> do they save."
