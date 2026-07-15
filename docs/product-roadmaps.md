# Product Engagement Roadmaps

> **Status:** Living roadmap  
> **Audience:** Operator running a client engagement; workbench contributor deciding what to ship next  
> **Prerequisite:** [Product Build Methodology](product-build-methodology.md), [Roadmap](roadmap.md)

## The reframing

The workbench roadmap tracks the *engine*: profiler adapters, codegen
archetypes, import pipeline, CLI commands. Getting the engine to 0.9.4
meant every generator worked and both reference engagements (farm and
Vizcarra Guitars) had green dry-runs.

But the engine being ready is not the same as the client app being ready.
The recent Vizcarra Guitars enrichment session showed that the bulk of the
remaining work is **specification enrichment**, not engine code:

- Schema contract grew from 6 tables to **18 tables** (4 data + 5 lookups + 9 transactions).
- Views grew from **2 to 39 view classes** and 58 templates.
- Import pipeline gained a second command (`import_transactions`) for **2,186 transaction rows**.
- The behavioral spec reached 1,691 lines and was **signed off by Keith Vizcarra**.
- The view manifest reached 998 lines mapping 13 workflows to 38 views.

All of that happened *after* 0.9.4 declared the engagement "GO."  The
engagement was not ready; the engine was ready.

This document is the authoritative product-side roadmap. It lives next to
the engine roadmap and answers a different question: **What does each
product repo need to reach before its tabular system is retired in the
wild?**

## Semver correction

Semver minors are integers, not decimal digits. `0.10.0` follows `0.9.x`,
`0.11.0` follows `0.10.x`, and so on. There is no need to rush to `1.0.0`
because the minor number is "running out."  We have ample room.

For this project:

- `0.9.x` = engine capability and joint cutover-prep (shipped to 0.9.4).
- `0.10.0+` = product-validated milestones earned inside the client repos.
- `1.0.0` = both product engagements retired, playbook proven, and the
  workbench ready to support a third engagement without heroic effort.

Patch numbers under each minor absorb workbench fixes and product-repo
polish discovered during validation.

---

## Engagement A: Vizcarra Guitars (Coda → Django)

### Definition of "Coda doc retired"

The Vizcarra team uses the generated Django app as the system of record
for every workflow currently performed in Coda. The Coda doc is
read-only/archive. The team can complete a full work cycle (intake →
evaluation → queue → bench work → billing → pickup → archive) without
opening Coda.

### Current state (2026-07-14)

| Phase | Layer | Status |
|-------|-------|--------|
| 0 | Profile & baseline | Partial — profiling done, PipelineState checkpoint not yet written |
| 1 | Domain knowledge | Missing — no `config/domain_context.yaml` |
| 2 | Schema contract | Complete — 18 tables, FK vocabularies, formula parity |
| 3 | Behavioral spec (MWBS) | Complete — signed off by Keith Vizcarra |
| 4 | Interaction contract | Complete — weekly actions, state machine, 8 alert rules |
| 5 | View manifest | Complete — 38 views, 39 view classes, 58 templates, 39 URL routes |
| 6 | Validation | Partial — 81 tests pass, smoke test 200 OK; workflows not hand-checked, acceptance criteria not executed, drift check pending, human sign-off pending |

### Product milestones

| Version | Mission | What it proves | Acceptance criteria | Test target |
|---------|---------|---------------|---------------------|-------------|
| 0.10.0 | `vizcarra-acceptance-validation` | The generated app can execute every workflow in the signed-off behavioral spec. | Every workflow in `build/behavioral-spec.yaml` is manually verified end-to-end; 3 acceptance suites pass; drift check shows Coda and DB counts/totals match; Keith signs off. | vizcarra-guitars |
| 0.11.0 | `vizcarra-parallel-run` | The app is trustworthy enough to run live alongside Coda without blocking daily work. | One full business week of parallel use; discrepancies logged and triaged; no blocking defects; data re-imports cleanly each morning. | vizcarra-guitars (production parallel) |
| 0.12.0 | `vizcarra-coda-retired` | Coda is no longer the system of record. | Coda permissions set to read-only; team uses Django app for intake, status changes, billing, and archive; rollback window expired without rollback. | vizcarra-guitars |
| 0.13.0 | `vizcarra-operational-maturity` | Post-cutover refinements are validated. | Print tags tested on real labels; alert thresholds tuned with team feedback; mobile workflow (phone/tablet) smoke-tested; performance acceptable on shop Wi-Fi. | vizcarra-guitars |

### Known gaps to close before 0.10.0

1. **Workflow hand-checks.** The smoke test proves URLs return 200; it does
   not prove a human can complete intake → evaluation → queue → in-progress
   → completed → picked up → billed.
2. **Acceptance criteria execution.** Three suites are written (status
   lifecycle, tax accuracy, instrument export) but not run against the
   generated app.
3. **Drift check.** No recent re-profile of Coda vs. the generated schema
   and record counts.
4. **Domain context (Phase 1).** Optional for cutover, but the methodology
   says every engagement should have one.
5. **PipelineState checkpoint (Phase 0).** Optional for cutover, but closes
   the methodology loop.
6. **Keith's operational questions** (from `docs/next-steps.md`):
   - Confirm status order from Coda `Index` values.
   - Validate orphan priorities (`D`, `*A`, `0-Priority`, `B`, `*-KEI`).
   - Verify alert thresholds (14 days awaiting parts? 30/60/90 payment
     reminders?).

### Workbench dependencies

| Product milestone | Likely workbench need |
|-------------------|----------------------|
| 0.10.0 | `wb drift check` or equivalent command; acceptance-test runner harness; maybe print-view archetype. |
| 0.11.0 | Import idempotency / morning re-import command; discrepancy log template. |
| 0.12.0 | Read-only source export/archive helper; cutover runbook template. |
| 0.13.0 | Mobile-responsive template defaults; alert-tuning DSL or config. |

---

## Engagement B: farm (Google Sheets → Django)

### Definition of "spreadsheet retired"

The farm team uses the generated Django app as the system of record for
the weekly workflows currently performed in Google Sheets. The Sheets are
read-only archive. Roles (Planner/Manager, Field Worker, Nursery Worker,
etc.) have role-specific landing pages and checklists they can complete
without opening Sheets.

### Current state (2026-07-14)

| Phase | Layer | Status |
|-------|-------|--------|
| 0 | Profile & baseline | Complete — `build/pipeline-state.yaml` (3,843 lines) inventories yearly workbooks |
| 1 | Domain knowledge | Complete — `config/domain_context.yaml` (156 lines) |
| 2 | Schema contract | Complete — `build/schema-contract-certified.yaml` |
| 3 | Behavioral spec (MWBS) | Partial — `build/behavioral-spec.yaml` is 8,009 lines but mechanical/draft (actors are tab names); `config/behavioral-spec.yaml` is 71 lines with 3 real actors but no workflows, decisions, rules, or acceptance tests |
| 4 | Interaction contract | Partial — `build/interaction-contract.yaml` (130 lines), not yet tied to real workflows |
| 5 | View manifest | Partial — `config/view-manifest.yaml` (943 lines, 72 entries), 14 generated list views emitted but not wired into `generated/urls_auto.py` |
| 6 | Validation | Partial — 204 tests pass (4 CropConfig failures waived), `test_bprs_scaffold.py` syntax error, generated views not serving |

### Product milestones

| Version | Mission | What it proves | Acceptance criteria | Test target |
|---------|---------|---------------|---------------------|-------------|
| 0.10.0 | `farm-behavioral-elicitation` | Real farm knowledge is captured in the behavioral spec. | Real actors (Field Manager, Pack House Lead, Harvest Lead, Nursery Lead, CSA Manager, Sales/Pack, Owner) with responsibilities and time pressures; real workflows (Monday Field Walk, Harvest Logging, Pack List, Nursery Seeding/Pot-Up, CSA Availability, Orders, Field Records) with job stories, steps, decisions, exceptions, business rules, reports, and acceptance criteria; signed off by farm team. | farm |
| 0.11.0 | `farm-interaction-contract` | Roles, weekly actions, status transitions, and alerts are fully specified. | Every role has weekly actions; every status field has a state machine; every alert has condition, severity, and surface view; workflow-to-view mapping is complete and reviewed. | farm |
| 0.12.0 | `farm-generated-views-wired` | Generated views replace hand-written `farm_ui/` views for core workflows. | All 72 manifest entries map to generated views; generated URLs wired and serving; real-data parity tests against the 19 `farm_ui` reference views pass; no hand-written view is required for the core weekly cycle. | farm |
| 0.13.0 | `farm-data-reconciliation` | Latest real spreadsheet data imports and reconciles cleanly. | Pull latest Sheets bundle; import pipeline runs with 0 errors; key counts match expected ranges; crop alias resolution still holds; reconciliation report signed off. | farm |
| 0.14.0 | `farm-spreadsheet-retired` | Google Sheets are no longer the system of record. | Sheets moved to read-only archive folder; team uses Django app for weekly workflows; one full cycle (plan → seed → field → harvest → pack → sales) completed in the app; rollback window expired without rollback. | farm |
| 0.15.0 | `farm-operational-maturity` | Post-cutover refinements are validated. | CSV export/print views tested for pack lists; mobile field checklist tested; performance acceptable; alert thresholds tuned. | farm |

### Known gaps to close before 0.10.0

1. **Real actors.** Current `build/behavioral-spec.yaml` actors are tab names
   (`planner`, `records`, `online`, `market`, `orders`, `available`,
   `field_walk`, `harvest`, `pack`, `nursery`, `seeding`). They need to
   become human roles.
2. **Real workflows.** `config/behavioral-spec.yaml` has `workflows: []`.
   Monday Field Walk, Harvest Logging, Pack List, etc. need job stories,
   steps, decisions, exceptions.
3. **Business rules and reports.** Tax, inventory, availability, seed-order
   rules need to be written down and signed off.
4. **Acceptance criteria.** No acceptance tests exist yet.
5. **Elicitation.** The spec cannot be inferred from sheet structure alone.
   The farm team must be interviewed.

### Workbench dependencies

| Product milestone | Likely workbench need |
|-------------------|----------------------|
| 0.10.0 | MWBS elicitor improvements; workflow template library; maybe actor/responsibility scaffolding from `farm_ui` view names. |
| 0.11.0 | Interaction-contract codegen (weekly actions, status transitions, alerts) consumed by view manifest. |
| 0.12.0 | `generate_views --archetype-list-from-manifest` wiring helper; list/dashboard/checklist/print archetypes complete; template block override stability. |
| 0.13.0 | Reconciliation report command; alias-resolution diagnostics. |
| 0.14.0 | Archive/export helper for Google Sheets; cutover runbook template. |

---

## Cross-cutting workbench implications

These product roadmaps change what the workbench ships next. The engine is
no longer the star; the engine's job is to make the product milestones
above cheaper and faster.

Likely cross-cutting workbench capabilities (not tied to a single product
milestone):

- **`wb drift check`** — compare a re-profiled source against the current
  schema contract and import counts.
- **Acceptance-test runner** — execute the acceptance criteria in a
  behavioral spec against the generated app.
- **Print-view archetype** — tags, pack lists, weekly summaries.
- **Mobile checklist archetype** — field/nursery workflows on phones.
- **Alert-tuning DSL** — configure thresholds without editing YAML.
- **Parallel-run discrepancy log** — structured log for live-vs-source
  comparisons.
- **MWBS elicitor improvements** — better prompts, worksheet generation,
  sign-off gate.

These become workbench mission briefs as the product roadmaps advance.

---

## Relationship to engine roadmap

[docs/roadmap.md](roadmap.md) continues to track *engine* releases. The
engine roadmap references this document for the product milestones that
earn the next minor. A workbench minor is still earned by validation in a
product repo, but the validation is now defined by the product roadmap,
not by an engine feature landing.

Rough mapping:

| Workbench version | Product milestone it enables or validates |
|-------------------|--------------------------------------------|
| 0.9.4 | Joint cutover-prep declared engine ready (revised: this was engine-ready, not product-ready). |
| 0.9.5–0.9.x | Patches for gaps surfaced by product roadmaps (drift command, wiring helper, elicitor fixes). |
| 0.10.0 | First product-validated minor: either Vizcarra acceptance validation or farm behavioral elicitation. |
| 0.11.0+ | Subsequent product milestones as each engagement advances. |
| 1.0.0 | Both engagements retired; consultant playbook proven; engine stable for third engagement. |

---

## How to update this document

1. After each product session, update the *Current state* table for that
   engagement.
2. When a milestone ships, move it to a *Shipped* section and tag the
   workbench version that validated it.
3. When a product gap requires a workbench change, add a workbench
   dependency and create a mission brief under `.pi/missions/`.
4. When both engagements are retired, revise the 1.0.0 definition and
   retire this document into a post-1.0 case-study.
