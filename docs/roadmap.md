# migration-workbench Roadmap

This roadmap is informed by the first end-to-end exercise of the full
pipeline — profiling a real Google Sheets corpus (56 workbooks, 239 tabs),
designing a schema for Long Season Farm (11 models, full grow-sell cycle),
and generating models/admin/import code via the contract-driven codegen.

The exercise revealed both strengths and gaps. This document prioritizes
what to build next, what to fix, and what to defer.

## Guiding principles

1. **Contract-first, not codegen-first.** The contract YAML is the
   source of truth. Codegen is a downstream consumer. Everything that
   makes contracts easier to write, validate, and evolve takes priority.
2. **Support designed models as first-class citizens.** Migration-workbench
   started with source-aligned models (one tab → one model). Real schemas
   include designed/aggregate entities (FieldEvent, InventoryEntry) that
   have no source tab. These are not exceptions — they are the norm.
3. **Keep scaffolding editable.** Generated files are starting points.
   Every generator must produce readable, idiomatic code that developers
   are happy to hand-edit afterward. Regeneration must not destroy edits
   without warning.
4. **Every gap found in a product repo is a workbench fix.** No
   vendoring, no monkey-patching. If farm needed it, the workbench
   should provide it.
5. **State ownership over artifact scattering.** Pipeline state
   should live in a single domain model object, not scattered across
   date-stamped JSON files. The DomainModel is the profiler's memory.
6. **Extraction over configuration.** The profiler extracts domain
   signals (workflow, archetype, roles) from the data. The human
   reviews and overrides, not authors from scratch.

## Immediate (next release, 0.2.x)

These are fixes and small enhancements exposed by the farm exercise that
can ship without major rearchitecture.

### Contract schema hardening

The farm exercise revealed missing Meta options and awkward
patterns for designed models.

**Add to `model_meta`:**
- `unique_together` (list of lists)
- `indexes` (list of index dicts)
- `constraints` (list of constraint dicts)
- `app_label` (override the CLI arg per table)

**Add `is_abstract: true` to model definition:**
- Emit `class Meta: abstract = True` instead of `db_table`
- Skip migration creation for abstract models
- Useful for mixin patterns across generated models

**Add `computed_fields` block:**
- Fields that exist in the model but are excluded from import
- Rendered as `@property` methods instead of model fields
- Solves the Availability-derived-view pattern cleanly

**Add `source_tab: null` or omit `bundle_worksheet_title`:**
- Explicit marker for designed models with no source tab
- Codegen skips import_config scaffolding for these
- Admin generator treats them as first-class (no change needed)

See `docs/schema-contract.md` for the full reference when updated.

### Makefile / build-system improvements

The product repo Makefile had several papercuts:

- **`make generate-admin` requires view-manifest.yaml exist.** The CLI
  accepts `--manifest` as optional — the Makefile guard is too strict.
  Add `make generate-admin-light` that runs without manifest, and
  `make generate-admin` for the full pipeline.

- **`make generate-models` overwrites models.py with `--force`.** Use
  `--diff` or `git diff` to review what changed between codegen runs.

- **`make validate-contract`** — runs `yaml.safe_load` + checks every
  FK target exists as a table name + verifies field references resolve.

- **`make post-generate`** — optional hook script at `scripts/post-generate.sh`
  that runs after `make generate`. Product repos use this to reapply
  hand-authored customizations that live outside the contract.

### Codegen quality-of-life fixes

- **`generate_models --diff`** flag: write to a temp file and show diff
  against current output before overwriting.
- **`generate_admin --manifest` truly optional in Makefile** (remove the
  `test -f` guard, let it pass `--manifest` only when the file exists).
- **Contract validation at codegen time:** warn if a FK target model
  isn't in the contract, warn if `import_config.fk_lookup` references
  fields not in the model, warn if `unique_on` fields repeat.
- **Import generator skips models without `import_config`** (already
  does this, but add a note to the generated file listing which were
  skipped and why).

### Upstream fixes carried forward

Two fixes already committed from the farm exercise:

- `render_field_kwargs`: handle `null` YAML key (parses as Python `None`)
- `render_field_kwargs`: choices rendered as `EnumName.choices` not
  `ModelName.EnumName` (enum classes are module-level, not model attrs)

These need to be in the 0.2.0 release.

## Short-term (0.3.x–0.4.x)

### Contract authoring tooling

The farm contract was 663 lines of hand-authored YAML for 11 models.
Most of the repetition is structural (every extra_field needs class +
kwargs dict). Two approaches:

**1. Contract scaffolding for designed models**
`scaffold_workbook_schema` already produces auto-generated drafts for source-aligned
models. Add `scaffold_designed_model --name FieldEvent --fields "event_type:CharField(30):choices=EventType,timestamp:DateTimeField"` that
emits a contract table skeleton with extra_fields pre-populated.

**2. Contract composition / includes**
Support `!include` or `$ref` patterns in contract YAML so common field
groups (e.g., timestamp+author audit fields) are defined once and reused.
This keeps contracts DRY as the model count grows.

### Post-generation hook system

The farm exercise required hand-editing `models.py` after generation
for: unique_together, properties, classmethods. Every edit is fragile
across regenerations.

**Design: `contract.hooks` block**

```yaml
hooks:
  after_model: |
    @property
    def signed_quantity(self):
        ...
  after_meta: |
    class Meta:
        unique_together = [["name", "variety"]]
  extra_methods: |
    @classmethod
    def harvest_needs(cls, week, year):
        ...
```

Hooks are Python source fragments injected at well-defined points in the
generated model class. They survive regeneration because they live in the
contract, not in the generated output.

This replaces the `scripts/post-generate.sh` approach with something
contract-native and per-model.

### Admin scaffold maturity

The generated `admin.py` in farm was 171 lines with TabularInlines
auto-detected from FK relationships — this worked well. But:

- **Inline field lists are auto-picked** — first 6 non-FK fields. The
  contract should support `admin.inlines` to override which fields appear.
- **`list_editable` not supported** in admin config. Add it.
- **`autocomplete_fields`** for FK fields with many rows. Useful for
  Crop selection in InventoryEntry admin.
- **Regeneration warning:** if the user has hand-edited admin.py, the
  `--force` flag should print a diff and require confirmation.

### Import pipeline foundations

The farm contract included `import_config` for 9 of 11 models, but
the import generator was not exercised end-to-end (bundles haven't
been pulled yet). Known gaps:

- **`unique_on` with FKs** — currently resolves FK values then uses them
  in `update_or_create`, but the FK resolution runs before the unique
  check. Need to verify this ordering works with multi-column unique
  constraints that include FK fields.
- **Column map ambiguity** — the current `column_map` maps field names
  to source headers. But designed models may want to map multiple source
  columns to one field (e.g., notes concatenation). Add transform hooks.
- **Import tier ordering is manual** — the `tier` integer is set by hand.
  Auto-detect dependency order from `fk_lookup` chains.

## Shipped: 0.5.x–0.9.x

### 0.5.0 — Migration safety & robustness

- **Migration safety checks:** `wb contract safety --old --new` detects
  destructive schema changes before codegen (field removed, nullable→non-nullable →
  DANGER; class change, max_length decreased, unique added → WARNING).
- **Null-key robustness:** `_diff_fields()` normalises YAML `null:` mapping keys
  to the string `"null"` to prevent `TypeError` in kwarg comparison.

### 0.6.0 — Profiler ingestion hardening & formula analysis

- **Reserved-character sanitization:** Tab names containing `|`, `:`, `\`, `/`,
  `*`, `?`, `"`, `<`, `>`, `%` are automatically replaced with underscore at
  ingestion, with a logged warning. Applied in both Google Sheets and Coda
  shape-structure functions.
- **Tab exclusion by pattern:** `tab_exclude_patterns` in `heuristics.tab_score`
  — a list of `{pattern, penalty}` dicts. Any tab whose title matches a
  regex pattern receives the configured penalty (default `-5`). Useful for
  blocking tabs matching known noise patterns (e.g. `"^Sheet\d+$"`, `"blankslate"`).
- **Formula structure analysis:** Profiler classifies every column into one of:
  `raw` (no formulas), `row_formula` (calculated-row), `expansion_formula`
  (auto-expanding), `hybrid` (mixed), or `empty` (all blanks). The taxonomy
  flows into schema contracts and view manifests.
- **Expansion formula penalty:** `expansion_formula_penalty` (default `0`) and
  `expansion_formula_threshold` (default `0.5`) in `heuristics.tab_score`
  reduce auto-selection scores for tabs dominated by auto-expanding formulas
  (pivot tables, dashboards, summary sheets).
- **Tab name pipes sanitized:** `|` characters in tab names are replaced with
  `_` during tab listing, preventing encoding issues in downstream bundle paths.

### 0.7.0 — Contract & codegen hardening (shipped 2026-05-14)

- **Profile-to-contract bridge:** `scaffold_workbook_schema` suggests
  designed/aggregate models from overlapping column patterns.
- **Contract review checklist:** FK lookup target validation, admin inlines
  target existence, computed_field snake_case naming, `--exit-zero` flag.
- **Contract composition:** `!include_list` YAML tag for splitting tables across
  files, cyclic include detection.
- **Per-table warning suppression:** `suppress_review_warnings` key in contract.
- **Codegen fixes:** preserve `extra_fields` order, no `.bak` backups,
  FK validation for `extra_fields`, `wb contract review --exit-zero`.
- **`make validate-contract` and `corpus-codegen-report`** in scaffolded CI.

### 0.8.0 — Import pipeline end-to-end (shipped 2026-05-15)

- **Per-tier transaction savepoints** — `--tier-atomic` wraps each tier in its own savepoint; preceding tiers persist on later-tier failure.
- **Per-row exception catching** — generated import methods catch `IntegrityError` and other exceptions per row, recording structured errors.
- **Error handling hardening** — new error codes (`type_mismatch`, `unique_violation`, `row_exception`), per-model `row_errors_count` in summary JSON.
- **End-to-end import fixture** — new 3-model test data exercising FK chains, `column_map` multi-source, `field_transforms`, and `field_parsers`.
- **Parsing edge-case coverage** — `None`, whitespace-only, and sentinel value handling in `to_int`, `to_decimal`, `to_bool`, `parse_iso_date`.
- **Bundle reader multi-source fix** — list-valued `column_map` entries no longer raise `TypeError`.

### 0.9.0 — View manifest, discovery & deployment (shipped 2026-05-15)

- **View manifest integration:** status_field promotion in `list_filter`, admin
  class comment, end-to-end integration tests. `status_field` override via
  manifest YAML and discovery interview.
- **Discovery interview pipeline hardening:** `status_override` question in
  interview, round-trip tests (parse → merge → admin generation), edge-case
  resilience for reordered sections and blank lines.
- **Drift check wiring:** `wb drift check` CLI command, `migration_safety_checks`
  integration, Makefile target for periodic CI use.
- **Production deployment:** `wb deploy --live` with health gate polling
  (`wait_for_healthy`), release event recording, full-path deploy smoke test.
- **Product scaffold maturity:** `diff-generated`, `generate-admin-light`,
  `post-generate`, `check-generated`, `snapshot-codegen`, `check-snapshots`,
  `drift-check` Makefile targets in `new_product.py` scaffold.
- **Codegen parity:** `--diff` flag added to `generate_import` command.
- **Deploy smoke test:** full-path integration tests for `_deploy_live()` with
  mocked fly CLI and real HTTP health endpoint.

### 0.9.1 — Makefile dedup & doc coverage (shipped 2026-05-17)

- **Makefile target deduplication:** shared `workbook/makefile_targets.py` module replaces inline Makefile template in product scaffold.
- **Documentation coverage:** docstrings and module docs for connectors, profiler, deployment, and workbook; `docs/INDEX.md`.
- **Pipeline manifest wiring:** `generate-pipeline-manifest` wired into `generate-all` Makefile target.

### 0.9.2 — Rich profiling & beta architecture (shipped 2026-05-18)

- **Profiler enrichment functions:** computed fields, FK candidates, import keys, and entity groupings for Google Sheets and Coda sources.
- **Cohort/Coda enrichment propagation:** enrichment fields flow through scaffold contract (`suggested_entity`, `suggested_fk_target`, `is_computed`, `is_import_key_candidate`, `cross_tab_group`).
- **Import key candidates from enrichment:** scaffold uses enrichment metadata to propose `unique_on` instead of defaulting to first column.
- **Domain knowledge flag:** `scaffold_workbook_schema --domain-knowledge` and example YAML for entity-aware contract generation.
- **`model_name` required:** explicit PascalCase model name on every contract table; no derivation from `suggested_model_name`.
- **`*_auto.py` output convention:** generated code writes to `models_auto.py` / `admin_auto.py` with stub re-export files; hand edits are preserved.
- **Unified `wb` CLI:** `wb generate {models,admin,import,manifest}` and `wb validate contract` subcommands.
- **Contract admin authoritative:** `generate_admin` treats contract `admin:` blocks as source of truth; view manifest is enrichment only.
- **`bundle_path` auto-derive:** scaffold always derives import config path from model name.
- **`validate_contract` management command:** standalone contract validation without code generation.
- **Clean error on missing `bundle_path`:** actionable guidance instead of raw traceback.

## Beta Gate (shipping now)

The beta criterion is "no-friction pipeline on full real product."
The first autonomous run revealed friction in three areas that are
being addressed as the final beta milestone:

### Domain Context Artifact

A `domain_context.yaml` that the profiler reads at scoring time,
providing period-aware structural deduplication, vocabulary-to-token
mapping, and glossary synonym expansion. This eliminates the
worst source of pipeline friction: structural duplicates profiled
4x across years, and blind heuristic authoring before any data
is seen.

See `docs/superpowers/specs/2026-05-19-domain-context-artifact-design.md`
for the design and `docs/superpowers/plans/2026-05-19-domain-context-artifact.md`
for the implementation plan.

### Pipeline friction fixes

- Empty `models_auto.py` stub on scaffold (Django starts cleanly before codegen)
- Config documentation key in `cohort_corpus.json`
- Phase 1 coverage overview artifact
- Drive folder timeout documentation

## Post-Beta Goal 1: DomainModel Orchestration

The pipeline's orchestration layer (`run_cohort_corpus`, 600+ lines
with three resume-mode branches) scatters state across date-stamped JSON
artifacts. Phase boundaries are files. Human override is JSON editing.
Domain intelligence injection (see domain context artifact above) adds
more artifacts to this pattern.

### DomainModel

A single `DomainModel` object that is the profiler's runtime state.
Created empty or loaded from one YAML file. Its methods are pipeline
phases. It serializes at checkpoint gates. The human reviews and
edits ONE file between phases — no more scattered JSON artifacts.

The domain context artifact schema (`periods`, `vocabulary`, `glossary`,
`deduplication`) is designed as the DomainModel's serialization format.
When DomainModel ships, the artifact is promoted from "input file"
to "the model itself."

See `docs/superpowers/specs/2026-05-20-domain-model-orchestration-and-frontend-manifest.md`
for the meta spec. A detailed orchestration spec spins off from it.

## Post-Beta Goal 2: Frontend Manifest Extraction

The profiler currently extracts what the data IS (schema contract) and
how it imports (bundle config). It does not extract how the data is
USED — the interaction contract.

### Profiler-to-UI signals

The profiler already has the sensors for interaction signals but
doesn't surface them as a contract:

- **Workflow sequence:** cross-sheet formula references encode
  upstream → downstream tab dependencies. A directed graph of which
  tabs feed which produces navigation and import order.
- **UI archetype classification:** formula-density, data-validation
  presence, row/column dimensions, and section headers reveal whether
  a tab is a form, a list, or a dashboard.
- **Role boundaries:** tabs with data-validation columns → data entry.
  Tabs with high formula density → review. Cross-references → data
  flows between roles.

### Enriched view manifest

These signals feed into the existing view manifest format (archetypes,
workflow positions, role hints, form field widgets, KPI sections).
The discovery interview seeds from them. Admin generation consumes
them immediately. Frontend codegen (React/Django templates) consumes
them in the next evolution.

Sub-specs spin off from the meta spec:
- Workflow sequence extraction
- UI archetype classification
- Frontend manifest enrichment

## Longer-term (post-v1.0)

### Provider interface hardening

The provider interface (connectors) is shared between Sheets and Coda
adapters, but the profiler and importer still have provider-specific
code paths. The DomainModel's provider-agnostic design creates the
natural integration point:

- DomainModel as provider-agnostic carrier for all three contracts
- Coda-specific signals (`is_relation_type`, `ref_tables_seen`)
  augment shared column profile fields
- Plugin system for third-party providers

### Frontend codegen from manifest

With an enriched view manifest carrying archetypes, workflow positions,
and role hints, frontend codegen becomes possible:
- List views with filters from `filterable_by`
- Form views with widgets from `data_validation_type`
- Dashboard views with KPI sections from formula analysis
- Navigation structure from workflow dependency graph

### Multi-model transactions and idempotency

The import pipeline uses `update_or_create` per row, which is safe but
not atomic across models. For multi-row imports (a harvest event that
creates both a FieldEvent and an InventoryEntry):

- **Transactional import tiers** — wrap each tier in `atomic()`.
- **Compensating actions** — if tier 3 fails, roll back tier 2's creates.
  Current approach (re-import with same `unique_on` keys) works for
  idempotent imports but has edge cases with auto-increment IDs.

### Postgres support at scale

Current Postgres mode works but is untested at scale. The farm uses
SQLite. Real concurrent access patterns may reveal:

- Migration locking differences (SQLite serializes, Postgres doesn't)
- Performance of FK resolution queries at 100k+ row imports
- Connection pooling for parallel import tiers

## Future ideas (not gated)

- **Management interface on the workbench Fly app** — A hosted runtime
  exposing the profiling → scaffold → contract loop as a web or API
  service, so operators can profile sources, review enrichment candidates,
  and author contracts without a local checkout. Products remain
  independent Fly deployments with their own data; the workbench
  helps author and manage the contracts that drive them.

## Non-goals (explicitly deferred)

- **GUI for contract authoring.** The YAML is the interface. Visual
  tooling would lock us into a narrow workflow before the contract
  format stabilizes. (See "Management interface" above — a hosted
  runtime is distinct from a GUI editor.)
- **Real-time sync back to source.** Migration-workbench is a one-way
  pipeline (source → Django). Bidirectional sync requires conflict
  resolution, change tracking, and a fundamentally different architecture.
- **Arbitrary ETL.** The pipeline is opinionated about shape (tabular →
  normalized CSV → Django models). Arbitrary ETL (JSON APIs, unstructured
  data) is out of scope.
- **Non-Django targets.** Codegen is Django-specific. Extracting a
  generic ORM layer is premature until Django codegen stabilizes.

## How the farm exercise shaped this roadmap

Every item above has a direct line to something we wrote, worked around,
or wished for during the farm implementation:

| Farm experience | Roadmap response |
|---|---|
| Hand-authored 663-line contract | Contract scaffolding, hooks system, unique_together in model_meta |
| `make generate-admin` blocked by missing manifest | Makefile flag fix, `generate-admin-light` target |
| `unique_together` required hand-edit after generation | Add to model_meta |
| Properties/methods required hand-edit after generation | `contract.hooks` block |
| Designed models (FieldEvent, InventoryEntry) have no scaffolding | `source_tab: null`, designed model scaffold command |
| No way to validate contract before codegen | `make validate-contract`, codegen-time contract validation |
| Couldn't tell what codegen changed across runs | `--diff` flag, `git diff` workflow |
| Upstream renderer bugs found mid-pipeline | Fixes committed, add to test suite |
| Import generator untested (no bundles pulled yet) | Import pipeline foundation section |
| View manifest / discovery pipeline not exercised | 0.9.x end-to-end testing, deploy smoke test |
| 114 test suite passed but no snapshot tests | Snapshot testing for generated output |

## v1.0 / Beta Criteria Status

| Criteria | Status |
|---|---|
| 1. No-friction pipeline on full real product | ⚠️ Domain context artifact and friction fixes in progress; next autonomous run will validate |
| 2. Healthy backups documented and exercised | ❌ Not started |
| 3. Production deployment live on Fly.io with real data | ⚠️ Code ready (0.9.x), live deploy pending |

## Tracking

Individual items are tracked as GitHub issues with `roadmap/` label.
The `v1.0` milestone collects the v1.0 criteria from README.md.
This document is updated when milestones ship or priorities shift.
