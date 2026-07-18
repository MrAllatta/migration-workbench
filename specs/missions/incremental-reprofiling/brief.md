# brief: incremental-reprofiling

Data engineer feedback on the migration-workbench architecture.
Source: simulated data engineer review, 2026-07-17.

## Context

The profiler pulls a full bundle at a point in time. If the source changes
during validation (new tab added, new year's data, column added), the
contract is stale. Re-profiling means re-pulling everything — hitting
Google Sheets rate limits (HTTP 429), spending hours on Coda API calls for
500+ row docs.

The PipelineState checkpoint helps (you can resume from a saved state),
but "resume" without a diff mechanism means re-profiling everything and
skipping phases you already have results for. That's caching, not
incrementality.

For the parallel-run period, the consultant needs to:
1. Know what changed in the source since the last profile.
2. Re-profile only the changed parts.
3. Update the contract incrementally (not regenerate from scratch).

## Goal

Design an incremental re-profiling mechanism:
1. Detect what changed in the source since the last profile (new tabs,
   changed tab dimensions, new columns).
2. Re-profile only the changed or new tabs.
3. Produce a profile delta that merges into the existing PipelineState.
4. Surface new or changed tabs for consultant review before merging.

This reduces re-profiling cost from "hours" to "minutes" and makes the
parallel-run period sustainable.

## Scope

### In-scope
- Source change detection: compare current broad inventory (tab count,
  column count, row count) against the last PipelineState checkpoint.
- Tab-level diff: identify new tabs, removed tabs, changed tabs (row count
  delta, column count delta).
- Selective deep-profile: re-run deep profiling only on changed or new tabs.
- Profile delta artifact: JSON listing what changed, what was re-profiled,
  and what's unchanged.
- PipelineState merge: merge the profile delta into the existing checkpoint
  without overwriting unchanged data.
- Consultant review surface: present the diff and let the consultant
  approve/reject each tab change before merging.

### Out-of-scope
- Cell-level change detection (that's the delta-import mission, not this).
- Schema contract regeneration (that's a separate step after profile merge).
- Real-time source monitoring. This is batch diffing on re-pull.
- Coda-specific incremental APIs (Coda doesn't expose change streams).

## Success Criteria
- [ ] `wb diff-profile --checkpoint build/pipeline-state.yaml --source-config config/cohort_corpus.json`
      produces a profile diff listing new/changed/removed tabs.
- [ ] Changed tabs show dimension deltas (row count before → after, columns
      added/removed).
- [ ] `wb reprofile --checkpoint build/pipeline-state.yaml --changed-tabs "Crop Planner,Field Record"`
      re-profiles only the specified tabs and merges results into the checkpoint.
- [ ] `wb reprofile --auto` detects changes automatically and re-profiles
      only changed tabs.
- [ ] Unchanged tabs are preserved in the merged checkpoint (not re-profiled).
- [ ] Existing PipelineState tests pass; new tests cover: no-change case,
      new tab, changed dimensions, removed tab.

## Constraints
- Must preserve existing PipelineState checkpoint format (YAML).
- Must not break `run_pipeline_state` or existing phase methods.
- Change detection must work for both Google Sheets and Coda sources.
- Re-profiling must respect rate limits (existing HTTP 429 retry logic).

## Reference
- PipelineState: `profiler/tools/pipeline_state.py`, `docs/pipeline-state.md`
- Broad inventory: PipelineState Phase 0/1 output
- Deep profile: PipelineState Phase 2 output
- Bundle pull: `docs/pull-bundle.md`
- Rate limit handling: `connectors/google_provider.py` (existing retry logic)

## Open Questions
1. Should the profile diff be a new PipelineState phase, or a standalone
   utility that operates on the checkpoint file?
2. How should removed tabs be handled? Remove from checkpoint? Flag for
   consultant review?
3. Should the diff detect column-level changes (new column in an existing
   tab) or only tab-level changes (row/column count deltas)?
4. For Coda, the broad inventory comes from `profile_coda_doc`. How does
   incremental work when the doc structure is discovered, not configured?

## Related Feedback
> "How expensive is re-profiling? If it's a full pull every time, you're
> going to hit rate limits on Google Sheets and spend hours on Coda API
> calls. What's the incremental cost? Can you re-profile a single tab
> without re-profiling the whole corpus?"
>
> "The PipelineState checkpoint helps here — you can resume from a saved
> state. But 'resume' implies you know what changed. If you don't have a
> diff mechanism, you're re-profiling everything and just skipping the
> phases you already have results for. That's not incremental; that's
> just caching."
