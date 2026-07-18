# brief: formula-parity-validation

Data engineer feedback on the migration-workbench architecture.
Source: simulated data engineer review, 2026-07-17.

## Context

The Vizcarra engagement validated formula parity: generated `@property`
methods reproduce Coda formula outputs with ≥83% parity across 552 real
rows. This is a useful smoke test, but it conflates two different questions:

1. **Output parity**: Does the generated code produce the same result as
   the source formula? (Mechanical — testable.)
2. **Semantic correctness**: Is the source formula the right business rule?
   (Judgment — requires human review.)

A formula that matches Coda output at 100% parity might still be wrong if
the Coda formula has a bug, an implicit behavior (lookup picks most-recent
match), or a precision loss (currency rounding). The parity test can't
distinguish "the formula is correct" from "the formula reproduces the same
bug."

Additionally, the ≥83% threshold is suspicious — the 17% gap needs
explanation. Is it rounding? Unimplemented formulas? Formulas that were
intentionally skipped? Without a distribution of errors (not just a summary
percentage), the consultant can't make an informed decision.

## Goal

Design a formula validation framework that goes beyond output parity:
1. Classify each formula comparison into: exact match, within-tolerance
   match, structural mismatch, unimplemented, and intentionally-skipped.
2. Record the consultant's judgment for each formula: "this is the correct
   business rule" vs. "this is a known Coda workaround" vs. "this needs
   redesign."
3. Produce a validation report that a human can review in 10 minutes,
   not 10 hours.
4. Accumulate formula-judgment patterns across engagements into the
   judgment taxonomy.

## Scope

### In-scope
- Formula comparison report: per-formula, per-row results with mismatch
  classification.
- Tolerance configuration: per-formula tolerance for numeric comparisons
  (e.g., ±0.01 for currency, ±0.001 for percentages).
- Consultant judgment surface: a management command or CLI subcommand
  that presents each formula comparison and records the consultant's
  verdict.
- Judgment taxonomy integration: formula verdicts feed into the existing
  confidence/judgment system in PipelineState.
- Precision audit: explicit check for floating-point accumulation errors
  in currency and percentage formulas.

### Out-of-scope
- Rewriting Coda formulas in Django. The generated `compute_*` methods
  reproduce the formula; this mission validates whether they should.
- Formula dependency graph analysis (that's the existing `formula_dependency.py`).
- Auto-correction of formula mismatches. The consultant decides.

## Success Criteria
- [ ] `wb validate-formulas --contract build/schema-contract.yaml --source-profile build/coda-profile.json`
      produces a per-formula comparison report.
- [ ] Each formula is classified: exact_match, tolerance_match (with delta),
      structural_mismatch, unimplemented, intentionally_skipped.
- [ ] Numeric precision is audited: currency values have ±0.01 tolerance,
      percentages ±0.001, counts exact.
- [ ] `wb validate-formulas --record-verdict` presents each formula and
      records the consultant's judgment (correct_business_rule,
      known_workaround, needs_redesign, skip).
- [ ] Verdicts are persisted in a judgment artifact (JSON or YAML) that
      PipelineState can reference.
- [ ] Existing formula parity tests pass; new validation tests cover:
      exact match, tolerance match, precision loss, unimplemented.

## Constraints
- Must not break existing `compute_*` methods or their tests.
- Tolerance defaults must be configurable per engagement (farm may have
  different precision requirements than Vizcarra).
- The validation report must be human-readable (Markdown or structured
  JSON, not raw test output).

## Reference
- Formula parity tests: `vizcarra-guitars/backend/apps/domain/tests/test_formula_parity.py`
- Formula dependency graph: `profiler/tools/formula_dependency.py`
- Judgment taxonomy: `docs/pipeline-state.md` (§Judgment Taxonomy)
- PipelineState: `profiler/tools/pipeline_state.py`
- Coda formula classification: `connectors/coda_source.py` (`classify_formula_columns`)

## Open Questions
1. Should the tolerance be per-column-type (currency, percentage, count)
   or per-formula (consultant override)?
2. How should the judgment artifact relate to PipelineState? Is it a new
   layer, or does it extend `domain_knowledge`?
3. For farm (Google Sheets), formulas are in-cell and often invisible to
   the profiler. Should this mission scope include Sheets formula
   extraction, or is it Coda-only for now?

## Related Feedback
> "Formula parity tells you the generated code produces the same output
> as the source formula, but it doesn't tell you the formula was correct
> in the first place. Coda formulas are notorious for having implicit
> behavior — a lookup that silently picks the most recent match, a
> conditional that doesn't handle nulls, a currency format that masks
> precision loss."
>
> "Your ≥83% parity threshold is suspicious — what does the 17% gap look
> like? Is it rounding? Is it a formula you didn't implement? A data
> engineer would want to see the distribution of errors, not just the
> summary percentage."
