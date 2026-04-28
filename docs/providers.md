# Providers

## Google Sheets (active)

Implementation files:

- `connectors/google_sheets.py`
- `connectors/google_provider.py`

Uses service account credentials from `GOOGLE_APPLICATION_CREDENTIALS` or ADC defaults.

Operational recommendation:

- Prefer ADC user login and service-account impersonation for local workflows.
- Use one workbench-owned service account shared to client Drive folders.
- See `docs/google-auth-runbook.md` for the April 2026 reference setup and WIF migration direction.

## Coda (stub)

Implementation file:

- `connectors/coda.py`

The adapter currently raises `NotImplementedError`, but the provider routing and config shape are already in place so command-level changes are not required when Coda support is added.