# migration-workbench Roadmap

Version history and direction.

```
0.0.x             Component assembly              ← shipped
0.1.0             Pipeline proven on real data    ← shipped
0.2.0             Spreadsheet replacement         ← shipped
0.3.0             Vertical migration templates    ← shipped
────────────────────────────────────────────────────────
0.4.0 – 0.5.0     Product validation + moat       ← current work
1.0.0             Cold-client ready               ← target
```

## Definition of 1.0.0

**A solo consultant can offer service to a cold client with a repeatable, promisable contract.**

This means:

1. **Process is documented end-to-end** — a consultant can follow a written runbook from first client call to deployed app.
2. **Delivery time is predictable** — the consultant can promise a timeline and hit it (±20%).
3. **Quality is certified** — the smoke test suite passes for the delivered app, and the consultant can point to a certification process.
4. **Each engagement makes the next one faster** — judgment taxonomy accumulates patterns; the archetype classifier improves with every vertical.
5. **Tooling supports the consultant, not replaces them** — confidence gates enforce human review at appropriate thresholds.
6. **Second vertical is validated** — the chassis has been exercised on at least two distinct domains (farm + one other), proving generality.

**Non-goals for 1.0.0:** self-service migration, multi-tenant hosting, real-time sync, non-Django targets, Postgres at scale, plugin ecosystem.

---

## Shipped

### 0.0.x — Component assembly

Every piece of the pipeline exists in isolation. Profiler works. Codegen works.
Import runtime works. They have not yet been coupled end-to-end on real data.

Contents unchanged from previous version. See git history for full 0.0.x changelog.

### 0.1.0 — Pipeline proven on real data

The profile→model→codegen→import→deploy pipeline exercised end-to-end on 56 workbooks, 239 tabs, 11-model schema contract. PipelineState checkpointing, schema contract scaffolding, codegen, import runtime, view manifest, discovery interviews, and Fly.io deployment all function on real data.

### 0.2.0 — Spreadsheet replacement

Admin generator produces production-grade output: status transitions, role-appropriate views, year/week filtering, proper field-level validation. Interaction contract merge path complete. Historical import loop proven across 5+ years. 922+ tests pass.

### 0.3.0 — Vertical migration templates

Template system for extracting reusable presets per vertical: domain context vocabulary, entity defaults, scoring heuristics, schema contract templates, interaction contract defaults, import error patterns. First vertical template (farm) extracted at v0.1.0 exploratory confidence. 959 chassis-gate tests pass.

---

## Current Work: 0.4.0–0.5.0 — Product validation + moat

The chassis runs. The first product (farm) is partially built but not yet a complete, validated reference. The judgment taxonomy exists only as a concept. The queue protocol coordinates agents but has no lifecycle enforcement.

These milestones close those gaps. They are ordered by dependency — each phase produces something the next phase needs.

### Phase 0: Harden ecosystem protocol

**Before any feature work, the coordination layer must be reliable.**

The current queue protocol (ecosystem.md) defines *what* the queues are but not *how* entries get created, consumed, archived, or monitored. This causes silent failures: a `next/` signal written but never read, a `ready/` signal never noticed, a stale `exercise/` signal hanging indefinitely.

**Deliverables:**

1. **Queue entry lifecycle** — every queue entry has four states with timestamps:
   ```
   created → active → consumed → archived
   ```
   Each transition is recorded. Timeouts for each state are configurable. Stale entries are flagged, not silently ignored.

2. **Validation gate on write** — writing to any queue validates the entry format against its schema (required fields, allowed values, reference integrity). Malformed entries are rejected, not silently dropped.

3. **Health check command** — `wb ecosystem health` inspects all queues and reports:
   - Number of entries per queue
   - Age of oldest unconsumed entry
   - Stale entries past timeout
   - Last successful write time per queue
   - Cross-queue consistency (e.g., every `results/` has a matching `exercise/`)

4. **Consumption acknowledgement** — readers must acknowledge consumption of queue entries. Entries that go unacknowledged past timeout are escalated.

5. **Updated ecosystem.md** — protocol documented with lifecycle states, validation rules, health check.

**Why this comes first:** If the orchestration layer is unreliable, every feature built on top of it is untrustworthy. The feedback loop (Phase 3) depends on reliable queue transitions.

---

### Phase 1: Ship farm as a complete product

Farm is the reference product. Until it ships end-to-end, the chassis is unvalidated and the taxonomy has no training data.

**Deliverables:**

1. **Fix farm test suite** — the 5 failing feature tests (issue #01 fallout) are repaired. All 7 feature tests + 10 smoke tests pass.

2. **Farm v0.3.0 admin functional** — smoke tests pass, admin renders correctly, status transitions work, role views show correct fields. Emit `ready/` signal for vertical templates.

3. **Farm v0.4.0 user-facing UI** — HTMX-based landing pages per role, dashboard views, navigation. Full app-replaces-spreadsheet experience for farm operators.

4. **Validation cycle closes** — exercise signal → integrate → smoke test → results signal. First complete pass of the hardening loop on a real product.

5. **Updated farm documentation** — reflect current state, not stale v0.1.0 assumptions.

**Why this comes before moat infrastructure:** The moat needs data. Farm is the first source of judgment taxonomy entries. Without a shipping product, the taxonomy has nothing to catalog.

---

### Phase 2: Judgment taxonomy registry

The accumulated pattern library of which signals → which archetypes → which admin behaviors work for which verticals. This is the defensible moat.

**Design principles:**
- **Capture, don't dictate** — records consultant decisions without prescribing them. The taxonomy grows organically from real decisions.
- **Queriable, not just logged** — a consultant can ask "what happened last time we saw this signal pattern?"
- **Confidence-gated** — every entry has a confidence score. Low-confidence entries require human review before reuse.

**Deliverables:**

1. **Taxonomy schema** — what gets captured:
   ```yaml
   vertical: farm                          # domain
   source_signals:                         # profiler input
     ui_archetype: form
     formula_density: 0.23
     cross_sheet_refs: 3
     null_rates: { "Crop Name": 0.0 }
   archetype_chosen: form                  # decision
   confidence: 0.85                        # how sure we were
   outcome: successful                     # did it work? (awaiting feedback)
   consultant_notes: "Field managers needed inline editing"
   deployed_at: "2026-06-01"
   feedback_received: null                 # populated by feedback loop
   ```

2. **Taxonomy CLI** — `wb taxonomy {add,query,review,export}`:
   - `add` — record a new pattern from a completed engagement
   - `query` — search patterns by vertical, signal, archetype, outcome
   - `review` — show patterns pending human review (confidence < 0.50)
   - `export` — produce a training set for the archetype classifier

3. **Taxonomy storage** — YAML file at `.omo/taxonomy/registry.yaml`, versioned alongside code. This makes the taxonomy part of the repo — reviewable, diffable, mergeable.

4. **Integration with v0.4.0 archetype matrix** — the weighted 12-signal classifier writes its decisions to the taxonomy. Every archetype assignment is captured.

**Why this is the moat:** AI can generate Django admin code. It cannot know that farm field managers need inline editing while guitar shop inventory managers need location-based dashboards. That knowledge comes from doing, and the taxonomy captures it.

---

### Phase 3: Feedback loop from deployed apps

A one-time interview (interaction contract) captures intent. A feedback loop captures reality — how operators actually use the generated app, and where it falls short.

**Deliverables:**

1. **Deploy-time instrumentation** — every deployed app includes a lightweight feedback endpoint (`/healthz` extended with usage signals). On deploy, the consultant console registers the app for monitoring.

2. **Usage signal schema** — what gets reported back:
   ```yaml
   app: farm
   environment: production
   period: "2026-W24"
   archetype_usage:
     form: { views: 1240, edits: 312, errors: 3 }
     list: { views: 4200, filters_applied: 890, exports: 45 }
     dashboard: { views: 580, avg_time_seconds: 45 }
   taxonomy_corrections:
     - tab: "Crop Planner"
       assigned_archetype: form
       observed_usage: "list-heavy"   # users treat it as a list view
       suggested_archetype: list
   ```

3. **Feedback ingestion** — `wb feedback ingest` reads signals, compares against taxonomy predictions, flags mismatches as curation entries for the consultant.

4. **Curation workflow** — mismatches appear in the consultant console as "pending review." The consultant can:
   - Accept the correction → taxonomy updated
   - Reject as noise → taxonomy annotated
   - Escalate to design change → new issue

**Why this matters:** The interaction contract captures what operators *say* they do. Usage data captures what they *actually* do. The gap between them is where the taxonomy gets refined.

---

### Phase 4: Consultant console

A tool for the solo consultant to manage clients, review confidence decisions, curate the taxonomy, and run deployments. Not a GUI for end-users — a cockpit for the operator.

**Deliverables:**

1. **Client registry** — `wb client {list,show,add}` with:
   - Name, vertical, deployment status, last smoke test date
   - Link to product repo and deployed URL
   - Taxonomy patterns contributed by this engagement

2. **Confidence review queue** — views all taxonomy entries with confidence < 0.50 or pending feedback correction. The consultant can review in batch, approve/reject, or write notes.

3. **Dashboard view** — summary:
   - Number of active clients
   - Number of taxonomy entries
   - Pending reviews
   - Queue health (from Phase 0)
   - Latest smoke test results

4. **Integration with quality gate** — before marking a client as "certified," the console checks that the smoke test suite passes and the judgment taxonomy has ≥1 entry for this vertical.

**Implementation approach:** CLI-first (extending `wb`), with the option of a web dashboard later. Phase 4 delivers the CLI. A web UI is post-1.0.0.

---

### Phase 5: Validate on a second vertical

The chassis is exercised on **vizcarra-guitars** (from spaces.yml). This proves generality and seeds the taxonomy with a second domain.

**Deliverables:**

1. **Scaffold vizcarra-guitars product repo** — run `new_product.py` with the vizcarra-guitars vertical template.

2. **Full pipeline on guitar shop data** — profile → schema contract → codegen → import → deploy. Use the consultant console to manage the engagement.

3. **Cross-vertical taxonomy** — guitar shop patterns are distinct from farm patterns. The taxonomy now has two domains, making cross-vertical queries meaningful.

4. **Chassis refinements** — any chassis gap found during vertical #2 is fixed upstream (following the patching boundary in AGENTS.md).

5. **Updated delivery time estimate** — vertical #2 takes N hours. The difference between vertical #1 (farm, ad-hoc) and vertical #2 (repeatable process) is the productivity improvement from the ecosystem.

**Why not skip to vertical #2 immediately:** Without the moat infrastructure (Phases 2-4), vertical #2 is just another ad-hoc engagement. The point is to *validate the repeatable process*, not just build another app.

---

### Phase 6: 1.0.0 release

**Definition of done — cold-client ready:**

| Criterion | How verified |
|-----------|-------------|
| Farm is a complete product | Admin + user UI deployed, smoke tests pass, feedback endpoint live |
| Second vertical is scaffolded | Full pipeline run on vizcarra-guitars, all steps documented |
| Ecosystem protocol is reliable | Queue lifecycle enforced, health check passes, stale entries caught |
| Judgment taxonomy is seeded | ≥50 entries across 2+ verticals, ≥1 feedback correction absorbed |
| Consultant console operates | Client registry, confidence review, quality gate integration all work |
| Chassis-gate passes | 959+ tests green on migration-workbench |
| Onboarding runbook exists | Written process from cold call to deployed app, with time estimates per phase |
| All smoke tests pass | 10-test suite passes on farm |
| Documentation is current | roadmap.md, ecosystem.md, AGENTS.md, all design docs reflect reality |
| Second vertical validates repeatability | vizcarra-guitars is built, deployed, and passes its own smoke tests |

**Non-goals for 1.0.0 (deferred to post-1.0.0):**
- Self-service prospect assessment ("upload your spreadsheet")
- Hosted multi-tenant consultant console (web UI)
- Third vertical (jewelry)
- Postgres support
- Real-time sync back to source
- Plugin ecosystem for providers

---

## Dependency Graph

```
Phase 0 (ecosystem hardening)
    │
    ▼
Phase 1 (ship farm)
    │
    ├─────────────────────┐
    ▼                     ▼
Phase 2 (taxonomy)   Phase 3 (feedback loop)
    │                     │
    └─────────┬───────────┘
              ▼
      Phase 4 (consultant console)
              │
              ▼
      Phase 5 (second vertical)
              │
              ▼
      Phase 6 (1.0.0 release)
```

Phases 2 and 3 can proceed in parallel after Phase 1 is underway.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Farm data is too messy for clean product | Medium | High | Already profiled 56 workbooks — the hard part is done. Remaining risk is admin polish. |
| Chassis has hidden farm-specific assumptions | Medium | High | Second vertical (Phase 5) exists specifically to catch this. |
| Taxonomy has too few entries to be useful | High | Medium | Even 50 entries across 2 verticals are enough to start seeing patterns. The value compounds. |
| Feedback loop reveals nobody uses the app | Low | Very High | If farm operators don't use the generated app, the approach is wrong. Mitigation: validate early with real users. |
| Solo consultant time is the bottleneck | Certain | High | The entire ecosystem exists to amplify consultant time. Console + taxonomy are force multipliers. |
| AI codegen improves faster than taxonomy grows | Medium | Very High | The moat is experiential knowledge (what to build, not how). AI codegen helps, doesn't threaten, this. |

---

## Post-1.0.0 Horizons

These are not commitments — they are directions the roadmap points toward after cold-client readiness is proven:

- **1.x** — Third vertical (jewelry), prospecting assessment tool, repeatable sales process
- **2.x** — Hosted web console, multi-client dashboard, feedback loop fully automated
- **3.x** — Self-service feasibility report for prospects, referral network

---

## How the farm exercise shaped this roadmap

Every item in "Shipped" and every phase in "Current Work" has a direct line to something discovered while building the first product repo.

| Discovery | Response |
|-----------|----------|
| Hand-authored 663-line contract was repetitive | Contract scaffolding, hooks system, designed model helpers |
| Issue #01: admin regeneration overwrites customizations | Stub convention with `# --- custom models below this line ---` |
| Queue protocol has no lifecycle enforcement | Phase 0: ecosystem hardening |
| No systematic capture of consultant decisions | Phase 2: judgment taxonomy registry |
| No way to know if deployed apps work well | Phase 3: feedback loop |
| Solo consultant needs a cockpit, not just CLI | Phase 4: consultant console |
| One vertical doesn't prove the chassis | Phase 5: second vertical validation |

---

## Tracking

Individual items are tracked in `.omo/plans/` as implementation plan documents.
This document is updated when milestones ship or priorities shift.
