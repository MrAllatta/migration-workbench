# brief: report-chart-archetypes

Data engineer feedback on the migration-workbench architecture.
Source: simulated data engineer review, 2026-07-17.

## Context

The workbench has six view archetypes: checklist, landing, dashboard, list,
reference, and print. These cover transactional workflows well — "show me
what I need to do today," "show me what's overdue," "show me the count of
things in each status."

But the moment someone asks "show me revenue by month for the last two
years" or "compare yield per field block across seasons," you're in
analytics territory. That's not a landing page or a dashboard — it's a
report. Reports need aggregation, grouping, date ranges, and ideally some
kind of visualization.

Additionally, the "reference" archetype is underspecified. A reference
table (crop catalog, price list) is read-heavy, rarely filtered by date,
often flat, and sometimes needs inline editing. If "reference" is just a
list archetype with different styling, that should be acknowledged
explicitly.

The platform vision ADR (001) claims archetypes are the platform seam.
If the archetype taxonomy has gaps, the platform claim is weakened.

## Goal

Audit the existing archetype taxonomy against real engagement needs:
1. Map every view in the farm and Vizcarra engagements to an archetype.
2. Identify views that don't fit any existing archetype.
3. For views that don't fit, determine whether they need a new archetype
   or are variations of existing ones.
4. If new archetypes are needed (report, chart), design the archetype
   shape (config dataclass, renderer, template, URL pattern).
5. If no new archetypes are needed, document why the existing taxonomy
   is sufficient.

This is a research mission first, implementation second. The goal is to
validate or invalidate the archetype taxonomy claim.

## Scope

### In-scope
- View inventory: list every view in farm's `farm_ui/` and Vizcarra's
  generated views, mapped to an archetype label.
- Gap analysis: identify views that don't fit checklist/landing/dashboard/
  list/reference/print.
- Archetype sufficiency assessment: for each gap, classify as:
  (a) variation of existing archetype (needs config, not new code),
  (b) new archetype needed, (c) post-1.0.0 concern.
- If (b): design the new archetype shape following the ViewArchetype
  protocol in `workbook/views/registry.py`.
- Reference archetype clarification: document what "reference" means
  explicitly (read-heavy flat list with optional inline edit).

### Out-of-scope
- Implementing chart/visualization libraries (that's a separate mission
  if the audit determines they're needed).
- Changing the ViewArchetype protocol or registry.
- Generating views (that's the codegen pipeline).
- Farm or Vizcarra engagement work (this is engine-level audit).

## Success Criteria
- [ ] A view inventory document exists mapping every farm and Vizcarra
      view to an archetype label (or "unclassified").
- [ ] Gap analysis classifies each unclassified view as (a), (b), or (c).
- [ ] If new archetypes are needed: archetype shape design follows the
      ViewArchetype protocol (config dataclass, renderer, template, URL).
- [ ] If no new archetypes: documentation explains why the existing
      taxonomy is sufficient with examples.
- [ ] Reference archetype is explicitly documented (not just "like list
      but different").
- [ ] Platform ADR (001) is updated with findings if the taxonomy changes.

## Constraints
- Must not break existing archetype packages or the registry.
- Must not change the ViewArchetype protocol.
- Research output must be grounded in real view code (not hypotheticals).
- If a new archetype is designed, it must be implementable within the
  existing registry framework.

## Reference
- View archetype registry: `workbook/views/registry.py`
- Existing archetypes: `workbook/views/{checklist,landing,dashboard,list}/`
- Platform ADR: `specs/adr/001-platform-vision-and-archetype-seams.md`
- Farm views: `farm-ui/` in the farm product repo
- Vizcarra views: generated in `vizcarra-guitars/backend/apps/domain/views/`
- Archetype matrix: `workbook/tools/archetype_matrix.py`

## Open Questions
1. Is "report" a distinct archetype, or a list archetype with aggregation
   config? The answer determines whether it's a new package or a config
   extension.
2. Should charts be archetype-level (each chart type is an archetype) or
   template-level (one "analytics" archetype with chart config)?
3. For the farm engagement specifically: do the hand-written `farm_ui/`
   views reveal patterns the generated views don't cover?
4. Is the "print" archetype (0.9.12) sufficient for pack lists and tags,
   or does it need to be more general?

## Related Feedback
> "The six archetypes you have cover the transactional workflows well.
> But the moment someone asks 'show me revenue by month for the last two
> years' or 'compare yield per field block across seasons,' you're in
> analytics territory. That's not a landing page or a dashboard — it's
> a report."
>
> "I'd also push on the 'reference' archetype. What is it, exactly? A
> reference table is a different beast from a transactional list. It's
> read-heavy, rarely filtered by date, often has a flat structure, and
> sometimes needs inline editing. If 'reference' is just a list archetype
> with different styling, call it that."
