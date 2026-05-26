# Pipeline State

> **Status:** Design spec  
> **Replaces:** DomainModel orchestration proposal  
> **Audience:** Profiler implementers, pipeline operators

The migration-workbench profiler currently scatters pipeline state across date-stamped JSON artifacts (`drive_discovery`, `in_scope_workbook_index`, `broad_profile_coverage`, `tab_shortlist`, `tab_selection`, `deep_profile_coverage`, `cohort_corpus.json`, and `domain_context.yaml`). Each phase reads several files from disk, computes, and writes several more. The human edits JSON between phases to override selection.

This spec replaces the monolithic "DomainModel" proposal with a **layered, checkpoint-based state model** called `PipelineState`.

---

## Core Principles

1. **State owns metadata; data lives externally.** Raw grid data, column profiles, and formula artifacts are large and machine-generated. The checkpoint surface is a small YAML file the human reviews and edits.
2. **Three layers stay distinct:** what the machine learned, what the human confirmed, and what was derived.
3. **Human checkpoint between every phase.** The operator opens one file, reviews the decisions from the phase just completed, edits inline, and resumes.
4. **Provider-agnostic shape.** The state model carries `source_tree` and `deep_profile_index` fields that accept Drive, Coda, or future provider metadata without forking the structure.
5. **YAML today, SQLite tomorrow.** The checkpoint file path stays the same; the storage backend can evolve transparently.
6. **Agent reasoning is explicit, not opaque.** Every autonomous decision the agent makes is recorded with a confidence score. The consultant reviews low-confidence decisions; high-confidence decisions are silently applied. Over engagements, the consultant's corrections teach the agent.

---

## Layered State Model

```python
@dataclass
class PipelineState:
    version: str                      # e.g., "0.2.0"

    # Layer 1 — What the machine learned (profiler outputs)
    discovery: DiscoveryState         # source_tree, workbook_index, inventory, shortlist
    deep_profile_index: DeepProfileIndex  # references to external JSON artifacts, not inline data

    # Layer 2 — What the human provided / confirmed
    domain_knowledge: DomainKnowledge  # evolves from today's DomainContext

    # Layer 3 — Derived contracts (computed from 1 + 2)
    schema_contract: SchemaContract | None
    interaction_contract: InteractionContract | None
```

### Layer 1: DiscoveryState

Carries the profiler's mechanical findings. Each field is small metadata, not raw cell data.

| Field | Type | Description |
|-------|------|-------------|
| `source_tree` | `dict` | Provider-specific folder/doc enumeration. For Sheets: Drive folder walk result. For Coda: doc list with doc IDs and URLs. |
| `workbook_index` | `list[dict]` | In-scope workbooks with extracted year, workbook code, and spreadsheet/doc ID. |
| `broad_inventory` | `list[dict]` | All discovered tabs with dimensions (row count, column count, formula density). |
| `shortlist` | `list[dict]` | Scored and deduplication-annotated tabs. Includes `selection_summary` with year distribution and dedup counts. |
| `approved_tabs` | `dict[str, list[str]]` | Final tab selection per workbook code, after human override. |

### Layer 2: DomainKnowledge

Evolves directly from the existing `DomainContext` dataclass in `profiler/tools/domain_context.py`. Carries vocabulary, year scope, deduplication strategy, entity definitions, glossary, and human scope notes.

| Field | Type | Description |
|-------|------|-------------|
| `domain` | `str` | Domain identifier, e.g., `"farm_management"`. |
| `vocabulary` | `VocabularyContext` | operational / reference / support / derived tokens mapped to heuristic scoring. |
| `year_scope` | `YearScope` | active, archived, forward year lists. |
| `deduplication` | `DeduplicationContext` | strategy (`latest_year` or `all`) and per-tab exceptions. |
| `entities` | `list[dict]` | Human-authored entity definitions: name, source tabs, fields, import keys, FK targets. |
| `glossary` | `dict[str, str]` | Synonym expansion map (e.g., `qty → quantity`). |
| `scope_notes` | `str` | Freeform operator notes from orientation. |

### Layer 3: Derived Contracts

Computed outputs that downstream stages consume. These are **not** hand-edited directly; instead, the operator edits Layer 2 (domain knowledge) or the intermediate checkpoint, and the contracts are regenerated.

| Contract | Consumed By | Description |
|----------|-------------|-------------|
| `schema_contract` | `generate_models`, `generate_import` | Data contract: models, fields, FKs, import tiers. |
| `interaction_contract` | `generate_admin`, future frontend codegen | UI/workflow contract: archetypes, dependency graph, role boundaries. See [Interaction Contract](interaction-contract.md). |

---

## Checkpoint YAML Format

The human checkpoint surface is **one file** — `pipeline-state.yaml`. It contains only Layers 1 and 2 metadata plus decisions. Raw grid data is referenced, never inlined.

```yaml
version: "0.2.0"

# Layer 1 — Machine discoveries
discovery:
  source_tree:
    provider: google_sheets
    folder_id: 1ABC...
    spreadsheets:
      - name: "101_FarmPlan_2023"
        id: 1DEF...
  workbook_index:
    - workbook_code: "101"
      year: 2023
      spreadsheet_id: 1DEF...
  broad_inventory:  # abbreviated; full data in external JSON
    _artifact: "data/profile_snapshots/broad_profile_coverage_2026-05-26.json"
  shortlist:
    _artifact: "data/profile_snapshots/tab_shortlist_2026-05-26.json"
    selection_summary:
      by_workbook_by_year:
        "101": {"2023": 4, "2024": 4}
      deduplicated_count: 14
      original_count: 48
  approved_tabs:
    "101": ["Crop Planner", "Field Record", "Harvest Availability"]

# Layer 2 — Human domain knowledge
domain:
  domain: "farm_management"
  vocabulary:
    operational: [crop, planting, harvest, field, variety]
    reference: [market, channel, customer]
  year_scope:
    active: [2025, 2026]
    archived: [2023, 2024]
  deduplication:
    strategy: latest_year
    exceptions:
      - tab_title: "Annual Budget"
        reason: "Changes meaning every year"
  entities:
    - name: "Season"
      source_tabs: ["Crop Planner"]
      fields:
        name: {type: CharField, max_length: 100, unique: true}
      import_key: [name]
  glossary:
    qty: quantity
    amt: amount
  scope_notes: "Focus on 2025-2026; 2023-2024 are historical only."

# Layer 3 — Derived (read-only in checkpoint)
schema_contract:
  _artifact: "build/schema-contract.yaml"
interaction_contract:
  _artifact: "build/interaction-contract.yaml"
```

### Design decisions

- **`_artifact` keys** reference external files. The checkpoint never embeds raw grid data or full column profiles. This keeps the YAML human-reviewable (hundreds of lines, not thousands).
- **`approved_tabs` is the human override surface.** Between Phase 2 (scoring/selection) and Phase 3 (deep profiling), the operator edits `approved_tabs` to add or remove tabs. The profiler reads this on resume.
- **Layer 3 contracts are regenerated, not edited.** If the operator wants to change the schema contract, they edit `domain_knowledge.entities` or `approved_tabs` and rerun the derivation phase.

---

## Phase Methods and Checkpoint Gates

```python
from migration_workbench.profiler.pipeline_state import PipelineState

state = PipelineState.load_or_create("config/cohort_corpus.json")

# Phase 0/1: Agent discovers source tree
state.discover(drive_service, sheets_service)
# Autonomous: enumerates folders, identifies workbooks
# Alert: flags workbooks with no year in title (can't auto-classify)
state.save_checkpoint("pipeline-state.yaml")           # Gate: review alerts

# Phase 1/2: Agent scores and selects tabs
state.score_and_select()
# Autonomous: scores tabs using domain context vocabulary
# Alert: tabs with ambiguous scores (0.3–0.7) flagged for review
# Blocking: duplicate tab detection requires human choice (latest year vs. all)
state.save_checkpoint("pipeline-state.yaml")           # Gate: resolve alerts, choose duplicates

# Phase 3: Agent deep-profiles approved tabs
state.deep_profile(sheets_service)
# Autonomous: classifies formula taxonomy, detects FK candidates
# Alert: FK candidate with low overlap ratio (0.5–0.8) flagged
state.save_checkpoint("pipeline-state.yaml")           # Gate: confirm FK targets

# Derivation: Agent builds contracts
state.derive_contracts()
# Autonomous: generates schema contract from profile + domain knowledge
# Alert: model with unresolved FK targets (TODO_TargetModel)
# Blocking: contract validation fails on duplicate model names
state.save_checkpoint("pipeline-state.yaml")           # Gate: resolve FKs, validate
```

### Makefile targets (thin wrappers)

```makefile
profile-phase1:
	python manage.py run_pipeline_state --config config/cohort_corpus.json --phase discover --checkpoint pipeline-state.yaml

profile-phase2:
	python manage.py run_pipeline_state --config config/cohort_corpus.json --phase score_and_select --checkpoint pipeline-state.yaml

profile-phase3:
	python manage.py run_pipeline_state --config config/cohort_corpus.json --phase deep_profile --checkpoint pipeline-state.yaml

profile-all:
	python manage.py run_pipeline_state --config config/cohort_corpus.json --phase all --checkpoint pipeline-state.yaml
```

---

## Judgment Taxonomy (Learning Surface)

Every `alert` the agent raises is a learning opportunity. The consultant's choice
teaches the agent for the next engagement.

Example taxonomy entry (accumulated across engagements):

| Decision | Confidence Threshold | Action | Vertical Override |
|----------|---------------------|--------|-------------------|
| Tab is operational (not pivot) | > 0.85 | Autonomous | Farm: lower to 0.75 |
| Column is FK candidate | > 0.80 | Autonomous | Farm: raise to 0.90 |
| Formula column is computed field | > 0.90 | Autonomous | None |
| Duplicate tab (same title, different year) | Any | Blocking (human must choose) | None |
| Model name from tab title | > 0.95 | Autonomous | Farm: use glossary |

The PipelineState checkpoint records every decision the agent made, its confidence,
and whether the consultant overrode it. This log is the training data for vertical
templates.

---

## Migration from Artifact-Based Pipeline

The existing `run_cohort_corpus()` function (600+ lines with three branch arms) is replaced by phase methods on `PipelineState`. Each arm becomes a guard clause:

| Old Behavior | New Behavior |
|--------------|--------------|
| Fresh run | `PipelineState.load_or_create()` → `discover()` → `score_and_select()` → `deep_profile()` |
| `resume_from_broad` | `PipelineState.load()` → skip `discover()` if `discovery.broad_inventory` exists → `score_and_select()` |
| `resume_from_tab_selection` | `PipelineState.load()` → skip `discover()` and `score_and_select()` if `approved_tabs` exists → `deep_profile()` |

Internal functions (`score_tab`, `compute_column_profiles`, `deduplicate_index_records`, `build_cohort_corpus_index`) become methods or delegates that read from `self.discovery` instead of parameters passed through a monolithic orchestration function.

---

## Storage Evolution

**Phase A (0.2.0):** Checkpoint is YAML. Human edits directly. `PipelineState.load()` parses YAML; `save_checkpoint()` writes YAML.

**Phase B (0.3.0+):** When state size exceeds comfortable YAML editing (e.g., 500+ tabs, deep profile metadata), `PipelineState` transparently migrates to SQLite at the same file path. The API stays identical:

```python
# Works for both YAML and SQLite backends
state = PipelineState.load("pipeline-state.yaml")
state.save_checkpoint("pipeline-state.yaml")
```

The SQLite schema mirrors the dataclass fields: `discovery`, `domain_knowledge`, `contracts` tables with JSON columns. Human review uses a small CLI (`wb state review`) or exports a filtered YAML view.

---

## Naming Discipline

The previous proposal used three names for the same concept (`DomainContext`, `DomainModel`, `PipelineContext`). This spec settles on one name:

| Name | What it is | Lives in |
|------|-----------|----------|
| `DomainContext` | **Human-authored** YAML file read by the profiler at scoring time | `config/domain_context.yaml` |
| `PipelineState` | **Runtime object** that accumulates knowledge across phases, serializes at checkpoints | `profiler/tools/pipeline_state.py` |
| `pipeline-state.yaml` | **Checkpoint file** the human reviews between phases | `build/pipeline-state.yaml` |

---

## Related Documents

- [Domain Context Artifact](schema-contract.md) — vocabulary, year scope, deduplication (existing implementation in `profiler/tools/domain_context.py`)
- [Interaction Contract](interaction-contract.md) — three-layer UI/workflow contract design
- [Schema Contract Reference](schema-contract.md) — data contract format consumed by codegen
- [Roadmap](roadmap.md) — 0.2.0 milestone criteria
