# brief: delta-import-drift-detection

Data engineer feedback on the migration-workbench architecture.
Source: simulated data engineer review, 2026-07-17.

## Context

The workbench pipeline is one-way: source → Django. During the parallel-run
period (weeks or months between "the app works" and "the spreadsheet is
retired"), the source keeps changing. Someone opens Sheets, updates a cell,
and the import has stale data. `wb drift check` exists but its scope and
recommendations are unclear.

The parallel-run period is where migrations actually die — not because the
tooling is wrong, but because the spreadsheet is still the system of record
in people's heads. Without a delta mechanism, the consultant either
re-profiles everything (expensive, hits rate limits) or trusts that the
source hasn't changed (dangerous).

## Goal

Design and implement a delta-import mechanism that:
1. Re-pulls the source bundle at a point in time.
2. Diffs the new bundle against what's currently in Django.
3. Surfaces what changed (added rows, modified rows, deleted rows) with
   timestamps or content hashes.
4. Lets the consultant approve or reject each change before applying.

This unblocks the parallel-run phase for both engagements (farm and
Vizcarra) and is a prerequisite for 1.0.0 cutover.

## Scope

### In-scope
- Row-level diffing: compare source CSV rows against Django model instances
  using a stable key (import_key from the schema contract).
- Content hashing: hash each row's normalized contents to detect silent
  modifications (cell changed without key change).
- Delta summary artifact: JSON listing added/modified/deleted counts per
  table, with per-row detail for modified rows.
- Consultant approval surface: a management command or CLI subcommand
  that presents the delta and accepts approve/reject per change.
- Reconciliation: after approval, apply approved changes via the existing
  import tier system.

### Out-of-scope
- Change-data-capture from the source (Google Sheets doesn't expose webhooks;
  Coda has limited webhook support). The delta is computed by diffing two
  bundles, not by streaming changes.
- Real-time sync. This is batch diffing, not streaming.
- Schema drift detection (columns added/removed from the source). That's
  `wb contract drift`, not this mission.

## Success Criteria
- [ ] `wb delta --source-bundle build/bundle-v2/ --target-models core.FieldBlock,core.Crop`
      produces a delta JSON with added/modified/deleted counts per model.
- [ ] Modified rows show the specific fields that changed (old value → new value).
- [ ] `wb delta --apply` applies approved changes through the existing tier
      system with atomic savepoints.
- [ ] `wb delta --dry-run` shows the delta without applying.
- [ ] Content hash is stable across identical re-pulls (same source → same hash).
- [ ] Delta diffing works for both Google Sheets bundles and Coda bundles.
- [ ] Existing import tests pass; new delta tests cover: no-change case,
      added rows, modified rows, deleted rows, key collision.

## Constraints
- Must use the existing import tier system for applying changes.
- Must not break `import_core` or `import_historical` behavior.
- Delta keys must match the schema contract's `import_key` fields.
- Hash algorithm must be deterministic and provider-agnostic (content hash,
  not source-specific metadata).

## Reference
- Schema contract format: `docs/schema-contract.md`
- Import tier system: `importer/base.py`, `importer/chassis.py`
- Existing drift check: `deployment/wb_cli.py` (`wb drift check`)
- Bundle format: `docs/pull-bundle.md`
- PipelineState checkpoint: `docs/pipeline-state.md`

## Open Questions
1. Should the delta command live in `importer/` (close to import) or
   `deployment/` (close to drift check)?
2. How should deleted rows be handled? Soft-delete (flag in DB)? Hard-delete?
   Ignore (source-of-truth is Django post-cutover)?
3. Should the delta artifact be part of PipelineState checkpoint, or a
   separate artifact?
4. What's the right key for Coda bundles where compound keys (first+last)
   are needed? The schema contract already defines this — does the delta
   command read it?

## Related Feedback
> "What I'd want to see: a delta import. Pull the source again, diff
> against what's in Django, surface what changed and when, and let the
> consultant approve or reject each change. Not a full re-profile — just
> the delta. That's how you keep the spreadsheet alive during parallel-run
> without letting data silently diverge."
