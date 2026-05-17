# Troubleshooting FAQ

Common errors organised by category. Each entry follows: **Symptom** → **Cause** → **Fix**.

---

## Auth failures

### Google service account not found

**Symptom:** `HttpError 403` / `Request had insufficient authentication` when profiling Sheets or Drive.

**Cause:** Application Default Credentials (ADC) are not configured, or the service account lacks access to the target resource.

**Fix:** See [docs/google-auth.md](google-auth.md) for ADC setup and impersonation. Share each client Drive folder with the profiler service account email (Viewer role is sufficient).

---

### Double impersonation

**Symptom:** Nested impersonation errors or unexpected 403s.

**Cause:** `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` is set in the environment while ADC is already an impersonated service account (e.g. via `gcloud config set auth/impersonate_service_account`).

**Fix:** Use only one impersonation mechanism. Unset `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` when ADC is already impersonating.

---

### Coda token invalid

**Symptom:** `Coda API 401` or `ValueError: Coda API token required`.

**Cause:** `CODA_API_TOKEN` is unset, invalid, or expired.

**Fix:** Set `CODA_API_TOKEN` in `.env`. Generate a token at **Settings → API** in Coda. The token's visibility matches the Coda user — it cannot read docs the user cannot open. See [docs/coda.md](coda.md).

---

### Browser "app blocked" during Google login

**Symptom:** `gcloud auth application-default login` fails with an "app blocked" screen when using Drive/Sheets scopes.

**Cause:** The OAuth consent screen does not list the required scopes for the desktop credential flow.

**Fix:** Use `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` instead so your user credential only needs `cloud-platform` scope, or use Workload Identity Federation. See [docs/google-auth.md](google-auth.md#troubleshooting).

---

## Profiler failures

### Rate limited (429)

**Symptom:** `HTTP 429 Too Many Requests` from Google Sheets or Coda API calls.

**Cause:** Exceeding API rate limits for the provider.

**Fix:** Retry with backoff is built into the connector. For large Coda docs, run `profile_coda_doc --no-columns` first, then `profile_coda_table` per table. Reduce parallel requests. See [docs/coda.md](coda.md#rate-limits).

---

### Empty tab / worksheet returns no rows

**Symptom:** `Worksheet '...' returned no rows` or empty grid.

**Cause:** Tab name mismatch, empty sheet, or the token's user cannot see the rows in the UI.

**Fix:** Verify `worksheet_title` matches the source exactly (names are case-sensitive). Confirm rows exist and the authenticated user can view them. List available tables with `profile_coda_table` without `--table`.

---

### Drive folder permission denied

**Symptom:** Sheets or Drive API returns 403 when accessing a client folder.

**Cause:** The service account has not been granted access to the Drive folder.

**Fix:** Share the Drive folder with the profiler service account email (Viewer is enough). Propagation can take a few minutes.

---

### Coda doc not found / table not found

**Symptom:** Coda API returns `404` or the table is not listed.

**Cause:** Doc URL resolution failed, or the table name is misspelled.

**Fix:** Set `doc_id` in config if URL resolution via `GET /resolveBrowserLink` fails. Table names are case-sensitive — list available tables with `profile_coda_table` without `--table`. See [docs/coda.md](coda.md#doc-url-vs-doc-id).

---

## Import failures

### Constraint violations (unique_violation)

**Symptom:** `IntegrityError: UNIQUE constraint failed` or summary JSON shows `"signature": "unique_violation"`.

**Cause:** Source data contains duplicate rows that violate a unique constraint on the target model.

**Fix:** Deduplicate source data or adjust `unique_on` fields in the import config. Rerun with `--validate-only` to detect without committing. See `FAILURE_SIGNATURE_OWNERSHIP` in [`importer/errors.py`](../importer/errors.py).

---

### Type mismatches

**Symptom:** Parse errors on int/decimal/date columns — summary JSON shows `"signature": "type_mismatch"`.

**Cause:** Source cell values cannot be coerced to the target field type (e.g. `"N/A"` in a decimal column).

**Fix:** Correct source data types or add a `column_map` transform in the bundle config. Use `--validate-only` to enumerate all type errors before applying.

---

### FK lookups failing (stale_fk)

**Symptom:** Summary JSON shows `"signature": "stale_fk"` with count > 0.

**Cause:** Reference data rows are missing from the database — the FK lookup returned no match.

**Fix:** Seed missing reference rows and rerun `--validate-only`. Ensure reference data tiers are imported before dependent tiers. See [`importer/lookups.py`](../importer/lookups.py) and `FAILURE_SIGNATURE_OWNERSHIP` in [`importer/errors.py`](../importer/errors.py).

---

### Sample guard triggers (LIVE-12)

**Symptom:** `Refusing to load committed data/sample_import into default db.sqlite3 while FARM_SQLITE_PATH is unset (LIVE-12).`

**Cause:** Running `apply` mode on the sample import bundle targeting the default development SQLite database without `FARM_SQLITE_PATH` configured.

**Fix:** Use `--validate-only` to test without writing, set `FARM_SQLITE_PATH` to a throwaway SQLite path, or opt in with an explicit escape flag. See [`importer/sample_guard.py`](../importer/sample_guard.py).

---

### Summary JSON error codes

**Symptom:** Import completes but the summary JSON shows unexpected `failure_signatures`.

**Cause:** Row-level errors mapped to structured error codes in the summary artifact.

**Fix:** Inspect `failure_signatures[]` in the summary JSON. Each entry includes `signature`, `owner_area`, `severity`, `escalation_path`, and `recovery`. Common codes:

| Signature | Severity | Recovery |
|-----------|----------|----------|
| `missing_required` | medium | Populate required source fields and rerun `--validate-only` |
| `namespace_mismatch` | medium | Correct source value namespaces |
| `stale_fk` | high | Seed missing reference rows |
| `type_mismatch` | medium | Correct source data types |
| `unique_violation` | high | Deduplicate source data or adjust `unique_on` |
| `row_exception` | high | Review row-level errors in the summary artifact |
| `fatal_import_exception` | high | Review fatal error and importer logs before retry |
| `unknown` | high | Classify the error and add ownership mapping |

See [`importer/errors.py`](../importer/errors.py) for the full ownership mapping.

---

## Deployment failures

### Fly secrets missing

**Symptom:** `/healthz` fails after deploy; logs show `KeyError` or `ValueError` for missing environment variables.

**Cause:** Required secrets (`DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `LITESTREAM_*`, `SQLITE_PATH`) are not set on the Fly app.

**Fix:** Set secrets with `flyctl secrets set --app migration-workbench-production KEY=value`. Validate required secrets via `wb manifest lint`. See [docs/deployment.md](deployment.md#secrets).

---

### Health check timeouts

**Symptom:** Deploy succeeds but `/healthz` returns non-200 or times out.

**Cause:** Migration errors, missing secrets, Litestream restore failure, or the gunicorn process failed to start.

**Fix:** Run `flyctl logs --app migration-workbench-production` to inspect startup errors. Common causes:
- **Migration errors** — roll back the deploy, fix the migration, redeploy.
- **Empty volume with no replica** — bootstrap with `ALLOW_EMPTY_SQLITE=1`, then unset.
- **Litestream restore failure** — verify `LITESTREAM_*` credentials and endpoint.

---

### Litestream replication errors

**Symptom:** `InvalidAccessKeyId`, `AccessDenied`, or "no such bucket" in the logs.

**Cause:** `LITESTREAM_*` secrets are incorrect, or the endpoint URL does not match the bucket provider.

**Fix:** Verify `LITESTREAM_ACCESS_KEY_ID`, `LITESTREAM_SECRET_ACCESS_KEY`, `LITESTREAM_BUCKUE` (typos are common). For Tigris, ensure `LITESTREAM_ENDPOINT` is `https://fly.storage.tigris.dev`. Confirm `LITESTREAM_REPLICA_PREFIX` or ensure `SPACES_ENV` is set in `fly.toml` `[env]`.

---

### Docker build failures

**Symptom:** CI deploy fails at the build step with errors from `flyctl deploy --remote-only`.

**Cause:** Missing dependencies, Dockerfile syntax, or build context issues.

**Fix:** Build locally first: `docker build .` to reproduce the error. Verify `Dockerfile` and `.dockerignore` are up to date. Common fixes:
- Missing Python dependencies — update `requirements.txt` or `pyproject.toml`.
- Litestream binary download fails — check `scripts/entrypoint.sh` for the download URL.

---

### 400/403 Django errors on Fly

**Symptom:** Deployed app returns 400 or 403 on any request.

**Cause:** `DJANGO_ALLOWED_HOSTS` or `CSRF_TRUSTED_ORIGINS` do not match the `*.fly.dev` hostname.

**Fix:** Set both secrets to the app's Fly domain. See [docs/deployment.md](deployment.md#secrets).

---

### Deploy auth failure

**Symptom:** GitHub Actions deploy fails with "authentication required" from Fly.

**Cause:** `FLY_API_TOKEN` GitHub secret is expired or revoked.

**Fix:** Generate a new Fly API token and set it as `FLY_API_TOKEN` in the GitHub repository secrets.

---

## Bundle validation failures

### Missing required headers

**Symptom:** `Header ... not found` error when running `pull_bundle` or `snapshot_bundle`.

**Cause:** Required header name in the config does not match the source after casefold matching.

**Fix:** Check for typos and case differences. Use `aliases` in the tab config to map alternative header names to canonical names. See [docs/pull-bundle.md](pull-bundle.md#tab-level-keys-live-mode--google-sheets).

---

### Checksum mismatches

**Symptom:** CSV integrity check fails after bundle transfer.

**Cause:** File corruption during transfer or modification after bundle creation.

**Fix:** Re-run `pull_bundle` to regenerate the bundle. Verify sha256 checksums before and after transfer. The manifest records `rows_written` — compare against expected row counts.

---

### Manifest structure errors

**Symptom:** `manifest.json` is missing required fields or fails schema validation.

**Cause:** The bundle was created with an older tool version, or the file was hand-edited.

**Fix:** Regenerate the bundle with the current `pull_bundle` or `snapshot_bundle`. Do not hand-edit `manifest.json`. The schema version is `bundle-draft-1` (see [docs/pull-bundle.md](pull-bundle.md#the-manifestjson)).

---

### Config must include at least one tab entry

**Symptom:** `Config must include at least one tab entry` error.

**Cause:** The `--config` JSON has an empty or missing `tabs` array.

**Fix:** Add tab entries to the config file. Each tab requires at minimum `output_path` and `required_headers`.

---

### File not found for source_csv (offline)

**Symptom:** `FileNotFoundError` when running `snapshot_bundle`.

**Cause:** The `source_csv` path is relative to the config file, but the CSV is not present at the resolved path.

**Fix:** Place CSV files next to the config file, or use absolute paths. Snapshot bundle resolves `source_csv` relative to the config file's directory.

---

### Coda doc version / 400 on latest

**Symptom:** HTTP 400 when `CODA_DOC_VERSION_LATEST=1` is set.

**Cause:** The snapshot for "latest" doc version is not ready yet.

**Fix:** Unset `CODA_DOC_VERSION_LATEST` and retry. See [docs/coda.md](coda.md#recommended-sequence) and the Coda API "Consistency" documentation.
