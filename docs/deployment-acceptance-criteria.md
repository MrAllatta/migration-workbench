# Deployment Acceptance Criteria (Sprint 1)

This defines executable acceptance criteria for the Fly-first deployment baseline.

## Scope

- Applies to spaces declared in `deploy/spaces.yml`
- Covers `preview` and `production` environments
- Assumes SQLite + Litestream baseline

## Commands and Criteria

### `wb deploy <space> --env <env> --dry-run`

Must:

- Resolve `<space>` and `<env>` from `deploy/spaces.yml`
- Validate required keys:
  - provider type and region
  - runtime commands
  - storage paths/volume size
  - required secrets list
  - replication settings
- Fail fast if required provider secrets are missing
- Resolve build inputs (image reference or dockerfile/context)
- Produce an explicit action plan (without provider mutation)
- Persist dry-run release metadata with deterministic release id
- Persist release metadata:
  - release id
  - git sha
  - actor
  - timestamp
  - outcome

Done when:

- Dry-run returns success with a release id
- dry-run metadata can be queried from release history

### `wb manifest lint`

Must:

- validate `deploy/spaces.yml` against required contract shape
- reject unknown/missing profile references
- reject per-space `storage.volume_gb` overrides (profile owns volume size)
- return stable error code `WB-MANIFEST-1001` on validation failures

Done when:

- command exits non-zero with structured diagnostics on invalid manifests

### `wb status <space> --env <env>`

Must report:

- provider app id/name
- current release id and git sha
- health state
- machine size/profile
- volume attachment state
- last backup timestamp
- replication lag indicator (or "unknown" if unavailable)

Done when:

- Output is machine-readable (`--json`) and human-readable default

### `wb logs <space> --env <env>`

Must:

- stream provider logs with optional `--since`
- include release id context where available

Done when:

- operator can correlate errors to the active release

### `wb backup create <space> --env <env>`

Must:

- create consistent SQLite backup artifact
- capture enough metadata to restore:
  - backup id
  - source app/release
  - timestamp
  - storage URI

Done when:

- returned backup id is restorable with `wb backup restore`

### `wb backup restore <space> --env <env> --backup <id>`

Must:

- stop write traffic during restore window
- restore database state from backup id
- run integrity verification
- restart app and verify health check

Done when:

- app returns healthy state and integrity check passes

### `wb rollback <space> --env <env> [--to-release <id>]`

Must:

- default to last known healthy release when id omitted
- redeploy or reactivate target release
- verify health
- record rollback event in release history

Done when:

- status reflects target release and healthy state

### `wb secrets apply <space> --env <env>`

Must:

- read required secret names from manifest
- verify local operator source has values
- apply to provider secret store without printing values

Done when:

- provider reports all required keys present

### `wb secrets rotate <space> --env <env> --key <KEY>`

Must:

- update one key in provider
- force safe restart/redeploy path when needed
- verify app health post-rotation

Done when:

- rotated key is active and app remains healthy

## Failure Policy

- Release command failure: stop and retain previous healthy release
- Health check failure after deploy: automatic rollback
- Restore failure: keep app in safe state, emit actionable error
- Any failure must include a remediation hint

## Non-Functional Requirements

- Every command supports `--json` for automation
- Errors are deterministic and include stable error codes
- Logs redact secret values
- A full deploy path completes within an agreed SLO target (to be measured and documented)

## Exit Conditions for Sprint 1

- `migration-workbench` self-host deployment works via `wb deploy`
- `farm` production deploy succeeds with health gating
- one successful backup and restore drill documented for each of:
  - `migration-workbench`
  - `farm`
- runbook links added to docs index/README for operator discovery
