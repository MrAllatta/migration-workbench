# Bundle commands: pull_bundle & snapshot_bundle

## Overview

The **bundle** is the normalized intermediate artifact between profiling and importing.
A bundle directory contains:

- One CSV per source tab (normalized — headers detected, rows aligned, columns mapped)
- A `manifest.json` describing what was pulled and how
- An optional `structure.json` with UI-level column metadata (when `--include-structure` is passed)

Importers consume bundles. Profilers produce the configs that drive bundle creation.

## Source config JSON

Both commands accept a `--config` JSON file describing the tabs to fetch or normalize.

### Common top-level keys

| Key | Required | Description |
|-----|----------|-------------|
| `provider` | no (default `google_sheets`) | Source provider: `google_sheets` or `coda` |
| `source_id` | no (auto-generated) | Identifies this bundle in the manifest |
| `tabs` | yes | Array of tab descriptors (see below) |
| `years` | no | Multi-year expansion — see [Multi-year bundles](#multi-year-bundles) |

### Tab-level keys (live mode — Google Sheets)

See [docs/examples/live-config.example.json](../docs/examples/live-config.example.json):

| Key | Required | Description |
|-----|----------|-------------|
| `spreadsheet_id` | yes | Google Sheet ID from the sheet URL |
| `worksheet_title` | yes | Name of the worksheet tab |
| `output_path` | yes | Relative path inside the bundle directory (e.g. `reference/blocks.csv`) |
| `required_headers` | yes | Array of column header strings the normalizer must find |
| `aliases` | no | Map of alternative header names to canonical names |
| `header_row_index` | no | 0-based row index of the header (auto-detected by default) |
| `anchor_token` | no | Text marker that identifies the header row |
| `output_headers` | no | Rename output columns (map of original → new name) |
| `column_map` | no | Transform or reorder columns in output |
| `default_values` | no | Default cell values keyed by column name |
| `row_transforms` | no | Per-row transform pipeline |
| `source_regions` | no | Named cell ranges within the sheet |
| `stop_on_blank_in` | no | Stop reading rows when this column is blank |
| `max_scan_rows` | no | Rows to scan for header detection (default 200) |
| `grid_unpivot` | no | Unpivot a grid layout into key/value columns |
| `append_without_header` | no | Append rows without writing header when output exists |

### Tab-level keys (live mode — Coda)

See [docs/examples/coda-live-config.example.json](../docs/examples/coda-live-config.example.json):

| Key | Required | Description |
|-----|----------|-------------|
| `doc_url` | yes* | Coda doc URL (`https://coda.io/d/...`). Alternative to `doc_id`. |
| `worksheet_title` | yes | Table name in the Coda doc |
| `output_path` | yes | Relative path inside the bundle directory |
| `required_headers` | yes | Array of column header strings |

`*` When using `provider: "coda"`, set `doc_url` (or `doc_id`) at the config root instead of per-tab.

### Tab-level keys (offline mode)

See [docs/examples/offline-config.example.json](../docs/examples/offline-config.example.json):

| Key | Required | Description |
|-----|----------|-------------|
| `source_csv` | yes | Path to a local CSV file (relative to the config file) |
| `output_path` | yes | Relative path inside the bundle directory |
| `required_headers` | yes | Array of column header strings |

All normalizer keys (`aliases`, `header_row_index`, `anchor_token`, `output_headers`, `column_map`, etc.) work in offline mode too.

### Multi-year bundles

Set `years` on the config to expand each tab across multiple spreadsheets:

```json
{
  "provider": "google_sheets",
  "tabs": [
    {
      "spreadsheet_id": "fallback-sheet-id",
      "worksheet_title": "Blocks",
      "worksheet_title_by_year": { "2025": "Blocks 2025" },
      "output_path": "blocks.csv",
      "required_headers": ["Block", "Type"]
    }
  ],
  "years": {
    "2024": { "spreadsheet_id": "sheet-2024-id" },
    "2025": { "spreadsheet_id": "sheet-2025-id" }
  }
}
```

Each year expands to `year_YYYY/output_path` and receives a `source_bundle_year` default value.

## Live mode: pull_bundle

Fetch tabs from a live provider and normalize them into a bundle directory:

```bash
python manage.py pull_bundle \
    --config docs/examples/live-config.example.json \
    --output-dir data/bundles/my-bundle
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--config` | yes | Path to the JSON config file |
| `--output-dir` | yes | Directory for the normalized bundle (created if missing) |
| `--include-structure` | no | Also emit `structure.json` with UI-level column metadata (Google Sheets only) |

### Environment variables

| Variable | Used for |
|----------|----------|
| `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` | Google Sheets ADC impersonation (see [docs/google-auth.md](google-auth.md)) |
| `CODA_API_TOKEN` | Coda API authentication (see [docs/coda.md](coda.md)) |

### Output

```
data/bundles/my-bundle/
├── manifest.json
├── reference/
│   ├── blocks.csv
│   └── grades.csv
└── structure.json         # only with --include-structure
```

## Offline mode: snapshot_bundle

Normalize local CSV snapshots without contacting a live provider:

```bash
python manage.py snapshot_bundle \
    --config docs/examples/offline-config.example.json \
    --output-dir data/bundles/my-offline-bundle
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--config` | yes | Path to the JSON config file (CSV paths are relative to this file) |
| `--output-dir` | yes | Directory for the normalized bundle |

## The manifest.json

Every bundle contains a `manifest.json` at its root:

```json
{
  "schema_version": "bundle-draft-1",
  "source_id": "example-live-source",
  "connector_version": "bundle-connector-1",
  "provider": "google_sheets",
  "tabs": [
    {
      "source_id": "1a2b3c4d5e6f7g8h",
      "source_name": "My Spreadsheet",
      "worksheet_title": "Blocks",
      "output_path": "reference/blocks.csv",
      "header_row_index": 3,
      "strategy": "required_header_set_scan",
      "rows_written": 142,
      "modified_time": "2025-03-15T14:30:00Z"
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `schema_version` | Contract version for the normalizer (`bundle-draft-1`) |
| `source_id` | User-defined or auto-generated bundle identifier |
| `connector_version` | Adapter version tag |
| `provider` | Name of the source provider |
| `tabs[]` | Per-tab output metadata |

### Tab manifest fields

| Field | Description |
|-------|-------------|
| `source_id` | Provider-specific document ID (spreadsheet ID or Coda doc ID) |
| `source_name` | Human-readable document name |
| `worksheet_title` | Tab or table name in the source |
| `output_path` | Relative path of the normalized CSV in the bundle |
| `header_row_index` | 0-based row index where headers were found |
| `strategy` | Detection strategy used (`required_header_set_scan`, `anchor_token`, etc.) |
| `rows_written` | Number of data rows written (excludes header) |
| `modified_time` | Source document modification timestamp (live mode only) |

### Offline manifest differences

Offline manifests omit `provider`, `source_name`, `worksheet_title`, and `modified_time`. Each tab entry includes `source_csv` (the original local path) instead.

## The normalized bundle directory

The bundle output structure is:

```
<output-dir>/
├── manifest.json
└── <per-tab output paths from config>
```

- Each CSV has a single header row followed by data rows.
- Rows are normalized (whitespace trimmed, spaces collapsed, headers matched via casefold + alias lookup).
- Missing required headers raise an error.
- Files are written with UTF-8 encoding and Unix line endings.

## Validating pulled data

After a bundle is created, verify:

- **Row counts** — Compare `rows_written` in the manifest to expected counts from the source.
- **Header presence** — Each CSV header row should match the `required_headers` from the config.
- **Checksums** — Compute `sha256sum` on each CSV if you need integrity verification across transfers.
- **Null row filter** — The normalizer drops rows where all cells are blank; a row with only whitespace is treated as empty.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `HttpError 403` / `Request had insufficient authentication` | Google ADC not configured | See [docs/google-auth.md](google-auth.md) |
| `Worksheet '...' returned no rows` | Tab name mismatch or empty sheet | Verify `worksheet_title` in the source |
| `Coda API 401` | Missing or invalid `CODA_API_TOKEN` | See [docs/coda.md](coda.md) |
| `Coda API 429` | Rate-limited | Backoff is built-in; reduce parallel requests |
| `Config must include at least one tab entry` | Config JSON has empty or missing `tabs` array | Add tab entries to the config |
| `Header ... not found` | Required header name doesn't match the source | Check for typos, case, or use `aliases` |
| File not found for `source_csv` | Path is relative to config, not CWD | Place CSVs next to the config file |

### Auth

- Google Sheets: See [docs/google-auth.md](google-auth.md) for ADC setup and service account impersonation.
- Coda: See [docs/coda.md](coda.md) for token setup and doc URL resolution.
