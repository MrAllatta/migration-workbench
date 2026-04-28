# Google Auth Runbook for Profiling

This runbook captures the setup used in April 2026 for shared profiling access across client projects.

## Goal

Use a single `migration-workbench` Google Cloud project and service account for Drive/Sheets profiling, instead of per-client service accounts and key files.

## Current working setup (thread-tested)

1. Create a dedicated GCP project for workbench tooling.
2. Link billing to the project.
3. Enable required APIs:
   - `drive.googleapis.com`
   - `sheets.googleapis.com`
   - `iamcredentials.googleapis.com`
   - `cloudresourcemanager.googleapis.com`
4. Create service account:
   - `mw-profiler@migration-workbench-prod.iam.gserviceaccount.com`
5. Allow operator impersonation of the service account:
   - `roles/iam.serviceAccountTokenCreator`
   - `roles/iam.serviceAccountUser`
6. Grant the service account project visibility:
   - `roles/viewer` on the workbench project.
7. Share the client parent Drive folder with the service account email (Viewer access is sufficient for read-only profiling).
8. Authenticate locally with ADC user login:
   - `gcloud auth application-default login`
   - `gcloud auth application-default set-quota-project migration-workbench-prod`
9. Run commands with service account impersonation:
   - one-off via `--impersonate-service-account=...`, or
   - config default via `gcloud config set auth/impersonate_service_account ...`

## Why this pattern

- Eliminates per-client service account sprawl.
- Keeps profiling permissions centrally managed.
- Works with existing `google.auth.default()` flows.
- Avoids storing long-lived service-account key files in client repos.

## Next step (recommended): WIF + SA impersonation

Move from local user ADC + optional key fallback to Workload Identity Federation.

Target state:

- Local dev and CI use short-lived federated credentials.
- No long-lived JSON key distribution.
- Service account impersonation remains the execution identity boundary.

Minimum WIF migration checklist:

1. Create workload identity pool/provider in `migration-workbench-prod`.
2. Bind external principals to impersonate `mw-profiler`.
3. Keep `roles/iam.serviceAccountTokenCreator` scoped to intended operators/CI identities.
4. Update runbooks to use ADC/WIF credential config instead of service-account key files.
