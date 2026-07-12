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
