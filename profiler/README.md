# Profiler

Read-only management commands that inspect Google Sheets, Drive, and Coda **before** bundle design. Outputs JSON/Markdown artifacts — **no Django model mutations**.

## Purpose

Discover structure, formulas, and corpus-scale signals so product repos can define bundle YAML and importers against reality.

## Google Sheets / Drive

| Command | Role |
|---------|------|
| `profile_preflight` | Folder / access smoke |
| `profile_drive_folder` | Folder tree snapshot |
| `profile_tab` | Single spreadsheet tab deep profile |
| `scan_formula_patterns` | Regex inventory of formula usage |
| `profile_cohort_corpus` | Multi-workbook Drive-folder pipeline |

Auth: see [docs/google-auth.md](../docs/google-auth.md).

## Coda

| Command | Role |
|---------|------|
| `profile_coda_preflight` | Token / doc smoke (`--smoke` for CI) |
| `profile_coda_doc` | Doc inventory |
| `profile_coda_table` | Per-table deep profile |
| `scan_coda_formula_columns` | Column-level formula scan |
| `profile_coda_corpus` | Multi-doc corpus pipeline |
| `profile_coda_canvas` | Page text / markdown export |

See [docs/coda.md](../docs/coda.md).

## Artifacts

Typically under `build/` (this repo) or product-owned `data/profile_snapshots/`. Coda corpus tooling lives in `profiler/tools/coda_corpus.py`; Sheets cohort tooling in `profiler/tools/cohort_corpus.py`. Shared Coda helpers: [`connectors/coda_source.py`](../connectors/coda_source.py).

## Configuration / env

- Sheets: ADC / impersonation per [docs/google-auth.md](../docs/google-auth.md).
- Coda: `CODA_API_TOKEN`; corpus Makefile targets may use `CODA_CORPUS_CONFIG`, `CODA_CORPUS_OUT_DIR`.

## Pointers

- [README](../README.md)
- [connectors/README.md](../connectors/README.md)
- Example configs: [example_data/](../example_data/), [docs/examples/](../docs/examples/)
