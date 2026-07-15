# Product Engagement Roadmaps

> **Status:** Living roadmap  
> **Audience:** Operator running a client engagement; workbench contributor deciding what to ship next  
> **Prerequisite:** [Product Build Methodology](product-build-methodology.md), [Roadmap](roadmap.md)

## What this document tracks

The workbench roadmap is the **engine** roadmap: profiler adapters, codegen
archetypes, CLI commands, test harnesses. It tells us whether the machinery
works.

This document is the **engagement** roadmap. It tracks the work required to
turn a real tabular system — a Coda doc, a Google Sheets corpus — into a
generated Django app that humans use as their system of record.

Both active engagements (Vizcarra Guitars and farm) are vehicles for the same
underlying capability:

```
profile  →  behavior model  →  UI design  →  codegen  →  generated app  →  validation  →  cutover
```

The hand-written `farm_ui/` was never the end state. It was the probe that
revealed how much of spreadsheet work is behavioral — roles, workflows,
decisions, exceptions, alerts, print artifacts, mobile interactions — and
how poorly a purely mechanical profile captures it. That realization is what
drove the MWBS behavioral-spec work. Now the goal is to refine that model
through to codegen: express the nuanced, data-based interactions of a real
shop or farm as generated views, then prove the generated app does the job.

The two engagements differ in source material, not in kind:

- **Vizcarra Guitars** has a dense, signed-off Coda doc. The recent session
  proved the behavior model → codegen loop on that doc, producing 39 view
  classes and 58 templates.
- **farm** has a multi-year Google Sheets corpus and the `farm_ui/` reference
  views. The same loop now needs to run there: profile the sheets, build the
  behavior model, design the UI expressions, push the required codegen
  upstream, and generate the farm app.

Neither engagement is finished. Both are test cases for the same pipeline.

## Semver correction

Semver minors are integers, not decimal digits. After `0.9.x` comes
`0.10.0`, then `0.11.0`, and so on. There is no need to rush to `1.0.0`
because the minor number is "running out." We have ample room.

- `0.9.x` = engine capability and joint cutover-prep (shipped to 0.9.4).
- `0.10.0+` = product-validated milestones earned inside the client repos.
- `1.0.0` = both product engagements retired, consultant playbook proven, and
  the workbench ready to support a third engagement without heroic effort.

Patch numbers absorb workbench fixes and product-repo polish discovered
during validation.

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
| 0.10.0 | `vizcarra-behavior-model-codegen` | The signed-off behavior model can drive codegen that produces the nuanced views Coda requires: status-driven lists, detail forms with computed totals, time tracking, build ledger, billing, print tags. | All 38 manifest views generate from the behavior model; formula-parity tests still pass; smoke tests 200 OK on real data; any codegen gaps needed for Coda-specific expressions are fixed upstream. | vizcarra-guitars |
| 0.11.0 | `vizcarra-generated-app-validation` | A human can complete the core shop workflows in the generated app. | Workflow hand-checks pass for intake, evaluation, queue, bench work, billing, time tracking, archive; acceptance suites pass; drift check clean. | vizcarra-guitars |
| 0.12.0 | `vizcarra-parallel-run` | The app is trustworthy enough to run live alongside Coda without blocking daily work. | One full business week of parallel use; discrepancies logged and triaged; no blocking defects; data re-imports cleanly each morning. | vizcarra-guitars (production parallel) |
| 0.13.0 | `vizcarra-coda-retired` | Coda is no longer the system of record. | Coda permissions set to read-only; team uses Django app for intake, status changes, billing, and archive; rollback window expired without rollback. | vizcarra-guitars |
| 0.14.0 | `vizcarra-operational-maturity` | Post-cutover refinements are validated. | Print tags tested on real labels; alert thresholds tuned with team feedback; mobile workflow (phone/tablet) smoke-tested; performance acceptable on shop Wi-Fi. | vizcarra-guitars |

### Work to close before 0.10.0

1. **Codegen hardening.** The behavior model is signed off; the generated
   views exist. Now prove the codegen is complete enough that every Coda
   expression the team relies on has a generated equivalent.
2. **Formula parity re-check.** New transaction models and views may have
   changed computed-field behavior; validate against latest Coda pull.
3. **Drift check.** Re-profile Coda vs. generated schema and record counts.
4. **Workflow hand-checks.** URLs returning 200 is not enough; a human must
   be able to complete intake → evaluation → queue → in-progress → completed
   → picked up → billed.
5. **Phase 0/1 catch-up.** Write `build/pipeline-state.yaml` and
   `config/domain_context.yaml` to close the methodology loop.
6. **Keith's operational questions** (from `docs/next-steps.md`):
   - Confirm status order from Coda `Index` values.
   - Validate orphan priorities (`D`, `*A`, `0-Priority`, `B`, `*-KEI`).
   - Verify alert thresholds (14 days awaiting parts? 30/60/90 payment
     reminders?).

### Workbench dependencies

| Product milestone | Likely workbench need |
|-------------------|----------------------|
| 0.10.0 | `wb drift check`; acceptance-test runner harness; print-view archetype; computed-field dependency graph. |
| 0.11.0 | Import idempotency / morning re-import command; discrepancy log template. |
| 0.12.0 | Read-only source export/archive helper; cutover runbook template. |
| 0.13.0 | Mobile-responsive template defaults; alert-tuning DSL or config. |

---

## Engagement B: farm (Google Sheets → Django)

### Definition of "spreadsheet retired"

The farm team uses the generated Django app as the system of record for the
weekly workflows currently performed in Google Sheets. The Sheets are
read-only archive. Roles (Planner/Manager, Field Worker, Nursery Worker,
etc.) have role-specific landing pages and checklists they can complete
without opening Sheets.

### What farm is for

farm is not an elicitation-only engagement. It is the second test of the
profile → behavior model → UI design → codegen → generated-app pipeline.

The hand-written `farm_ui/` proved that weekly checklists, role landings,
dashboards, and print views are necessary. It did not prove that the
workbench can generate them from a behavior model. That is the work: take
the patterns `farm_ui/` exposed, generalize them into MWBS + codegen, and
produce a generated farm app that matches or exceeds the hand-written one.

This means farm and Vizcarra need the same sequence of capabilities:

1. **Profile and behavior model** the source data and the human work.
2. **Design the UI expressions** (lists, checklists, dashboards, forms,
   print views, alerts) that the behavior model must produce.
3. **Push the required codegen upstream** so the workbench can emit those
   expressions from YAML.
4. **Generate the app** and validate it against real farm data and real
   workflows.

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
| 0.10.0 | `farm-behavior-model-codegen` | The farm sheets and `farm_ui/` reference views can be expressed as a behavior model and generated app. | Real actors and workflows captured in `config/behavioral-spec.yaml`; view manifest defines the UI expressions (checklist, landing, dashboard, list, form, print) the hand-written views proved necessary; generated views emit and serve; real-data parity tests against `farm_ui/` reference views pass; codegen gaps are fixed upstream. | farm |
| 0.11.0 | `farm-generated-app-validation` | A human can complete the core weekly farm workflows in the generated app. | Workflow hand-checks pass for Monday Field Walk, harvest logging, pack list, nursery seeding/pot-up, CSA availability, orders; acceptance suites pass; drift check clean. | farm |
| 0.12.0 | `farm-parallel-run` | The app is trustworthy enough to run live alongside Sheets without blocking daily work. | One full business week of parallel use; discrepancies logged and triaged; no blocking defects; data re-imports cleanly each morning. | farm (production parallel) |
| 0.13.0 | `farm-spreadsheet-retired` | Google Sheets are no longer the system of record. | Sheets moved to read-only archive folder; team uses Django app for weekly workflows; one full cycle (plan → seed → field → harvest → pack → sales) completed in the app; rollback window expired without rollback. | farm |
| 0.14.0 | `farm-operational-maturity` | Post-cutover refinements are validated. | CSV export/print views tested for pack lists; mobile field checklist tested; performance acceptable; alert thresholds tuned. | farm |

### Work to close before 0.10.0

1. **Behavior model.** Replace tab-name actors (`planner`, `records`,
   `online`, `market`, `orders`, `available`, `field_walk`, `harvest`,
   `pack`, `nursery`, `seeding`) with real farm roles. Capture the real
   workflows: Monday Field Walk, Harvest Logging, Pack List, Nursery
   Seeding, Nursery Pot-Up, CSA Availability, Orders, Field Records.
2. **UI design.** Decide which archetypes (checklist, landing, dashboard,
   list, form, print) each workflow needs, using `farm_ui/` as the
   reference vocabulary, not the final implementation.
3. **Codegen refinement.** Identify what the workbench cannot yet generate
   from the behavior model and fix it upstream. farm is a co-development
   partner for the codegen, not just a consumer.
4. **Generated app.** Wire generated views into `generated/urls_auto.py`,
   run parity tests against `farm_ui/`, and prove the generated app serves
   real data.
5. **Pre-existing 0.9.x gaps.** Fix the 4 CropConfig test failures, the
   `test_bprs_scaffold.py` syntax error, and the unwired generated views.

### Workbench dependencies

| Product milestone | Likely workbench need |
|-------------------|----------------------|
| 0.10.0 | MWBS elicitor improvements; workflow template library; actor/responsibility scaffolding from view names; checklist/landing/dashboard/print archetype completeness; wiring helper for generated views. |
| 0.11.0 | Acceptance-test runner; drift check; alias-resolution diagnostics. |
| 0.12.0 | Import idempotency / morning re-import command; discrepancy log template. |
| 0.13.0 | Archive/export helper for Google Sheets; cutover runbook template. |
| 0.14.0 | Mobile checklist archetype; CSV/print view archetype; alert-tuning DSL. |

---

## Cross-cutting workbench implications

These product roadmaps change what the workbench ships next. The engine's
job is to make the behavior-model → codegen → generated-app loop cheaper
and more expressive for both engagements.

Likely cross-cutting capabilities:

- **`wb drift check`** — compare a re-profiled source against the current
  schema contract and import counts.
- **Acceptance-test runner** — execute the acceptance criteria in a
  behavioral spec against the generated app.
- **Print-view archetype** — tags, pack lists, weekly summaries.
- **Mobile checklist archetype** — field/nursery/shop workflows on phones.
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
earn the next minor. A workbench minor is earned by validation in a product
repo, and the validation criteria are defined by the product roadmap.

Rough mapping:

| Workbench version | Product milestone it enables or validates |
|-------------------|--------------------------------------------|
| 0.9.4 | Engine capability and joint cutover-prep. |
| 0.9.5–0.9.x | Patches for gaps surfaced by product roadmaps (drift command, wiring helper, elicitor fixes). |
| 0.10.0 | Behavior model → codegen → generated app proven in one engagement. |
| 0.11.0 | Generated app validated against real human workflows in one engagement. |
| 0.12.0–0.14.0 | Acceptance, parallel run, and source retirement in each engagement. |
| 1.0.0 | Both engagements retired; consultant playbook proven; engine stable for a third engagement. |

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
