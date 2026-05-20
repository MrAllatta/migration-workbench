# Meta Spec: DomainModel Orchestration and Frontend Manifest Extraction

> **Date:** 2026-05-20
> **Type:** Meta spec — spawns sub-specs for implementation
> **Status:** Draft

## Pure statement of direction

The migration-workbench produces customized Django applications from spreadsheet and Coda sources. The pipeline already extracts what the data IS (schema contract) and how it imports (bundle config). It does not yet:

1. Own its state in a single runtime object that accumulates knowledge across phases.
2. Extract how the data is USED — the interaction contract: which tabs are forms, which are dashboards, which columns drive workflow, which roles touch which views.

The next major evolution closes both gaps. The profiler becomes a **domain translator** that produces three contracts from messy spreadsheets: **data**, **import**, and **interaction**. The orchestration layer consolidates scattered artifact I/O into a single `DomainModel` object whose methods are phases and whose YAML serialization is the human's review surface.

---

## Part 1: DomainModel Orchestration

### What's broken

Today, pipeline state lives in six JSON artifacts (`drive_discovery`, `in_scope_workbook_index`, `broad_profile_coverage`, `tab_shortlist`, `tab_selection`, `deep_profile_coverage`) plus a `cohort_corpus.json` config, a `domain_context.yaml` (in flight), and a `domain-knowledge.yaml`. Each phase reads several files from disk, computes, and writes several more. The human edits JSON between phases to override selection. The dedup function must be called at exactly the right line in `run_cohort_corpus` or Phase 3 profiles structural duplicates. Knowledge from Phase 1 doesn't inform Phase 3 without being re-read from disk.

### What the DomainModel is

A single Python object (`DomainModel`) that is the profiler's runtime state. It is created empty or loaded from a YAML file. Its methods are pipeline phases. It serializes at checkpoint gates.

```
from migration_workbench.profiler.domain_model import DomainModel

model = DomainModel.load("build/farm/domain_model.yaml")

model.discover(drive_service, sheets_service)     # Phase 0/1
model.save()                                       # Gate: human inspects drive tree

model.score_and_select()                          # Phase 1/2
model.save()                                       # Gate: human reviews selection

model.deep_profile(sheets_service)                 # Phase 3
model.save()                                       # Gate: human reviews column profiles

model.enrich()                                     # FK, computed, entity groups

contract_yaml = model.to_schema_contract()
view_manifest_yaml = model.to_view_manifest()
```

**The state it owns:**

```python
@dataclass
class DomainModel:
    domain: DomainContext           # domain vocabulary, periods, glossary, entities
    source_tree: SourceTree         # Drive folder walk result
    workbook_index: list[dict]      # in-scope workbook records
    broad_inventory: list[dict]     # discovered tabs with dimensions
    shortlist: list[dict]           # scored and dedup-annotated tabs
    approved_tabs: dict             # {workbook_code: [tab_titles]}
    deep_profiles: list[dict]       # per-tab grid data and column profiles
    column_candidates: list[dict]   # scored column headers
    schema_contract: dict           # generated contract
    view_manifest: dict             # generated interaction contract
```

**The human checkpoint surface is ONE file.** Between phases, the human opens `domain_model.yaml`, reviews the section the phase just populated, edits inline, and resumes. No more finding `tab_shortlist_2026-05-19.json` in a directory of date-stamped artifacts.

### Makefile targets remain thin wrappers

```
profile-phase1:     model = DomainModel.load_or_create(config); model.discover(); model.save()
profile-phase2:     model = DomainModel.load(config); model.score_and_select(); model.save()
profile-phase3:     model = DomainModel.load(config); model.deep_profile(); model.save()
profile-all:        model = DomainModel.load_or_create(config); model.discover(); model.score_and_select(); model.deep_profile(); model.enrich(); model.save()
```

### What ports directly

The internal functions (`score_tab`, `compute_column_profiles`, `enrich_fk_candidates`, `deduplicate_index_records`, `build_cohort_corpus_index`, `derive_column_candidates`) are methods or delegates — they read from `self` instead of parameters passed through a 600-line orchestration function.

### What gets replaced

`run_cohort_corpus()` — the 600-line function with three branch arms (fresh, resume_from_broad, resume_from_tab_selection). Each arm becomes a guard clause in the corresponding method.

### Sub-spec to spawn

- **DomainModel orchestration spec** — detailed schema for the DomainModel dataclass, YAML serialization format, phase method signatures, checkpoint gates, migration from current artifact-based pipeline, CLI surface

---

## Part 2: Frontend Manifest Extraction

### What the profiler already knows about interaction

These signals exist today but aren't surfaced as a contract:

| Signal | Source | What it means |
|--------|--------|---------------|
| `data_validation_type` | `compute_column_profiles()` | Column has a dropdown, checkbox, date picker, or number constraint |
| `formula_pattern = "expansion_formula"` | `compute_column_profiles()` | Column is a generated matrix, not data entry |
| `formula_pattern = "row_formula"` | `compute_column_profiles()` | Column is computed per row, not data entry |
| `cross_sheet_refs` | `compute_column_profiles()` | Column references another sheet — upstream dependency |
| `is_section_header` | `compute_column_profiles()` | Column is a visual divider, not data |
| `functions_used` | `summarize_tab()` | Tab uses SUM, VLOOKUP, FILTER — business logic signals |
| `formula_cell_count` | `summarize_tab()` | Tab is formula-heavy → likely a dashboard or computed view |
| `null_rate` | `summarize_tab()` | Column is sparse → likely optional or workflow-dependent |
| `status_field inference` | `_infer_status_field()` | Column named "Status"/"State"/"Stage" with dropdown → workflow state |
| `time_scope inference` | `_infer_time_scope()` | Year, week, date columns → temporal filters for UI |
| `editable vs computed split` | `_build_view_entry()` | Formula columns → computed, non-formula → editable |
| `filterable_by` | `_build_view_entry()` | Columns with data validation → filterable in UI |
| `tab_sequence` | `_build_workflow_hints()` | Tab position ordering → default navigation sequence |

### What's missing

Three categories of signals the profiler doesn't extract but could:

**1. Workflow sequence** — which tabs feed which

Cross-sheet `VLOOKUP`/`IMPORTRANGE` references encode upstream → downstream relationships. A tab full of formulas referencing another tab is *downstream*. A tab that's the target of many references is *upstream*. This yields a directed graph of tab dependencies that the UI can render as a workflow or navigation structure.

**2. UI archetype classification** — is this tab a form, a list, or a dashboard?

| Archetype | Signals |
|-----------|---------|
| **Form** | Many columns with data validation, high non-null rate, low formula density, single-digit merged spans |
| **List** | Moderate columns, moderate null rate, presence of status column, import range references |
| **Dashboard** | High formula density, expansion formulas, pivot-style columns, multi-column merged spans, low unique-count per column |
| **Reference** | Low row count, high uniqueness, many columns, near-zero formula density, column names match glossary patterns |

**3. Role boundaries** — which tabs are editable by whom

Tabs with `data_validation_type` columns and low formula density suggest *data entry* (someone fills them in). Tabs with high formula density and zero data validation suggest *review* (someone reads them). Cross-references suggest data flows between roles. The discovery interview already captures role hints per view; the profiler can seed them.

### What the frontend manifest becomes

Today's view manifest is authored manually or scaffolded from contract heuristics. The profiler-enriched manifest adds:

```yaml
views:
  CropPlanner:
    ui_archetype: form
    workflow_position: upstream
    feeds_into: [FieldRecord, HarvestAvailability]
    role_hints:
      primary: field_manager
      reviews: []
    form_fields:
      - column: Crop
        widget: dropdown
        required: true
      - column: Quantity
        widget: number
    computed_display:
      - column: Total Harvest
        source: SUM formula
    default_filters: [year, status]
    default_sort: [planting_date]
  WeeklySales:
    ui_archetype: dashboard
    workflow_position: downstream
    fed_by: [HarvestRecord, PackRecord, MarketList]
    role_hints:
      primary: operations_manager
      reviews: [field_manager]
    kpi_sections:
      - label: Revenue by Market
        source_columns: [Market, SalesAmount]
    computed_display:
      - column: Weekly Total
        source: SUM formula
```

This feeds into admin generation (what exists today) and into future frontend generation (what this meta spec enables).

### Sub-specs to spawn

- **Workflow sequence extraction spec** — cross-sheet reference analysis, dependency graph construction, upstream/downstream classification
- **UI archetype classification spec** — signal thresholds for form/list/dashboard/reference detection, confidence scoring, human override surface
- **Frontend manifest enrichment spec** — merging profiler signals into the view manifest format, propagating through discovery interview, feeding admin and future frontend codegen

---

## Part 3: Integration Points

### DomainModel as the carrier

All three contracts (data, import, interaction) live in the DomainModel. The profiler populates them. The human reviews them. Codegen consumes them.

```
DomainModel
├── domain_context        # vocabulary, periods, glossary, entities
├── source_tree           # raw Drive folder walk
├── workbook_index        # in-scope workbooks with period values
├── broad_inventory       # all discovered tabs
├── shortlist             # scored and selected tabs
├── approved_tabs         # final selection after overrides
├── deep_profiles         # grid data and column profiles
├── column_candidates     # scored column headers
├── schema_contract       # data contract (models, fields, FKs)
├── import_config         # import contract (bundles, tiers, transforms)
├── view_manifest         # interaction contract (archetypes, workflow, roles)
└── domain_knowledge      # human-authored entity definitions (field types, FK targets)
```

### Provider abstraction

The DomainModel is provider-agnostic. The `source_tree` field carries a Drive folder walk for Sheets or a doc list for Coda. The `deep_profiles` field carries per-tab grid data regardless of source. The enrichment passes (entity grouping, FK detection, UI archetype classification) operate on the same column profile structure regardless of provider. Coda-specific signals (`is_relation_type`, `ref_tables_seen`) augment the same column profile fields.

### Agency boundaries

The DomainModel surfaces human judgment at checkpoint gates. Between phases, the human edits `domain_model.yaml` to override selection, adjust vocabulary, reclassify archetypes, or bind entities. Autonomous mode reads the model from its last save and proceeds without interruption — but the checkpoint surface is always available.

---

## Spinoff Specs and Plans

### Immediate (build on current domain context artifact)

1. **`spec/domain-model-orchestration.md`** — DomainModel dataclass schema, YAML serialization, phase methods, checkpoint gates, migration path from `run_cohort_corpus`. Spec → plan → implement.

2. **`plan/domain-context-artifact.md`** — Already written. Ships period-aware dedup, vocabulary mapping, glossary expansion. Proves the domain context schema that becomes the DomainModel's seed.

### Short-term (build on DomainModel)

3. **`spec/workflow-sequence-extraction.md`** — Cross-sheet formula reference graph. Upstream/downstream classification. Dependency ordering for import and UI navigation.

4. **`spec/ui-archetype-classification.md`** — Form/list/dashboard/reference signal thresholds. Confidence scoring. Per-tab archetype assignment with human override.

5. **`plan/frontend-manifest-enrichment.md`** — Merge profiler workflow/archetype/role signals into view manifest YAML. Feed admin generation. Expose in discovery interview.

### Medium-term (build on frontend manifest)

6. **`spec/frontend-codegen-from-manifest.md`** — Generate Django views, templates, or React components from the enriched view manifest. List views with filters from `filterable_by`. Form views with widgets from `data_validation_type`. Dashboard views with KPI sections from formula analysis.

7. **`spec/provider-abstraction-hardening.md`** — Unify Sheets and Coda enrichment pipelines. DomainModel as provider-agnostic carrier. Coda-specific signals generalized.

---

## Guiding Principles

**State ownership over artifact scattering.** The DomainModel owns all pipeline state. JSON files are serialization, not communication.

**Extraction over configuration.** The profiler extracts signals (workflow, archetype, roles) from the data. The human reviews and overrides, not authors from scratch.

**Provider agnosticism.** Signals extracted from Sheets and Coda enrich the same column profile structure. Provider-specific signals augment, not fork.

**Checkpoints over automation.** Every phase has a human gate. Autonomous mode blasts through gates, but the surface exists for review.

**The schema-design loop stays.** Profile → Observe → Draft → Decide → Author → Gate → Drift check. The DomainModel is the runtime context for this loop. The frontend manifest is a new output of the Observe and Draft steps.
