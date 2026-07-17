# Mission Brief: vizcarra-views-deploy (Track A, 0.7.1)

## Goal
Make the Vizcarra Guitars `domain` app migration-ready by profiling the three
FK-target tables referenced from the **Clients** contract, generating their
contracts/models/admin/import artifacts, and deploying a generated view that
proves the Django app works end-to-end against real Coda data.

## Context
The `vizcarra-generate-import` mission (0.6.2) produced a `Clients` model in
the product repo. Its schema contract references three tables that do not yet
exist as Django models:

- `WorkOrders` — the primary work-order table
- `Instruments` — instrument inventory/details (two FKs from Clients)
- `ArchivedWorkOrders` — archived work orders

The `profile_coda_doc` command already emitted a full doc profile
(`build/_out/coda-doc-profile.json` / `.md`) listing these tables and their
columns, but we do not yet have certified schema contracts, generated models,
or migrations for them.

## Success criteria

### Must have
1. **Profiled tables** — `profile_coda_table` (or equivalent) used to emit
   column profiles for `WorkOrders`, `Instruments`, and `ArchivedWorkOrders`.
2. **Certified contracts** — three schema-contract YAML files under
   `vizcarra-guitars/build/_out/` for each table.
3. **Generated models** — `models_auto.py` extended (or regenerated) to include
   all three tables, with FK targets existing in the same app so migrations can
   run without lazy-reference failures.
4. **Generated admin & import** — `admin_auto.py` and `import_domain.py`
   include the new tables.
5. **Migrations run** — `python manage.py migrate` succeeds in
   `vizcarra-guitars`.

### Should have
6. **FK resolution** — Clients FKs (`WorkOrders`, `Instruments`×2,
   `ArchivedWorkOrders`) point to concrete models in the `domain` app.
7. **Real-data import smoke test** — at least one of the new tables imports a
   non-zero row count from Coda without crashing.

### Nice to have
8. **Generated view deployed** — a checklist or landing view (from 0.6.1 or
   0.6.3) rendered for one of the new tables and exercised in a browser/test.

## Non-goals
- Replacing hand-written Vizcarra UI (this is scaffolding only).
- Handling every one of the 138 Instruments columns perfectly; focus on the
  core columns and FK relationships.
- Production polish of the generated admin.

## Validation

### Workbench
- `make chassis-gate` green.

### Product repo
- `vizcarra-guitars` migrations apply cleanly.
- `python manage.py import_domain --dry-run` (or equivalent) reports row
  counts for the new tables.
- At least one real-data test passes against the generated models (e.g. create
  a record, assert expected fields).

## Version gate
0.7.1 (minor). End-to-end real-data validation in `vizcarra-guitars`.

## Out of scope
- Pushing to origin (human action per branch discipline).
- PyPI upload (blocked until 1.0.0).

## Artifacts
- `.pi/missions/vizcarra-views-deploy/journal.md`
- `vizcarra-guitars/build/_out/schema-contract-*.yaml` (one per table)
- `vizcarra-guitars/backend/apps/domain/models_auto.py`
- `vizcarra-guitars/backend/apps/domain/admin_auto.py`
- `vizcarra-guitars/backend/apps/domain/management/commands/import_domain.py`
- `vizcarra-guitars/backend/apps/domain/tests/test_*.py`
