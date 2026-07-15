# migration-workbench Roadmap

Version history and direction.

```
0.0.x                  Component assembly                          ← shipped
0.1.0 → 0.3.0          Pipeline proven on real data               ← shipped
                       (legacy series 0.1.0–0.9.3 overlaid; see Semver Recovery)
0.4.0 → 0.5.3          Spreadsheet replacement + moat             ← shipped
────────────────────────────────────────────────────────────────────────────
0.6.0+                 Coda + Sheets engagement validation + UI codegen  ← current work
1.0.0                  Both engagements replaced in the wild      ← target
```

## Semver correction

Semver minor versions are integers, not decimal digits. After `0.9.x` comes
`0.10.0`, then `0.11.0`, and so on. We are **not** forced to jump to `1.0.0`
once the patch digit fills up. This roadmap now uses the full `0.10.0+` space
for product-validated milestones before `1.0.0`.

## Product roadmaps are now first-class

This document remains the **engine** roadmap — it tracks workbench capabilities
(profiler adapters, codegen archetypes, CLI commands). The engagements
themselves need their own roadmaps:

- [Vizcarra Guitars product roadmap →](product-roadmaps.md#engagement-a-vizcarra-guitars-coda--django)
- [Farm product roadmap →](product-roadmaps.md#engagement-b-farm-google-sheets--django)

The engine roadmap below references those product roadmaps for the milestones
that earn the next minor. A workbench minor is earned by validation in a
product repo, and the validation criteria are defined by the product roadmap,
not by an engine feature landing.

## Definition of 1.0.0

**Both tabular systems that teams rely on — one Google Sheets engagement (farm)
and one Coda engagement (vizcarra-guitars) — are now generated Django apps they
use day-to-day, and the consultant playbook for repeating that outcome is
proven.**

`1.0.0` is a **product and business milestone**, not an engine completeness
milestone. The engine reached capability-readiness at `0.9.4`; the engagements
still have specification enrichment, validation, parallel runs, and cutover
work to do. That work is mapped in [product-roadmaps.md](product-roadmaps.md).

This means:

1. **Process is documented end-to-end** — a consultant can follow a written
   runbook from first client call to deployed app.
2. **Delivery time is predictable** — the consultant can promise a timeline
   and hit it (±20%).
3. **Quality is certified** — the smoke test suite passes for the delivered
   app, and the consultant can point to a certification process.
4. **Each engagement makes the next one faster** — judgment taxonomy
   accumulates patterns; the archetype classifier improves with every
   vertical.
5. **Tooling supports the consultant, not replaces them** — confidence gates
   enforce human review at appropriate thresholds.
6. **Both engagements are validated, end-to-end, on generated UI** — the
   chassis has replaced tabular systems on two distinct domains (farm +
   vizcarra-guitars), proving generality across both Google Sheets and Coda.
   Farm's hand-written `farm_ui/` proved the UI patterns; the workbench must
   generate the views that replace both farm's spreadsheet and Vizcarra's Coda
   doc. 1.0.0 requires both cut-overs to be complete.

**Non-goals for 1.0.0:** self-service migration, multi-tenant hosting,
real-time sync, non-Django targets, Postgres at scale, plugin ecosystem.

---

## Current Work: 0.6.0+ — Two Tracks Converge on 1.0.0

**Track A (Coda engagement validation)** hardens the Vizcarra Guitars Coda
engagement for cut-over. Each Track A milestone earns a minor by validating
one segment against real Vizcarra data.

**Track B (UI codegen extraction + farm cut-over)** extracts the UI patterns
farm's hand-written `farm_ui/` proved, turns them into workbench codegen, and
applies that codegen back to farm to retire the farm spreadsheet. Farm is both
the proving ground and the first cut-over target.

`farm_ui/` has 15 templates, 5 view modules, role landings, weekly checklists
with HTMX toggles, dashboards, print views — all hand-written. The MWBS
schema (`profiler/tools/behavioral_spec.py`) already ships the semantic
input for UI generation: `Actor`, `JobStory`, `WorkflowStep`,
`BehavioralEvent`, `BusinessRule`, `Report`, `AcceptanceCriterion`. Nothing
in `workbook/codegen/` consumes it (`model_generator.py`,
`admin_generator.py`, `import_generator.py` — no `view_generator` or
`template_generator`). Track B closes that gap. Each Track B milestone earns
a patch (validated on farm) that feeds into the next engagement.

### Milestone Table

| Version | Track | Mission | Proves | Test target |
|---------|-------|---------|-------|-------------|
| 0.5.3   | A     | `coda-relation-column-profiler` + `coda-formula-classification` | Coda profiler reads relation columns and formula taxonomy (unit-tested) | workbench |
| 0.6.0   | A     | `vizcarra-profile-clients` | Coda profiler produces a valid contract against real data | vizcarra-guitars |
| 0.6.1   | B     | `wb-checklist-archetype` | Weekly checklist + HTMX toggle extractable from a contract + view manifest | farm |
| 0.6.2   | A     | `vizcarra-generate-import` | Codegen + import pipeline on Coda-sourced data; row counts match | vizcarra-guitars |
| 0.6.3   | B     | `wb-landing-archetype` | Role-based landing + summary cards generated from behavioral spec actors | farm |
| 0.7.1   | A     | `vizcarra-views-deploy` | View manifest + admin + deploy — full stack on Coda | vizcarra-guitars |
| 0.7.2   | B     | `wb-dashboard-archetype` | Dashboard with alert counts generated from behavioral reports | farm |
| 0.7.3   | B     | `wb-view-codegen-pipeline` | New `wb generate views` command, template package, product-skin override blocks; wired into `generate-all` | farm |
| 0.8.1   | A     | `vizcarra-generated-ui` | Vizcarra consumes the view codegen pipeline | vizcarra-guitars |
| 0.8.2   | A     | `vizcarra-people-type` | Coda People columns map to Django users; ownership/audit fields resolve correctly | vizcarra-guitars |
| 0.8.3   | A     | `vizcarra-formula-parity` | Business-critical Coda formulas match generated computed fields on real records | vizcarra-guitars |
| 0.8.4   | A     | `vizcarra-import-pipeline` | Repeatable, reconciled Coda→Django import pipeline; row counts and key totals match | vizcarra-guitars |
| 0.8.5   | B     | `farm-behavioral-codegen` | Views generated directly from MWBS behavioral spec | farm |
| 0.8.6   | B     | `farm-workflow-coverage` | All farm spreadsheet workflows mapped to generated views | farm |
| 0.8.7   | B     | `farm-data-migration` | Real farm spreadsheet data imported/reconciled | farm |
| 0.9.4   | —     | `cutover-prep` | Joint dry-run, readiness checklist, runbook, and go/no-go for both engagements | farm + vizcarra |
| 1.0.0   | —     | `cutover` | Both farm spreadsheet and Vizcarra Coda doc retired in the wild | farm + vizcarra |

Patch numbers under each collision-free minor absorb the granular fixes real
data surfaces. See *Semver Recovery* for why `0.7.0`, `0.8.0`, and
`0.9.0`–`0.9.3` are skipped.

### Post-0.9.4 product milestones

`0.9.4` proved the workbench engine was capable of supporting both
engagements. The engagements themselves still need specification enrichment,
validation, parallel runs, and cutover. Those milestones live in
[product-roadmaps.md](product-roadmaps.md); the engine versions that validate
them are recorded here.

| Version | Track | Mission | Proves | Test target |
|---------|-------|---------|-------|-------------|
| 0.10.0  | A     | `vizcarra-acceptance-validation` | Every signed-off workflow can be completed in the generated app; acceptance criteria pass; drift check clean | vizcarra-guitars |
| 0.10.0  | B     | `farm-behavioral-elicitation` | Real actors, workflows, decisions, exceptions, rules, reports, and acceptance criteria signed off by farm team | farm |
| 0.11.0  | A     | `vizcarra-parallel-run` | One week of live parallel use next to Coda with no blocking defects | vizcarra-guitars |
| 0.11.0  | B     | `farm-interaction-contract` | Weekly actions, status transitions, alerts, and workflow-to-view mapping complete | farm |
| 0.12.0  | A     | `vizcarra-coda-retired` | Coda doc is read-only; team uses Django app for all workflows | vizcarra-guitars |
| 0.12.0  | B     | `farm-generated-views-wired` | Generated views replace hand-written `farm_ui/` views for core workflows; real-data parity tests pass | farm |
| 0.13.0  | A     | `vizcarra-operational-maturity` | Print tags, alert tuning, mobile workflows validated post-cutover | vizcarra-guitars |
| 0.13.0  | B     | `farm-data-reconciliation` | Latest spreadsheet bundle imports and reconciles cleanly | farm |
| 0.14.0  | B     | `farm-spreadsheet-retired` | Google Sheets are read-only archive; team uses Django app for full weekly cycle | farm |
| 0.15.0  | B     | `farm-operational-maturity` | CSV/print views, mobile field checklist, performance, alert tuning validated post-cutover | farm |
| 1.0.0   | —     | `product-market-fit` | Both engagements retired; consultant playbook proven; engine ready for third engagement | farm + vizcarra |

The A and B tracks now advance independently. A workbench minor is earned
when either track completes its milestone against real product data.

### Semver policy

| Bump | Criteria |
|------|----------|
| **Patch** 0.x.y+1 | Code written, unit-tested, `make chassis-gate` green. **Not validated against real data.** Bug fixes, docs, internal completions, archetype extractions proven only on the source engagement. |
| **Minor** 0.x+1.0 | A capability **proven end-to-end against real data in a product repo**. The minor is *earned by validation*, not by adding code. Code alone is a patch. `x` is an integer: after `0.9.x` comes `0.10.0`, `0.11.0`, etc. |
| **1.0.0** | Both engagements retired per their product roadmaps; the consultant playbook is proven; the workbench is ready to support a third engagement without heroic effort. |

The core inversion: **minors are not for features, they are for proven
product capabilities.** The 0.5.3 Coda work is a patch because it is unit-tested
only. `vizcarra-profile-clients` running cleanly against real Vizcarra data is
what earns 0.6.0. The post-0.9.4 minors are defined in
[product-roadmaps.md](product-roadmaps.md).

---

## Semver Recovery (PyPI Block)

The changelog has two interleaved version series. The **legacy series**
(`0.1.0` → `0.1.3` → `0.7.0` → `0.8.0` → `0.9.0` → `0.9.3`) was released
to PyPI; its early numbering jumped from `0.1.3` straight to `0.7.0`. Later
development **reset** local numbering via `v0.0.9` and climbed
`0.2.0` → `0.3.0` → `0.3.1` → `0.4.x` → `0.5.x` → `0.5.3`.

**Consequence:** PyPI's highest published version is `0.9.3`. The local
package version is `0.5.3`. PyPI rejects any upload whose version is
`<= 0.9.3`.

**Until we catch up, releases are local-only** (tagged in git for the
operator, not pushed to PyPI). We catch up monotonically:

- Local tags continue from `0.5.3` upward, skipping any number that
  collides with a legacy git tag: `0.7.0`, `0.8.0`, `0.9.0`, `0.9.1`,
  `0.9.2`, `0.9.3`.
- The `0.6.x` range is entirely free — `0.6.0` through `0.6.3` are the
  next minors.
- After `0.6.x`, the next free numbers are `0.7.1`+ (skipping `0.7.0`),
  `0.8.1`+ (skipping `0.8.0`), `0.9.4`+ (skipping `0.9.0`–`0.9.3`),
  then `0.10.0`, `0.11.0`, and so on. `1.0.0` is reserved for the product
  market-fit milestone defined above.
- The first PyPI-publishable release is **`1.0.0`** — the first version
  that exceeds `0.9.3` and meets the 1.0.0 definition.
- Patch numbers under each collision-free minor are fine (e.g. `0.7.1`,
  `0.7.2`; `0.7.0` is the only collision in that series).
- Minors are integers: `0.10.0` is valid and follows `0.9.x` naturally.

The full changelog in `README.md` is a single reverse-chronological
timeline. The legacy numbers stand — we do **not** rewrite git history. Once
the local series reaches `1.0.0` and continues monotonically past `0.9.3`,
PyPI uploads resume.

Until then: **the package is in remediation. The local version is below
PyPI's latest by design.**

---

## Dependency Graph

```
Engine (workbench)                    Engagement A (Vizcarra)              Engagement B (farm)
0.9.4 engine-ready                    0.10.0 acceptance-validation          0.10.0 behavioral-elicitation
     │                                      │                                    │
     │                                      ▼                                    ▼
     │                                0.11.0 parallel-run                0.11.0 interaction-contract
     │                                      │                                    │
     │                                      ▼                                    ▼
     │                                0.12.0 coda-retired                 0.12.0 generated-views-wired
     │                                      │                                    │
     │                                      ▼                                    ▼
     │                                0.13.0 operational-maturity          0.13.0 data-reconciliation
     │                                                                               │
     │                                                                               ▼
     │                                                                          0.14.0 spreadsheet-retired
     │                                                                               │
     │                                                                               ▼
     │                                                                          0.15.0 operational-maturity
     │                                      │                                    │
     └──────────────────────────────────────┴────────────────────────────────────┘
                                                 │
                                                 ▼
                                           1.0.0 product-market-fit
```

Track A validates the pipeline on a Coda-sourced engagement. Track B extracts
UI patterns from farm's hand-written `farm_ui/`, hardens them into workbench
codegen, and then applies that codegen back to farm. The two tracks run in
parallel after 0.9.4. The engagement milestones are defined in
[product-roadmaps.md](product-roadmaps.md); each product-validated milestone
earns the corresponding workbench minor. Both engagements must reach
retirement before `1.0.0`. Cross-cutting workbench capabilities (e.g.,
`wb drift check`, acceptance-test runner, print-view archetype) are pulled
forward by whichever engagement needs them first.

**Track status after 0.9.4:** The engine is ready. The workbench can profile,
codegen, import, and serve views against both Coda and Sheets data. Both
engagements have completed the engine-side validation missions (Vizcarra
0.8.1—0.8.4; farm 0.8.5—0.8.7). The next work is **product-side**: spec
enrichment, validation, parallel runs, and cutover for each engagement. The
Vizcarra session of 2026-07-14 proved that even after the engine is "ready,"
specification enrichment can be substantial (6→18 tables, 2→39 views, 0→2186
transaction rows, full MWBS sign-off). Product milestones now own the
timeline. If a product mission surfaces workbench gaps, they are fixed
upstream and the product repo's version pin is bumped per the patching
boundary contract.

---

## Shipped

### 0.4.0 → 0.5.3 — Spreadsheet replacement + moat

Admin generator produces production-grade output: status transitions,
role-appropriate views, year/week filtering, proper field-level validation.
Interaction contract merge path complete. Historical import loop proven
across 5+ years. Formula dependency graph (networkx) for cross-sheet FK
inference. Vertical template system (farm) for entity defaults, scoring
heuristics, schema contract templates. Coda profiler with relation column
detection and formula classification. 1620 chassis-gate tests pass.

### 0.1.0 → 0.3.0 — Pipeline proven on real data

Profile→model→codegen→import→deploy pipeline exercised end-to-end on 56
workbooks, 239 tabs, 11-model schema contract. PipelineState checkpointing,
schema contract scaffolding, codegen, import runtime, view manifest,
discovery interviews, and Fly.io deployment all function on real data.

### 0.0.x — Component assembly

Every piece of the pipeline exists in isolation. Profiler works. Codegen
works. Import runtime works. They have not yet been coupled end-to-end on
real data. See git history for the 0.0.x changelog.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Coda data is too messy for clean profile | Medium | High | Profiler already reads relation columns and formula taxonomy (0.5.3). Vizcarra is the gate. |
| Workbench has hidden Sheets-specific assumptions | Medium | High | Track A (Vizcarra) exists specifically to catch this. |
| UI archetypes extracted from farm are too farm-specific | Medium | High | Track B extraction briefs require generic templates with product-skin override blocks. |
| Solo consultant time is the bottleneck | Certain | High | The workbench exists to amplify consultant time. Generated UI is the largest single force multiplier. |

---

## Post-1.0.0 Horizons

Directions the roadmap points toward after cold-client readiness is proven:

- **1.x** — Third engagement; prospecting assessment tool.
- **2.x** — Hosted consultant console; multi-client dashboard.
- **3.x** — Self-service feasibility report for prospects; referral network.

---

## How the farm exercise shaped this roadmap

| Discovery | Response |
|-----------|----------|
| Hand-authored 663-line contract was repetitive | Contract scaffolding, hooks system, designed model helpers |
| Issue #01: admin regeneration overwrites customizations | Stub convention with `# --- custom models below this line ---` |
| No systematic capture of consultant decisions | Behavioral spec (MWBS) with elicitor, sign-off gate, coverage map |
| **Hand-written `farm_ui/` is the engagement bottleneck, and farm's own spreadsheet is not yet retired** | **Track B: extract UI archetypes as workbench codegen, then apply that codegen back to farm to retire its spreadsheet** |

---

## Tracking

Mission briefs live in `.pi/missions/<slug>/brief.md` in this repo and the
equivalent coordination directory in product repos (the harness chooses the
path; see AGENTS.md). This document is updated when milestones ship or
priorities shift.