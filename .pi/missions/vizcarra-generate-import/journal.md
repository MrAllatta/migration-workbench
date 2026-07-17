# Journal: vizcarra-generate-import

## 2026-07-11 — Boot

**Decision:**
`wb-checklist-archetype` shipped (0.6.1). Both tracks have one mission each
delivered. Continuing Track A with the codegen pipeline against the Vizcarra
contract is the natural next step — we have the contract, the pipeline is
battle-tested on farm, and executing it proves the pipeline works on a
non-farm schema for the first time.

### Contract state
- 1 table: Clients (46 columns, 4 FK resolutions, import_config)
- FK targets: WorkOrders, Instruments×2, ArchivedWorkOrders
- app_label: domain
- No computed fields that would need property definitions

### Starting state
- Branch: `master` (workbench)
- vizcarra-guitars: main branch, no feat branch yet
- `make chassis-gate`: 1671 passed, 1 warning

## 2026-07-11 — Session 1 (COMPLETE)

### Done
- Created `domain/` app in vizcarra-guitars with generated models/admin/import
- Fixed upstream bug: `render_computed_property()` comment-only expression
  crash (added `return None` fallback)
- 11 tests passing in vizcarra-guitars
- Squash-merged to master, tagged v0.6.2
- 1671 passed, 1 warning

### Key findings
- The FK targets (WorkOrders, Instruments, ArchivedWorkOrders) don't exist
  in the domain app — they need to be profiled in a future mission for
  the models to migrate cleanly
- The contract's computed_fields.expression was a bare `# TODO:` comment
  which broke the model generator — fixed upstream
- vizcarra-guitars venv had stale editable install of migration-workbench
  (0.1.0) that didn't include the `workbench` package — reinstalled
