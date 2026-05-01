# Deployment — migration-workbench on Fly.io

Single operator entrypoint for hosting **this repository’s** Django app on Fly.io with SQLite, Litestream replication to object storage, and GitHub Actions deploys. Other spaces in [`deploy/spaces.yml`](../deploy/spaces.yml) (`farm`, `vizcarra-guitars`, `jewelry`) follow the same manifest pattern but have their own operator docs in those repos.

---

## Why Fly + SQLite + Litestream

- **Platform:** Fly.io primary; VPS adapter deferred until a concrete requirement appears.
- **Data:** SQLite-first, WAL mode, single-tenant / low-concurrency workloads.
- **Durability:** Litestream replicates to **Tigris** (Fly-native S3-compatible) or any S3-compatible bucket (AWS S3, R2, Spaces, …).
- **Secrets:** Values live in Fly secrets and GitHub Actions secrets — never in tracked files.
- **Manifest:** [`deploy/spaces.yml`](../deploy/spaces.yml) declares app names, regions, profiles, required secrets, and replication templates per space.

### Profiles (logical)

| Profile | CPU | RAM | Volume |
|---------|-----|-----|--------|
| tiny | 1 shared | 256 MB | 5 GB |
| small | 1 shared | 512 MB | 5 GB |
| small-plus | 1 shared | 512 MB | 10 GB |

The `migration-workbench` space uses **small** (`migration-workbench` in the manifest).

### SQLite durability targets

- Continuous WAL replication via Litestream.
- Schema-affecting releases should use a pre-release backup checkpoint when the control plane supports it (see roadmap).
- Restore flow: stop writes → restore → integrity check → resume traffic (RPO minutes; RTO under ~30 minutes with operator guidance).

---

## Canonical identifiers

Use these strings verbatim in commands.

| Concept | Value |
|---------|-------|
| Fly app — production | `migration-workbench-production` |
| Fly app — preview | `migration-workbench-preview` |
| Region | `ewr` |
| Volume name | `data` |
| Mount path | `/data` |
| SQLite file | `/data/db.sqlite3` |
| Health check | `/healthz` |
| Production URL | `https://migration-workbench-production.fly.dev` |
| Preview URL | `https://migration-workbench-preview.fly.dev` |
| Branch → production | `main` |
| Branches → preview | `preview/*` |
| CI workflow | `.github/workflows/ci.yml` (name: `CI`) |
| Deploy workflow | `.github/workflows/deploy.yml` |
| GitHub secret for Fly | `FLY_API_TOKEN` |

Fly configs: [`fly.toml`](../fly.toml), [`fly.preview.toml`](../fly.preview.toml). `[env]` sets `SPACES_ENV` (`production` vs `preview`) so Litestream writes **`migration-workbench/<env>/`** inside the bucket when `LITESTREAM_REPLICA_PREFIX` is unset.

---

## Tigris storage (recommended on Fly)

Provision an S3-compatible bucket tied to Fly:

```bash
flyctl storage create -a migration-workbench-production -n <bucket-name>
```

Fly may inject `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_ENDPOINT_URL_S3`, `BUCKET_NAME`. The container entrypoint expects **Litestream-prefixed** variables; map them explicitly:

```bash
flyctl secrets set \
  LITESTREAM_ACCESS_KEY_ID="..." \
  LITESTREAM_SECRET_ACCESS_KEY="..." \
  LITESTREAM_BUCKET="<bucket-name>" \
  LITESTREAM_ENDPOINT="https://fly.storage.tigris.dev" \
  --app migration-workbench-production
```

Repeat for **`migration-workbench-preview`** with the **same** bucket credentials if you use one shared bucket (preview and production differ by prefix via `SPACES_ENV`, not by bucket name).

If `fly storage create` already set duplicate `AWS_*` secrets on production only, that is optional noise; Litestream reads `LITESTREAM_*`.

---

## First-time Fly bootstrap

Do these once per app before automated Deploy succeeds.

### 1. Create apps

```bash
flyctl apps create migration-workbench-production
flyctl apps create migration-workbench-preview
```

### 2. Create volumes (5 GB, `ewr`)

```bash
flyctl volumes create data --app migration-workbench-production --region ewr --size 5
flyctl volumes create data --app migration-workbench-preview --region ewr --size 5
```

### 3. Mounts

[`fly.toml`](../fly.toml) and [`fly.preview.toml`](../fly.preview.toml) include `[mounts]` → `/data`. No separate `fly volumes attach` needed.

### 4. Secrets

Required per [`deploy/spaces.yml`](../deploy/spaces.yml) for `migration-workbench`:

- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS` (per app hostname)
- `CSRF_TRUSTED_ORIGINS` (HTTPS origins per app)
- `LITESTREAM_ACCESS_KEY_ID`, `LITESTREAM_SECRET_ACCESS_KEY`, `LITESTREAM_BUCKET`
- `SQLITE_PATH` — typically `/data/db.sqlite3`

Optional for non-AWS endpoints:

- `LITESTREAM_ENDPOINT`
- `LITESTREAM_REPLICA_PREFIX` — if unset, derived from `SPACES_ENV` in Fly env (set in `fly.toml` / `fly.preview.toml`).

`DJANGO_PRODUCTION` / `DJANGO_DEBUG` are set in Fly `[env]` in the checked-in TOML files.

Bootstrap without an existing replica: temporarily `ALLOW_EMPTY_SQLITE=1`, deploy once, verify Litestream, then unset.

Validate manifest locally:

```bash
python -m deployment.wb_cli --manifest deploy/spaces.yml --json manifest lint
# or: make manifest-lint
```

### 5. GitHub Actions

Repository secret **`FLY_API_TOKEN`** — only GitHub-side credential; app secrets stay on Fly.

### 6. TLS

`*.fly.dev` certificates are automatic. Custom domain: `flyctl certs add <domain> --app migration-workbench-production`.

### 7. First deploy

After CI on `main`, Deploy runs automatically. Manual:

```bash
flyctl deploy --config fly.toml --remote-only --app migration-workbench-production
curl -fsS https://migration-workbench-production.fly.dev/healthz
```

---

## Routine operations

1. Push to `main` or `preview/<name>`.
2. CI succeeds → Deploy runs (`workflow_run`).
3. Deploy picks branch: `main` → `fly.toml` / production app; `preview/*` → `fly.preview.toml` / preview app.
4. Steps: manifest lint → `flyctl deploy --remote-only` → `/healthz` smoke (bounded retries).

Other branches: Deploy job skipped.

```bash
flyctl releases list --app migration-workbench-production
flyctl machines list --app migration-workbench-production
```

---

## Rollback

```bash
flyctl releases list --app migration-workbench-production
flyctl deploy --image <digest_or_ref> --config fly.toml --app migration-workbench-production
curl -fsS https://migration-workbench-production.fly.dev/healthz
```

Use `fly.preview.toml` and the preview app for preview rollback.

---

## Failure modes

| Symptom | Check |
|---------|--------|
| `/healthz` fails after deploy | `flyctl logs`; migration errors, missing secrets, Litestream restore |
| `InvalidAccessKeyId` / Litestream errors | Fix `LITESTREAM_*`; confirm endpoint for Tigris |
| `SPACES_ENV` / prefix errors | Ensure `[env]` in fly TOMLs or set `LITESTREAM_REPLICA_PREFIX` |
| Migrate fails on boot | Logs; roll back; fix migration |
| 400/403 Django | `DJANGO_ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` match `*.fly.dev` |
| Deploy auth failure | Rotate `FLY_API_TOKEN` in GitHub |

Secret rotation (e.g. every 90 days): rotate Fly secrets and token, then empty commit or re-run Deploy.

---

## Manifest contract

[`deploy/spaces.yml`](../deploy/spaces.yml) declares per space:

- Identity, environments (`preview` / `production`), region, profile
- Runtime: internal port, processes, health path
- Build: Dockerfile / context
- Storage paths, volume profile
- Replication and backup metadata
- Required secret **names** (not values)

Lint:

```bash
wb manifest lint --manifest deploy/spaces.yml
```

---

## Deploy lifecycle (target)

1. Resolve config from manifest  
2. Preflight (secrets, volume, Litestream)  
3. Build image  
4. Pre-release checkpoint when schema changes  
5. Release / migrations (here: entrypoint on boot; manifest `release` may be `true`)  
6. Start machines  
7. Health gate  
8. Record release metadata  

---

## Control plane roadmap (`wb` CLI)

**Today (implemented)**

- `wb manifest lint` — validate `deploy/spaces.yml`
- `wb deploy <space> --env <preview|production> --dry-run` — plan without provider mutation

**Target commands** (Fly-first; incremental)

| Command | Goal |
|---------|------|
| `wb deploy` | Real deploy (replacing raw `flyctl` for operators) |
| `wb status` | App, release, health, volume |
| `wb logs` | Stream logs with release context |
| `wb backup create` / `wb backup restore` | SQLite backup drill |
| `wb rollback` | Healthy rollback |
| `wb secrets apply` / `wb secrets rotate` | Sync secrets from manifest |

Acceptance-style criteria (from earlier sprint docs): structured `--json`, deterministic errors, dry-run release ids — tracked as implementation milestones, not blockers for manual Fly operation.

**Phase 2:** Extract a provider interface after a second space is stable on Fly.

---

## Observability (target)

Per release: git SHA, actor, timestamp, health, backup/replication signals — surfaced via `wb` when implemented.

---

## Related files

| File | Role |
|------|------|
| [`deploy/spaces.yml`](../deploy/spaces.yml) | Manifest |
| [`deployment/wb_cli.py`](../deployment/wb_cli.py) | `wb` entrypoint |
| [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) | Automated deploy |
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | CI gate |
| [`scripts/entrypoint.sh`](../scripts/entrypoint.sh) | Litestream, migrate, Gunicorn |
| [`Dockerfile`](../Dockerfile) | Image |
