# Deployment Spec v0.2

This document defines the initial deployment standard for spaces managed by `migration-workbench`.

## Decision

- Primary platform: Fly.io
- Secondary platform: deferred (VPS adapter only for concrete constraints)
- Control plane: deployment behavior lives in `migration-workbench`
- Data model: SQLite-first for single-tenant, low-concurrency spaces

## Scope

### In scope

- Standard deploy/backup/restore/rollback workflow for all spaces
- Fly-based `preview` and `production` environments
- SQLite durability with WAL mode and Litestream replication
- Per-space profile declarations in workbench config

### Out of scope (for now)

- Multi-provider plugin framework
- Managed Postgres/Redis by default
- Kubernetes support
- Advanced traffic split strategies

## Hard Requirements

- Each space deploys from one workbench manifest entry.
- Each production space must use:
  - attached Fly volume
  - SQLite in WAL mode
  - Litestream replication to object storage (Tigris or S3-compatible)
- Deploy pipeline must include:
  - preflight checks
  - release step
  - health gate
  - automatic failure path
- Deploys that can alter schema must perform a pre-release backup checkpoint.
- Secrets must not be committed to git-tracked files.

## Architecture Plan

### Phase 1 (now): Fly-concrete implementation

Implement Fly end-to-end first; avoid premature adapter abstractions.

Required CLI surface:

- `wb deploy <space> --env <env> --dry-run`
- `wb status <space> --env <env>`
- `wb logs <space> --env <env>`
- `wb backup create <space> --env <env>`
- `wb backup restore <space> --env <env> --backup <id>`
- `wb rollback <space> --env <env> [--to-release <id>]`
- `wb secrets apply <space> --env <env>`
- `wb secrets rotate <space> --env <env> --key <KEY>`

`wb deploy` currently ships with `--dry-run` only. Provider-mutating deploy actions are intentionally deferred until the manifest and release metadata contracts are exercised in production-like runs.

### Phase 2 (later): extract provider interface

After at least two spaces are stable on Fly, extract a provider interface from the proven implementation.

## Manifest Model

Manifest lives at `deploy/spaces.yml` and declares:

- space identity and ownership metadata
- environments (`preview`, `production`)
- region and profile
- runtime process commands, internal port, and health checks
- build source (`image` or `dockerfile` + `context`)
- storage and volume sizing
- replication defaults plus per-space path templates
- backup checkpoint method and retention
- provider type and optional overrides

## Profiles

Logical profiles are provider-agnostic in naming and translated by the Fly implementation:

- `tiny`: 1 shared CPU, 256 MB RAM, 5 GB volume
- `small`: 1 shared CPU, 512 MB RAM, 5 GB volume
- `small-plus`: 1 shared CPU, 512 MB RAM, 10 GB volume

Initial mapping:

- `farm`: `small-plus`
- `migration-workbench`: `small`
- `vizcarra-guitars`: `small`
- `jewelry`: `tiny`

## SQLite Durability Contract

- SQLite runs in WAL mode.
- Litestream continuously replicates WAL changes to object storage.
- Schema-affecting releases create a checkpoint backup before release.
- Restore is atomic:
  1. stop writes
  2. restore database state
  3. run integrity check
  4. resume app traffic

Default operational targets:

- RPO: minutes
- RTO: under 30 minutes with operator guidance

## Secrets Contract

- Secret values are managed in provider secret stores (Fly secrets).
- Manifests contain only secret names, never values.
- Workbench commands apply and rotate provider secrets.

## Deploy Lifecycle

1. Resolve config (`space`, `env`, `profile`, provider settings)
2. Preflight (secrets, volume, litestream, env invariants)
3. Build image
4. Pre-release backup checkpoint (when required)
5. Run release command (migrations/static prep)
6. Start deployed release
7. Verify health checks
8. Mark success and record release metadata

Failure behavior:

- Release hook failure: stop; keep previous release active
- Health gate failure: rollback to last healthy release
- Rollback event: persisted in release history and flagged for operator follow-up

## Observability Minimum

Per space and release:

- release id, git sha, timestamp, actor
- health state and last successful probe
- last backup timestamp and replication lag signal
- memory/disk usage snapshot
- structured logs accessible from workbench CLI

## Alternative Strategy

### Active alternative

- Fly-first implementation is active.

### Deferred alternative

- VPS adapter is deferred until a concrete requirement appears:
  - customer hosting/compliance constraints
  - validated cost pressure that outweighs operator time
