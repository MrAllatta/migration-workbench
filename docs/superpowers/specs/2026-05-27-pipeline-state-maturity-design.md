# PipelineState Maturity — Design Spec

> **Status:** Approved design  
> **Audience:** Implementers  
> **Covers:** P0+P1 gaps identified in PipelineState maturity assessment

## Scope

Six work items to take PipelineState from "structured checkpoint container" to "live pipeline orchestrator":

| Priority | Work Item |
|----------|-----------|
| P0 | Decision record logging |
| P0 | Real phase method implementations |
| P0 | Contract artifact resolution on load |
| P1 | Version migration registry |
| P1 | Post-init validation |
| P1 | Artifact path derivation from checkpoint location |

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Phase method implementation | Delegate to existing profiler tools | Fastest path; existing `run_cohort_corpus()` does real work; PipelineState wraps it with decision recording |
| Decision storage | Flat `decisions` list on `PipelineState` | Simplest to review, diff between checkpoints, and query for judgment taxonomy |
| Config routing | Store config dict privately on PipelineState at load/create time | Eliminates config re-plumbing through management command |
| Contract resolution | Eager resolution during `load()` | Fully hydrated state, no lazy-loading footguns |
| Version migration | Dict-of-callables registry applied in `load()` | Simple, explicit, no external dependencies |

## 1. Decision Recording

### New dataclass: `DecisionRecord`

```python
@dataclass
class DecisionRecord:
    phase: str                       # "discover", "score_and_select", "deep_profile", "derive_contracts"
    decision_type: str               # "tab_scoring", "fk_candidate", "model_name", etc.
    entity_ref: str                  # what was decided about (tab title, column name)
    value: Any                       # chosen value
    confidence: float                # 0.0–1.0
    reasoning: str                   # why the agent chose this
    overridden: bool = False         # was this overridden by consultant?
    override_value: Any | None = None
    overridden_at: str | None = None # ISO timestamp
```

### On PipelineState

```python
decisions: list[DecisionRecord] = field(default_factory=list)

def record_decision(self, phase, decision_type, entity_ref, value,
                    confidence, reasoning) -> None: ...
```

### Confidence levels (from agent-harness.md)

| Range | Classification | Consultant role |
|-------|---------------|-----------------|
| >= 0.90 | Autonomous | Silent apply |
| 0.50–0.90 | Alert | Review & confirm |
| < 0.50 | Blocking | Must decide |

### Serialization

Decisions serialize as a YAML array in the checkpoint. When a consultant edits the checkpoint YAML between saves, `load()` detects changes against the last-saved decisions snapshot and auto-records overrides.

## 2. Phase Method Rewrites

### `discover(drive_service, sheets_service) -> PipelineState`

**Guard:** Raises if `source_tree` already populated.

**Behavior:**
1. Calls `run_cohort_corpus(drive_service, sheets_service, config, out_dir, ...)` from `profiler.tools.cohort_corpus`
2. Maps returned artifact paths onto PipelineState fields:
   - `discovery.source_tree` ← `artifact_paths["discovery"]`
   - `discovery.workbook_index` ← `artifact_paths["index"]`
   - `discovery.broad_inventory` ← `artifact_paths["broad_coverage"]`
   - `discovery.shortlist` ← `artifact_paths["tab_shortlist"]`
   - `discovery.approved_tabs` ← `artifact_paths["tab_selection"]`
3. Records `tab_scoring` decisions from each shortlist entry
4. Returns `self`

### `score_and_select() -> PipelineState`

**Guard:** Raises if `source_tree` is None or `shortlist` is None.

**Behavior:**
1. Re-scores `broad_inventory` using `domain_knowledge.vocabulary` (no API calls)
2. Updates `shortlist` with new scores and rationales
3. Records scoring decisions
4. Auto-selects high-confidence tabs (confidence >= 0.90) into `approved_tabs`, flags low-confidence ones (< 0.90) for consultant review
5. Returns `self`

### `deep_profile(sheets_service) -> PipelineState`

**Guard:** Raises if `approved_tabs` is None.

**Behavior:**
1. Calls `run_cohort_corpus()` in `resume_from_tab_selection` mode with approved tabs
2. Populates `deep_profile_index.entries` from deep coverage artifact
3. Records `fk_candidate` and `computed_field` decisions
4. Returns `self`

### `derive_contracts() -> PipelineState`

**Guard:** Raises if `deep_profile_index.entries` is empty.

**Behavior:**
1. Calls contract-building pipeline (existing `scaffold_workbook_schema` or equivalent)
2. Populates `schema_contract` and `interaction_contract`
3. Records `model_name` and `fk_resolution` decisions
4. Returns `self`

### Helper methods moved into PipelineState

These move from the management command:
- `_load_config(config_path)` — reads config JSON
- `_today_stamp()` — returns ISO date string
- `_load_json_artifact(path, default)` — reads JSON file with fallback
- `_build_services()` — builds Google API service objects (for `discover()` and `deep_profile()`)
- `_derive_out_dir()` — derives output directory from config or default

The `_config` field is populated by `load_or_create()` and used by phase methods.

## 3. Contract Artifact Resolution

Currently `_from_resolved_dict()` ignores `schema_contract` and `interaction_contract` keys.

**Fix:** `load()` passes `base_dir` to `_from_resolved_dict()`, which calls `_resolve_artifacts()` on the contract keys before assigning. Eager resolution — fully hydrated state after load.

```python
@classmethod
def _from_resolved_dict(cls, raw: dict[str, Any], base_dir: Path) -> PipelineState:
    ...
    schema_raw = _resolve_artifacts(raw.get("schema_contract"), base_dir)
    schema_contract = schema_raw if isinstance(schema_raw, dict) and schema_raw else None

    interaction_raw = _resolve_artifacts(raw.get("interaction_contract"), base_dir)
    interaction_contract = interaction_raw if isinstance(interaction_raw, dict) and interaction_raw else None
```

## 4. Version Migration Registry

```python
_CHECKPOINT_MIGRATIONS: dict[str, list[Callable[[dict], dict]]] = {
    # "0.0.8": [_migrate_v0_0_8_to_v0_0_9],
}

@classmethod
def _apply_migrations(cls, raw: dict[str, Any]) -> dict[str, Any]:
    version = raw.get("version", "0.0.0")
    current = "0.0.9"  # sync with version field default
    for from_ver, migrations in sorted(_CHECKPOINT_MIGRATIONS.items()):
        if _version_less_than(version, from_ver) and _version_less_eq(from_ver, current):
            for migrate_fn in migrations:
                raw = migrate_fn(raw)
    raw["version"] = current
    return raw
```

Called in `load()` after YAML parse, before `_from_resolved_dict()`. Each migration function takes and returns a raw dict (the parsed YAML structure).

### Version comparison helpers

```python
def _version_less_than(v1: str, v2: str) -> bool:
    """Compare two semver strings."""
    ...

def _version_less_eq(v1: str, v2: str) -> bool:
    ...
```

## 5. Post-Init Validation

Lightweight `__post_init__` on each dataclass:

| Dataclass | Checks |
|-----------|--------|
| `PipelineState` | `version` is str; warn if `approved_tabs` present without `workbook_index` |
| `DiscoveryState` | `source_tree` is dict or None; `workbook_index` is list; etc. |
| `DomainKnowledge` | `vocabulary` has all 4 keys; `year_scope` has all 3 keys |
| `DeepProfileIndex` | `entries` is list |
| `DecisionRecord` | `confidence` is 0.0–1.0 |

Type errors raise `TypeError`. Warnings use `logger.warning`.

## 6. Artifact Path Derivation

Replace hardcoded paths with checkpoint-relative paths in `_to_dict_with_artifacts()`:

| Current | New |
|---------|-----|
| `"build/schema-contract.yaml"` | `base_dir / "schema-contract.yaml"` |
| `"build/interaction-contract.yaml"` | `base_dir / "interaction-contract.yaml"` |

Contracts sit alongside the checkpoint file, not in a hardcoded `build/` directory.

## Files Affected

| File | Change |
|------|--------|
| `profiler/tools/pipeline_state.py` | All 6 work items |
| `profiler/management/commands/run_pipeline_state.py` | Simplified to thin CLI wrapper |
| `profiler/tests/test_pipeline_state.py` | New test classes for decisions, migrations, validation |
| `profiler/tests/test_run_pipeline_state_command.py` | Updated for simplified command |

## Non-Goals (out of scope for this pass)

- SQLite storage backend (Phase B in design spec)
- Audit trail / diff detection between checkpoints
- Concurrent access safety (file locking)
- Inlining profiler logic into PipelineState (delegation wrappers now; inline later)
- Decision taxonomy learning loop (requires accumulation across engagements)
