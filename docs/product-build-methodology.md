# Product Build Methodology

> **Status:** Design spec
> **Audience:** Pipeline operators building a product app to replace a
> spreadsheet or Coda doc
> **Prerequisite reading:** [Pipeline State](pipeline-state.md),
> [Schema Contract Reference](schema-contract.md),
> [Interaction Contract](interaction-contract.md),
> [View Manifest Reference](view-manifest.md)

## The problem this solves

The workbench ships a specification pipeline: profile → domain knowledge →
schema contract → behavioral spec → interaction contract → view manifest →
codegen. Each layer has a well-defined format (MWBS dataclasses, YAML
artifacts, checkpoint gates) and a code generator that consumes it.

Building the workbench's *capabilities* — proving each generator works
against real data — takes you to 0.9.4. The profiler reads relation
columns. The codegen emits ForeignKeys. Views render from a manifest.
Import pipelines reconcile 27 000 rows with zero errors. `make
chassis-gate` is green.

But **the generated app is only as deep as the specification that drives
it.** And the specifications produced during capability-building are
mechanically inferred: actors derived from tab names, events from column
headers, workflows left empty. The structures exist. The content is
shallow.

A human cannot do their job with the generated app until the
specifications capture *what humans actually do* with the spreadsheet.
That requires populating the spec layers with real knowledge — roles,
workflows, decisions, exceptions, acceptance criteria — to the depth
where the codegen produces a complete application.

**This document defines the methodology for that work.** It is the bridge
between "the workbench works" and "the spreadsheet is retired."

## Core principle: the spec is the artifact

Every product app is generated from a stack of specification artifacts.
When the generated app falls short, the fix is **always** in the spec, not
in the generated code. Patching a generated Django template is a symptom
that the specification didn't capture something.

The specification stack, from bottom to top:

```
PipelineState checkpoint     →   What data exists, which tabs are in scope
Domain Knowledge             →   Vocabulary, entities, business concepts
Schema Contract              →   Models, fields, types, FK targets, import keys
Behavioral Spec (MWBS)       →   Actors, workflows, job stories, decisions, exceptions
Interaction Contract         →   Role-based weekly actions, status transitions, alerts
View Manifest                →   Specific views mapped to workflows (lists, forms,
                                 dashboards, checklists, print views)
Codegen Manifest             →   Machine-derived execution plan consumed by generators
```

Each layer builds on the one below it. A view manifest entry references a
workflow from the behavioral spec. A workflow references an actor. An
actor's responsibilities constrain the interaction contract. The schema
contract provides the data model that every view operates on.

The methodology is: **enrich each layer to completion before moving to the
next, regenerating at every step to surface gaps early.**

## The phases

Each phase has:
- **Input:** which spec artifacts it consumes
- **Tooling:** which workbench commands and Make targets drive it
- **Output:** which spec artifacts it enriches or produces
- **Acceptance criteria:** what "done" means for that layer

### Phase 0 — Profile and baseline

The mechanical baseline. The profiler reads the source system and produces
the initial PipelineState checkpoint. No human enrichment yet — this
establishes what the spreadsheet *contains*.

| Aspect | Detail |
|--------|--------|
| **Input** | Source system (Google Sheets folder ID, Coda doc URL), `cohort_corpus.json` config |
| **Commands** | `make profile-phase-discover`, `make profile-phase-score`, `make profile-phase-deep`, `make profile-phase-derive` |
| **Output** | `build/pipeline-state.yaml` (discovery state, approved tabs, deep profile index), initial `build/schema-contract.yaml`, initial `build/behavioral-spec.yaml` |
| **Done when** | PipelineState checkpoint exists with `approved_tabs` reviewed by a human. Every tab in the source is classified as in-scope or out-of-scope. Initial schema contract parses. Initial behavioral spec parses (even if shallow). |

The human gate at this phase is **tab selection** — which tabs are
operational data, which are reference, which are noise.

### Phase 1 — Domain Knowledge

The human enriches the vocabulary, entities, and business concepts that
the profiler uses for scoring and the codegen uses for naming.

| Aspect | Detail |
|--------|--------|
| **Input** | `config/domain_context.yaml` (may not exist yet — create from `docs/domain-knowledge.example.yaml`) |
| **Commands** | `make draft-domain-context`, `make validate-domain-context` |
| **Output** | Enriched `config/domain_context.yaml`: domain identifier, operational/reference/support vocabulary, year scope, deduplication strategy, entity definitions with field types and import keys, glossary of synonym expansions |
| **Done when** | Every business entity has a canonical name, a list of source tabs, and at minimum: field names with Django types, an import key, and known FK targets. The glossary covers every column header abbreviation found in the source. |

This is the layer where "Crop Planner tab" becomes "the `CropPlan` entity
with fields `crop` (FK→Crop), `planned_week` (IntegerField), `quantity`
(IntegerField), import key `[crop, planned_week]`."

If entity definitions are incomplete, the schema contract will be
incomplete — no FK targets, no import keys, model names derived from tab
titles instead of business concepts.

### Phase 2 — Schema Contract

The schema contract is the data-model contract. It specifies every model,
every field, every FK target, and every import key. It is consumed by
`generate-models`, `generate-admin`, and `generate-import`.

| Aspect | Detail |
|--------|--------|
| **Input** | `build/pipeline-state.yaml` (deep profile), `config/domain_context.yaml` (entities), `build/behavioral-spec.yaml` (events inform computed fields) |
| **Commands** | `make scaffold-schema` (initial), `make validate-contract`, `make generate-models`, `make generate-admin`, `make generate-import` |
| **Output** | Certified `build/schema-contract.yaml` (or `build/schema-contract-certified.yaml`), generated `models_auto.py`, `admin_auto.py`, import command |
| **Done when** | Every column in every approved tab has a field in the schema contract. Every FK relationship is resolved (no `TODO_TargetModel`). Compound import keys are defined for tables that need them. Computed fields are flagged with their expressions. The contract validates. `generate-models` produces a runnable `models_auto.py`. |

The schema contract is the most mature specification layer in the
workbench. The gap here is usually not format but completeness — columns
that were missed, FK relationships not detected, import keys not defined
for tables with natural compound keys.

### Phase 3 — Behavioral Specification (MWBS)

**This is the critical layer.** The behavioral spec captures what humans
*do* with the data: who they are, what workflows they execute, what
decisions they make, what exceptions they handle. The MWBS schema has all
the structures; the work is populating them with real knowledge.

The behavioral spec has seven top-level sections:

| Section | Description | Mechanical baseline | Target state |
|---------|-------------|---------------------|--------------|
| `actors` | Business participants with responsibilities, time pressures, access levels | Tab names with `"Manage <name>"` | Real human roles (e.g. "Field Manager," "Pack House Lead") with actual responsibilities |
| `events` | Discrete, named, past-tense business facts with typed payloads | Column names with inferred types | Real business events (e.g. "Planting Completed," "Harvest Logged") with real payload fields |
| `workflows` | Complete workflow specs: job stories, steps, inputs, decisions, exceptions, acceptance tests | 1 placeholder workflow | 15–20 real workflows, each with a job story a human would recognize |
| `decisions` | Human judgment points within workflows | Empty | Every place a human makes a choice that changes what happens next |
| `exceptions` | Documented exception paths: condition, severity, detection, response | Empty | Every "if this goes wrong, do that" the spreadsheet currently handles informally |
| `rules` | Workflow-independent business constraints | Empty | Cross-cutting rules like "a field block cannot host two crops simultaneously" |
| `reports` | Operational report artifacts that support specific decisions | Empty | Print views, weekly summaries, anything someone prints or screenshots today |

Each workflow has a rich structure:

```yaml
workflows:
- id: monday_field_walk
  title: Monday Field Walk
  job_story:
    when: "Monday morning, before the crew arrives"
    i_need_to: "review every active field block and record crop stage, pest pressure, and task needs"
    so_i_can: "print the week's task list and adjust the planting schedule"
  actor: field_manager
  frequency: weekly
  peak_pressure: "Monday 6:00–7:30 AM, before crew briefing at 8:00"
  operational:
    max_duration_minutes: 90
    spreadsheet_access: "laptop at the pack house, then printed lists in the field"
    mobile_required: false
    offline_required: true
  steps:
    - id: print_field_list
      title: Print active field list
      actor_action: "Print the Field Record tab filtered to this week's active blocks"
      system_provides: ["List of all field blocks with crop, planting date, days since planting"]
    - id: walk_blocks
      title: Walk every active block
      actor_action: "Walk each block, observe crop stage, note any pest or disease pressure"
      contains_decision: "block_needs_action"
      emits: "field_observation"
  decisions:
    - id: block_needs_action
      title: Does this block need action this week?
      description: "Based on crop stage, pest pressure, and days since last cultivation"
      information_system_must_provide:
        - "Crop stage at last observation"
        - "Days since planting"
        - "Days since last cultivation"
        - "Current pest pressure (if any)"
      outcome_recorded_as: "FieldRecord.status"
  exceptions:
    - id: pest_outbreak
      title: Pest pressure exceeds threshold
      condition: "Pest observation count > action threshold for crop type"
      severity: blocking
      current_handling: "Call owner directly; do not wait for weekly review"
  acceptance_tests:
    - id: field_walk_completeness
      type: coverage
      description: "Every active field block has an observation record for the current week"
      assertion: "COUNT(FieldRecord WHERE week = current_week) >= COUNT(FieldBlock WHERE status = 'active')"
```

| Aspect | Detail |
|--------|--------|
| **Input** | `config/domain_context.yaml`, `build/pipeline-state.yaml` (deep profile), initial `build/behavioral-spec.yaml` (mechanical baseline), `build/interaction-contract.yaml` if it exists |
| **Commands** | `make generate-discovery-interview` (generates elicitation questionnaire from profiler signals), human conducts interview, `make merge-discovery-notes` |
| **Output** | Enriched `build/behavioral-spec.yaml` with real actors, workflows, decisions, exceptions, rules, reports, acceptance tests. `build/interaction-contract.yaml` with role-based weekly actions. |
| **Done when** | Every actor is a real human role (not a tab name). Every recurring human task has a workflow entry with at minimum: a job story, an actor, a frequency, and at least one step. Every decision the spreadsheet currently records as a status column or a formula flag is captured as a Decision. Every exception the team currently handles informally is documented in Exceptions. Coverage map shows ≥80% of spreadsheet interactions mapped to workflows. |

This phase requires **elicitation** — talking to the people who use the
spreadsheet. The workbench provides the `discovery-interview` tool to
generate a structured questionnaire from profiler signals, but the
conversation is human. The agent can draft workflows from interview notes;
the consultant must verify them with the business owner.

### Phase 4 — Interaction Contract

The interaction contract maps workflows to role-based views. It answers:
who sees what, when, and what can they do with it?

| Aspect | Detail |
|--------|--------|
| **Input** | `build/behavioral-spec.yaml` (workflows, actors, decisions), `build/profiler-signals.yaml` (archetype classification) |
| **Commands** | Human authors or enriches `build/interaction-contract.yaml`; `make validate-contract` |
| **Output** | Enriched `build/interaction-contract.yaml`: per-role weekly actions, status transitions per entity, alert rules, workflow-to-view mapping |
| **Done when** | Every role has documented weekly actions. Every status field has defined transitions. Alert thresholds are defined. Each workflow from the behavioral spec maps to at least one view. |

The interaction contract answers questions like:

- "What does the Field Manager see when they log in on Monday at 6:00 AM?"
- "What alerts appear on the dashboard if a crop is behind schedule?"
- "Can the Pack House lead edit the harvest record, or only the Field Manager?"

### Phase 5 — View Manifest

The view manifest specifies the concrete views the codegen will produce:
lists, forms, dashboards, checklists, print views. Every entry maps to a
workflow from the behavioral spec and a role from the interaction
contract.

| Aspect | Detail |
|--------|--------|
| **Input** | `build/behavioral-spec.yaml` (workflows), `build/interaction-contract.yaml` (roles, weekly actions), `build/schema-contract.yaml` (data model) |
| **Commands** | `make generate-view-manifest` (initial from interaction contract), `make generate-views`, `make generate-all` |
| **Output** | `build/view-manifest.yaml` or `build/codegen-manifest.yaml`, generated views (`views_auto.py`, `urls_auto.py`, templates) |
| **Done when** | Every workflow from the behavioral spec has a corresponding view entry with the correct archetype (list, form, dashboard, checklist, print). Editable fields and computed fields are specified. Time scope and filtering are correct. The generated views render with real data and no broken URLs. |

The view manifest is not a tab listing — it's a workflow mapping. A
single spreadsheet tab might generate multiple views (a form for data
entry, a list for review, a print view for the field). Multiple tabs
might merge into a single dashboard. The manifest is the bridge between
"what people do" and "what the app shows."

### Phase 6 — Validation and iteration

The generated app is compared against the source spreadsheet.
Acceptance criteria from the behavioral spec drive the comparison.

| Aspect | Detail |
|--------|--------|
| **Input** | Generated app (models, admin, views, import), source spreadsheet/Coda doc, `build/behavioral-spec.yaml` (acceptance criteria) |
| **Commands** | `make test`, `make check-generated`, `make drift-check`, `make audit-imports`, manual walkthrough of every workflow |
| **Output** | Gap list: each gap classified as a spec deficiency (return to appropriate phase) or a workbench deficiency (file upstream). Updated specs. Regenerated app. |
| **Done when** | A human can complete every workflow from the behavioral spec using only the generated app, without consulting the spreadsheet. Acceptance criteria from the behavioral spec pass. |

## The iteration loop

Phases are sequential on first pass but iterative in practice. A gap found
in Phase 6 may require returning to Phase 2 (missing FK), Phase 3
(workflow not captured), or Phase 5 (wrong view archetype).

```
  ┌──────────────────────────────────────────────────┐
  │                                                  │
  ▼                                                  │
Phase 0    Profile & baseline                        │
Phase 1    Domain Knowledge                          │
Phase 2    Schema Contract                           │
Phase 3    Behavioral Spec (MWBS)                    │
Phase 4    Interaction Contract                      │
Phase 5    View Manifest                             │
Phase 6    Validation                                │
  │                                                  │
  └── Gap found? ──► Classify gap ──► Return to      │
                                      appropriate     │
                                      phase ──────────┘
```

**Classification rules:**

| Gap | Classification | Return to |
|-----|---------------|-----------|
| Missing field, wrong type, unresolved FK | Spec deficiency | Phase 2 (Schema Contract) |
| Workflow not captured, missing decision, undocumented exception | Spec deficiency | Phase 3 (Behavioral Spec) |
| Wrong view archetype, missing filter, wrong editable fields | Spec deficiency | Phase 5 (View Manifest) |
| Generated code is malformed despite correct spec | Workbench deficiency | Upstream fix in migration-workbench |
| Missing feature in spec language (can't express this thing the spreadsheet does) | Workbench deficiency | Upstream spec format change + codegen update |

A spec deficiency is fixed in the product repo's spec artifacts and the
app is regenerated. A workbench deficiency is fixed upstream in
migration-workbench, released as a patch, and the product repo's version
pin is bumped.

## Integration with existing tools and docs

This methodology is the **operational complement** to the workbench's
existing specification layer docs:

| Layer | Design spec | Reference |
|-------|-------------|-----------|
| Profile & PipelineState | [Pipeline State](pipeline-state.md) | PipelineState checkpoint, phase methods, gate discipline |
| Domain Knowledge | — | `config/domain_context.yaml`, `profiler/tools/domain_context.py` |
| Schema Contract | [Schema Design Loop](schema-design-loop.md) | [Schema Contract Reference](schema-contract.md) |
| Behavioral Spec | — | `profiler/tools/behavioral_spec.py` (MWBS dataclasses), `build/behavioral-spec.yaml` |
| Interaction Contract | [Interaction Contract](interaction-contract.md) | Three-layer design (signals → human → manifest) |
| View Manifest | — | [View Manifest Reference](view-manifest.md), `build/view-manifest.yaml` |

The [Schema Design Loop](schema-design-loop.md) describes a 10-step loop
for the schema contract specifically. This methodology extends that
pattern to the full specification stack — particularly the behavioral
spec, which the design loop doesn't cover.

## Comparison: capability missions vs. product build

The workbench roadmap shipped 17 missions proving each generator works
against real data. Those missions enriched specs *just enough* to exercise
the codegen — one workflow, one dashboard, one checklist archetype. The
metrics were: does it parse, does it render, does the import succeed.

Product build has different metrics:

| Capability mission asks | Product build asks |
|-------------------------|---------------------|
| Does the view render? | Can the field manager complete Monday field walk without the spreadsheet? |
| Does the import succeed? | Does every row in the spreadsheet have a home in the schema? |
| Does the codegen produce valid Python? | Does the generated app cover every workflow a human executes? |
| Do 5 tests pass? | Do acceptance criteria from the behavioral spec pass? |
| 1 workflow defined | All 15–20 real workflows defined |

The workbench capability missions proved the factory works. Product build
is running the factory at full capacity — feeding it complete
specifications and iterating until the output is a replacement, not a
demo.

## Per-product roadmaps

Each product repo should have its own build roadmap, living alongside
the workbench's capability roadmap. Suggested location:
`docs/build-roadmap.md` in the product repo.

The product roadmap is a checklist of phases, each with the spec layer,
commands to run, and the acceptance criteria for that layer. It is not a
Gantt chart — it's a living document that the operator checks off as each
layer reaches completion.

A product roadmap template:

```markdown
# Build Roadmap — [product name]

> Source: [Google Sheets / Coda]
> Target: Generated Django app replacing the source
> Methodology: [product-build-methodology.md](../../migration-workbench/docs/product-build-methodology.md)

## Phase 0 — Profile and baseline
- [ ] Profiler run complete, PipelineState checkpoint exists
- [ ] Tab selection reviewed and approved
- [ ] Initial schema contract generated
- [ ] Initial behavioral spec generated

## Phase 1 — Domain Knowledge
- [ ] Domain context YAML authored: domain, vocabulary, year scope
- [ ] Entity definitions complete: every business entity has name, source tabs, fields, import key
- [ ] Glossary covers all column header abbreviations

## Phase 2 — Schema Contract
- [ ] Every column in approved tabs has a field in the contract
- [ ] Every FK resolved (no TODO_TargetModel)
- [ ] Compound import keys defined where needed
- [ ] Contract validates; generate-models produces runnable models_auto.py

## Phase 3 — Behavioral Spec
- [ ] Actors are real human roles with responsibilities and time pressures
- [ ] Every recurring human task has a workflow entry with job story, actor, frequency, steps
- [ ] Every status column in the spreadsheet is captured as a Decision
- [ ] Exceptions documented for known failure modes
- [ ] Business rules defined for cross-cutting constraints
- [ ] Reports defined for print/summary artifacts
- [ ] Acceptance criteria written for every workflow
- [ ] Coverage map shows ≥80% of spreadsheet interactions mapped

## Phase 4 — Interaction Contract
- [ ] Every role has documented weekly actions
- [ ] Status transitions defined per entity
- [ ] Alert rules defined
- [ ] Workflow-to-view mapping complete

## Phase 5 — View Manifest
- [ ] Every workflow has a corresponding view entry
- [ ] Archetypes correct (list, form, dashboard, checklist, print)
- [ ] Editable/computed fields specified
- [ ] Generated views render with real data

## Phase 6 — Validation
- [ ] Full test suite passes
- [ ] Every workflow from behavioral spec can be completed in generated app
- [ ] Acceptance criteria pass
- [ ] Drift check: re-profile source vs. generated schema
- [ ] Human sign-off: spreadsheet can be frozen
```

## Naming discipline

This document introduces no new names. It uses the existing workbench
vocabulary:

| Concept | Name | Location |
|---------|------|----------|
| Profiler checkpoint | `PipelineState` | `build/pipeline-state.yaml` |
| Domain vocabulary | `DomainContext` | `config/domain_context.yaml` |
| Data model | Schema Contract | `build/schema-contract.yaml` |
| Workflow specification | Behavioral Spec (MWBS) | `build/behavioral-spec.yaml` |
| Role-based UI contract | Interaction Contract | `build/interaction-contract.yaml` |
| View definitions | View Manifest | `build/view-manifest.yaml` |
| Machine execution plan | Codegen Manifest | `build/codegen-manifest.yaml` |
| Product build plan | Build Roadmap | `docs/build-roadmap.md` (in product repo) |
