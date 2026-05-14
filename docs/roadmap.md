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

## Immediate (next release, 0.2.x)

These are fixes and small enhancements exposed by the farm exercise that
can ship without major rearchitecture.

### Contract schema v1.3

The v1.2 contract supports enums, admin config, model_base, and field
overrides. The farm exercise revealed missing Meta options and awkward
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

- **`make generate-models` overwrites models.py without warning.**
  Already has `--force` flag. Add `make diff-generated` target that
  shows what changed between codegen runs: `diff -u models.py.bak models.py`.

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
`scaffold_workbook_schema` already produces v1.0 drafts for source-aligned
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

## Medium-term (0.5.x–0.6.x)

### Schema design loop tooling

The farm exercise followed the schema design loop (Profile → Observe →
Draft → Decide → Author → Gate → Drift). Tooling for phases 3-5 (Draft
through Author) is weakest.

- **Contract diff tool** — compare two contract versions and emit the
  model/field/add/remove/change delta. Essential for drift checking and
  code review.
- **Profile-to-contract bridge** — `scaffold_workbook_schema` already
  does this for source-aligned models. Extend it to suggest designed
  model structures from profile patterns (e.g., "these three tabs have
  overlapping columns → possible designed model").
- **Schema review checklist** — `wb contract review --contract contract.yaml`
  that checks for common issues: missing `unique_together`, nullable
  FKs without `on_delete`, implicit `blank=True` on CharFields, etc.

### Generated code quality verification

- **`make check-generated`** — runs `py_compile` on generated files,
  then `python -c "from core.models import *"` to verify imports,
  then `manage.py check` to catch Django-level issues.
- **Migration safety checks** — detect if contract changes would
  produce destructive migrations (nullable→non-nullable, removed fields).
  Warn before generation.
- **Snapshot testing** — store generated output in `build/codegen-snapshots/`
  by contract version. CI compares snapshots to detect unexpected
  output changes.

### View manifest and discovery integration

The view manifest and discovery interview pipeline was not exercised
in the farm implementation (admin was generated without manifest).
These need end-to-end testing:

- **Admin generation from view manifest** — verify that `editable_fields`,
  `computed_fields`, `filterable_by` actually influence the generated
  admin (list_display, readonly_fields, list_filter).
- **Discovery interview merge** — the `make merge-discovery-notes`
  pipeline patches the view manifest. This should feed into admin
  regeneration cleanly.
- **Status field detection** — the heuristic picks the first CharField
  with choices. Allow manual override in the manifest.

## Longer-term (post-v1.0)

### Provider interface extraction

The farm exercise used Google Sheets exclusively. The provider interface
(connectors) is shared between Sheets and Coda adapters, but the profiler
and importer still have provider-specific code paths. After a second
provider is stable on Fly:

- **Abstract provider interface** — common base class for profiling,
  pulling, and auth.
- **Plugin system** — third-party providers can register without forking.
- **Profile format unification** — profiler artifacts should be
  provider-agnostic (column types, row counts, formula detection).

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

## Non-goals (explicitly deferred)

- **GUI for contract authoring.** The YAML is the interface. Visual
  tooling would lock us into a narrow workflow before the contract
  format stabilizes.
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
| `unique_together` required hand-edit after generation | Add to model_meta in v1.3 |
| Properties/methods required hand-edit after generation | `contract.hooks` block |
| Designed models (FieldEvent, InventoryEntry) have no scaffolding | `source_tab: null`, designed model scaffold command |
| No way to validate contract before codegen | `make validate-contract`, codegen-time contract validation |
| Couldn't tell what codegen changed across runs | `make diff-generated`, `--diff` flag |
| Upstream renderer bugs found mid-pipeline | Fixes committed, add to test suite |
| Import generator untested (no bundles pulled yet) | Import pipeline foundation section |
| View manifest / discovery pipeline not exercised | Medium-term integration testing |
| 114 test suite passed but no snapshot tests | Snapshot testing for generated output |

## Tracking

Individual items are tracked as GitHub issues with `roadmap/` label.
The `v1.0` milestone collects the v1.0 criteria from README.md.
This document is updated when milestones ship or priorities shift.
