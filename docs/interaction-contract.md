# Interaction Contract

> **Status:** Design spec  
> **Replaces:** Flat view-manifest as the single UI contract  
> **Audience:** Workbook implementers, frontend codegen authors, pipeline operators

The schema contract captures what the data **IS** (models, fields, types).
The interaction contract captures how the data is **USED** (who fills it out,
when, in what sequence, for what purpose).

This is critical for the consultant because:

- A **dashboard** tab should be read-only in the generated admin.
- A **form** tab needs inline editing, validation, and status workflow.
- A **reference** tab needs search, not bulk import.
- Workflow sequence informs tab ordering and navigation.
- Role boundaries inform Django group permissions.

The profiler extracts these signals automatically. The consultant confirms or
overrides them. The result is a better admin and better client advice.

This spec replaces the flat design with a **three-layer interaction contract**:

1. **Profiler signals** — machine-generated, read-only, regenerated on every profile run.
2. **Human interaction contract** — consultant-authored or discovery-interview-derived, preserved across profiler reruns.
3. **Codegen manifest** — derived by merging 1 + 2, consumed by `generate_admin` and future frontend codegen.

---

## The Three Layers

```
Profiler signals (machine-generated, read-only)
        ↓
Human interaction contract (operator-authored, stable)
        ↓
Codegen manifest (derived, deterministic, consumed by generators)
```

### Layer 1: Profiler Signals

**Artifact:** `build/profiler-signals.yaml`  
**Generator:** `scaffold_view_manifest --signals-only`  
**Policy:** Safe to overwrite on every profile run. Contains no human decisions.

The output format is a flat list of signal entries (one per tab) with 12
heuristic signals used for archetype classification:

```yaml
version: 2
generated_at: "2026-06-01T12:00:00+00:00"
signals:
  - tab_title: Crop Planner
    workbook_code: farm_corpus
    ui_archetype: form
    confidence_score: 0.87                # 0.0–1.0 margin-based confidence
    column_count: 12                      # total columns in the tab
    avg_null_rate: 0.23                   # average null rate across columns
    formula_density: 0.02                 # formula cell count / total cells
    cross_sheet_refs: 2                   # count of cross-sheet references
    null_rates:
      notes: 0.45
      planting_date: 0.0
    has_status_column: true               # inferred from header + data validation
    has_time_scope: true                  # year/week/date columns detected
    data_validation_density: 0.38         # fraction of columns with validation
    header_formula_count: 2               # columns with formula-keyword headers
    header_entity_count: 4                # columns with entity-keyword headers
    merged_cell_ratio: 0.0                # fraction of merged header cells
    row_count: 152
    expansion_formula_ratio: 0.0          # fraction of expansion-formula columns
    archetype_scores:                     # score vector for all 4 archetypes
      form: 0.87
      list: 0.20
      dashboard: 0.10
      reference: 0.03

  - tab_title: Weekly Sales
    workbook_code: farm_corpus
    ui_archetype: dashboard
    confidence_score: 0.92
    column_count: 8
    avg_null_rate: 0.05
    formula_density: 0.78
    cross_sheet_refs: 2
    null_rates: {}
    has_status_column: false
    has_time_scope: false
    data_validation_density: 0.0
    header_formula_count: 0
    header_entity_count: 1
    merged_cell_ratio: 0.25
    row_count: 52
    expansion_formula_ratio: 0.12
    archetype_scores:
      form: 0.05
      list: 0.10
      dashboard: 0.92
      reference: 0.02
```

### Layer 2: Human Interaction Contract

**Artifact:** `build/interaction-contract.yaml`  
**Authored by:** Discovery interview + operator manual edits  
**Policy:** Never overwritten by the profiler. Merged additively on re-interview.

```yaml
version: interaction-contract-1
views:
  CropPlanner:
    archetype: form                   # human-confirmed or overridden
    role_owner: field_manager         # Django group name or custom role
    role_reviewers: []               # who reviews / approves
    workflow_notes: "Filled out every Monday by field managers."
    status_semantics:
      field: status
      values:
        - Planted: "Seed in ground, not yet sprouted"
        - Growing: "Sprouted, being tended"
        - Harvested: "Ready for sale"
    operator_actions:
      - "Mark crop as harvested"
      - "Add weekly bed count"

  WeeklySales:
    archetype: dashboard
    role_owner: operations_manager
    role_reviewers: [field_manager]
    workflow_notes: "Read-only summary for operations review."
    kpi_sections:
      - label: "Revenue by Market"
        source_columns: [Market, SalesAmount]
```

### Layer 3: Codegen Manifest

**Artifact:** `build/codegen-manifest.yaml`  
**Generator:** `merge_interaction_contract` (or implicit in `generate_admin`)  
**Policy:** Fully derived. Regenerated whenever signals or human contract changes.

This is the format that `generate_admin` and future frontend generators consume. It is the old `view-manifest-draft-1` format, but with enriched fields from Layer 1 + 2 merged in.

```yaml
version: codegen-manifest-1
generated_from:
  signals: build/profiler-signals.yaml
  interaction_contract: build/interaction-contract.yaml

views:
  - name: crop_plan_entry
    entity: crop_plan_entry
    source_tab: Crop Planner
    type: form                          # from human contract (Layer 2)
    archetype_confidence: 0.87           # from profiler signals (Layer 1)
    editable_fields: [crop, quantity, planting_date]
    computed_fields: [total_harvest]
    filterable_by: [source_bundle_year, status]
    status_field: status
    status_values: [Planted, Growing, Harvested]
    time_scope:
      year_field: source_bundle_year
      week_field: plan_week
      date_field: planting_date
      default_scope: current_season
    role_owner: field_manager           # from human contract
    role_reviewers: []
    workflow_position: upstream          # derived from dependency graph
    feeds_into: [HarvestRecord, FieldRecord]

workflow_graph:
  tabs:
    CropPlanner: {archetype: form, role_owner: field_manager}
    HarvestRecord: {archetype: list, role_owner: field_manager}
    WeeklySales: {archetype: dashboard, role_owner: operations_manager}
  edges:
    - from: CropPlanner
      to: HarvestRecord
      ref_type: VLOOKUP
    - from: HarvestRecord
      to: WeeklySales
      ref_type: SUM_range

tab_sequence:
  - Crop Planner
  - Field Record
  - Harvest Availability
  - Weekly Sales
```

---

## UI Archetype Classification

The profiler assigns a `ui_archetype` signal based on column metadata and formula analysis. The human may override in the interaction contract.

| Archetype | Profiler Signals | Human Override Surface |
|-----------|------------------|------------------------|
| **Form** | Many columns with data validation, high non-null rate, low formula density, single-digit merged spans | "This tab is filled out weekly by field staff" |
| **List** | Moderate columns, moderate null rate, presence of status column, import-range references | "This is a reference lookup table" |
| **Dashboard** | High formula density, expansion formulas, pivot-style columns, multi-column merged spans, low unique-count per column | "Read-only summary for operations" |
| **Reference** | Low row count, high uniqueness, many columns, near-zero formula density, column names match glossary patterns | "Master data, seeded once" |

The `confidence` field indicates how strongly the signals converge. A low-confidence form (e.g., 0.52) means the signals are ambiguous and the human should decide.

---

## Consultant Decision Support

The profiler's archetype classification is not frontend codegen.
It answers operational questions that guide the consultant's configuration:

| Archetype | Consultant Question | Admin Implication |
|-----------|---------------------|-------------------|
| **Form** | "Who fills this out? How often?" | Inline editing, validation, status workflow |
| **List** | "Is this a lookup table or operational log?" | Search, filters, importable vs. read-only |
| **Dashboard** | "Who reads this? What decisions does it inform?" | Read-only, charts/graphs, email reports |
| **Reference** | "Is this master data or derived?" | Seed data, infrequent edits, heavy linking |

The consultant uses these answers to configure the generated admin
and to advise the client on workflow changes.

### CLI Decision Surface: `--explain` and `--min-confidence`

The `scaffold_view_manifest --signals-only` command supports two flags that
expose the archetype classification reasoning to the consultant:

**`--explain`**
Print a human-readable explanation for each tab's archetype classification.
Shows the winning label, confidence margin, top contributing signals (with
their raw values and contribution scores), and a low-confidence
RECOMMENDATION when the winning margin is slim.

Required: `--signals-only` must also be set.

**`--min-confidence <float>`**
Only show explanations for tabs with a confidence score *below* the given
threshold. For example, `--min-confidence 0.7` hides tabs whose archetype
is clearly established and shows only the ambiguous ones. Requires
`--explain`.

```bash
python manage.py scaffold_view_manifest             \
    --structure build/structure.json                  \
    --signals-only                                    \
    --explain                                         \
    --min-confidence 0.7
```

Example output:

```
Crop Planner — form (confidence 0.87, margin 0.67 over list at 0.20)
  Description: Structured data-entry form with moderate column count,
    data validation, and status tracking.
  Top contributing signals:
    - has_status_column: 1.0 → +3.0
    - data_validation_density: 0.38 → +3.0
    - column_count: 12.0 → +2.0
    - formula_density: 0.02 → +2.0
    - header_entity_count: 4.0 → +2.0

---

Weekly Sales — dashboard (confidence 0.92, margin 0.82 over list at 0.10)
  Description: High-formula summary view with cross-sheet references
    and chart-like layout.
  Top contributing signals:
    - formula_density: 0.78 → +4.0
    - expansion_formula_ratio: 0.12 → +2.0
    - merged_cell_ratio: 0.25 → +2.0
    - cross_sheet_ref_count: 2 → +2.0
  Signals against:
    - avg_null_rate: 0.05 → -2.0

---

2/3 tabs below --min-confidence 0.7
```

The "Signals against" section shows which signal values *weaken* the
winning archetype's score — these are the dimensions the consultant should
investigate if the classification feels wrong.

The summary line at the end (visible with `--min-confidence`) tells the
consultant how many tabs need attention, so they can focus their review
on the ambiguous cases rather than reading every tab's explanation.

---

## Dependency Graph (Workflow Sequence)

## Dependency Graph (Workflow Sequence)

Cross-sheet `VLOOKUP`, `IMPORTRANGE`, and `SUM` range references encode upstream → downstream relationships. The profiler extracts these into a directed graph.

**Why a graph instead of `workflow_position: upstream`:**

If tab A feeds both B and C, and B feeds D, a boolean-ish enum loses the branching structure. The graph preserves:
- Import ordering (topo-sort for tier assignment)
- UI navigation trees (which tabs naturally follow which)
- Role boundaries (subgraphs often map to role ownership)
- Drift detection (edges appearing/disappearing across runs reveal structural changes)

```yaml
workflow_graph:
  tabs:
    CropPlanner: {archetype: form, role_owner: field_manager}
    HarvestRecord: {archetype: list, role_owner: field_manager}
    PackRecord: {archetype: list, role_owner: field_manager}
    WeeklySales: {archetype: dashboard, role_owner: operations_manager}
  edges:
    - from: CropPlanner
      to: HarvestRecord
      ref_type: VLOOKUP
    - from: CropPlanner
      to: PackRecord
      ref_type: VLOOKUP
    - from: HarvestRecord
      to: WeeklySales
      ref_type: SUM_range
    - from: PackRecord
      to: WeeklySales
      ref_type: SUM_range
```

This graph is stored in the profiler signals layer and propagated into the codegen manifest. It is **not** editable by the human — if the graph is wrong, the source spreadsheet formula references are wrong, and that should be fixed at the source.

---

## Role Boundaries

The interaction contract defines role ownership at the view level. The codegen manifest propagates this to generated admin and future frontend code.

```yaml
# interaction-contract.yaml
views:
  CropPlanner:
    role_owner: field_manager
    role_reviewers: []
```

```python
# Generated admin.py (future capability, not yet implemented)
@admin.register(CropPlanEntry)
class CropPlanEntryAdmin(ModelAdmin):
    # ...
    def has_change_permission(self, request, obj=None):
        return request.user.groups.filter(name="field_manager").exists()
```

**Open question:** Should `role_owner` map to Django groups, permission codenames, or a custom `User` field? This is left to the product repo's auth model. The interaction contract stores the role label; the codegen layer maps it to the concrete auth mechanism via a configuration hook.

---

## Merge Semantics

When the profiler reruns, the merge tool reconciles new signals against the existing human contract:

| Scenario | Action |
|----------|--------|
| New tab appears in signals | Add to codegen manifest with default (empty) human contract entry |
| Tab removed from signals | Preserve human contract entry but mark `deprecated: true` in codegen manifest |
| Archetype signal changes | Update `archetype_confidence` in codegen manifest; do **not** override human-confirmed `archetype` |
| Human overrides archetype | Human value wins; signal is informational only |
| New edge in dependency graph | Add to codegen manifest; no human action required |
| Edge removed from graph | Remove from codegen manifest; log warning for operator review |

---

## Discovery Interview Integration

The existing discovery interview (`generate_discovery_interview` / `merge_discovery_notes`) writes to the **human interaction contract** layer, not directly to the codegen manifest.

```
scaffold_view_manifest --signals-only → profiler-signals.yaml
                                        ↓
generate_discovery_interview --signals profiler-signals.yaml → discovery-interview.md
                                        ↓
operator fills in interview
                                        ↓
merge_discovery_notes --signals profiler-signals.yaml --interview discovery-interview.md → interaction-contract.yaml
                                        ↓
generate_admin --contract schema-contract.yaml --manifest codegen-manifest.yaml → admin_auto.py
```

The `merge_discovery_notes` command becomes the **merge tool** that produces the interaction contract from interview answers + profiler signals.

---

## Related Documents

- [View Manifest Reference](view-manifest.md) — the legacy `view-manifest-draft-1` format (now the codegen manifest layer)
- [Pipeline State](pipeline-state.md) — runtime state model that carries the interaction contract
- [Schema Contract Reference](schema-contract.md) — data contract consumed alongside the interaction contract
- [Schema Design Loop](schema-design-loop.md) — step 6 covers view manifest and discovery interview
