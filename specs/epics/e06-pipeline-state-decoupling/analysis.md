# PipelineState Responsibility Analysis

**Source file:** `profiler/tools/pipeline_state.py` (3042 lines)
**Target:** Split into thin `PipelineState` checkpoint object + phase modules under `profiler/pipeline/phases/`

---

## 1. Checkpoint/Persistence Concerns (~1337 lines)

These form the **thin PipelineState checkpoint object** and its support layer. They concern *what* the state is, *how to save/load it*, and *how to migrate old formats*.

### 1.1 Dataclass definitions (lines 288–503)

| Class | Purpose |
|-------|---------|
| `DiscoveryState` | Source tree, workbook index, broad inventory, shortlist, approved tabs |
| `DeepProfileIndex` | References to external deep-profile JSON artifacts |
| `DomainKnowledge` | Human-provided domain context (vocabulary, year scope, entities) |
| `DecisionRecord` | Individual operator/agent decision with confidence and rationale |

### 1.2 PipelineState class — state fields only (lines 505–571)

All `@dataclass` fields defining what PipelineState holds:

- **Layer fields:** `version`, `discovery`, `deep_profile_index`, `domain_knowledge`
- **Contract fields:** `schema_contract`, `interaction_contract`
- **BPRS fields:** `operational_model`, `behavioral_spec`, `validation_record`, `coverage_report`, `formula_scan_results`, `test_scaffold`, `doc_scaffold`
- **Bookkeeping:** `decisions`, `completed_phases`, `artifact_provenance`, `operator_priority`, `profiler_signals_path`
- **Runtime-only fields (underscore prefix):** `_config`, `_out_dir`, `_date_stamp`, `_signals_output_path`, `_signals_cache`, `_checkpoint_dir`

### 1.3 Serialization layer (lines 822–1140, 2988–3042)

| Method | Concern |
|--------|---------|
| `save_checkpoint()` | Serialize to YAML, externalize large fields to JSON artifacts |
| `load()` | Deserialize from YAML, resolve artifact references, apply migrations |
| `load_or_create()` | Load existing checkpoint or create fresh from config JSON |
| `_to_dict_with_artifacts()` | Convert state to plain dict, write large lists to external JSON |
| `_from_resolved_dict()` | Reconstruct PipelineState from fully-resolved plain dict |
| `_resolve_artifacts()` (module-level) | Recursively resolve `{"_artifact": "path"}` dicts into inline data |
| `_write_contract_artifact()` (module-level) | Write contract artifact to disk |

### 1.4 Migration system (lines 109, 123–280, 1140–1163)

| Item | Concern |
|------|---------|
| `_CHECKPOINT_CURRENT_VERSION` | Current schema version string (`"0.3.0"`) |
| `_CHECKPOINT_MIGRATIONS` | Registry of version → migration function list |
| `_migrate_v0_0_8_to_v0_0_9` | No-op migration |
| `_migrate_v0_0_9_to_v0_1_0` | Legacy → BPRS unified pipeline migration |
| `_migrate_v0_2_0_to_v0_3_0` | Sentinels → explicit `completed_phases` list |
| `_apply_migrations()` | Orchestrate migration chain on load |
| `_is_scored_shortlist()` | Heuristic to detect migrated shortlist format |

### 1.5 Validation (lines 2268–2359)

| Method | Concern |
|--------|---------|
| `validate()` | Internal consistency checks: vocab keys, year_scope, approved_tabs cross-reference, decision completeness |

### 1.6 Helper utilities (lines 41–107, 100)

| Function | Concern |
|----------|---------|
| `_extract_approved_tabs()` | Recursive `approved_tabs` extraction from artifact dicts |
| `_version_tuple()` | Semver string → comparable tuple |
| `_version_less_than()` / `_version_less_eq()` | Version comparison |
| `_col_index_to_letter()` | Excel-style column letter conversion |
| `_load_json_artifact()` | Safe JSON file loader |
| `_parse_raw_deep_profile()` | Parse deep profile data into column list |

### 1.7 Runtime configuration & bookkeeping (lines 573–672, 746–821)

| Method | Concern |
|--------|---------|
| `__post_init__()` | Field type validation on construction |
| `configure()` | Set runtime config, out_dir, date_stamp |
| `record_decision()` | Append a decision record |
| `record_artifact_provenance()` | Track artifact origin |
| `get_artifact_provenance()` | Retrieve provenance for artifact key |
| `load_profiler_signals()` | Lazy-resolve profiler signals from checkpoint-relative path |

### 1.8 Module-level constants (lines 1–38, 109–120)

| Constant | Concern |
|----------|---------|
| `_ARTIFACT_FIELDS` | Fields externalized to JSON artifacts |
| `_CHECKPOINT_CURRENT_VERSION` | Current schema version |
| `_PHASE_ORDER` | Canonical phase ordering for dependency tracking |
| Imports | All from stdlib / Django / profiler tools |

---

## 2. Phase Logic (~1650 lines)

These are the **phase methods on PipelineState** that contain domain-specific logic for each pipeline step. They read from and write to PipelineState fields. Each should become a module under `profiler/pipeline/phases/`.

### 2.1 Core pipeline phases

| Method | Lines | Description |
|--------|-------|-------------|
| `discover()` | 1343–1443 | Phase 0/1: Discover source tree, enumerate workbooks, score tabs. Delegates to `run_cohort_corpus()`. Populates discovery fields. |
| `score_and_select()` | 1445–1564 | Phase 1/2: Re-score tabs using domain knowledge. Calls `score_tab()`, updates shortlist, auto-selects high-confidence tabs. |
| `deep_profile()` | 1566–1647 | Phase 3: Deep-profile approved tabs via `run_cohort_corpus()` resume mode. Populates deep_profile_index. |
| `_enrich_entry_with_formula_dependencies()` | 1649–1800 | Run formula dependency analysis on single deep-profile entry. |
| `_extract_columns_from_entry()` | 1801–1862 | Extract column definitions from a deep-profile entry. |
| `derive_contracts()` | 1863–1948 | Phase 4: Build schema_contract and interaction_contract from deep profiles. Includes tab classification, UI-config filtering, profiler signals emission. |
| `scan_formulas()` | 1950–2044 | Scan approved workbooks for formula patterns via `scan_workbook_patterns()`. |
| `_classify_deep_profiled_tabs()` | 2046–2111 | Classify tabs via `classify_tabs_batch()`, store in interaction_contract. |
| `_filter_ui_config_tabs()` | 2112–2178 | Filter UI-config tabs from the interaction contract. |
| `_emit_profiler_signals()` | 2179–2267 | Emit profiler signals YAML artifact alongside contracts. |

### 2.2 BPRS phase methods

| Method | Lines | Description |
|--------|-------|-------------|
| `derive_operational_model()` | 2365–2473 | Derive BPRS operational model from profiler artifacts. Resolves out_json references. |
| `derive_behavioral_spec()` | 2474–2589 | Derive MWBS behavioral spec from operational model. |
| `derive_state_projections()` | 2590–2624 | Derive projections (contract, tests, docs) from operational model. |
| `_derive_schema_contract_from_operational_model()` | 2625–2661 | Schema contract from operational model. |
| `_derive_test_scaffold_from_operational_model()` | 2662–2750 | Test scaffold from operational model (includes template classes). |
| `_derive_doc_scaffold_from_operational_model()` | 2752–2923 | Markdown documentation from operational model. |
| `validate_operational_model()` | 2925–2956 | Validate operational model, compute coverage. |
| `validate_behavioral_spec()` | 2958–2980 | Validate behavioral spec, compute coverage. |

### 2.3 Service construction (belongs to phase setup, not checkpoint)

| Method | Lines | Description |
|--------|-------|-------------|
| `_build_google_services()` | 650–671 | Build Google Drive and Sheets API service objects. |

---

## 3. Proposed Module Layout

```
profiler/pipeline/
├── __init__.py              # Exports PipelineState (from state.py)
├── base.py                  # Existing CorpusPipeline ABC (unchanged)
├── pipeline.py              # Existing CorpusPipelineDispatcher (unchanged)
├── adapters/                # Existing adapters (unchanged)
├── selection.py             # Existing selection utils (unchanged)
├── utils.py                 # Existing utility helpers (unchanged)
├── state.py                 # NEW: Thin PipelineState checkpoint object
│                            #   - All dataclasses (DiscoveryState, DeepProfileIndex,
│                            #     DomainKnowledge, DecisionRecord)
│                            #   - PipelineState class (fields + serialization only)
│                            #   - save_checkpoint(), load(), load_or_create()
│                            #   - _to_dict_with_artifacts(), _from_resolved_dict()
│                            #   - _apply_migrations(), migration functions
│                            #   - validate(), _resolve_artifacts()
│                            #   - record_decision(), record_artifact_provenance()
│                            #   - configure()
│                            #   - Module-level constants and helpers
│
└── phases/                  # NEW: Phase modules
    ├── __init__.py
    ├── discover.py          # discover() logic (delegates to cohort_corpus)
    ├── score_select.py      # score_and_select() logic
    ├── deep_profile.py       # deep_profile() + enrichment helpers
    ├── derive_contracts.py   # derive_contracts() + classify/filter/signal helpers
    ├── scan_formulas.py      # scan_formulas() logic
    ├── operational_model.py  # derive_operational_model() + related
    └── behavioral_spec.py    # derive_behavioral_spec() + validate + scaffold
```

### 3.1 Dependency flow

Each phase module:
1. Imports `PipelineState` from `..state`
2. Exports a function that takes `PipelineState` + phase-specific args → `PipelineState`
3. The old `PipelineState.phase_method()` becomes a thin wrapper or gets removed

```
state.PipelineState  ←  phases.discover  ←  run_pipeline_state command
                     ←  phases.score_select
                     ←  phases.deep_profile
                     ←  phases.derive_contracts
                     ←  phases.scan_formulas
                     ←  phases.operational_model
                     ←  phases.behavioral_spec
```

### 3.2 Phase size estimates (target lines extracted)

| Phase module | Source lines | Est. new LOC |
|-------------|--------------|--------------|
| `state.py` (checkpoint only) | ~1337 | ~800–900 |
| `phases/discover.py` | ~100 | ~100 |
| `phases/score_select.py` | ~120 | ~120 |
| `phases/deep_profile.py` | ~300 (incl. enrichment) | ~300 |
| `phases/derive_contracts.py` | ~400 (incl. classify/filter/signal) | ~400 |
| `phases/scan_formulas.py` | ~95 | ~95 |
| `phases/operational_model.py` | ~300 (incl. project/scaffold) | ~300 |
| `phases/behavioral_spec.py` | ~100 (derive + validate) | ~100 |

### 3.3 Retained backward compat layer

The original `PipelineState` class in the old location (`profiler/tools/pipeline_state.py`) becomes a thin re-export shim for one release cycle:

```python
# profiler/tools/pipeline_state.py — backward compat shim
from profiler.pipeline.state import PipelineState, DiscoveryState, ...
```

All existing consumers (tests, `run_pipeline_state` command, cohort corpus modules) continue to work without changes.

---

## 4. Key Design Decisions

**Decision 1: One module per concrete phase, not one per abstract phase.**
The `CorpusPipeline` ABC in `base.py` has 7 abstract phases (discover, build_index, broad_profile, select, deep_profile, derive_columns, enrich_columns). PipelineState's phases map differently: some correspond, some don't. Each phase module should cover one `PipelineState.completed_phases` entry.

**Decision 2: Phase functions receive PipelineState, mutate it, return it.**
Preserving the existing chaining pattern (`return self`) keeps `run_pipeline_state` command code simple:

```python
state = pipeline_state.discover()
state = pipeline_state.score_and_select()
state = pipeline_state.deep_profile()
```

**Decision 3: `_build_google_services()` stays in state.py or moves to connector utils.**
It's a service factory, not phase logic. It doesn't belong in any single phase module. Best home might be `connectors/google_sheets.py` or a shared utility.

**Decision 4: Load-bearing private methods (`_enrich_*`, `_classify_*`, `_filter_*`, `_emit_*`) travel with their caller phase.**
These are implementation details of specific phases and should be private within their phase module. They don't need to be testable from outside.

---

## 5. Consumer Map

| Consumer | File | Uses |
|----------|------|------|
| `run_pipeline_state` command | `profiler/management/commands/run_pipeline_state.py` | Imports `PipelineState`, calls phase methods |
| PipelineState tests | `profiler/tests/test_pipeline_state.py` (2360 lines) | Tests all dataclasses + serialization + phases |
| Phase tests | `profiler/tests/test_pipeline_state_phases.py` (158 lines) | Tests phase methods |
| Cohort corpus | `profiler/tools/cohort_corpus.py` | Called by phase methods |
| Pipeline dispatcher | `profiler/pipeline/pipeline.py` | Separate concern (CorpusPipeline) |

**Test migration plan:** Tests for checkpoint/serialization logic stay in `test_pipeline_state.py`. Tests for phase logic move to per-phase test files under `profiler/tests/test_phases_*.py` or stay in the existing file with updated imports.