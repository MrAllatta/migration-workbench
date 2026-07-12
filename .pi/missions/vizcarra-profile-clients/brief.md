# brief: vizcarra-profile-clients

## Context
Track A (Coda engagement validation). The workbench Coda profiler now detects
relation columns and classifies formula columns (0.5.3 unit-tested). Neither
feature has been run against a real Coda doc. The Vizcarra Guitars Coda doc
(`dCMrB5f1AZE`) has a "Clients" table with 6 required headers (First, Last,
Business Name, Partner, Birthday, Notes). Live config at
`configs/live-config.json`.

The goal of this mission is to **prove the Coda profiler produces a valid
schema contract against real customer data**. Running cleanly against the
Vizcarra doc earns 0.6.0.

## Goal
Run the enhanced Coda profiler against the Vizcarra Guitars Coda doc.
Produce a profile JSON that includes `relation_columns` and
`formula_classifications`, then produce a schema contract from that profile.
Write both artifacts to the vizcarra-guitars repo.

## Repo
migration-workbench (profiler/connector changes) + vizcarra-guitars (target)

## Starting State
- `configs/live-config.json` in vizcarra-guitars defines the "Clients" tab
  with 6 required headers
- `profile_coda_table` command exists and accepts `--doc`, `--table`, `--out`
- `build_contract` accepts `table_profiles` dict
- The Coda doc is live and accessible with a valid API token in `CODA_API_TOKEN`
- 1620 tests pass; `make chassis-gate` is green on latest master

## Scope
### In-scope
1. Check out branch `feat/vizcarra-profile-clients` in migration-workbench.
2. Run `profile_coda_table` against the Vizcarra Coda doc's "Clients" table.
3. Capture any profiler errors or gaps (Coda API issues, missing metadata).
4. Produce a schema contract from the profile via `scaffold_workbook_schema`
   or `build_contract()`.
5. Write the profile JSON and schema contract YAML to the vizcarra-guitars repo
   under `build/_out/`.
6. Profile the entire doc structure for reference (`profile_coda_doc`).
7. If `relation_columns` or `formula_classifications` are missing or empty for
   the Clients table, debug and fix the profiler.
8. **Page composition profiling** (added 2026-07-11): Profile which tables
   are embedded on which pages using `profile_coda_doc --pages`. The Coda
   REST API's page export-to-markdown endpoint (already implemented as
   `export_page_markdown()` in `coda_source.py`) returns the full page with
   all embedded tables; a new markdown parser in
   `profiler/tools/page_profiler.py` extracts this composition. The output
   maps each page to its embedded tables and tries to match them to known
   table names. This unlocks Track B codegen (mirror Coda's page-as-UI in
   generated Django views).

### Out-of-scope
- Import pipeline (that's 0.6.2, `vizcarra-generate-import`)
- UI generation (that's Track B → 0.6.1/0.6.3/0.7.1+)
- Deploy (that's 0.7.1, `vizcarra-views-deploy`)
- Editing the schema contract beyond initial generation (human judgment)

## Success Criteria
- [ ] `profile_coda_table --doc https://coda.io/d/VG-2025_dCMrB5f1AZE --table Clients --out build/_out/coda-profile.json`
      completes without error
- [ ] The profile JSON's `summary` contains a non-empty `relation_columns`
      array and/or `formula_classifications` array, or the Coda API explains
      why they are absent (documented in journal)
- [ ] `scaffold_workbook_schema --bundle-config configs/live-config.json --table-profile build/_out/coda-profile.json --out build/_out/schema-contract.yaml`
      produces a valid contract with all 6 required headers mapped to fields
- [ ] A `profile_coda_doc` artifact is produced listing all tables in the doc
- [ ] `profile_coda_doc --pages` produces a `page_composition` array mapping
      each page to its embedded tables (with section names, column headers,
      and matched table names where applicable)
- [ ] `make chassis-gate` passes in workbench
- [ ] All artifacts are committed to the feat/vizcarra-profile-clients branch

## Constraints
- Do NOT modify the live Vizcarra Coda doc.
- Do NOT commit to master. Work in `feat/vizcarra-profile-clients`.
- If the Coda API requires columns not present in the live-config, update the
  brief (human judgment) rather than guessing.

## Reference
- Vizcarra live config: `configs/live-config.json`
- Coda doc URL: `https://coda.io/d/VG-2025_dCMrB5f1AZE`
- Profiler command: `python manage.py profile_coda_table`
- Coda provider: `connectors/coda.py`, `connectors/coda_source.py`
- Schema contract builder: `workbook/schema_contract.py`

## Earns
0.6.0 — Coda profiler proven against real data.
