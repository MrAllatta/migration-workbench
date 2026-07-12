# brief: vizcarra-generate-import

## Context
Track A (Coda → Django pipeline). 0.6.0 generated a validated schema contract
for the Vizcarra Clients table. That contract has 46 columns, 4 resolved FK
targets (WorkOrders, Instruments×2, ArchivedWorkOrders), and an import_config
with column_map. The workbench's codegen pipeline (generate_models,
generate_admin, generate_import) is battle-tested on farm.

This mission executes the codegen pipeline against the Vizcarra contract and
proves the generated code works in the vizcarra-guitars product repo.

## Goal
Generate Django `domain/models.py`, `domain/admin.py`, and an import
management command from the Clients schema contract, wire them into
vizcarra-guitars, and prove they work with a real-data test.

## Repo
vizcarra-guitars (primary) + migration-workbench (codegen pipeline)

## Starting State
- `vizcarra-guitars/build/_out/schema-contract.yaml` — validated Clients
  contract (46 columns, 4 FK resolutions, import_config)
- `vizcarra-guitars/backend/apps/core/` — existing core app (empty models.py)
- `vizcarra-guitars/backend/apps/core/models.py` — placeholder
- No `domain/` app exists yet
- workbench `generate_models`, `generate_admin`, `generate_import` commands
  available via editable install

## Scope
### In-scope
1. Create `backend/apps/domain/` app structure (models.py, admin.py, etc.)
2. Add `"domain"` to INSTALLED_APPS in settings.py
3. Run `generate_models --contract` → `domain/models_auto.py`
4. Run `generate_admin --contract` → `domain/admin_auto.py`
5. Run `generate_import --contract` → import management command
6. Write unit tests in `domain/tests/` that:
   - Verify the generated models import and can be migrated (sync-db)
   - Verify the generated admin imports without error
   - Verify the import command can parse the import_config
7. Run tests against real data (create a synthetic CSV bundle, exercise import)

### Out-of-scope
- Profile other tables (WorkOrders, Instruments) — that's a future mission
- Deploy generated views — that's `vizcarra-views-deploy` (0.7.1)
- Run real Coda data through the import pipeline — requires CSV bundles that
  don't exist yet. Validation is with synthetic test fixtures.

## Success Criteria
- [ ] `domain/models_auto.py` imported by `domain/models.py` via stub convention
- [ ] `domain/admin_auto.py` imported by `domain/admin.py` via stub convention
- [ ] Import management command is registered in `domain/management/commands/`
- [ ] `python manage.py import_domain --help` works
- [ ] Unit tests pass in vizcarra-guitars against SQLite
- [ ] `make chassis-gate` passes in workbench
- [ ] Feature branch squash-merged to vizcarra-guitars main
- [ ] Tag v0.6.2

## Constraints
- The `domain/` app is the target for generated models (contract.app_label)
- Use stub convention from stub_writer: `*_auto.py` + `MARKER` in stub
- Do NOT modify migration-workbench for vizcarra-specific logic

## Earns
0.6.2 — Codegen pipeline proven against Vizcarra schema contract.
