# Post-0.6 Release Slicing: Path to v1.0

**Date:** 2026-05-14
**Status:** Draft

## Summary

After 0.6 (profiler improvements — tab sanitization, tab exclusion patterns, formula
analysis), three more slices bridge to v1.0: contract/codegen hardening (0.7), import
pipeline end-to-end (0.8), and view manifest + discovery + deployment (0.9). Each
slice targets a v1.0 criterion and builds on the previous.

## Current state

- **v0.4.0 released.** Contract diff, column transforms, contract composition, snapshot
  testing, schema review CLI, migration safety checks shipped.
- **v0.5.0 (unreleased).** Migration safety checks, null-key robustness.
- **v0.6.0 (in development).** Tab sanitization, tab_exclude_patterns, formula pattern
  classifier, connector-level tab name sanitization.
- **v1.0 criteria (from README):**
  1. End-to-end pipeline exercised on real corpus — _met (farm exercise)_
  2. Schema design loop completed — _partially met (phases 1-5 exercised)_
  3. Production deployment live on Fly.io with real data — _not met_
  4. PyPI release with all gaps patched — _not met_

## 0.7 — Contract & codegen hardening

**Goal:** Make the schema-design loop (phases 3–5: Draft → Decide → Author) production-
quality for the current corpus exercise.

### Items

- **Profile-to-contract bridge extension.**
  `scaffold_workbook_schema` currently emits v1.0 drafts for source-aligned models
  (one tab → one model). Extend it to suggest designed/aggregate model structures
  from profile patterns — e.g., three overlapping tabs → possible designed model,
  columns shared across tabs → potential FK relationships.
- **Contract review checklist round-out.**
  The basic `wb contract review` shipped in 0.4.0 (max_length, nullable FK on_delete,
  unique_together, str_template). Add checks surfaced by the farm and current corpus:
  `import_config.fk_lookup` field resolution, `computed_fields` naming conventions,
  `admin.inlines` target model existence.
- **Codegen hardening from corpus feedback.**
  Fix every papercut the current corpus reveals in generated models.py, admin.py, and
  imports.py. Priority: non-idiomatic output, importability issues, diff noise on
  regeneration.
- **`make validate-contract` in CI.**
  Wire the validate-contract target into the scaffolded product's CI pipeline so
  contract regressions are caught in the product repo, not at codegen time.

### v1.0 criteria served

Closes design-loop phases 3-5. Lays ground for criteria 2 (schema loop) and
unblocks 0.8.

## 0.8 — Import pipeline end-to-end

**Goal:** Get real data flowing. Exercise the import generator with actual bundles
from the current corpus.

### Items

- **Import pipeline exercised on real bundles.**
  Pull bundles, run `generate_import`, verify `update_or_create` with `unique_on`
  works correctly across FK chains. Fix ordering edge cases in auto-tier detection.
- **Column transforms with real data.**
  Exercise `column_map` multi-source lists and `field_transforms` lambdas on actual
  bundle data. The feature shipped in 0.4.0 but wasn't exercised end-to-end; real
  data will surface edge cases (null handling, type coercion, multi-column join
  behavior).
- **Import summary & error handling hardening.**
  The importer produces structured summaries. Harden for real-world failures:
  missing rows, type mismatches, FK resolution errors, partial tier failures.
- **Multi-model atomic tiers.**
  Wrap each import tier in `transaction.atomic()`. Ensure that a failing tier
  doesn't leave partial state, and that idempotent re-import works after failure.

### v1.0 criteria served

Makes data flow, which is prerequisite for deployment (criterion 3) and completes
the schema loop's Author importer phase (criterion 2).

## 0.9 — View manifest, discovery & deployment

**Goal:** Close the schema-design loop and ship a production deployment.

### Items

- **View manifest integration.**
  Verify `editable_fields`, `computed_fields`, `filterable_by` drive generated admin
  output (list_display, readonly_fields, list_filter). The farm generated admin
  without a manifest — this exercises that path end-to-end.
- **Discovery interview pipeline.**
  Run `generate_discovery_interview` → operator fills questionnaire →
  `merge_discovery_notes` patches the manifest → admin regenerates with workflow
  metadata (phase 6-7 of the design loop).
- **Status field override.**
  The heuristic picks the first CharField with choices. Allow manual
  `status_field` override in the view manifest, since the heuristic will guess
  wrong for some models.
- **Production deployment on Fly.io.**
  Deploy the scaffolded product with real imported data, health checks passing,
  CI/CD pipeline rolling. This is the hardest v1.0 criterion and the one least
  exercised so far.
- **Drift check.**
  Wire `wb contract diff` as a periodic check (phase 10 of the design loop).
  Re-profile periodically and diff against checked-in snapshots to detect
  source-corpus drift before it breaks imports.

### v1.0 criteria served

Directly delivers criteria 2 (full schema loop) and 3 (production deployment).
Criterion 4 (PyPI release) is then scoped as a release-engineering task.

## 1.0 — Release

- Tag v1.0.0.
- Publish to PyPI.
- Update roadmap: mark v1.0 criteria as met.
- Document what 1.x means (no more breaking changes without semver major).

## Non-goals (deferred past 1.0)

- **Provider interface extraction / plugin system.** After a second provider is
  stable on Fly. Unblocks no v1.0 criterion.
- **Postgres at scale.** The farm uses SQLite. Real concurrent patterns can wait.
- **GUI for contract authoring.** The YAML is the interface; visual tooling locks
  in a narrow workflow before the format stabilizes.
- **Bidirectional sync.** One-way pipeline is intentional.

## Relationship to client product exercise

The current corpus exercise feeds directly into 0.7 — every issue found in profiling,
contract authoring, or codegen is a 0.7 item. The import and deployment work in 0.8
and 0.9 depend on having solid contracts and generated code first.
