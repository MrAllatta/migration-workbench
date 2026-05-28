# migration-workbench Roadmap

Version history and direction.

```
0.0.1 – 0.0.N   Component assembly           ← shipped
0.1.0            Pipeline proven on real data ← current
0.2.0            Spreadsheet replacement      ← next milestone (handoff)
0.3.0+           Consultant accelerant         ← future
```

---

## Shipped: 0.0.x — Component assembly

Every piece of the pipeline exists in isolation. Profiler works. Codegen works.
Import runtime works. They have not yet been coupled end-to-end on real data.

### Profiler pipeline

- **Phase 0 preflight:** validate auth, credentials, drive access — Google Sheets and Coda.
- **Phase 1 discovery:** enumerate Drive folder tree, build workbook index, broad profile,
  heuristic tab scoring with domain context integration.
- **Phase 2 refinement:** re-run scoring with adjusted config — no API calls.
- **Phase 3 deep profiling:** fetch full grid data, classify formula taxonomy
  (raw / row_formula / expansion_formula / hybrid / empty), detect cross-sheet
  and cross-workbook references, extract data validation rules.
- **Domain context artifact:** `domain_context.yaml` with vocabulary (operational /
  reference / support / derived), glossary synonyms, entity definitions, year scope
  with active/archived/forward periods, and tab deduplication strategy.
  - Vocabulary feeds tab scoring tokens and column priority scores.
  - Glossary expands tab titles and column headers for synonym matching.
  - Year-aware coverage bonus and deduplication (latest year only per tab).
  - Validation gate: `validate_domain_context --strict` blocks pipeline on empty vocabulary.
  - `draft_domain_context` command infers starter YAML from drive tree + raw notes.
- **Column enrichment:** computed field detection, FK candidate suggestion, import key
  identification, entity grouping — propagated through profiler JSON artifacts and
  consumed by `scaffold_workbook_schema`.
- **Tab selection overrides:** human-editable `tab_selection_*.json` supports
  add/remove/replace per workbook code; `--resume-from-tab-selection` preserves edits.
- **Coda corpus:** doc enumeration, broad profile, table scoring (with Coda-specific
  heuristics for relation columns and formula column density), deep profiling,
  relationship summary, optional canvas extraction.
- **PipelineState:** Layered checkpoint model (`PipelineState` dataclass, `.yaml` I/O)
  with 4-phase dispatch (discover → score_and_select → deep_profile → derive_contracts),
  resume with guard clauses, and deterministic artifact externalization. Each phase
  records a gate closure preventing re-entry. See [Pipeline State](pipeline-state.md)
  for the full design and [Agent Harness](agent-harness.md) for the philosophy.
- **Auxiliary commands:** `scan_formula_patterns`, `extract_workbook_codes`,
  `snapshot_bundle`, `pull_bundle`.

### Schema contract system

- **Contract YAML format (v1.0–1.3):** `columns[]` with source-to-field mapping,
  profiler format type inference, field class derivation (DecimalField, DateField,
  BooleanField, ForeignKey, TextField), nullability hardening.
- **v1.1 hardening blocks:** `model_meta` (verbose_name, ordering, db_table,
  unique_together, indexes, constraints, abstract), `str_template`, `extra_fields`,
  `computed_fields`, `fk_resolutions`, `field_overrides`, `hooks` (after_model /
  after_meta / extra_methods), `import_config`, `admin`, `source_tab: null` for
  designed models.
- **`scaffold_workbook_schema`:** dual code path — from `--bundle-config` with
  optional profiler JSONs, or from `--cohort-corpus-out-dir` reading raw grid samples.
  Post-processing: designed model detection via column overlap analysis, FK column
  flagging, computed field detection, contract hardening, domain knowledge merge.
- **Designed model detection:** `find_column_overlap_groups()` — Jaccard-like ratio
  >= 0.5 between tab column sets produces suggested aggregate entities.
- **Contract validation:** `validate_contract --strict` checks valid Python identifiers,
  no duplicate model names, no null model names, FK target existence, import_config
  field resolution.
- **Contract review:** `review_contract()` — CharField max_length, nullable FK on_delete,
  str_template, FK lookup targets, admin inline targets, computed field naming.
- **Contract diff and migration safety:** `diff_contracts()` + `migration_safety_checks()`
  — detect removed fields, type changes, nullability changes with DANGER/WARNING levels.
- **Contract composition:** `!include` / `!include_list` YAML tags with cyclic detection.
- **`scaffold_designed_model`:** CLI helper emitting single-table YAML skeletons from
  `--fields` specs.

### Codegen

- **`generate_models`:** renders `models_auto.py` with FK resolution, `class Meta`
  (indexes, constraints, unique_together, ordering, verbose_name, abstract),
  `__str__` from template, `@property` computed fields, hooks injection at
  after_model / after_meta / extra_methods, enum choice classes from `enums` block.
- **`generate_admin`:** renders `admin_auto.py` with `@admin.register(Model)` classes,
  list_display/list_filter/search_fields auto-detection, FK link methods (clickable
  admin links via `reverse()` + `format_html()`), TabularInline for reverse FK
  relationships, status action methods (mark-as-*), time-scope filtering via
  date_hierarchy + get_queryset year filter, AbstractUser support with BaseUserAdmin.
- **`generate_import`:** renders `BaseImportCommand` subclass with topological-tiered
  pipeline, per-model `_import_<Model>()` methods, column_map resolution, FK lookup,
  field parser inference, field-level `_prepare_<field>()` stubs, `_prepare_row()`
  and `_before_save()` hooks.
- **Stub convention:** `models.py` / `admin.py` re-export from `*_auto.py` with
  a `# --- custom models below this line ---` marker preserving hand edits.
- **Resilience:** `PartialOutputCollector` + `--continue-on-error` on all generators
  — rejects invalid tables without aborting the full run.
- **Identifier safety:** `to_python_identifier()` sanitizes field names; warnings
  emitted when names are modified.
- **`--diff` flag:** all generators support diff output instead of overwrite.

### Import runtime

- **`BaseImportCommand`:** tier system with atomic savepoints, validate-only / dry-run
  / apply modes, error recording per row per model with failure signatures,
  summary JSON (created / updated / skipped / error counts).
- **Bundle reader:** CSV header detection, column_map application, alias resolution,
  default value injection, multi-source column concatenation.
- **FK resolution:** two-pass exact then normalized matching with LRU cache.
- **Type parsing:** `to_int`, `to_decimal`, `to_bool`, `parse_iso_date` (ISO + US
  date formats). Handles None, whitespace-only, sentinel values per `AGENTS.md` conventions.

### View manifest & discovery

- **View manifest scaffolding:** from `structure.json` + optional schema contract.
  Infers editable vs computed fields, status field (regex on headers with data validation),
  time scope (year_field / week_field / default_scope), tab sequence, filterable fields.
- **Discovery interview:** generates Markdown questionnaire with HTML-comment markers
  for role ownership, status semantics, status overrides, weekly actions, access control.
- **Answer merging:** `merge_discovery_notes` parses answers, patches view manifest
  with role_hints, weekly_actions, view notes, status overrides.
- **Discovery summary:** `render_summary()` produces stakeholder-ready Markdown recap.

### Build system

- **Shared `makefile_targets.py` module:** all generate, validate, deploy targets
  produced by a single Python module; consumed by product repo Makefiles via
  `new_product.py` scaffold.
- **Preflight gate:** `make preflight` validates env vars, domain context, runtime.
- **Product scaffold:** `new_product.py` generates full Django project with Makefile,
  Dockerfile, fly.toml, deploy/spaces.yml, CI/CD workflows, AGENTS.md.

### wb CLI

- `wb manifest lint` — validate `deploy/spaces.yml` against manifest schema.
- `wb deploy --dry-run` / `--live` — record release event, optionally deploy to
  Fly.io with health gate polling and release event recording.
- `wb contract {review,diff,safety,validate}` — contract analysis commands.
- `wb drift check` — baseline vs new contract comparison with migration risk assessment.
- `wb generate {models,admin,import,manifest}` — delegate to Django management commands.

### Deployment

- Fly.io deploy: Docker build, fly deploy, health gate polling (`wait_for_healthy`),
  RELEASE_ID secret setting, outcome recording (deploy_succeeded_healthy / failed).
- Release store: `ReleaseRecord` DB table + `release-events.jsonl` (append-only).
- Manifest validation: full schema check for spaces.yml (profiles, replication,
  build config, secrets, environments).
- Deploy smoke tests: integration tests with mocked fly CLI and real HTTP health endpoint.

### Documentation

- README, architecture, deployment (Fly / Litestream / Tigris), google-auth,
  troubleshooting FAQ, schema contract reference, end-to-end tutorial, contributor guide.
- AGENTS.md with domain vocabulary, naming rules, patching boundary, human judgment points.
- Full doc map at `docs/INDEX.md`.
- Docstring coverage at 80% (interrogate gate in CI).

### CI/CD

- `make chassis-gate`: migrate, test, lint, ruff format check, doc coverage.
- PyPI trusted publishing via GitHub workflow.
- Fly deploy workflow.

---

## 0.1.0 — Pipeline proven on real data (current)

The profile→model→codegen→import→deploy pipeline has been exercised
end-to-end on the farm engagement — 56 workbooks, 239 tabs, spanning
an 11-model schema contract. PipelineState checkpointing,
schema contract scaffolding, codegen, import runtime, view manifest
generation, discovery interviews, and Fly.io deployment all function
on real data.

Fixes discovered during farm execution have been collected in the
`pipeline-maturity` branch. These address coupling issues between
pipeline stages, import path bugs, and multi-year import scaffolding
that the 0.0.x isolation work did not surface.

### What shipped

The full 0.0.x component catalog operated as a coupled system on a
production corpus. Breakages found mid-pipeline were fixed upstream
with test coverage, validating the patching boundary defined in AGENTS.md.
All pipeline commands can be invoked in sequence on a real source.

### Carried to 0.2.0

Farm execution revealed that "pipeline runs" is the prerequisite, not
the terminal milestone. The gate criteria below carry forward into
the 0.2.0 spreadsheet replacement milestone:

- **Full historical import loop** — year directory iteration,
  `source_bundle_year` injection across 5+ years of data.
- **30-minute gate from scratch** — single command sequence, zero
  manual edits.
- **Admin that replaces the spreadsheet** — view manifest and
  discovery interview meaningfully change admin output; stakeholder
  can complete weekly cycle without the source workbook.

---

## 0.2.0 — Spreadsheet replacement (next milestone)

The goal: a product repo running a generated Django app that operators
genuinely prefer to the spreadsheet. Not "pipeline runs" but
"the app replaces the workbook."

### Interaction contract Layer 1–3

The three-layer design from [Interaction Contract](interaction-contract.md)
must be fully wired:

1. **Profiler signals** — `scaffold_view_manifest --signals-only` produces
   `profiler-signals.yaml` with ui_archetype, formula_density, cross-sheet
   references, null rates, confidence scores.
2. **Human interaction contract** — the discovery interview feeds operator
   answers into `interaction-contract.yaml`. Archetype override, role ownership,
   status semantics, workflow notes.
3. **Codegen manifest** — merge tool produces the manifest consumed by
   `generate_admin`. Operator workflow intent controls generated admin behavior:
   dashboards render read-only, forms get inline editing, lists get
   search-first UX.

### Admin quality bar

- **Status workflows:** mark-as-* actions, status transition validation.
- **Role-appropriate views:** field_manager sees their forms; operations sees
  dashboards; admin sees everything.
- **Time-scoped filtering:** year/week picker, current-season default.
- **FK navigation:** clickable admin links, inline related records.
- **Import year selector** for bundled historical data.

### Full historical import loop

`pull_bundle` → per-year CSV directories → import command iterates
year directories, resolves per-year paths, injects `source_bundle_year`.
`make import-historical` target wraps the loop. Proven across 5+ years
of real farm data.

### View manifest and discovery on real data

scaffold → interview → merge → regenerate admin. The merged manifest
changes admin output meaningfully — not just cosmetic field reordering.

### Gate

- Generated admin passes a workflow audit: a stakeholder can complete
  their weekly cycle without touching the spreadsheet.
- All historical years import with zero unexpected errors.
- `make chassis-gate` is green.

---

## 0.3.0+ — Consultant accelerant

Each version encodes more consultant judgment into the agent harness,
making the operator faster. Not a feature list — a judgment-compounding system.

### 0.3.0 — Vertical migration templates

After N engagements in a vertical (farm, school, clinic), extract reusable presets:
domain context vocabulary, entity defaults, scoring heuristics, schema contract templates,
interaction contract defaults, and import error patterns. The 10th farm migration should
be 5x faster than the 1st because the agent starts with learned defaults.

### 0.4.0 — Interaction contract: consultant decision support

The profiler extracts how the data is USED, not just what it IS. UI archetype
classification (form / list / dashboard / reference) tells the consultant how to
configure the generated admin. Workflow dependency graphs reveal operational sequences.
Role boundaries inform permission design.

The immediate value is consultant decision support, not frontend codegen. Better
decisions produce better admin defaults as a side effect.

See [Interaction Contract](interaction-contract.md) for the three-layer design.

### 0.5.0+ — Platform (conditional)

Only after the judgment taxonomy is dense enough to make the agent reliably correct:

- Hosted workbench for consultants who prefer a web UI to CLI
- Self-service assessment for prospects ("Upload your spreadsheet, get a migration feasibility report")
- Provider plugin system (only after 10+ verticals prove the model)
- Postgres mode at scale
- Multi-model transaction safety in import pipeline

Self-service end-user migration remains a non-goal until the agent error rate
is provably near-zero.

---

## Non-goals

- **Self-service end-user migration without consultant review.** The agent makes too
  many mistakes on messy real-world data. Human judgment is mandatory until the
  judgment taxonomy is dense enough to make the agent provably correct.
- **GUI for contract authoring (today).** YAML is the consultant interface for now.
  A hosted consultant UI is a 0.5.0+ possibility, not 0.3.0.
- **Real-time sync back to source.** One-way pipeline (source → Django). Bidirectional
  sync requires conflict resolution and change tracking.
- **Arbitrary ETL.** Pipeline is opinionated: tabular → normalized CSV → Django models.
  JSON APIs and unstructured data are out of scope.
- **Non-Django targets.** Codegen is Django-specific. Extracting a generic ORM layer
  is premature.

---

## How the farm exercise shaped this roadmap

Every item in "Shipped" has a direct line to something discovered while building
the first product repo. The exercise that informed the current design was profiling
a 56-workbook, 239-tab Google Sheets corpus and designing an 11-model schema.

| Discovery | Response |
|-----------|----------|
| Hand-authored 663-line contract was repetitive | Contract scaffolding, hooks system, designed model helpers |
| `make generate-admin` blocked by missing manifest | Makefile flag fix, `generate-admin-light` target |
| unique_together required hand-edit after generation | Added to model_meta block |
| Properties/methods required hand-edit | `contract.hooks` block (after_model, extra_methods) |
| Designed models with no source tab had no scaffolding | `source_tab: null`, `scaffold_designed_model` |
| No way to validate contract before codegen | `validate_contract --strict`, codegen-time validation |
| Couldn't tell what codegen changed across runs | `--diff` flag, `git diff` workflow |
| Upstream renderer bugs found mid-pipeline | Fixes committed with test coverage |
| Import generator untested | Import pipeline foundation (tiers, FK resolution, error recording) |
| View manifest / discovery not exercised | 0.0.x end-to-end tests, deploy smoke test |

---

## Tracking

Individual items are tracked as GitHub issues with `roadmap/` label.
This document is updated when milestones ship or priorities shift.
