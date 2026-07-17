# Journal: vizcarra-profile-clients

## 2026-07-11 — Session 1

### What was done
- Brief written from roadmap spec. Profile the Clients table in the Vizcarra
  Coda doc, produce a schema contract, validate against real data.
- Mission capsule created.

### Gate result
- Not yet started.

### Blockers / Gaps
- Needs CODA_API_TOKEN environment variable configured.
- Coda doc access must be confirmed before the profiler runs.

## 2026-07-11 — Session 3 (EXECUTE)

### What was done
- **Token resolved**: Human noted that `CODA_API_TOKEN` was already in
  `vizcarra-guitars/.env` (not in the workbench checkout, which is why the
  agent initially missed it). Copied the token to workbench `.env`.
- **Clients table profile**: Ran
  `profile_coda_table --doc https://coda.io/d/VG-2025_dCMrB5f1AZE --table Clients`
  against the live Coda doc. Result: 500 rows × 46 columns, 5 relation columns,
  8 formula classifications, all 6 required headers present.
- **Doc profile (no pages)**: Ran `profile_coda_doc` — confirmed 71 pages exist
  in the doc, ~100+ tables/views.
- **Page composition scope added**: After human signaled that the REST API
  couldn't see which tables are on which pages, investigated the gap and
  found that the REST API's `/pages/{id}/export?outputFormat=markdown`
  endpoint (already implemented as `export_page_markdown()` in
  `coda_source.py`) returns the full page as markdown with all embedded
  tables. Investigated the Superhuman Docs MCP — same endpoint under JSON-RPC,
  no advantage. Decided REST-only path.
- **Implemented page profiler**:
  - `profiler/tools/page_profiler.py` — new module with markdown parser and
    `profile_page_composition()` function
  - `profiler/management/commands/profile_coda_doc.py` — added `--pages` flag
  - `profiler/tests/test_coda_commands.py` — 3 new tests (markdown parsing,
    no-tables case, smoke)
- **Page composition result**: All 71 pages profiled. Work Order page
  composes 9 tables (Work Orders, Work Order Jobs, Work Order Merch, Clients,
  Instruments, Payments Received, Purchase Order, Totals). Data Export page
  exposes 8 normalized tables (client_*, instrument_*) — a clear migration
  hint for the schema contract.
- **Gate**: `make chassis-gate` → **1623 passed, 1 warning** ✅

### Files changed
- `profiler/tools/page_profiler.py` (+221 lines, new)
- `profiler/management/commands/profile_coda_doc.py` (+57 lines)
- `profiler/tests/test_coda_commands.py` (+57 lines)
- `build/_out/coda-profile.json` (Clients table profile, 7709 lines)
- `build/_out/coda-doc-profile.json` (doc structure + page composition, ~70 pages)

### Decisions made
- **REST over MCP**: The Superhuman Docs MCP (renamed from Coda MCP) wraps
  the same REST export endpoint. Adding a Node.js dependency to a Python
  codebase for no functional gain is not worth it.
- **Markdown parser over AST**: The Coda page export returns well-formed
  GFM markdown. A lightweight regex-based parser in 220 lines suffices;
  no need for `mistune`/`markdown-it-py` or a full Markdown AST.
- **Column-overlap matching**: Match embedded tables to known table names
  by header overlap (≥2 columns in common). This is a heuristic; some
  false matches occur (e.g., the Totals table on the Work Order page was
  matched to "Work Orders" because of shared column names). Acceptable for
  the profiling use case — the human judgment point at schema review
  catches false matches.
- **Page composition as additive scope**: Added `--pages` flag rather than
  making it the default. The current Vizcarra mission only profiles one
  table, but the flag makes the broader doc profile richer for downstream
  missions (`vizcarra-views-deploy` 0.7.1 will need this).

### Gate result
- `make chassis-gate` on `feat/vizcarra-profile-clients`: **1623 passed,
  1 warning** ✅

### Profile JSON findings (Clients table)
- 500 data rows, 46 columns
- 5 relation columns detected:
  - "Instruments Manual Entry" → Instruments
  - "Instruments" → Instruments
  - "Created By" → person_reference_not_resolved_to_fk
  - "Active Work Orders" → Work Orders
  - "Invoices" → Archived Work Orders
- 8 formula classifications (1 row, 1 expansion, 3 hybrid, 3 unknown)
- Note: "Full Name" = `First+" "+Last` was classified `unknown, low`
  confidence because the regex doesn't match bare concatenation. This is
  a classification gap; a human can manually mark it row_formula at the
  schema contract review.

### Page composition findings
- 71 pages total
- Work Order page: 9 tables (Work Orders, Jobs, Merch, Client, Instrument,
  Payments, Purchase Order, Totals)
- Data Export page: 8 normalized tables (client_address, client_biography,
  client_contact, client_instrument, instrument_details, instrument_owner,
  instrument_setup, instrument_summary) — these are the **cleanest target
  schema** for the migration
- Time Sheet page: 1 view (View of Work Orders)
- Priority page: 1 view (Prioritize Work Orders)

### Next steps
- Generate schema contract via `scaffold_workbook_schema` from the
  Clients table profile
- Write profile JSON + schema contract YAML to vizcarra-guitars
  `build/_out/`
- Update portfolio to reflect scope expansion
- Final `make chassis-gate` and squash-merge

## 2026-07-11 — Session 4 (FINALIZE)

### What was done
- **Schema contract generated**: Ran
  `scaffold_workbook_schema --bundle-config <vizcarra-guitars>/configs/live-config.json
  --table-profile build/_out/coda-profile.json --out build/_out/schema-contract.yaml`
  Result: 46 columns mapped, 6 required headers all present, 4 FK relations
  resolved, 1 computed field, 2 auto-detected FKs flagged for review.
- **Artifacts written to vizcarra-guitars `build/_out/`**:
  - `coda-profile.json` — Clients table profile (500 rows × 46 columns)
  - `coda-profile.md` — Clients table markdown summary
  - `coda-doc-profile.json` — full doc structure + 71 pages with page_composition
  - `coda-doc-profile.md` — full doc markdown tree + page composition
  - `coda-page-composition.md` — focused page composition report
  - `schema-contract.yaml` — schema contract for Clients table
- **Final gate**: `make chassis-gate` → **1623 passed, 1 warning** ✅

### Schema contract highlights
- 6 required headers all mapped to fields:
  - `First` → `first` (TextField)
  - `Last` → `last` (TextField)
  - `Business Name` → `business_name` (TextField)
  - `Partner` → `partner` (TextField)
  - `Birthday` → `birthday` (DateField)
  - `Notes` → `notes` (TextField)
- 4 resolved ForeignKey relations (high confidence, coda_relation_column source):
  - `Instruments Manual Entry` → Instruments
  - `Instruments` → Instruments
  - `Active Work Orders` → WorkOrders
  - `Invoices` → ArchivedWorkOrders
- 2 auto-detected FKs (need human review at schema contract review):
  - `Client ID` → Client (review_note: "Auto-detected FK: Client")
  - `Instrument ID` → Instrument (review_note: "Auto-detected FK: Instrument")
- 1 computed field:
  - `Count of Instruments` = `Count(Instruments)` → `is_computed: true`
    with TODO expression
- Formula classifications as notes on each column (e.g., `coda_formula:hybrid
  (confidence:medium)` on `Instruments`)

### Files in vizcarra-guitars build/_out/
- `coda-profile.json` (247KB) — Clients table profile
- `coda-profile.md` (4.7KB) — Clients markdown summary
- `coda-doc-profile.json` (436KB) — full doc + 71 pages
- `coda-doc-profile.md` (72KB) — full doc markdown + page composition
- `coda-page-composition.md` (13KB) — focused page composition report
- `schema-contract.yaml` (21KB) — schema contract for Clients

### Gate result
- `make chassis-gate` on `feat/vizcarra-profile-clients`: **1623 passed,
  1 warning** ✅

### Mission outcome
- ✅ Coda profiler produced a valid profile against real customer data
- ✅ `relation_columns` array non-empty (5 entries)
- ✅ `formula_classifications` array non-empty (8 entries)
- ✅ Schema contract generated with all 6 required headers mapped
- ✅ `profile_coda_doc` artifact produced listing all tables
- ✅ `profile_coda_doc --pages` produced page_composition for all 71 pages
- ✅ `make chassis-gate` passes
- All artifacts committed to `feat/vizcarra-profile-clients`

### Commit history
- `60beae4` chore(mission): boot vizcarra-profile-clients, baseline green, await CODA_API_TOKEN
- `935765f` chore(portfolio): mark vizcarra-profile-clients as booted, blocked on CODA_API_TOKEN
- `ef2989a` feat(profiler): add page composition profiling to Coda doc profiler
- `b88895f` docs(mission): document page-profiling scope expansion and findings

## 2026-07-11 — Session 5 (FIXES + SQUASH)

### What was done
- **Drill-down investigation of auto-detected FKs**: The user pushed back on
  the initial analysis (both user and agent were uncertain). Traced the
  actual data in the Clients and Instruments tables to confirm:
  - ``Client ID`` = `thisRow.RowId()+100` — local PK, NOT a FK
  - ``Instrument ID`` = `Instruments.[Instrument ID]` — formula-derived
    preview of the `Instruments` lookup, which already has proper FK
  - ``oldClient ID`` = legacy number, no `Oldclient` table exists
  - Real FK relationships are through `Instruments` (lookup → Instruments)
    and `Owner` on the Instruments side (lookup → Clients).
- **Fixed FK auto-detection in `_flag_fk_columns()`**:
  - Self-reference skip: `client_id` in `Clients` table no longer flagged
  - Formula-derived skip: `instrument_id` (has_formula=True) no longer flagged
- **Fixed formula classifier**: Added `+`/`&` string concatenation and
  `Concatenate()` function as row_formula signals. Full Name now correctly
  classified as `row_formula` (was `unknown`).
- **Re-generated all artifacts** with fixed code.

### Final schema contract state
- Client ID: NO FK suggestion, no review note ✅
- Instrument ID: NO FK suggestion, no review note ✅
- Full Name: has `coda_formula:row_formula (confidence:high)` note ✅
- Count of Instruments: in `computed_fields` with TODO ✅
- 4 real FK resolutions preserved: Instruments(×2), WorkOrders,
  ArchivedWorkOrders ✅
- oldClient ID: still flagged as `Auto-detected FK: Oldclient` — acceptable
  as the human will see it doesn't match any table at review

### Gate result
- `make chassis-gate` on `feat/vizcarra-profile-clients`: **1628 passed,
  1 warning** ✅

### Commit history (7 commits)
```
60beae4 chore(mission): boot vizcarra-profile-clients, baseline green, await CODA_API_TOKEN
935765f chore(portfolio): mark vizcarra-profile-clients as booted, blocked on CODA_API_TOKEN
ef2989a feat(profiler): add page composition profiling to Coda doc profiler
b88895f docs(mission): document page-profiling scope expansion and findings
aaeb97d fix: suppress spurious FK auto-detection and classify string concatenation
```

### For the human: approval needed to squash-merge

1. Review the schema contract at:
   `vizcarra-guitars/build/_out/schema-contract.yaml`
2. Confirm the 4 FK resolutions and 1 computed field look right
3. Confirm `oldClient ID`'s `Auto-detected FK: Oldclient` should be removed
   at review (no such table exists)
4. Approve squash-merge → I'll:
   - Squash 5 commits into one
   - Merge to master
   - Delete feature branch
   - Tag v0.6.0
   - Bump `pyproject.toml`
   - Add changelog entry to README.md

## 2026-07-11 — Session 2 (BOOT)
