# Deployment

Validates per-space deployment manifests and exposes the **`wb`** CLI for lint and deploy **dry-run**. Release metadata hooks live here for future provider-backed deploys.

## Purpose

Single manifest ([`deploy/spaces.yml`](../deploy/spaces.yml)) describes Fly apps, regions, profiles, secrets **names**, SQLite paths, Litestream settings, and environments (`preview` / `production`).

## Commands

```bash
python -m deployment.wb_cli --manifest deploy/spaces.yml manifest lint
# Installed entry point:
wb manifest lint --manifest deploy/spaces.yml
wb deploy <space> --env <preview|production> --dry-run
```

**Today:** `manifest lint` is fully supported; **`wb deploy` mutating Fly is not** — operators use `flyctl deploy` plus [.github/workflows/deploy.yml](../.github/workflows/deploy.yml). Roadmap: real `wb deploy`, status, logs, backup/restore — see [docs/deployment.md](../docs/deployment.md).

## Manifest lint

Validates structure, profiles (`tiny` / `small` / `small-plus`), required keys per space, and replication metadata. Use in CI and before manual deploys.

## Pointers

- [docs/deployment.md](../docs/deployment.md) — Fly bootstrap, Tigris/Litestream, CI/CD
- [wb_cli.py](wb_cli.py) — CLI entry
