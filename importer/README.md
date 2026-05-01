# Importer

Django management command chassis for **preflight** (validate-only) and **apply** imports from normalized bundles, with deterministic **summary JSON** and structured row-level failures.

## Purpose

Subclass `importer.base.BaseImportCommand` in product repos; keep domain logic in bundle YAML and thin command classes — not in workbench internals unless fixing chassis bugs.

## Authoring

1. Subclass **`BaseImportCommand`**.
2. Implement **`_run_import_pipeline(self)`**.
3. Use **`self.tier(name, callback)`** for ordered logging bands.

**Helpers:** `record_row_error`, `record_missing_required`, `record_stale_fk`, `_resolve_fk_by_text`, `_int`, `_dec`, date/split helpers.

**Modes:**

| Mode | Behavior |
|------|----------|
| `--validate-only` / `--preflight` | Full path under rollback transaction |
| `--dry-run` | Parse-only |
| (default) | Apply writes |

**Summary artifact:** `--summary-json /path/to/file.json` — schema version `1.0`; per-model outcomes, row errors, failure signatures, escalation summary.

## Bundle contract (normalized directory)

Emitted by the profiler / pull pipeline:

- `manifest.json`
- `reference/*.csv`
- `year_YYYY/*.csv` (optional)

**Header detection:** scan first `max_scan_rows` rows (default 200); first row containing all `required_headers`; fall back to `anchor_token` or `header_row_index`. Normalize: trim, collapse spaces, casefold, aliases.

**Tab config fields** (bundle YAML): `required_headers`, `aliases`, `output_headers`, `column_map`, `default_values`, `row_transforms`, `source_regions`, `stop_on_blank_in`, `grid_unpivot`, `append_without_header`.

## Design discipline

Follow [docs/schema-design-loop.md](../docs/schema-design-loop.md): prefer bundle + contract changes over patching shared importer internals.

## Pointers

- [README](../README.md)
- [workbook/README.md](../workbook/README.md) — upstream schema-contract YAML
