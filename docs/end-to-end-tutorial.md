# End-to-End Tutorial: Profile → Contract → Import

This walkthrough takes a spreadsheet (Google Sheets or Coda) and runs the full
migration-workbench pipeline: profiling, bundling, schema contract authoring,
code generation, and data import.

## Prerequisites

- Python 3.11+
- A virtual environment with migration-workbench installed:
  ```bash
  python3 -m venv .venv
  .venv/bin/pip install "migration-workbench[dev]"
  ```
- **For Google Sheets:** `GOOGLE_APPLICATION_CREDENTIALS` pointing to a service
  account JSON key. See [docs/google-auth.md](google-auth.md).
- **For Coda:** `CODA_API_TOKEN` set in your environment.
- A test spreadsheet with at least one well-structured tab (headers, a few
  dozen rows, no merged-cell chaos).

---

## Step 1: Profile preflight

Verify that credentials, scopes, and folder access work before spending time on
deeper profiles.

```bash
python manage.py profile_preflight --smoke
```

On success:

```
credentials path exists: /home/user/.config/gcloud/application_default_credentials.json
profile_preflight smoke ok
```

The `--smoke` flag skips network calls.  Omit it to actually hit the Google
Drive/Sheets API:

```bash
python manage.py profile_preflight --folder <drive-folder-id-or-url>
```

Expected output:

```
credentials path exists: /home/user/.config/gcloud/application_default_credentials.json
drive/sheets clients initialized
folder readable: My Spreadsheet Folder (abc123...)
profile_preflight ok
```

**What it checks:**
- `GOOGLE_APPLICATION_CREDENTIALS` exists (or ADC fallback)
- Drive v3 + Sheets v4 clients initialise
- Folder (if `--folder` given) is readable
- Drive `about().get()` confirms the authenticated user

---

## Step 2: Profile a tab

Profile a single spreadsheet tab to inspect structure, formula density, and
null rates before committing to a bundle config.

```bash
python manage.py profile_tab --spreadsheet-id <sheet-id> --tab "Crop Planner" --out /tmp/profiles/crop_planner.json
```

If you omit `--tab`, the command lists all tabs in the spreadsheet and exits:

```
[ 0] sheetId=0           rows=105   cols=12  Crop Planner
[ 1] sheetId=123456789    rows=42    cols=8   Block Reference
[ 2] sheetId=987654321    rows=18    cols=5   Notes
```

When `--out` is provided, two artifacts are produced:

| File | Contents |
|------|----------|
| `crop_planner.json` | Raw grid + summary (column names, types, formula skeletons, null rates) |
| `crop_planner.md` | Human-readable summary (Markdown) |

The summary JSON includes per-column stats (`has_formula`, `null_rate`,
`unique_count_sample`, `is_relation_type`) and top formula skeletons —
essential data for the schema design loop.

---

## Step 3: Pull a bundle

The `pull_bundle` command reads a JSON config that describes source tabs and
their expected headers, then fetches and normalises each tab into a
deterministic CSV bundle.

First create a config file (e.g. `config/live.json`):

```json
{
  "provider": "google_sheets",
  "source_id": "farm-2025",
  "tabs": [
    {
      "spreadsheet_id": "replace-with-google-sheet-id",
      "worksheet_title": "Crop Planner",
      "output_path": "reference/crop_planner.csv",
      "required_headers": ["Crop", "Plant Date", "Beds Used", "Notes"]
    }
  ]
}
```

Then run:

```bash
python manage.py pull_bundle --config config/live.json --output-dir /tmp/bundle
```

Output directory structure:

```
/tmp/bundle/
├── manifest.json
├── reference/
│   └── crop_planner.csv
└── structure.json       (only with --include-structure)
```

**`manifest.json`** lists each tab, its `output_path`, row count, and source
metadata.  **`reference/crop_planner.csv`** is the normalised CSV with headers
resolved via the configured `required_headers` / `aliases` / `column_map`
logic.

Add `--include-structure` to also emit `structure.json` with per-tab UI
metadata (header ordering, formula columns, validation types).

---

## Step 4: Scaffold a workbook schema

Generate a first-draft schema-contract YAML from the bundle config and
optionally from tab-profile artifacts.

```bash
python manage.py scaffold_workbook_schema \
  --bundle-config config/live.json \
  --out /tmp/schema-contract.yaml
```

Example output:

```
scaffolding schema contract from bundle config: config/live.json
wrote /tmp/schema-contract.yaml
```

The generated YAML looks like:

```yaml
source:
  provider: google_sheets
  source_id: farm-2025
tables:
  - suggested_model_name: cropplanner
    bundle_worksheet_title: Crop Planner
    bundle_output_path: reference/crop_planner.csv
    columns:
      - suggested_field_name: crop
        suggested_field_type: string
        notes: ""
      - suggested_field_name: plant_date
        suggested_field_type: date
        notes: ""
      - suggested_field_name: beds_used
        suggested_field_type: integer
        notes: ""
      - suggested_field_name: notes
        suggested_field_type: text
        notes: ""
```

> This is an **advisory** scaffold.  Model names, field types, and relations
> need human review before they become real Django models.

Review it carefully — this YAML is the bridge between profiling and code
generation.

---

## Step 5: Harden the contract

Edit `/tmp/schema-contract.yaml` to add production-grade metadata.  Save as
`contract-v1.yaml`.

```yaml
source:
  provider: google_sheets
  source_id: farm-2025
tables:
  - suggested_model_name: CropPlan
    bundle_worksheet_title: Crop Planner
    bundle_output_path: reference/crop_planner.csv
    model_meta:
      verbose_name: "Crop Plan"
      verbose_name_plural: "Crop Plans"
      ordering: ["plant_date"]
    str_template: "{self.crop} — {self.plant_date}"
    columns:
      - suggested_field_name: crop
        suggested_field_type: string
        django_field_class: CharField
        django_field_kwargs:
          max_length: 200
      - suggested_field_name: plant_date
        suggested_field_type: date
        django_field_class: DateField
      - suggested_field_name: beds_used
        suggested_field_type: integer
        django_field_class: IntegerField
      - suggested_field_name: notes
        suggested_field_type: text
        django_field_class: TextField
        django_field_kwargs:
          blank: true
          default: ""
    import_config:
      tier: 1
      bundle_path: "reference/crop_planner.csv"
      required_headers: [Crop, Plant Date, Beds Used, Notes]
      column_map:
        crop: Crop
        plant_date: Plant Date
        beds_used: Beds Used
        notes: Notes
      unique_on: [crop, plant_date]
      required_source_columns: [crop]
```

**Key additions:**
- `model_meta` — verbose names, ordering
- `str_template` — `__str__` representation
- `django_field_class` + `django_field_kwargs` — explicit field types
- `import_config` — `tier`, `bundle_path`, `column_map`, `unique_on`, etc.

If your data has foreign key relationships, add `fk_resolutions`:

```yaml
    fk_resolutions:
      block:
        model: Block
        on: name
```

And for multi-source `column_map` or field transforms:

```yaml
    column_map:
      crop: Crop
      plant_date: Plant Date
    field_transforms:
      full_name:
        sources: [First, Last]
        transform: "lambda first, last: f'{first} {last}'.strip()"
```

---

## Step 5b: Generate the View Manifest

A view manifest adds UI and workflow concerns on top of the schema contract:
which fields are editable, which column tracks status, which columns drive
temporal scoping, and which columns should appear in admin list filters.

```bash
python manage.py scaffold_view_manifest \
  --structure profiler-output/structure.json \
  --contract build/schema-contract.yaml \
  --out build/view-manifest.yaml
```

> **Tip:** If you ran `pull_bundle --include-structure`, the `structure.json`
> file is already in `profiler-output/`. The view manifest is re-generatable
> at any time by re-running this command.

The generated `build/view-manifest.yaml` contains one entry per spreadsheet
tab. Open it and review:
- **`status_field`** / **`status_values`** — does the correct status column
  have its distinct values listed?
- **`time_scope`** — are the year/week/date columns correctly identified?
- **`editable_fields`** — do these match the columns users should edit?
- **`computed_fields`** — do these match formula columns?

Edit the manifest if needed — it is hand-editable. The admin generator reads
these values to produce `list_display`, `list_filter`, `date_hierarchy`,
`get_queryset` year-scoping, and bulk status actions.

See the [View Manifest Reference](view-manifest.md) for the full format.

---

## Step 6: Generate models, admin, and import command

### 6a — Generate models

```bash
python manage.py generate_models \
  --contract /tmp/contract-v1.yaml \
  --out backend/apps/core/models.py \
  --app-label core \
  --force
```

Produces a Django `models.py` with `CropPlan` model, `Meta`, `__str__`, and
any `extra_fields` or `computed_fields` defined in the contract.

### 6b — Generate admin

```bash
python manage.py generate_admin \
  --contract /tmp/contract-v1.yaml \
  --out backend/apps/core/admin.py \
  --app-label core \
  --force
```

Produces `admin.py` with `ModelAdmin` registrations, `list_display`,
`search_fields`, `list_filter`, `readonly_fields`, and `TabularInline` classes
for reverse FK relationships.

### 6c — Generate import command

```bash
python manage.py generate_import \
  --contract /tmp/contract-v1.yaml \
  --out backend/apps/core/management/commands/import_core_data.py \
  --app-label core \
  --force
```

Produces a `BaseImportCommand` subclass with `_run_import_pipeline`, per-model
`_import_<model>()` methods, alias-aware header resolution, `update_or_create`
with `unique_on`, FK lookups via `_resolve_fk_by_text`, and per-tier
savepoints.

---

## Step 7: Run the import

### Validate only (transaction rolled back)

```bash
python manage.py import_core_data /tmp/bundle --validate-only
```

The full import pipeline runs inside a transaction that is **always rolled
back**.  Useful for CI and first-time smoke testing.

### Dry run (parse only, no writes)

```bash
python manage.py import_core_data /tmp/bundle --dry-run
```

Parses CSVs and counts rows but never touches the database.  Fastest feedback
loop for config iteration.

### Live import

```bash
python manage.py import_core_data /tmp/bundle --summary-json /tmp/import-summary.json
```

Writes to the database.  The optional `--summary-json` flag writes a detailed
summary artifact.

### Reading the summary JSON

```json
{
  "summary_schema_version": "1.0",
  "started_at": "2025-05-17T10:30:00Z",
  "finished_at": "2025-05-17T10:30:02Z",
  "stats": {
    "CropPlan": {
      "processed": 0,
      "created": 42,
      "updated": 3,
      "errors": 0,
      "row_errors_count": 0
    }
  },
  "failure_signatures": [],
  "escalation_summary": {
    "total_rows": 45,
    "total_errors": 0,
    "failure_signature_count": 0,
    "error_codes": []
  }
}
```

**Key fields:**
- `stats.<Model>.created` / `updated` / `errors` — per-model outcome.
- `failure_signatures` — structured errors by code
  (`unique_violation`, `type_mismatch`, `row_exception`).
- `escalation_summary` — rollup for CI gates.

---

## Step 7b: Generate the Pipeline Manifest

A pipeline manifest is an execution plan that maps each contract table to its
source spreadsheets per year. It is used by downstream tooling to orchestrate
pull and import commands across years.

```bash
python manage.py generate_pipeline_manifest \
  --contract build/schema-contract.yaml \
  --corpus-config config/cohort_corpus.json \
  --out build/pipeline-manifest.yaml
```

The generated file is machine-only and should not be hand-edited.

See the [Pipeline Manifest Reference](pipeline-manifest.md) for the full format.

---

## Step 8: Next steps

- **Iterate the contract** — run `validate-only` after every config change.
- **Schema design loop** — see [docs/schema-design-loop.md](schema-design-loop.md)
  for the full profile → observe → draft → decide → author cycle.
- **Add more tabs** — extend `config/live.json` with additional tab entries,
  re-run `pull_bundle`, harden the contract, and regenerate.
- **Deployment** — see [docs/deployment.md](deployment.md) for Fly.io +
  Litestream setup, secrets, and CI/CD.
- **View manifest + discovery interview** — after `pull_bundle
  --include-structure`, run `scaffold_view_manifest` and the discovery
  interview workflow to capture UI/UX metadata (see
  [workbook/README.md](../workbook/README.md)).

---

## Coda alternative

Each Google Sheets command in this tutorial has a Coda equivalent (same steps,
different commands):

| Sheets | Coda |
|--------|------|
| `profile_preflight` | `profile_coda_preflight` |
| `profile_tab` | `profile_coda_table` |
| `profile_cohort_corpus` | `profile_coda_corpus` |
| `scan_formula_patterns` | `scan_coda_formula_columns` |

Bundle configs for Coda use `"provider": "coda"`, and you may optionally
include `doc_url` / `doc_id` fields.  The schema-contract, codegen, and import
commands are provider-agnostic — once the bundle exists, the pipeline is
identical.  See [docs/coda.md](coda.md) for details.
