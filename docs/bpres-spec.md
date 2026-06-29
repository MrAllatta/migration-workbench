# Business Process Reverse Engineering System (BPRES)
## Specification for migration-workbench

**Status:** Draft v1.0  
**Applies to:** migration-workbench chassis, all migration projects  
**Produces:** Migration Workbench Behavioral Specification (MWBS)

---

## 1. Purpose and Position

Workbook profiling discovers what a spreadsheet *stores*. The Business Process Reverse Engineering System discovers what a business *does*.

Profiling produces:
- Entity schema and relationships
- Formula dependency graph
- Historical data inventory
- Calculation logic

BPRES produces:
- Business events and the workflows that emit them
- Actor responsibilities and decision points
- Exception handling protocols
- Operational performance requirements
- Acceptance criteria for every workflow
- A signed-off specification that gates the builder

The profiler output and the MWBS document together constitute the complete migration source of truth. Neither is sufficient alone. The profiler without BPRES produces an application that covers data and structure but cannot replace the spreadsheet in practice. BPRES without the profiler produces a specification with no grounding in the actual data model.

### 1.1 Position in the Chassis Pipeline

```
PROFILER ──► ELICITOR ──► [draft MWBS]
                               │
                          ELICITATION
                           SESSION
                               │
                          [resolved MWBS]
                               │
                          SIGN-OFF GATE
                               │
                 ┌─────────────┴─────────────┐
              BUILDER                   COVERAGE ENGINE
                 │                           │
             [modules]               [coverage report]
                 │                           │
              DEPLOYER ◄───────── [completion gate]
```

The sign-off gate is a hard stop. The builder does not run without an operator-signed MWBS. This is the primary mechanism that moves strategic human intervention from build time — where it is expensive, late, and opaque — to specification time, where it is cheap, early, and traceable.

---

## 2. Design Principles

### Business-first

The specification describes how the business operates, not how software should be implemented. Every element should be readable by the operator without technical translation.

Bad: `"Display adjustment modal with quantity delta field."`  
Good: `"Inventory manager records quantity correction after physical count."`

### Event-centric

Business behavior is expressed as events — discrete, named, past-tense facts that the business cares about having occurred. Events are the connective tissue between workflows, actors, and the data model. They become application commands, audit records, and integration contracts.

Events are not UI actions. They are business facts.

`Seeded`, `Transplanted`, `Harvested`, `Sold`, `InventoryAdjusted`, `ShortfallRecorded`

### Decisions are human

Workflows contain judgment. The specification must make decision points explicit and define what information the system is responsible for surfacing. The system is not required to automate what operators currently decide by inspection.

### Exceptions are mandatory

Every workflow must document its failure modes. Most spreadsheet dependencies survive migration because nobody documented what happens when things go wrong. A migration that cannot handle the exceptions the spreadsheet handles — however informally — has not replaced the spreadsheet.

### Observable

Every workflow outcome must produce a verifiable system state. "The farmer feels confident about harvest" is not an outcome. "A harvest order record exists, is associated with the active sales plan, and all line items have a status of `assigned` or `flagged_short`" is an outcome.

### Provenance-tracked

Every element in the MWBS document carries a provenance record: whether it was inferred from spreadsheet structure or elicited from the operator. Elicited elements route to manual verification in QA. Inferred elements route to automated testing. Provenance is not documentation overhead — it is a QA routing mechanism.

---

## 3. System Components

| Component | Role | Input | Output |
|-----------|------|-------|--------|
| **Elicitor** | Infers draft MWBS from profiler output | Profiler output package | Draft MWBS with placeholders |
| **Elicitation Protocol** | Fills what cannot be inferred | Draft MWBS + operator session | Resolved MWBS |
| **MWBS Document** | The specification artifact | Resolved MWBS | Signed-off YAML document |
| **Sign-off Gate** | Pipeline enforcement | Signed MWBS | Build authorization |
| **Builder Integration** | Consumes MWBS to generate code | Signed MWBS + profiler output | Modules with embedded test stubs |
| **Coverage Engine** | Tracks and reports completion | Build artifacts + MWBS | Coverage report |

---

## 4. MWBS Schema

The MWBS document is YAML. It is machine-readable by the builder and human-readable by the operator. The operator should be able to review the document in a plain text editor or printed form.

### 4.1 Document Header

```yaml
spec_version: "1.0"
schema: "mwbs/v1"

project:
  name: ""
  source_files: []
  profiler_run_date: ""
  elicitor_run_date: ""
  elicitation_session_date: ""
  version: 1
  status: draft                        # draft | in_review | signed_off
  developer: ""
  operator: ""
```

### 4.2 Business

```yaml
business:
  name: ""
  domain: ""
  description: >
    One paragraph describing what the business does, in the operator's
    language. Used to ground LLM builder prompts.
  peak_operational_periods: []         # e.g. "market week", "spring planting"
```

### 4.3 Actors

Actors are business participants who trigger or participate in workflows. They become permission and ownership candidates in the application.

```yaml
actors:

  - id: field_manager
    name: Field Manager
    responsibilities:
      - Crop planning and bed assignment
      - Harvest scheduling
      - Field crew coordination
    time_pressures:
      - "Market morning: task completion required before 6am"
      - "Weekly planning: Monday before crew arrives"
    access_level: ""                   # populated by builder from actor role
```

### 4.4 Events

Events are immutable business facts. Past tense. Named in PascalCase. They represent things that have happened and cannot be undone — only compensated.

Events are the primary integration contract between workflows. When workflow A emits an event, workflow B may consume it as a trigger or input. This makes the dependency between workflows explicit and testable.

```yaml
events:

  - id: crop_seeded
    name: CropSeeded
    description: Seeds placed into germination trays.
    producer: nursery_manager
    payload:
      - field: crop
        type: entity_ref(crop)
        required: true
      - field: variety
        type: string
        required: true
      - field: quantity_seeds
        type: integer
        required: true
      - field: tray_count
        type: integer
        required: true
      - field: seeding_date
        type: date
        required: true
      - field: target_transplant_date
        type: date
        required: false
    consumed_by:
      - nursery_schedule_generation
      - transplant_planning
    provenance:
      source: inferred
      inference_signals:
        - rule: INF-03
          signal: "Manual entry zone in NurseryLog tab: crop, variety, qty, date columns"
        - rule: INF-02
          signal: "Formula chain: NurseryLog → TransplantSchedule via seeding_date + days_to_transplant"
```

**Note on commands vs events:** Commands express intent (`GenerateHarvestPlan`). Events express facts (`HarvestPlanGenerated`). The MWBS specifies events. Commands are a builder concern — each workflow step that emits an event implies a corresponding command. The builder derives commands from event definitions; they are not separately specified here.

### 4.5 Workflows

Workflows are the primary migration unit. A migration is not complete until every signed-off workflow is executable without the spreadsheet.

Each workflow contains:
- A job story (human-readable intent)
- Operational requirements (testable constraints)
- Steps with explicit decision points
- Declared event emissions
- Exception references
- Provenance record

```yaml
workflows:

  - id: weekly_harvest_planning

    title: Weekly Harvest Planning

    # Job story: human-readable, written in operator language.
    # The actor, situation, and outcome must be specific enough
    # that the operator would recognize their own work in it.
    job_story:
      when: >
        Monday morning before market week, after customer orders
        are confirmed but before crew arrives.
      i_need_to: >
        Generate a picking list that covers all committed customer
        orders, organized by bed and crop, showing quantities
        and flagging anything I cannot fulfill.
      so_i_can: >
        Brief the harvest crew and start picking before 6am
        without returning to the office.

    actor: field_manager
    frequency: weekly
    peak_pressure: "Monday 5:30am pre-market"

    trigger:
      type: scheduled
      description: >
        Start of each market week. Actor initiates; system does
        not auto-trigger.

    inputs:
      - id: confirmed_customer_orders
        source_event: OrderConfirmed
      - id: current_inventory
        source_event: InventoryAdjusted
      - id: crop_maturity_estimates
        source: CropMaturityRecord

    steps:
      - id: step_01
        title: Review active orders
        description: >
          Actor reviews all confirmed orders for the current
          market week. System displays orders grouped by customer,
          with line item quantities.
        actor_action: review
        system_provides:
          - Confirmed orders for current market week
          - Customer priority flags
        emits: ~

      - id: step_02
        title: Check crop availability
        description: >
          Actor compares order commitments against projected
          available harvest. System computes availability from
          inventory and maturity records.
        actor_action: review
        system_provides:
          - Available quantity per crop (inventory + projected harvest)
          - Gap between committed and available per line item
        contains_decision: prioritize_harvest_when_short
        emits: ~

      - id: step_03
        title: Generate harvest order
        description: >
          Actor confirms the harvest plan. System creates harvest
          order records grouped by bed and crop.
        actor_action: confirm
        system_provides:
          - Draft harvest order organized by bed
          - Flagged shortfall items
        emits: HarvestOrderGenerated

      - id: step_04
        title: Print or export picking list
        description: >
          Actor produces a physical or mobile-accessible picking
          list for crew use in the field.
        actor_action: export
        system_provides:
          - Picking list formatted for field use
          - Organized by bed sequence, not customer
        emits: PickingListProduced

    emits:
      - HarvestOrderGenerated
      - PickingListProduced

    exceptions:
      - ref: EX-harvest-001    # insufficient_inventory
      - ref: EX-harvest-002    # missing_maturity_data

    operational:
      max_steps: 4
      max_duration_minutes: 5
      spreadsheet_access: forbidden
      mobile_required: false       # field crew uses paper list; planner uses desktop
      offline_required: false

    data_entry:
      frequency: weekly
      volume: low                  # actor confirms; does not enter line items
      preferred_input: mouse       # review and confirm workflow, not data entry
      batch_capable: false

    priority: 1                    # from operator stack rank

    provenance:
      source: hybrid
      inference_signals:
        - rule: INF-04
          signal: "Print range on HarvestOrders tab"
        - rule: INF-02
          signal: "Formula chain: WeeklySales → HarvestOrders via crop/quantity columns"
        - rule: INF-09
          signal: "Repeated HarvestOrders tab structure across 52 weeks"
      elicited_elements:
        - "Peak pressure time (5:30am) and market morning context: stated by operator"
        - "max_duration_minutes (5): stated by operator; spreadsheet takes 8-12 min"
        - "Bed-sequenced picking list (vs customer-sequenced): stated by operator"
        - "Crew uses paper list in field: stated by operator"
      verification_required: true
```

### 4.6 Decisions

Decision sections document human judgment points within workflows. They are extracted from workflow steps that contain `contains_decision` and specified fully here.

The system is responsible for surfacing required information. The system is not required to make the decision.

```yaml
decisions:

  - id: prioritize_harvest_when_short
    title: Harvest Prioritization Under Shortage
    within_workflow: weekly_harvest_planning
    within_step: step_02

    description: >
      When projected harvest cannot fulfill all committed orders,
      field manager decides which orders to fulfill in full,
      which to fulfill partially, and which to flag for sales
      manager follow-up.

    information_system_must_provide:
      - Available quantity per crop with confidence level
      - Committed quantity per crop per customer
      - Customer priority tier (CSA member vs wholesale vs spot)
      - Crop replacement lead time (days to next harvest)
      - Historical shortfall frequency per crop

    criteria_actor_applies:
      - Customer commitment priority (CSA first)
      - Crop perishability (cannot defer harvest)
      - Relationship history with customer
      - Labor capacity for partial harvest

    outcome: harvest_priority_assignment
    outcome_recorded_as: HarvestPrioritySet

    automation_level: human_only
    rationale: >
      Prioritization involves relationship judgment the system
      cannot encode. System surfaces data; actor decides.

    provenance:
      source: elicited
      elicited_elements:
        - "Entire decision structure: not present in spreadsheet; operator currently does this by memory"
      verification_required: true
```

### 4.7 Exceptions

Exceptions are mandatory. Every workflow must reference at least one exception. An MWBS document with no exceptions is incomplete and will not pass the sign-off gate validation.

Exception documentation is where most tacit spreadsheet knowledge lives. The inference rule `INF-11` surfaces IFERROR and ISBLANK patterns as exception candidates, but the response protocol almost always requires elicitation.

```yaml
exceptions:

  - id: EX-harvest-001
    title: Insufficient Inventory for Committed Orders
    workflow: weekly_harvest_planning

    condition: >
      Planned harvest quantity for any line item is less than
      committed order quantity.

    severity: warning               # warning | error | blocking

    detection:
      method: system_computed
      trigger: step_02 completion

    responses:
      - id: r1
        action: flag_shortfall_items
        mechanism: inline_in_harvest_order
        actor: system
        emits: ShortfallRecorded

      - id: r2
        action: notify_sales_manager
        mechanism: in_app_notification
        actor: system
        emits: ~

      - id: r3
        action: manual_override
        description: >
          Field manager may override shortfall flag by entering
          a revised committed quantity with a note.
        actor: field_manager
        emits: CommitmentRevised

    current_handling: >
      Farmer manually identifies shortfalls by scanning row totals,
      crosses out quantities in pencil, and calls customers from
      memory. No audit record exists.

    migration_improvement: >
      System creates ShortfallRecorded event and notifies sales
      manager automatically. Revision history is preserved.

    provenance:
      source: elicited
      elicited_elements:
        - "Pencil cross-out and phone call protocol: stated by operator"
        - "No current audit record: confirmed by operator"
      verification_required: true

  - id: EX-harvest-002
    title: Missing Crop Maturity Data
    workflow: weekly_harvest_planning

    condition: >
      A committed crop has no maturity record for the current week,
      making availability estimate impossible.

    severity: blocking

    detection:
      method: system_computed
      trigger: step_02 initiation

    responses:
      - id: r1
        action: block_harvest_plan_generation
        mechanism: inline_error_in_step_02
        actor: system

      - id: r2
        action: prompt_maturity_entry
        description: >
          System prompts field manager to enter maturity estimate
          before proceeding.
        actor: field_manager
        emits: CropMaturityRecorded

    current_handling: >
      Farmer estimates from memory based on seeding date and
      experience. No prompt or block exists in spreadsheet.

    provenance:
      source: elicited
      elicited_elements:
        - "Memory-based estimation: stated by operator"
      verification_required: true
```

### 4.8 Business Rules

Rules are workflow-independent constraints. They apply globally or across multiple workflows. Rules become validators, computed fields, and automated test assertions.

```yaml
rules:

  - id: BR-001
    title: Inventory Non-Negative
    expression: "current_inventory >= 0"
    severity: error
    applies_to: all_inventory_adjustments
    violation_response: block_and_alert
    provenance:
      source: inferred
      inference_signals:
        - rule: INF-08
          signal: "Conditional formatting on inventory quantity column: red fill at < 0"
      verification_required: false

  - id: BR-002
    title: Harvest Order Requires Active Sales Plan
    expression: "harvest_order.sales_plan_id IS NOT NULL"
    severity: error
    applies_to: HarvestOrderGenerated
    violation_response: block
    provenance:
      source: inferred
      inference_signals:
        - rule: INF-06
          signal: "VLOOKUP from HarvestOrders tab into WeeklySales tab via plan_id"
      verification_required: false

  - id: BR-003
    title: Seeding Date Must Precede Transplant Date
    expression: "transplant_date > seeding_date"
    severity: error
    applies_to: TransplantScheduled
    violation_response: block
    provenance:
      source: inferred
      inference_signals:
        - rule: INF-05
          signal: "Date formula: seeding_date + days_to_transplant in NurseryLog tab"
      verification_required: false
```

### 4.9 Reports

Reports are operational outputs. They are not screens — they are artifacts that leave the system (printed, exported, displayed) and support specific decisions. Every report must name the decision it supports.

```yaml
reports:

  - id: weekly_picking_list

    title: Weekly Picking List
    audience: field_manager
    frequency: weekly
    format: print_and_mobile

    source_events:
      - HarvestOrderGenerated
      - CropMaturityRecorded

    displays:
      - Crop and variety
      - Bed location (in field sequence)
      - Target quantity
      - Harvest notes

    decisions_supported:
      - weekly_harvest_planning

    operational:
      must_function_offline: false
      time_to_generate_seconds: 30

    provenance:
      source: inferred
      inference_signals:
        - rule: INF-04
          signal: "Print range on HarvestOrders tab"
      verification_required: false
```

### 4.10 Acceptance Tests

Acceptance tests define the contract for spreadsheet replacement. Each test maps to a workflow and contains typed acceptance criteria. The criterion type determines how the test is executed and by whom.

**Criterion types:**

| Type | Definition | Executor |
|------|------------|----------|
| `completion` | All required records or actions are present | Automated |
| `coverage` | All relevant source records are included; none silently dropped | Automated |
| `accuracy` | Output values match expected results | Automated |
| `sequence` | Steps execute in required order; pre-conditions enforced | Automated |
| `speed` | Task completes within stated threshold | Performance test |
| `recovery` | Error states are handled; no silent failures | Automated |
| `independence` | Workflow completes without spreadsheet access | Manual / operator |

Any criterion with `verification_required: true` in its provenance is executed by the operator, not automated infrastructure. The test stub is generated; passing it requires operator sign-off, not a test runner.

```yaml
acceptance_tests:

  - id: AT-harvest-001
    workflow: weekly_harvest_planning
    priority: 1

    scenario:
      given:
        - at_least_one_confirmed_order_exists_for_current_week
        - inventory_records_exist_for_all_committed_crops
        - crop_maturity_records_exist_for_all_committed_crops
      when:
        actor: field_manager
        action: generate_harvest_plan
        context: monday_morning_before_6am
      then:
        - HarvestOrderGenerated_event_exists
        - PickingListProduced_event_exists

    criteria:

      - id: AT-harvest-001-C1
        type: completion
        description: >
          All confirmed order line items for the current week
          appear in the generated harvest order.
        assertion: >
          count(harvest_order.line_items) ==
          count(confirmed_orders.line_items WHERE week = current_week)
        test_type: automated
        verification_required: false

      - id: AT-harvest-001-C2
        type: coverage
        description: >
          No committed crop is absent from the harvest order
          without a corresponding shortfall flag.
        assertion: >
          FOR EACH order.line_item:
            line_item IN harvest_order.line_items
            OR ShortfallRecorded event EXISTS for line_item
        test_type: automated
        verification_required: false

      - id: AT-harvest-001-C3
        type: speed
        description: >
          Full harvest plan generated within 5 minutes of
          actor initiating step_01.
        threshold_seconds: 300
        test_type: performance
        verification_required: false

      - id: AT-harvest-001-C4
        type: recovery
        description: >
          When committed quantity exceeds available harvest for
          any line item, that item is flagged in the harvest order
          and ShortfallRecorded event is emitted. Item is not
          silently dropped.
        test_type: automated
        verification_required: false

      - id: AT-harvest-001-C5
        type: sequence
        description: >
          Harvest order cannot be confirmed until actor has
          reviewed the availability check in step_02.
        test_type: automated
        verification_required: false

      - id: AT-harvest-001-C6
        type: independence
        description: >
          Field manager completes weekly harvest planning workflow
          from Monday order review through picking list production
          without opening a spreadsheet.
        test_type: manual
        verifier: operator
        verification_required: true
        notes: >
          Operator performs this workflow during the first live
          market week. Sign-off required before migration is
          declared complete for this workflow.
```

### 4.11 Coverage Map

The coverage map is the project management view of the MWBS. It answers the question: what is the current behavioral coverage of this migration?

```yaml
coverage_map:

  workflows:
    - id: weekly_harvest_planning
      title: Weekly Harvest Planning
      source: hybrid
      priority: 1
      status: signed_off              # draft | in_review | signed_off
      acceptance_test: AT-harvest-001
      criteria_count: 6
      verification_required_count: 1
      exceptions_documented: 2

  summary:
    total_workflows: 0               # populated by Elicitor
    signed_off: 0
    behavioral_coverage_pct: 0       # signed_off / total_workflows * 100
    spreadsheet_independence_pct: 0  # AT independence criteria passing / total
```

### 4.12 Sign-off Block

```yaml
sign_off:

  statement: >
    I confirm that the job stories and acceptance criteria in this
    document reflect workflows I actually perform, that the
    acceptance criteria are conditions I would use to evaluate
    whether this application is usable in my operation, and that
    the priority stack rank reflects the order in which I need
    these workflows available.

  operator:
    name: ""
    date: ""
    signature: ""                    # initials or typed name

  developer:
    name: ""
    date: ""

  scope_exclusions:
    - workflow: ""
      reason: ""
      deferred_to: ""               # future phase or out of scope

  amendment_log:
    - date: ""
      affected_workflow: ""
      change_description: ""
      re_signed: false
```

**Validation rules enforced before sign-off is accepted:**

1. All `[REQUIRES_ELICITATION]` placeholders resolved
2. Every workflow has at least one exception reference
3. Every workflow has at least two acceptance criteria (one `completion`, one other)
4. Every workflow has a `priority` value
5. Every decision has `information_system_must_provide` populated
6. `scope_exclusions` must document any workflow from the Elicitor's candidate list that is absent from `workflows`

---

## 5. Elicitor Specification

The Elicitor is a chassis command that consumes profiler output and produces a draft MWBS document. It does not make up what it cannot see. Elements it cannot infer are scaffolded as `[REQUIRES_ELICITATION]` placeholders with a description of what is needed and why.

### 5.1 Profiler Output Package (Elicitor Input)

| Element | Profiler Field | Description |
|---------|---------------|-------------|
| Schema map | `schema.tables` | Tables, fields, types, keys |
| Entity graph | `entities` | Relationships between entities |
| Formula dependency tree | `formulas.dependencies` | Which cells consume which |
| Tab inventory | `sheets` | All sheets with metadata |
| Column annotation | `columns.zones` | Entry / calculated / display zones |
| Print ranges | `sheets[*].print_range` | Defined print areas |
| Named ranges | `named_ranges` | Business-named cell regions |
| Data validation | `columns[*].validation` | Dropdown lists and constraints |
| Conditional formatting | `columns[*].conditional_format` | Rules and color codes |
| Formula patterns | `formulas.patterns` | IFERROR, VLOOKUP, aggregates, etc. |
| Comment/note content | `cells[*].notes` | Inline annotations by the operator |

### 5.2 Inference Rule Catalog

| Rule | Spreadsheet Signal | Infers MWBS Element |
|------|--------------------|---------------------|
| INF-01 | Tab sequence with shared entity columns | Workflow stage sequence → `steps` order |
| INF-02 | Formula chain crossing tab boundary | Data handoff → event emission between workflow stages |
| INF-03 | Column with no formula predecessors in entry zone | Actor input trigger → workflow `inputs` |
| INF-04 | Print range defined on sheet | Artifact output → `reports` candidate |
| INF-05 | Date column with downstream filter formulas | Scheduling trigger → `trigger.type: scheduled` |
| INF-06 | VLOOKUP / INDEX-MATCH referencing another sheet's key | Entity relationship → event `consumed_by`, navigation pattern |
| INF-07 | SUM / COUNT aggregate across row set | Inventory check or reporting workflow |
| INF-08 | Conditional formatting on quantity column | Threshold rule → `rules` candidate, alert workflow |
| INF-09 | Repeated tab structure (same columns, different periods) | Periodic workflow → `frequency` |
| INF-10 | Year or season suffix on tab names | Annual cycle workflow + multi-year import scope flag |
| INF-11 | IFERROR, IF(ISBLANK), IF(ISERROR) formula patterns | Exception currently managed by formula convention → `exceptions` candidate |
| INF-12 | Named range | Domain entity candidate → event `payload` field |
| INF-13 | Data validation dropdown list | Enumeration → `rules` candidate, constrained field |
| INF-14 | Pivot table or dedicated summary sheet | Report candidate → `reports` |
| INF-15 | Hidden columns | Intermediate calculation, not operator-facing → exclude from UI spec |
| INF-16 | Manually entered codes or abbreviations | Domain vocabulary → enum, validated field |
| INF-17 | Sheet referenced by many other sheets as lookup source | Master entity → primary domain aggregate |
| INF-18 | Cell notes and comments | Exception handling or override convention → `exceptions` candidate |
| INF-19 | Row with totals formula at bottom of data range | Batch operation boundary → workflow step boundary |
| INF-20 | Tab names or column headers containing person names or roles | Actor candidates |

### 5.3 What the Elicitor Cannot Infer

The following elements are always scaffolded as `[REQUIRES_ELICITATION]`. The Elicitor flags them with a description of what the elicitation session must establish:

| Element | Reason |
|---------|--------|
| `operational.max_duration_minutes` | Speed tolerance is a business expectation, not a spreadsheet property |
| `job_story.when` context and time pressure | Situational context exists in the operator's mind, not the file |
| `decisions` criteria and information requirements | Judgment logic is not encoded in formulas |
| `exceptions[*].current_handling` | Informal exception handling is behavior, not structure |
| `exceptions[*].responses` (response protocol) | Recovery procedures are operational, not formulaic |
| `data_entry.preferred_input` | UI preferences are operator knowledge |
| `data_entry.offline_required` | Infrastructure constraints are not in the spreadsheet |
| `priority` stack rank | Relative importance across workflows is a business decision |
| Paper process workflows | Workflows not in any spreadsheet are invisible to the Elicitor |
| `actors[*].time_pressures` | Operational timing is not in the data model |

### 5.4 Elicitor Output

The Elicitor produces:

1. **Draft MWBS document** — all inferred elements populated with provenance records; all elicited elements scaffolded as `[REQUIRES_ELICITATION: <description of what is needed>]`
2. **Elicitation worksheet** — a session guide generated from the placeholders, organized for a 60–90 minute operator session
3. **Candidate workflow list** — the full list of workflows detected by inference, before prioritization, including any that were ambiguous or low-confidence
4. **Inference confidence log** — for each inferred element, the rule(s) that triggered it and the signal in the profiler output

---

## 6. Elicitation Protocol

The elicitation session resolves all `[REQUIRES_ELICITATION]` placeholders. It is a structured conversation with the operator, not a survey. The developer runs it using the elicitation worksheet generated by the Elicitor. Estimated duration: 60–90 minutes per migration scope.

### 6.1 Session Sections

**Section 1: Workflow Walk-Through**

For each draft workflow, ask:

- "Does this match something you actually do?"
- "What are you doing right before this? What triggers it?"
- "Walk me through what you actually do, step by step."
- "What does success look like when you're done?"

Record any steps that differ from the Elicitor's draft. Record triggers and outcomes in the operator's words before translating to schema language.

**Section 2: Speed Calibration**

For each workflow:

- "How long does this take you in the spreadsheet today?"
- "If the app took [2x current time], would that be acceptable?"
- "Is there a hard time limit for this — something that has to be done before a crew arrives or a customer shows up?"

Record threshold in minutes. Mark as `verification_required: true`.

**Section 3: Paper Process Inventory**

The most important section. Surfaces workflows invisible to the Elicitor.

- "What do you do on [peak period: market day / planting week / harvest] that you do NOT do in the spreadsheet?"
- "What do you track on paper, in your head, or in a notebook?"
- "Is there anything you've always wished the spreadsheet could do but couldn't?"

Add each discovered workflow as a new MWBS entry with `provenance.source: elicited`.

**Section 4: Exception Review**

For each workflow:

- "What goes wrong with this? What happens when the numbers don't work out?"
- "What do you do when that happens — right now, in practice?"
- "Does the spreadsheet help you handle it, or do you work around the spreadsheet?"
- "Is there anything you've lost because you didn't catch an exception in time?"

This section will frequently reveal that current exception handling leaves no audit record. Document both the current state and the desired behavior.

**Section 5: Decision Inventory**

For each workflow step that involves comparison, judgment, or override:

- "What are you deciding here?"
- "What information do you look at to make that call?"
- "Could the app make this decision for you, or do you need to make it yourself?"
- "What do you need to see to feel confident in your decision?"

**Section 6: Priority Stack Rank**

Present the full candidate workflow list. Ask the operator to rank the five most important. These become the build order and the minimum viable migration threshold.

Ask: "If you could only use the app for these five things in the first month, which five would let you stop opening the spreadsheet most often?"

### 6.2 Session Outputs

- Completed elicitation worksheet
- Annotated draft MWBS with all placeholders resolved
- Any new workflows added from paper process inventory
- Operator priority stack rank
- Developer notes on ambiguous or conflicting answers (for follow-up, not for interpretation)

---

## 7. Sign-off Gate Specification

### 7.1 Gate Mechanism

The builder pipeline checks for a valid signed-off MWBS document before running. If the check fails, the builder emits an error and stops.

```
GATE CHECK:
  1. MWBS document exists at project path
  2. schema version is valid
  3. sign_off.operator.name is non-empty
  4. sign_off.operator.date is non-empty
  5. ALL validation rules pass (see Section 4.12)
  6. coverage_map.workflows count > 0
  7. No [REQUIRES_ELICITATION] placeholders remain in document

IF any check fails:
  emit BUILD_BLOCKED error with list of failing checks
  exit with non-zero status
```

### 7.2 What Sign-off Means

The operator has confirmed:

- Every job story reflects real work they perform
- Every acceptance criterion is a condition they would use to evaluate the app
- The priority stack rank reflects what they need available first
- Workflows listed in `scope_exclusions` are understood to be out of scope for this phase

Sign-off is a specification agreement, not a legal contract. It can be amended. Amendments require a new sign-off pass on the affected workflows, recorded in `sign_off.amendment_log`.

### 7.3 Amendment Protocol

When a workflow changes after sign-off:

1. Developer updates the affected workflow in the MWBS document
2. Developer adds an entry to `sign_off.amendment_log`
3. Operator reviews changed section and re-signs (`re_signed: true` in log)
4. Builder is re-run for affected modules only

Amendments do not invalidate the full sign-off. They extend it.

---

## 8. Builder Integration

### 8.1 MWBS as Builder Prompt Input

The signed MWBS document is injected into every builder prompt for the modules it covers. Builder prompt templates must reference:

- The `job_story` when generating the module's UI and flow
- The `operational` constraints when generating navigation and interaction patterns
- The `emits` list when generating event infrastructure
- The `decisions` when generating information display requirements
- The `exceptions` when generating error handling paths
- The `acceptance_tests` when generating test stubs

Builder prompt wrapper:

```
You are building [module_title] for [business.name].

This module must support the following workflow:

JOB STORY:
When [job_story.when], the [actor.name] needs to [job_story.i_need_to]
so they can [job_story.so_i_can].

OPERATIONAL CONSTRAINTS:
- Maximum steps: [operational.max_steps]
- Maximum duration: [operational.max_duration_minutes] minutes
- Spreadsheet access: [operational.spreadsheet_access]

EVENTS THIS MODULE EMITS:
[emits list]

DECISIONS THIS MODULE MUST SUPPORT (not automate):
[decisions with information_system_must_provide]

EXCEPTIONS THIS MODULE MUST HANDLE:
[exceptions with responses]

ACCEPTANCE CRITERIA (all must be testable):
[acceptance_tests.criteria list]

The module is not complete until all acceptance criteria have
corresponding test stubs. Do not declare completion until
test stubs exist for all criteria listed above.
```

### 8.2 Criterion-to-Test Mapping

| Criterion Type | Generated Artifact |
|----------------|-------------------|
| `completion` | Automated assertion against database state |
| `coverage` | Automated count comparison (source vs. output records) |
| `accuracy` | Automated value comparison against known test fixtures |
| `sequence` | Automated workflow state machine test |
| `speed` | Performance test with threshold from criterion |
| `recovery` | Automated error path test with assertion on error state |
| `independence` | Manual test stub with operator verification note |

Builder must generate the test stub for every criterion before marking a module complete. Stubs may be failing — failing stubs are acceptable. Absent stubs are not.

### 8.3 Module Completion Gate

A module is complete when:

1. All acceptance criteria for its associated workflow have test stubs
2. All `automated` and `performance` test stubs are passing
3. All `manual` test stubs are either:
   - Marked `verified: true` with operator sign-off date, or
   - Scheduled for verification in the acceptance testing phase

The builder may not mark a module complete based on its own assessment of structural coverage. Completion is determined by the criterion checklist.

---

## 9. Coverage Engine

### 9.1 Coverage Dimensions

Six dimensions are tracked. All six must reach 100% for migration completion.

| Dimension | Definition | Source |
|-----------|------------|--------|
| **Data** | All source records imported into target schema | Import report: row counts, validation errors |
| **Formula** | All spreadsheet calculations reproduced as application logic or business rules | Formula dependency tree vs. rule/computation inventory |
| **Structural** | All domain entities and operations have corresponding modules | Entity graph vs. module inventory |
| **Workflow** | All signed-off workflows are executable | AT independence criteria: passing or operator-verified |
| **Exception** | All documented exceptions are handled | Exception list vs. recovery test results |
| **Report** | All operational reports are available | Report list vs. generated report verification |

### 9.2 Coverage Report Format

```yaml
coverage_report:
  generated: ""
  project: ""

  data:
    source_records: 0
    imported_records: 0
    import_errors: 0
    coverage_pct: 0

  formula:
    formulas_in_source: 0
    formulas_reproduced: 0
    coverage_pct: 0

  structural:
    entities_in_model: 0
    entities_with_modules: 0
    coverage_pct: 0

  workflow:
    workflows_signed_off: 0
    workflows_independent: 0     # independence AT passing or verified
    coverage_pct: 0

  exception:
    exceptions_documented: 0
    exceptions_tested: 0
    coverage_pct: 0

  report:
    reports_specified: 0
    reports_available: 0
    coverage_pct: 0

  spreadsheet_independence_pct: 0   # workflow.coverage_pct; the headline metric

  completion_gate_passed: false
```

### 9.3 Definition of Complete Migration

A migration is complete when all six coverage dimensions reach 100% AND the following conditions hold:

1. All historical data is imported and validated
2. All spreadsheet calculations are reproduced as application logic
3. All signed-off workflows have passing automated tests or documented operator verification
4. All documented exceptions have passing recovery tests
5. All operational reports are available and verified
6. `spreadsheet_independence_pct` equals 100%

**The spreadsheet can be retired only when `completion_gate_passed: true`.**

Structural coverage at 100% is necessary but not sufficient. A migration where the application has all the right modules but the farmer cannot do their Thursday morning harvest planning has not replaced the spreadsheet.

---

## 10. Implementation Phases

### Phase 0 — Validation (immediate, no new code)

Use the MWBS schema manually. Take one existing project's profiler output, run the Elicitor inference rules by hand as an LLM prompt, produce a draft MWBS document, conduct an elicitation session with the operator, finalize and sign off.

Goal: validate the schema, discover what the Elicitor prompt needs to produce useful output, and measure the gap between the Elicitor's draft and what the operator session reveals.

Deliverable: a hand-produced MWBS document for the farm migration's top-priority five workflows.

### Phase 1 — Document format and manual gate

- Finalize and freeze the MWBS schema (this document)
- Implement sign-off gate as a pre-check in the builder pipeline (file existence + validation rules)
- Elicitation worksheet is a template document, generated manually from the draft MWBS
- Builder prompt templates updated to accept MWBS sections as input

Deliverable: builder refuses to run without a valid signed-off MWBS document.

### Phase 2 — Elicitor as chassis command

- Implement `workbench elicit [profiler_output]` command
- Elicitor applies inference rule catalog to profiler output
- Produces draft MWBS document with provenance records and `[REQUIRES_ELICITATION]` placeholders
- Produces elicitation worksheet from placeholder inventory
- Produces inference confidence log

Deliverable: `workbench elicit` produces a usable draft that covers all inferrable elements and clearly marks what the session must establish.

### Phase 3 — Criterion-to-test scaffolding and coverage reporting

- Builder generates test stubs from acceptance criteria
- Coverage Engine aggregates test results against MWBS criterion list
- Coverage report generated alongside each build
- Module completion gate enforces criterion checklist
- `workbench coverage` command produces current coverage report

Deliverable: coverage report with six-dimensional view; completion gate blocks deployment until 100%.

### Phase 4 — Schema tooling and editor support

- MWBS JSON Schema published for editor validation
- MWBS YAML validated on load, not only at sign-off time
- Amendment workflow supported as a chassis command
- Coverage map rendered as a project dashboard view

---

## Appendix A: Farm Migration Candidate Workflow Inventory

Initial candidates from Elicitor inference (illustrative; to be validated in Phase 0 session):

| ID | Workflow | Source | Inference Rules | Priority | Elicitation Required |
|----|----------|--------|-----------------|----------|---------------------|
| WF-01 | Weekly harvest planning | HarvestOrders tab | INF-04, INF-02, INF-09 | TBD | Speed, decisions, exceptions |
| WF-02 | Weekly sales plan creation | WeeklySales tab series | INF-09, INF-03 | TBD | Priority, customer intake flow |
| WF-03 | Annual crop plan by bed | CropPlan tab matrix | INF-10, INF-17 | TBD | Planning horizon, revision workflow |
| WF-04 | Transplant scheduling | NurseryLog → TransplantSchedule | INF-02, INF-05 | TBD | Lead time rules, exception cases |
| WF-05 | Direct seeding scheduling | DirectSeed tab (parallel to WF-04) | INF-01, INF-09 | TBD | Difference from transplant workflow |
| WF-06 | Post-sales inventory reconciliation | Inventory tab, sales → inventory formula chain | INF-02, INF-07 | TBD | Timing, adjustment protocol |
| WF-07 | End-of-season sales reporting | Summary/aggregate tab | INF-14, INF-07 | TBD | Audience, decisions supported |
| WF-08 | Nursery succession seeding | NurseryLog date pattern | INF-09, INF-05 | TBD | Succession logic, spacing rules |
| WF-09 | Market order intake | Customer entry zone in WeeklySales | INF-03, INF-20 | TBD | Channel, volume, speed requirement |
| WF-10 | Harvest crew briefing | **Not in spreadsheet** | Paper process | TBD | Full elicitation required |
| WF-11 | CSA member communication on shortfall | **Not in spreadsheet** | Paper process | TBD | Full elicitation required |
| WF-12 | Bed assignment and rotation planning | CropPlan spatial columns | INF-17, INF-12 | TBD | Rotation rules, multi-year view |

WF-10 and WF-11 are invisible to the Elicitor. They will only appear in the MWBS if the Paper Process Inventory section of the elicitation session surfaces them.

---

## Appendix B: MWBS Validation Checklist

Pre-sign-off checklist enforced by the gate:

```
SCHEMA
[ ] spec_version present and valid
[ ] project.status == signed_off
[ ] sign_off.operator.name non-empty
[ ] sign_off.operator.date non-empty

COMPLETENESS
[ ] At least one actor defined
[ ] At least one workflow defined
[ ] Every workflow references at least one exception
[ ] Every workflow has at least two acceptance criteria
[ ] At least one acceptance criterion is type: completion
[ ] At least one acceptance criterion is type other than completion
[ ] Every workflow has a priority value
[ ] Every decision has information_system_must_provide populated
[ ] No [REQUIRES_ELICITATION] placeholders remain

SCOPE
[ ] Every workflow in Elicitor candidate list is either:
    - present in workflows[], or
    - listed in sign_off.scope_exclusions with reason

COVERAGE MAP
[ ] coverage_map.workflows count matches workflows[] count
[ ] Every workflow in workflows[] appears in coverage_map
```
