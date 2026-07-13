# journal: farm-behavioral-codegen

Track B 0.8.5 — Build a MWBS-to-archetype adapter so views can be
generated directly from behavioral specs, applied to farm.

## Status
Planned.

## Branch
Workbench: `feat/farm-behavioral-codegen`
Farm: direct commits to `main` (per `farm/AGENTS.md`)

## Log

### 2026-07-12 — Designed
- Brief written: MWBS dataclasses exist; view codegen exists; no
  adapter connects them.  Add a `mwbs_to_archetype` module, derive
  farm MWBS, parity-test against `PlannerLandingView` and
  `CropListView`.

### 2026-07-13 — Booted
- `master` chassis-gate: green.
- Worktree `../migration-workbench-farm-behavioral-codegen` on
  branch `feat/farm-behavioral-codegen`.
- Portfolio marked Active: `farm-behavioral-codegen` (Track B, 0.8.5).
- Preconditions: `vizcarra-import-pipeline` (0.8.4) shipped;
  `vizcarra-generated-ui` (0.8.1) established the view codegen pipeline.
- Farm `WORKBENCH` env var pointed at worktree; `make install-dev-workbench`
  replaced 0.7.1 with 0.8.4 editable install from feat branch.
- Farm baseline tests: 90 passed (farm_ui + generated).

### 2026-07-13 — Vertical Slice 1: MWBS landing adapter

- `workbook/codegen/mwbs_to_archetype.py` created with `landing_from_actor`
  and `list_from_workflow_step`.
- Adapter maps Actor responsibilities → SummaryCards with heuristic ORM
  count expressions.
- 8 unit tests cover landing shape, responsibility parsing, report mapping,
  renderable output, idempotency, and list step config.

### 2026-07-13 — Vertical Slice 2: Farm MWBS + parity tests

- `scripts/derive_farm_mwbs.py` constructs elicitor inputs from existing
  contract.yaml, view-manifest.yaml, and domain_context.yaml.
- `config/behavioral-spec.yaml` derived with 3 real actors (planner_manager,
  field_worker, nursery_worker) matching farm_ui/views/landing.py.
- `model_name_overrides` parameter added to adapter for explicit Django
  model name mapping.
- Apostrophe bug fixed in `_responsibility_to_model_name`.
- 10 real-data parity tests: generated landing views match farm's hand-written
  views in card structure, model references, and valid Python output.
- Farm test suite: 100 passed (up from 90).

### 2026-07-13 — Vertical Slice 3: List generator + list parity tests

- `workbook/codegen/list_generator.py` with `ListArchetype` dataclass and
  `render_list_view_py` generating ListView subclasses (model, filters,
  ordering, pagination, filter-option sidebar context).
- `list_from_workflow_step` extended with ordering, paginate_by, and
  context_object_name.
- 3 new unit tests: renderable view code, pagination, ordering (11 total).
- 4 new farm parity tests: CropListView and FieldBlockListView validated
  against generated views.
- Farm test suite: 104 passed.
- Workbench `make chassis-gate`: green.

**All 8 success criteria met. Ready for release.**
