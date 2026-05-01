# Google auth for Sheets / Drive profiling

Use **one** GCP project and **one** service account for read-only profiling across client folders instead of per-client key files.

## Reference setup

1. Dedicated GCP project + billing.
2. Enable APIs: `drive.googleapis.com`, `sheets.googleapis.com`, `iamcredentials.googleapis.com`, `cloudresourcemanager.googleapis.com`.
3. Create a service account (example name pattern: `mw-profiler@…iam.gserviceaccount.com`).
4. Grant the **operator** impersonation on that SA: `roles/iam.serviceAccountTokenCreator`, `roles/iam.serviceAccountUser`; grant the SA `roles/viewer` on the project if needed.
5. Share each client’s Drive folder with the **service account email** (Viewer is enough for profiling).
6. Local ADC: `gcloud auth application-default login`, set quota project: `gcloud auth application-default set-quota-project <project-id>`.
7. Run profiler commands with `--impersonate-service-account=…` or `gcloud config set auth/impersonate_service_account …`.

This matches `google.auth.default()` in `connectors/google_provider.py`.

## Why impersonation over JSON keys

- Fewer long-lived secrets in repos.
- Central permission boundary at the shared SA.
- Easier rotation than scattering key files.

## Toward Workload Identity Federation (WIF)

Target: short-lived federated credentials for local dev and CI, no JSON keys. Checklist: create WIF pool/provider in the GCP project, bind principals allowed to impersonate the profiler SA, keep `serviceAccountTokenCreator` narrowly scoped.

## Troubleshooting

- **Browser “app blocked”** on `application-default login` with Drive/Sheets scopes: try logging in **with** `--impersonate-service-account` and explicit scopes including `drive.readonly` and `spreadsheets.readonly`.
- **Double impersonation:** do not set `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` in the shell when ADC is already an impersonated service account — causes nested impersonation errors.

More connector detail: [connectors/README.md](../connectors/README.md).
