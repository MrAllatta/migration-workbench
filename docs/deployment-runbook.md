# Deployment Runbook — `migration-workbench`

> **Canonical identifiers used throughout this document**
>
> | Item | Value |
> |------|-------|
> | CI workflow display name | `CI` (`.github/workflows/ci.yml`) |
> | Deploy workflow display name | `Deploy` (`.github/workflows/deploy.yml`) |
> | GitHub Actions secret | `FLY_API_TOKEN` |
> | Production Fly app | `migration-workbench-production` |
> | Preview Fly app | `migration-workbench-preview` |
> | Health check path | `/healthz` |

---

## 1. One-Time Bootstrap (first deploy)

Perform these steps once per environment before the `Deploy` workflow can succeed.

### 1.1 Create Fly apps

```bash
flyctl apps create migration-workbench-production
flyctl apps create migration-workbench-preview
```

### 1.2 Create persistent volumes

```bash
# Production — 5 GB in ewr (primary_region from deploy/spaces.yml)
flyctl volumes create data --app migration-workbench-production --size 5 --region ewr

# Preview
flyctl volumes create data --app migration-workbench-preview --size 5 --region ewr
```

### 1.3 Set required secrets

All secrets listed under `spaces.migration-workbench.secrets.required` in `deploy/spaces.yml`
must be set before the first deploy.  The only credential stored in GitHub Actions is
`FLY_API_TOKEN`; all others live exclusively in the Fly secrets store.

```bash
# Set for production (repeat with --app migration-workbench-preview for preview)
flyctl secrets set \
  DJANGO_SECRET_KEY="…"          \
  DJANGO_ALLOWED_HOSTS="…"       \
  CSRF_TRUSTED_ORIGINS="…"       \
  SQLITE_PATH="/data/db.sqlite3" \
  LITESTREAM_ACCESS_KEY_ID="…"   \
  LITESTREAM_SECRET_ACCESS_KEY="…" \
  LITESTREAM_BUCKET="…"          \
  --app migration-workbench-production
```

### 1.4 Add `FLY_API_TOKEN` to GitHub Actions

In the repository **Settings → Secrets and variables → Actions**, add a repository
secret named exactly `FLY_API_TOKEN`.  This is the only secret the `Deploy` workflow
reads from GitHub.

### 1.5 First deploy

Push a commit to `main`.  The `CI` workflow runs first; on success it triggers the
`Deploy` workflow automatically.  To deploy manually before that pipeline is wired:

```bash
flyctl deploy --config fly.toml --remote-only --app migration-workbench-production
```

Verify:

```bash
curl -fsS https://migration-workbench-production.fly.dev/healthz
```

---

## 2. Routine Operations

### 2.1 Automated deploy (normal path)

1. Push to `main` (or `preview/<branch>`).
2. `CI` chassis-gate runs; on success `Deploy` is triggered automatically via
   `workflow_run`.
3. `Deploy` resolves the Fly app name from the branch:
   - `main` → `migration-workbench-production` using `fly.toml`
   - `preview/*` → `migration-workbench-preview` using `fly.preview.toml`
4. Manifest lint runs, then `flyctl deploy --remote-only`, then `/healthz` smoke check.

Branches that are neither `main` nor `preview/*` are silently skipped by `Deploy`.

### 2.2 Check deploy status

```bash
flyctl releases list --app migration-workbench-production
```

### 2.3 View running machines

```bash
flyctl machines list --app migration-workbench-production
```

---

## 3. Rollback

```bash
# List releases to find the prior image
flyctl releases list --app migration-workbench-production

# Re-deploy the last known-good image
flyctl deploy --image <registry.fly.io/migration-workbench-production:prior-deployment-id> \
  --config fly.toml --app migration-workbench-production

# Verify
curl -fsS https://migration-workbench-production.fly.dev/healthz
```

Target rollback time: < 5 minutes.

---

## 4. Failure Modes

### 4.1 `/healthz` 503 after deploy

- SSH into the machine: `flyctl ssh console --app migration-workbench-production`
- Check logs: `flyctl logs --app migration-workbench-production`
- Common causes: migration failure in entrypoint, missing secret, Litestream restore timeout.
- If unrecoverable: rollback via Section 3.

### 4.2 Empty replica on first boot

If `LITESTREAM_BUCKET` is set but the replica does not yet exist, `litestream restore`
exits non-zero.  The entrypoint propagates this exit and the Machine restarts.  Bootstrap
by running an initial `litestream replicate` from a local DB or by starting without
`LITESTREAM_BUCKET` for the very first commit.

### 4.3 Hosts / CSRF misconfiguration

Symptoms: all POST requests return 403, or app returns 400 on every request.
Fix: update `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` secrets in Fly, then redeploy.

### 4.4 `FLY_API_TOKEN` expired or missing

The `Deploy` workflow fails at the `flyctl deploy` step with an authentication error.
Rotate the token in Fly, update the `FLY_API_TOKEN` repository secret, and re-run the
workflow from the GitHub Actions UI.

---

## 5. Secret Rotation

Rotate Fly app secrets every 90 days.  `FLY_API_TOKEN` in GitHub Actions follows the
same cadence.  After rotation, trigger a deploy to confirm the new secrets are accepted.

---

## 6. Phase B / C Notes (not yet implemented)

- **Phase B**: preflight gates (volume exists, all required secrets present, replica
  reachable) will be added as a step in `Deploy` before `flyctl deploy`.
- **Phase C**: `flyctl deploy` will be replaced by `wb deploy --execute` once the CLI
  execute path is implemented.  The workflow job id (`deploy`) and secret name
  (`FLY_API_TOKEN`) will remain unchanged.
