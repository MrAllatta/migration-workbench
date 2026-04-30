# Deployment Runbook — `migration-workbench`

## Purpose and scope

This document is the single operator entrypoint for the `migration-workbench` application
running on Fly.io.  It covers first-time Fly bootstrap, routine deploy operations, rollback,
and failure-mode diagnosis.  Procedures here are scoped exclusively to the
`migration-workbench` space; other spaces managed by `deploy/spaces.yml` (`farm`,
`vizcarra-guitars`, `jewelry`) have separate runbooks and are referenced only by name.

---

## Canonical identifiers

Every example command in this document uses these strings verbatim.  Do not substitute
paraphrases, short-forms, or space aliases.

| Concept | Value |
|---------|-------|
| Fly app — production | `migration-workbench-production` |
| Fly app — preview | `migration-workbench-preview` |
| Fly region | `ewr` |
| Persistent volume name | `data` |
| Volume mount inside Machine | `/data` |
| SQLite file path | `/data/db.sqlite3` |
| HTTP health check path | `/healthz` |
| Production URL | `https://migration-workbench-production.fly.dev` |
| Preview URL | `https://migration-workbench-preview.fly.dev` |
| Git branch → production | `main` |
| Git branches → preview | `preview/*` |
| CI workflow file | `.github/workflows/ci.yml` (display name `CI`) |
| Deploy workflow file | `.github/workflows/deploy.yml` (display name `Deploy`) |
| GitHub Actions secret | `FLY_API_TOKEN` |

**APP_NAME** in command placeholders below is always one of the two Fly app values above.

---

## 1. First-time Fly bootstrap

Perform all steps in order, once per environment, before the `Deploy` workflow can succeed.

### 1.1 Create Fly apps

```bash
flyctl apps create migration-workbench-production
flyctl apps create migration-workbench-preview
```

### 1.2 Create persistent volumes

Volume name `data` and region `ewr` are fixed by `deploy/spaces.yml`
(`provider.primary_region`, `storage.sqlite_path` prefix).  Size 5 GB matches the `small`
profile (`volume_gb: 5`).

```bash
# Production
flyctl volumes create data \
  --app migration-workbench-production \
  --region ewr \
  --size 5

# Preview
flyctl volumes create data \
  --app migration-workbench-preview \
  --region ewr \
  --size 5
```

### 1.3 Attach volume / mount

Once `fly.toml` (production) and `fly.preview.toml` (preview) exist, each must contain a
`[mounts]` section that binds the volume to `/data`:

```toml
[mounts]
source      = "data"
destination = "/data"
```

`flyctl deploy` reads this config automatically; no extra `flyctl volumes attach` command is
needed.

### 1.4 Set required secrets

`deploy/spaces.yml` → `spaces.migration-workbench.secrets.required` lists every Fly secret.
`SQLITE_PATH` is an environment variable (not a Fly secret) and must also be set.

```bash
# Set for production; repeat with --app migration-workbench-preview for preview.
flyctl secrets set \
  DJANGO_SECRET_KEY="…"               \
  DJANGO_ALLOWED_HOSTS="…"            \
  CSRF_TRUSTED_ORIGINS="…"            \
  LITESTREAM_ACCESS_KEY_ID="…"        \
  LITESTREAM_SECRET_ACCESS_KEY="…"    \
  LITESTREAM_BUCKET="…"               \
  --app migration-workbench-production

# SQLITE_PATH is an env var (deploy/spaces.yml → environment.required).
# Set it the same way via flyctl secrets so it is available at runtime:
flyctl secrets set \
  SQLITE_PATH="/data/db.sqlite3" \
  --app migration-workbench-production
```

Optional secrets read by `scripts/entrypoint.sh`:

| Variable | Purpose |
|----------|---------|
| `LITESTREAM_ENDPOINT` | S3-compatible endpoint URL (Spaces / R2 / MinIO); omit for AWS S3. |
| `LITESTREAM_REPLICA_PREFIX` | Object-key prefix inside the bucket.  If unset, the entrypoint derives it from `SPACES_ENV` or `FLY_ENV`; if none are set, startup fails. |

Verify the complete secret set matches the manifest before deploying:

```bash
python -m deployment.wb_cli --manifest deploy/spaces.yml manifest lint
```

### 1.5 Add `FLY_API_TOKEN` to GitHub Actions

In the repository **Settings → Secrets and variables → Actions**, add a repository secret
named exactly `FLY_API_TOKEN`.  This is the only deploy credential stored in GitHub; all
app-specific secrets live in the Fly secrets store.

### 1.6 TLS / certificates

Fly provisions a `*.fly.dev` TLS certificate automatically for both app names.  To attach a
custom domain, run:

```bash
flyctl certs add <your-domain> --app migration-workbench-production
```

No additional configuration is required for the default `fly.dev` hostnames.

### 1.7 First deploy

Push a commit to `main`.  The `CI` workflow runs first; on success it triggers the `Deploy`
workflow automatically via `workflow_run`.

To deploy manually before the CI pipeline is wired:

```bash
flyctl deploy \
  --config fly.toml \
  --remote-only \
  --app migration-workbench-production
```

Verify the application started successfully:

```bash
curl -fsS https://migration-workbench-production.fly.dev/healthz
```

Expected: HTTP 200.

---

## 2. Routine operations

### 2.1 Automated deploy path

1. Push to `main` or `preview/<branch-name>`.
2. The `CI` workflow runs; on success it triggers the `Deploy` workflow
   (`.github/workflows/deploy.yml`) via `workflow_run`.
3. `Deploy` resolves the Fly app name from the triggering branch:
   - `main` → `migration-workbench-production` (config: `fly.toml`)
   - `preview/*` → `migration-workbench-preview` (config: `fly.preview.toml`)
4. Steps: manifest lint → `flyctl deploy --remote-only` → `/healthz` smoke test
   (12 retries × 10 s = 2-minute window).

Branches that are neither `main` nor `preview/*` are silently skipped; the `Deploy` job does
not run.

### 2.2 Check release history

```bash
flyctl releases list --app migration-workbench-production
flyctl releases list --app migration-workbench-preview
```

### 2.3 View running Machines

```bash
flyctl machines list --app migration-workbench-production
flyctl machines list --app migration-workbench-preview
```

---

## 3. Rollback

Target recovery time: < 5 minutes.

```bash
# Step 1: list releases to identify the prior known-good image.
flyctl releases list --app migration-workbench-production

# Step 2: redeploy that image.
#   <digest_or_ref> is the full image reference shown in the releases list,
#   e.g. registry.fly.io/migration-workbench-production:deployment-01ABCDEF…
flyctl deploy \
  --image <digest_or_ref> \
  --config fly.toml \
  --app migration-workbench-production

# Step 3: verify.
curl -fsS https://migration-workbench-production.fly.dev/healthz
```

For preview:

```bash
flyctl releases list --app migration-workbench-preview

flyctl deploy \
  --image <digest_or_ref> \
  --config fly.preview.toml \
  --app migration-workbench-preview

curl -fsS https://migration-workbench-preview.fly.dev/healthz
```

---

## 4. Failure modes

### 4.1 `/healthz` returns 503 or never becomes healthy after deploy

**Symptom:** smoke-test step in `Deploy` workflow exhausts retries and fails.

**Check:**

```bash
flyctl logs --app migration-workbench-production
flyctl ssh console --app migration-workbench-production
```

**Common causes:** migration failure in `scripts/entrypoint.sh`, missing Fly secret, or
Litestream restore timeout (see §4.2).

**Mitigate:** roll back via Section 3 while diagnosing.

---

### 4.2 Litestream replica empty or misconfigured

**Symptom:** Machine restarts in a loop; logs show `litestream restore` failing or the
`entrypoint` printing `set LITESTREAM_REPLICA_PREFIX or SPACES_ENV or FLY_ENV`.

**Check:** confirm all three Litestream secrets are set and non-empty:

```bash
flyctl secrets list --app migration-workbench-production
# Expect: LITESTREAM_ACCESS_KEY_ID, LITESTREAM_SECRET_ACCESS_KEY, LITESTREAM_BUCKET present.
```

Confirm the replica prefix: `scripts/entrypoint.sh` derives the S3 path as
`migration-workbench/<env>` from `LITESTREAM_REPLICA_PREFIX` (or falls back to `SPACES_ENV`
→ `FLY_ENV`).  If none of these are set, startup fails intentionally to prevent writing to
the bucket root.

**Mitigate:**

- If the replica does not yet exist (first boot): set `ALLOW_EMPTY_SQLITE=1` temporarily to
  allow creation of a fresh database, then remove it once replication is confirmed running.
- If credentials are wrong: correct `LITESTREAM_ACCESS_KEY_ID` / `LITESTREAM_SECRET_ACCESS_KEY`
  / `LITESTREAM_BUCKET` via `flyctl secrets set`, then redeploy.

---

### 4.3 Migrations failed on boot

**Symptom:** Machine exits non-zero; logs show `python manage.py migrate` traceback before
Gunicorn starts.

**Check:**

```bash
flyctl logs --app migration-workbench-production
```

Look for Django migration errors in the output.  The entrypoint runs `manage.py migrate
--noinput` synchronously before Gunicorn starts (`scripts/entrypoint.sh`).

**Mitigate:** roll back to the prior release (Section 3), fix the migration, and redeploy.

---

### 4.4 Hosts / CSRF misconfiguration

**Symptom:** every request returns 400 (`DJANGO_ALLOWED_HOSTS` mismatch) or every POST
returns 403 (`CSRF_TRUSTED_ORIGINS` mismatch).

**Check:** confirm the Fly secrets match the actual hostname:

```bash
# DJANGO_ALLOWED_HOSTS must include migration-workbench-production.fly.dev
# CSRF_TRUSTED_ORIGINS must include https://migration-workbench-production.fly.dev
flyctl secrets list --app migration-workbench-production
```

**Mitigate:**

```bash
flyctl secrets set \
  DJANGO_ALLOWED_HOSTS="migration-workbench-production.fly.dev" \
  CSRF_TRUSTED_ORIGINS="https://migration-workbench-production.fly.dev" \
  --app migration-workbench-production
# A new Machine release is triggered automatically; no manual redeploy needed.
```

---

### 4.5 `FLY_API_TOKEN` expired or missing

**Symptom:** `Deploy` workflow fails at the `flyctl deploy` step with an authentication
error.

**Mitigate:** generate a new token in the Fly dashboard, update the `FLY_API_TOKEN`
repository secret in GitHub Actions **Settings → Secrets**, then re-run the failed workflow
from the GitHub Actions UI.

---

## 5. Secret rotation

Rotate Fly app secrets (`DJANGO_SECRET_KEY`, Litestream credentials) and `FLY_API_TOKEN` on
a regular cadence (recommended: every 90 days).  After rotating any secret, trigger a
redeploy to confirm the new values are accepted:

```bash
# Push an empty commit to force a deploy, or re-run the latest Deploy workflow run.
git commit --allow-empty -m "chore: verify rotated secrets"
git push origin main
```

---

## 6. Related references

- `deploy/spaces.yml` — canonical manifest; source of truth for app names, regions, secret
  lists, and volume sizes.  Run `python -m deployment.wb_cli --manifest deploy/spaces.yml manifest lint`
  to validate.
- `deployment/wb_cli.py` — CLI entry point; subcommand `manifest lint` validates schema
  drift.
- `.github/workflows/deploy.yml` — deploy workflow; reads branch name to resolve app name
  and Fly config file.
- `.github/workflows/ci.yml` — CI workflow; `Deploy` triggers only after `CI` succeeds.
- `scripts/entrypoint.sh` — container entrypoint; handles Litestream restore, Django
  migrations, and Gunicorn startup.
- `Dockerfile` — image build; static assets collected at build time, `/opt/venv` houses the
  virtualenv.
- `fly.toml` / `fly.preview.toml` — Fly configuration for production and preview; must
  include matching `[mounts]` and `[[services]]` for the volume and health check path
  defined above.
