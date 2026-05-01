# Connectors

Provider adapters between live sources and the normalized bundle pipeline.

## Purpose

`connectors` implements **Google Sheets** and **Coda** access: HTTP sessions, auth, ID resolution, row flattening, and adapter entry points used by `pull_bundle` and profilers.

## Public surface (by provider)

### Google Sheets

- `connectors/google_sheets.py` — sheet/grid access.
- `connectors/google_provider.py` — routing and `google.auth.default()`.

**Configuration:** `GOOGLE_APPLICATION_CREDENTIALS` or Application Default Credentials. Prefer ADC + service-account impersonation for local and shared-folder access; see [docs/google-auth.md](../docs/google-auth.md).

### Coda

- `connectors/coda.py` — `CodaAdapter` for `pull_bundle` and importer flows.
- `connectors/coda_source.py` — session, pagination, `resolveBrowserLink`, doc id parsing, row grid flattening, retries.

**Configuration:** `CODA_API_TOKEN` (bearer; read access to the doc). Optional: `api_token` in live JSON; `CODA_DOC_VERSION_LATEST=1` for consistency header. Per-tab: `worksheet_title` (table or view name) or `table_id`, `output_path`, `required_headers`; optional `max_rows`, `value_format` (`rich` / `simple`).

**Profiling / formulas:** Coda returns column-level `formulaText`. See [docs/coda.md](../docs/coda.md).

## Pointers

- [README](../README.md) — project overview
- [profiler/README.md](../profiler/README.md) — profiling commands
- Live config examples: [docs/examples/](../docs/examples/)
