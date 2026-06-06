# migration-workbench Roadmap

Version history and direction.

```
0.0.1 – 0.0.N   Component assembly              ← shipped
0.1.0            Pipeline proven on real data    ← shipped
0.2.0            Admin generation maturity       ← shipped
0.3.0            User-facing UI codegen           ← next milestone
0.4.0            Role-based interfaces            ← next milestone
0.5.0+           Consultant accelerant (platform) ← conditional
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

## Shipped: 0.1.0 — Pipeline proven on real data

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

## Shipped: 0.2.0 — Admin generation maturity

The admin generator now produces production-grade Django admin configuration: status transitions,
role-appropriate views, year/week filtering, and proper field-level validation. The interaction
contract merge path is complete. The historical import loop handles year-suffixed CSV bundles,
proven across 5+ years of real farm data. All 922 tests pass, full chassis-gate green.

This milestone improves what the workbench generates — higher-quality Django admin code. It does
not deliver a spreadsheet replacement. See the carry-forward note below for what remains unmet.

- **Interaction contract merge path:**
  `access_hints` from interaction contract flow through `merge_manifests`
  into the codegen manifest consumed by `generate_admin`. Per-role supplement
  (form/list/dashboard/reference) indexed correctly across all tabs.
- **Admin quality bar:**
  Status transitions (list-valued from v3 manifest, list_editable/exclude
  hygiene, FK/readonly validation). Role-appropriate views (field_manager
  sees forms, operations sees dashboards, admin sees everything).
  Time-scoped filtering (year/week picker, current-season default).
  Inline deduplication, unique YearWeekFilter names per model.
- **Full historical import loop:**
  `pull_bundle` → per-year CSV directories → `import_historical` walks
  tab-named bundle directories, collects year-suffixed CSVs, processes
  in year order with `source_bundle_year` injection.

---

### Gate criteria carried forward

The 0.1.0 milestone carried three gate criteria for spreadsheet replacement
into 0.2.0. Two were met; one was not:

| Criterion | 0.1.0 carried | 0.2.0 result |
|-----------|---------------|--------------|
| Full historical import loop | Yes | ✅ Delivered |
| 30-minute gate from scratch | Yes | ✅ Delivered |
| Admin that replaces the spreadsheet — stakeholder can complete weekly cycle without the source workbook | Yes | ❌ Carried to 0.3.0 |

**Why the third criterion was not met:** "Spreadsheet replacement" is a product
outcome, not a workbench feature. It requires (a) a quality gate with
repeatable smoke tests that verify a domain user's workflow, (b) product agent
certification via 3 consecutive clean passes, and (c) generated user-facing UI
code (views, templates, interactive components) — none of which existed in the
workbench at 0.2.0. The gap is formally documented in `.omo/issues/04`.

The workbench's role is to ship generic code generation capabilities that
product repos (like farm) consume to achieve spreadsheet replacement. This
milestone delivered admin codegen maturity. User-facing UI codegen is the
next milestone.

---

## Next: 0.3.0 — User-facing UI codegen

The workbench ships generic code generation for user-facing Django views,
templates, and interactive components — not just admin.

- **Carried forward from 0.2.0:** Generate views, templates, and URL routing
  that let a domain user complete a read/update workflow without the source
  spreadsheet. The farm engagement validates this capability.

- **HTMX interactive components:** Generate inline editing (status toggles,
  boolean checklists), modal forms, and live-update fields using HTMX.
  Archetype-aware: `form` archetypes get editable forms, `list` archetypes
  get sortable tables, `dashboard` archetypes get summary cards.

- **Admin functional improvements (validated on farm data):**
  Computed columns in admin list_display (PlantingPlan.planted, etc.).
  list_editable for nursery boolean fields (seeded/germinated/thinned).
  Conditional row highlighting via CSS rules. Custom admin actions
  (record planting event, mark as ordered). FK autocomplete tuning.

- **Quality gate required:** The `app-replaces-spreadsheet` quality gate
  must include tests that verify user-facing views render with real data,
  not just admin pages. (The current gate tests admin rendering only —
  see issue #04).

See the farm engagement design at
`docs/superpowers/specs/2026-06-04-app-replaces-spreadsheet-design.md`
for the validating example.

## Next: 0.4.0 — Role-based interfaces

The workbench ships codegen for role-aware views, dashboards, and
permission scaffolding.

- **Role-based views:** Generate landing pages per role archetype
  (planner: crop planning dashboard, operations: field task list,
  admin: full CRUD). Group-based routing with automatic queryset scoping.

- **Dashboard views:** Generate summary cards, aggregate counts, and
  status breakdowns from schema contract metadata. Archetype-aware
  rendering (dashboard archetype → card layout, list archetype → table).

- **Permission scaffolding:** Generate Django Group creation, permission
  checks (has_change/view/add/delete_permission), and row-level access
  from interaction contract roles.

- **Print-friendly outputs:** Generate list views optimized for printing
  (weekly field task lists, inventory sheets).

See `.omo/next/v0.4.0-phase1-archetype-matrix.yaml` and related plans.

## Conditional: 0.5.0+ — Consultant accelerant / Platform

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

## Milestone certification

Milestones in this roadmap describe **workbench capabilities** — what the
migration-workbench package can generate. A milestone is **shipped** when:

1. All code is merged to `master` and released to PyPI
2. `make chassis-gate` passes (migrate, test, lint, doc coverage)
3. The roadmap document is updated

A milestone that describes a **product outcome** (e.g., "user can complete
a workflow without the source spreadsheet") requires additional certification:

4. A quality gate definition in `.omo/quality-gates/<milestone>.yaml` with
   deterministic pass/fail criteria
5. 3 consecutive clean passes of the quality gate smoke tests, certified by
   the product agent
6. Manual verification where the milestone specifies it

Outcome milestones are validated against product repos (e.g., farm). The
workbench ships generic capabilities; the product repo proves they work.

---

## How the farm exercise shaped this roadmap

Every item in "Shipped" has a direct line to something discovered while building
the first product repo (farm). The exercise that informed the current design was profiling
a 56-workbook, 239-tab Google Sheets corpus and designing an 11-model schema. Farm validates what the workbench
generates; it does not define what the workbench ships.

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
