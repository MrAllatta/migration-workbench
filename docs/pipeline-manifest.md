# Pipeline Manifest Reference

> **Artifact:** `build/pipeline-manifest.yaml`
> **Generator:** `python manage.py generate_pipeline_manifest`
> **Version:** `1.0`

A pipeline manifest is a machine-generated execution plan that bridges a schema
contract and corpus configuration into per-year, per-table pull/import
instructions. It is **never hand-edited** and can be regenerated at any time.

## Top-Level Structure

```yaml
version: "1.0"
generated_from:
  contract: schema-contract.yaml
  corpus_config: cohort_corpus.json
source:
  provider: google_sheets
  corpus_years: [2025, 2026]
tables:
  - model: crop_plan_entry
    bundle_worksheet_title: Crop Planner
    output_pattern: "{year}/crop_plan_entry.csv"
    default_values:
      source_bundle_year: "{year}"
    required_headers:
      - Block
      - Crop
    years:
      - year: 2025
        spreadsheet_id: 1ABC...
        worksheet_title: Crop Planner
      - year: 2026
        spreadsheet_id: 1DEF...
        worksheet_title: Crop Planner
```

## Keys

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `version` | yes | string | Manifest format version (`1.0`) |
| `generated_from` | yes | object | Source file references |
| `source` | yes | object | Provider metadata |
| `tables` | yes | array | One entry per contract table |

### Table Entry Keys

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `model` | yes | string | Lowercase snake_case model name |
| `bundle_worksheet_title` | yes | string | Spreadsheet tab title for bundle output |
| `output_pattern` | yes | string | CSV output path template (`{year}` placeholder) |
| `default_values` | yes | object | Static column values per row (supports `{year}`) |
| `required_headers` | yes | array | Columns that must exist in source data |
| `years` | yes | array | Per-year spreadsheet resolution |

## Generation

```bash
# Basic usage
python manage.py generate_pipeline_manifest \
  --contract build/schema-contract.yaml \
  --corpus-config config/cohort_corpus.json \
  --out build/pipeline_manifest.yaml

# With corpus index files for spreadsheet ID resolution
python manage.py generate_pipeline_manifest \
  --contract build/schema-contract.yaml \
  --corpus-config config/cohort_corpus.json \
  --corpus-dir config/ \
  --out build/pipeline_manifest.yaml

# Diff against existing (safe for CI)
python manage.py generate_pipeline_manifest \
  --contract build/schema-contract.yaml \
  --corpus-config config/cohort_corpus.json \
  --diff

# Makefile target
CORPUS_CONFIG=config/cohort_corpus.json make generate-pipeline-manifest
PIPELINE_MANIFEST_OUT=build/pipeline_manifest.yaml CORPUS_CONFIG=config/cohort_corpus.json make generate-pipeline-manifest
```
