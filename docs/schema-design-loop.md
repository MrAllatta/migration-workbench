# Schema Design Loop

This loop keeps spreadsheet-driven importer work in product-owned configuration and schema docs, not ad hoc patches in importer internals.

## Loop Steps (with Agent-Harness Boundaries)

| Step | Agent Role | Consultant Role |
|------|-----------|-----------------|
| **1. Profile** | Runs profiler phases autonomously. Flags ambiguous tabs/columns for review. | Reviews `pipeline-state.yaml` alerts. Approves tab selection. |
| **2. Observe** | Not involved. | Reads profiler output. Understands business operations. Pure human judgment. |
| **3. Draft contract** | Proposes schema contract from profile + domain knowledge. | Hardens: model names, FK targets, field overrides. |
| **4. Decide per app** | Not involved. | Chooses lift / modify / rebuild per app area. Client-specific consulting. |
| **5. Author tab config** | Proposes `column_map`, `fk_lookup`, `field_parsers`. | Confirms or overrides. |
| **6. Author interaction contract** | Classifies UI archetypes, proposes workflow sequence, role boundaries. | Confirms with business owner. |
| **7. Discovery interview** | Generates questionnaire from profiler signals. | Conducts interview, merges answers into interaction contract. |
| **8. Author importer** | Generates import command from hardened contract. | Reviews, runs validate-only. |
| **9. Gate** | Runs tests, validates, checks. | Interprets results. Decides if ready. |
| **10. Drift check** | Re-profiles, diffs against snapshots. | Evaluates if changes are material. |

## Are We Patching?

Use this quick diagnostic when deciding where a change belongs.

- Changes in loop steps 4-8 are expected design work.
- Changes in `importer/*` command body logic are workbench-level changes and should be rare.
- If an importer bug fix requires code edits outside bundle config and thin importer subclasses, treat it as a smell and revisit the schema contract/config first.
