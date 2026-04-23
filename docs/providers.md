# Providers

## Google Sheets (active)

Implementation files:

- `connectors/google_sheets.py`
- `connectors/google_provider.py`

Uses service account credentials from `GOOGLE_APPLICATION_CREDENTIALS` or ADC defaults.

## Coda (stub)

Implementation file:

- `connectors/coda.py`

The adapter currently raises `NotImplementedError`, but the provider routing and config shape are already in place so command-level changes are not required when Coda support is added.
