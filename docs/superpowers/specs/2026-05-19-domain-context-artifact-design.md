# Domain Context Artifact Design

Date: 2026-05-19

## Problem

The migration-workbench profiler has structural intelligence (formula classification, FK detection, entity grouping) but lacks domain intelligence. There is no way to inject what-the-business-is before heuristics are configured. An autonomous pipeline run revealed ten friction points, the most critical being:

1. **Year scope is not a first-class concept** — "Crop Planner" in workbook 402 for 2023 and 2026 are treated as independent tabs, resulting in ~4x redundant API calls in Phase 3.
2. **Heuristic authoring is blind** — tokens must be populated from intuition before any data has been seen.
3. **No pre-profiling domain capture** — raw notes contain entity boundaries and operational vocabulary, but the pipeline never reads them.
4. **No deduplication of structural duplicates** — the coverage bonus awards +1 for appearing in 3+ years, which penalizes rather than helps when tabs are structurally identical across years.
5. **Config is the only integration point** — `cohort_corpus.json` must carry both mechanical settings and domain knowledge, leading to opaque placeholders and risk of overfitting.

## Approach

**Approach B (land now) with a designed path to Approach C (active development):**

- **B:** Introduce a `domain_context.yaml` artifact that the profiler reads at scoring time. Config stays thin (mechanical settings). Domain knowledge lives in the artifact (vocabulary, year scope, entities, glossary). Add a domain context reader to the profiler. Fix deduplication and shortlist output. Fix startup bootstrap friction.
- **Path to C:** The domain context artifact is designed as C's serialization format. In B→C, the profiler writes back to the artifact at phase boundaries. In C, a `PipelineContext` object replaces scattered config + artifacts.
- **C:** `PipelineContext` dataclass accumulates knowledge across phases. Start from `domain_context.yaml`, enrich in Phase 1 with discovered structure, update in Phase 2 from scoring results, add column profiles and FK candidates in Phase 3. Serialize at each phase boundary for human review.

## Section 1: Domain Context Artifact

### Schema

```yaml
domain: string                    # e.g., "farm_management"
description: string              # human-readable domain summary
year_scope:
  active: [int]                  # years to profile in full
  archived: [int]                 # years to skip or deprioritize
  forward: [int]                 # future years for forward-looking tabs
deduplication:
  strategy: latest_year | all     # default: latest_year
  exceptions:                     # tab titles to always profile per-year
    - tab_title: string
      reason: string
entities:
  - name: string                  # PascalCase entity name
    tabs: [string]                # tab titles that belong to this entity
    operational: bool
    description: string
vocabulary:
  operational: [string]           # seed operational_tokens
  reference: [string]            # seed reference_tokens
  support: [string]              # seed support_tokens
  derived: [string]               # seed derived_tokens
glossary:                         # synonym expansion
  abbr: full_form                 # qty → quantity, amt → amount
scope_notes: string               # freeform notes from orientation
```

### Design decisions

- **`vocabulary` maps to heuristic tokens, not config duplication.** The profiler translates `vocabulary.operational` → `operational_tokens` and merges with any tokens already in `cohort_corpus.json`. Domain language stays in the domain context; mechanical settings stay in the config.
- **`year_scope` is first-class.** Tabs from `archived` years are excluded from Phase 3 deep profiling by default. Tabs from `forward` years are included. Tabs from `active` years are fully profiled.
- **`deduplication.strategy: latest_year` is the default.** When the same tab title appears across multiple years in the same workbook code, profile only the latest year's instance. The human can override with `deduplication.exceptions` for tabs that change meaning across years.
- **`entities` are sparse pre-profiling, rich post-profiling.** Pre-profiling entities (from raw notes) have `name`, `tabs`, `operational`, and `description`. Post-profiling (from `domain-knowledge.yaml`) they gain `fields`, `import_key`, `fk_to`, and Django field types.
- **`glossary` enables synonym expansion** in token matching. "Qty" matches "quantity" in tab/column names. This is the first bridge toward Approach C's runtime intelligence.
- **The schema is extensible.** The reader ignores unknown keys gracefully. Future sections (discovered entities, profiler suggestions, scoring history) can be added without breaking backward compatibility.

### How it enters the pipeline

One new top-level key in `cohort_corpus.json`:

```json
{
  "domain_context": "config/domain_context.yaml",
  "folder_name": "...",
  "workbook_id_regex": "...",
  ...
}
```

The profiler loads the domain context at the start of Phase 1 and passes it into `select_tabs_from_inventory()`, `score_tab()`, and `derive_column_candidates()`. When `domain_context` is absent or the file doesn't exist, behavior is identical to today — no breaking change.

### Scaffold

`make new-product` generates an empty `domain_context.yaml` template with comments:

```yaml
domain: ""                       # e.g., "farm_management"
description: ""                  # What does this business do?
year_scope:
  active: []                     # e.g., [2025, 2026]
  archived: []                   # e.g., [2023, 2024]
  forward: []                    # e.g., [2026]
deduplication:
  strategy: latest_year
  exceptions: []
entities: []
vocabulary:
  operational: []
  reference: []
  support: []
  derived: []
glossary: {}
scope_notes: ""
```

The scaffold also generates `docs/orientation.md` with instructions for the Orient step:

1. Read raw notes in `data/raw_notes/`
2. Extract entity names, relationships, temporal scope
3. Identify the active year(s) and archived year(s)
4. Map entity names to tab names
5. Write domain context before running Phase 1

## Section 2: Profiler Internal Changes

### 2a. Domain context reader

New function in `profiler/tools/cohort_corpus.py`:

```python
@dataclass
class DomainContext:
    domain: str = ""
    description: str = ""
    year_scope: dict = field(default_factory=lambda: {"active": [], "archived": [], "forward": []})
    deduplication: dict = field(default_factory=lambda: {"strategy": "latest_year", "exceptions": []})
    entities: list[dict] = field(default_factory=list)
    vocabulary: dict = field(default_factory=lambda: {"operational": [], "reference": [], "support": [], "derived": []})
    glossary: dict = field(default_factory=dict)
    scope_notes: str = ""

def load_domain_context(path: str | Path) -> DomainContext | None:
    """Load domain context YAML. Return None if file doesn't exist."""
```

The reader strips `_`-prefixed keys (for future documentation keys) and ignores unknown sections.

`select_tabs_from_inventory()` gains `domain_context: DomainContext | None = None` parameter:
- When present, filter inventory rows by `year_scope.active` + `year_scope.forward` before scoring.
- Apply deduplication after aggregation: for each `(workbook_code, tab_title)` group with multiple years, keep only the latest year unless the tab title appears in `deduplication.exceptions`.
- Instead of `coverage_bonus = 1 if len(years) >= 3`, use `coverage_bonus = 1 if tab appears in >= 2 active or forward years` — a tab that appears consistently in active years suggests operational importance; appearing in many years including archived ones is just structural duplication and is now handled by deduplication, not by a bonus.

`score_tab()` gains `vocabulary: dict | None = None` parameter:
- When present, merge `vocabulary.operational` into `operational_tokens`, etc.
- Tokens from domain context are merged with (not replaced by) tokens from `cohort_corpus.json` config.

`derive_column_candidates()` gains `glossary: dict | None = None` parameter:
- When present, expand column header matching: if header contains a glossary key (e.g., "Qty"), also match against the glossary value ("quantity").

### 2b. Year-aware deduplication

Current behavior in `select_tabs_from_inventory()` (lines 574-649): tabs are aggregated by `(workbook_code, tab_title)` across all years, and a `coverage_bonus` of +1 is awarded for appearing in 3+ years.

New behavior when `domain_context` is present:

1. After scoring and aggregation, for each `(workbook_code, tab_title)` group:
   - If `deduplication.strategy == "latest_year"` and the group spans multiple years:
     - Keep only the latest year's instance for Phase 3 selection
     - Mark other instances as `structural_duplicate_of: {workbook_code}/{tab_title}/{latest_year}`
     - Record `duplicate_years: [2023, 2024]` on the surviving instance so the human can see what was deduplicated
   - If the tab title appears in `deduplication.exceptions`, keep all years
2. Replace `coverage_bonus` calculation:
   - `coverage_bonus = 1` if the tab appears in >= 2 `active` or `forward` years
   - `coverage_bonus = 0` if the tab only appears in `archived` years
   - Never award a bonus for structural duplication across archived years

When `domain_context` is absent, current behavior is preserved (all years, existing coverage bonus).

### 2c. Summary view in shortlist output

Add a `selection_summary` key to `tab_shortlist_<date>.json`:

```json
{
  "generated_from": "broad_profile_coverage_2026-05-19.json",
  "candidate_count": 15,
  "selected_count": 8,
  "selection_summary": {
    "by_workbook_by_year": {
      "402": {"2023": 0, "2024": 0, "2025": 4, "2026": 4},
      "501": {"2023": 0, "2025": 2}
    },
    "deduplicated_count": 14,
    "original_count": 48,
    "deduplication_note": "latest_year strategy applied; 34 structural duplicates removed",
    "year_distribution": {"2023": 5, "2024": 3, "2025": 6, "2026": 6}
  },
  "selected": [...]
}
```

The summary is always included (not behind a flag). It adds minimal overhead and immediately reveals the multi-year duplication problem without reading the full shortlist.

## Section 3: Pipeline Friction Fixes

### 3a. Empty models_auto.py stub

The scaffold's `ensure_stub()` function in `workbook/codegen/stub_writer.py` should also write an empty `models_auto.py` when it doesn't exist, containing only:

```python
# Auto-generated by make new-product. Populated by make generate-models.
```

This ensures Django starts cleanly before `make generate-models` runs. The `generate_models` command already overwrites this file.

### 3b. Config documentation key

Add a `_documentation` key to `cohort_corpus.example.json` with explanatory comments for each config field. The config reader strips `_`-prefixed keys, so they don't affect pipeline behavior.

Also update `new_product.py` scaffold to include `_documentation` in the generated `config/cohort_corpus.json`.

### 3c. Phase 1 coverage overview

Add a `broad_profile_coverage_summary_<date>.json` artifact to Phase 1 output. This is a compact grouping of discovered tab names by workbook code, without per-tab detail:

```json
{
  "generated_from": "drive_discovery_2026-05-19.json",
  "workbook_codes": {
    "402": ["Crop Planner", "Nursery Schedule", "Field Record", "Harvest Availability"],
    "501": ["Planting Log", "Variety List"]
  },
  "year_coverage": {
    "2023": ["402", "501"],
    "2024": ["402"],
    "2025": ["402", "501", "601"],
    "2026": ["402"]
  }
}
```

This replaces the need to read the full 3928-line shortlist to understand what tabs exist.

### 3d. Drive folder timeout

Update the `profile-drive-folder` Makefile target documentation (rendered by `workbook/makefile_targets.py`) to note: "First-time enumeration of folders with 20+ spreadsheets may take 2-3 minutes." The Makefile target already supports a `TIMEOUT` variable override.

## Section 4: Path to C — Runtime Pipeline Context

The domain context artifact is designed as Approach C's serialization format.

### B (land now)

- Domain context is a static YAML written by hand (or from raw notes)
- Profiler reads it once at Phase 1 start
- Vocabulary, year scope, and deduplication drive scoring and selection
- Human reviews and edits before and between phases

### B→C (bridge)

- Profiler writes back to `domain_context.yaml` at phase boundaries
- After Phase 1: append discovered entities (from `enrich_entity_groupings()`), matched tab names, suggested vocabulary (from tab/column name frequency analysis)
- After Phase 2: record heuristic changes and their effects
- Human reviews diff between phases

### C (full runtime context)

- `PipelineContext` dataclass replaces scattered config + artifact pattern
- All state lives in one object: heuristics, domain knowledge, profiler discoveries, scoring results, human overrides
- Phases become functions that take and return `PipelineContext`
- `domain_context.yaml` is `PipelineContext.serialize()`
- The schema we defined for B is already the right shape — it has sections for domain description, entities, vocabulary, and scope. C adds sections for profiler discoveries, scoring history, and human decisions.

### What doesn't change between B and C

- The domain context schema
- The concept of vocabulary-maps-to-tokens
- Year scoping and deduplication
- The glossary
- The shortlist summary output

### What changes

- Who writes the artifact (human-only in B, human+profiler in B→C, pipeline context in C)
- How it flows through the pipeline (read once at start in B, read-and-written at phase boundaries in B→C, in-memory context object in C)

### What C enables

- Autonomous heuristic suggestion: the profiler can analyze tab/column name frequencies and propose `vocabulary` entries
- Cross-project learning: domain contexts from similar domains can seed new projects
- Feedback loop from discovery interview: interview answers can patch the domain context and re-run phases
- Continuous drift detection: comparing domain context across runs reveals structural changes in the source data

## Overfit guardrails

This design was motivated by a specific farm management project, but the abstractions are domain-agnostic:

- `vocabulary` is generic — any domain has operational/reference/support/derived terms
- `year_scope` generalizes to any temporal dimension ( fiscal years, quarters, semesters)
- `deduplication` applies to any multi-period dataset
- `entities` is the same shape as existing `domain-knowledge.yaml`
- `glossary` is pure synonym expansion with no domain assumptions

The farm-specific hardcoded `_ENTITY_KEYWORDS` in `enrichment_utils.py` should eventually be replaced by vocabulary drawn from the domain context. This is a C-era task — for B, the hardcoded keywords remain as a fallback when no domain context is provided.

## Files to create or modify

### New files

- `profiler/tools/domain_context.py` — `DomainContext` dataclass, `load_domain_context()`, `merge_vocabulary()`, `apply_deduplication()`
- `example_data/domain_context.example.yaml` — annotated example template
- `docs/orientation.md` content added to scaffold's `docs/operator.md` and `AGENTS.md`

### Modified files

- `profiler/tools/cohort_corpus.py` — `DomainContext` integration in `select_tabs_from_inventory()`, `score_tab()`, `derive_column_candidates()`, summary output, coverage overview artifact
- `profiler/tools/enrichment_utils.py` — `glossary_lookup()` synonym expansion function
- `workbook/codegen/stub_writer.py` — ensure `models_auto.py` stub is written when empty
- `scripts/new_product.py` — add `domain_context.yaml` to scaffold, add `_documentation` to `cohort_corpus.json` template, add Phase 0 orientation instructions to `operator.md` and `AGENTS.md`
- `workbook/makefile_targets.py` — add drive folder timeout documentation, add `domain_context` path to phase targets
- `example_data/cohort_corpus.example.json` — add `_documentation` key and `domain_context` path