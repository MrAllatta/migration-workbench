# ADR-001: Platform vision and archetype seams

**Date:** 2026-07-15
**Status:** Accepted
**Deciders:** operator (ralph), agent

## Context

The migration-workbench began as a migration tool: profile a tabular source
(Coda, Google Sheets), generate a schema contract, import data, and serve it
through Django admin. The farm engagement's hand-written `farm_ui/` views
revealed that a generated admin alone is insufficient — teams need role-based
checklists, landings, dashboards, and print views to replace their spreadsheet
entirely.

The Vizcarra Guitars engagement then proved the behavior-model → codegen →
generated-app loop works end-to-end: 39 view classes, 58 templates, 38 views
in the manifest, all generated from a signed-off MWBS behavioral spec.

These two engagements, taken together, reveal a larger trajectory:

> **Profile the source → model behavior → design interaction → generate a
> served app → validate → deploy.**

This is not a migration tool. It is a **platform for generating bespoke served
apps from behavioral specifications**. The source could be Coda, Sheets,
Airtable, Notion, or a direct interview. The output is a running Django app.
The archetypes (checklist, landing, dashboard, list, reference, print) are the
**view primitives** of that platform.

## Decision

We commit to the platform vision and begin architecture hardening to support it:

### 1. The workbench is a platform, not a migration tool

The long-term identity of this project is a **codegen platform** that takes
behavioral specs in YAML and produces production-quality Django apps. The
migration use case (Coda → Django, Sheets → Django) is a concrete application
of this platform, but not the limit of it.

### 2. Archetypes are the platform seam

Each view archetype (checklist, landing, dashboard, list, reference, print)
must be a **pluggable module** with:

- A config dataclass
- View source renderer
- Template HTML renderer
- URL pattern renderer
- Combined-module renderers (`views_auto_py`, `urls_auto_py`)

These are governed by a `ViewArchetype` protocol and a registry so that
`generate_views` dispatches by archetype label instead of importing each
archetype directly.

### 3. Architecture hardening is a prerequisite for product velocity

The current large files (`pipeline_state.py`, `view_generator.py`,
`wb_cli.py`, `contract.py`, corpus orchestrators) are God objects that slow
product changes. They must be split into **deep modules** (small interfaces,
substantial hidden behavior) as documented in `docs/roadmap.md` §0.9.5–0.9.x.

### 4. The split/decoupling milestones are patches, not minors

Architecture-hardening patches (0.9.5–0.9.x) earn no minor on their own.
They are validated by `make chassis-gate`, not by product-repo validation.
They unblock the minors (0.10.0+) that follow.

### 5. Product repos may register custom archetypes

From 1.x onward, a product repo should be able to:

- Register a custom archetype
- Override a default archetype renderer
- Add a vertical-specific provider adapter
- Define a new codegen target

This requires the archetype seams to be **public and stable**.

## Consequences

### Positive

- The archetype registry makes `generate_views` extensible without editing
  core files.
- Deep modules make the codebase navigable by both human and AI agents
  (the "ralph principle").
- New verticals (third engagement post-1.0.0) can add archetypes without
  forking the platform.
- The platform vocabulary — archetype, registry, provider, behavior model —
  gives the product roadmaps a shared language.

### Negative

- Architecture hardening delays feature work by 0.9.5–0.9.x patches. The
  operator must balance downstream product pressure against refactoring.
- The `ViewArchetype` protocol is an abstraction that must earn its keep.
  Lap 2 (0.9.6) will validate it against a concrete archetype addition
  (reference or print).
- Product repos that extend the platform (post-1.0.0) must commit to an
  interface that is still being hardened.

### Risks

- If the product repos push harder than the hardening schedule, the protocol
  may become a bottleneck. Mitigation: each patch includes a smoke test that
  generated artifacts still compile and serve.
- The platform vision might outpace the market: migration tooling is proven;
  codegen platform is aspiration. Mitigation: each product engagement uses
  only the parts of the platform it needs; the platform grows from real
  use, not from speculation.

## Verification

- `grep -c ViewArchetype workbook/views/registry.py >= 1` after 0.9.6.
- `grep -c 'view_generator' workbook/codegen/view_generator.py` after 0.9.5
  shows only re-exports.
- Each architecture-hardening milestone passes `make chassis-gate`.
