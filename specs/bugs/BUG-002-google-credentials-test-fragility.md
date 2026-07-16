# BUG-002: `test_run_pipeline_state_resume` calls real Google auth in CI

## Status

Under review. Found during CI triage after lint/format gate fixes.

## Severity

High — CI gate failure; test is not hermetic.

## Symptom

`make chassis-gate` fails in CI with:

```
FAILED profiler/tests/test_run_pipeline_state_command.py::test_run_pipeline_state_resume
google.auth.exceptions.DefaultCredentialsError: Your default credentials were not found.
```

Locally the test passes because the developer environment has Application Default Credentials configured.

## Root cause

The test seeds a partial checkpoint and then runs `run_pipeline_state --phase=all`. The inline comment claims `discover`, `score_and_select`, and `deep_profile` are seeded as complete, but the code only calls:

```python
state.discover()
state.score_and_select()
```

It never adds `"deep_profile"` to `state.completed_phases`. Therefore, when `run_pipeline_state --phase=all` loads the checkpoint, it executes the `deep_profile` phase, which calls `PipelineState._build_services()`:

```python
# profiler/management/commands/run_pipeline_state.py (around line 391)
_drive, sheets_service = self._build_services()
state.deep_profile(sheets_service)
```

`_build_services()` builds Google Drive/Sheets services via `connectors.google_sheets.build_google_service()`, which calls `google.auth.default()`. Without ADC in CI, this raises `DefaultCredentialsError`.

The existing mock `@patch("profiler.tools.cohort_corpus.run_cohort_corpus")` is a red herring: it covers `run_cohort_corpus`, but the failure occurs in `PipelineState._build_services` before any cohort corpus call.

## Code path

```
run_pipeline_state --phase=all
  ├─ loads checkpoint (deep_profile not in completed_phases)
  ├─ _run_deep_profile()
  │    └─ _build_services()
  │         └─ connectors.google_sheets.build_google_service()
  │              └─ google.auth.default()  ← raises DefaultCredentialsError
```

## Affected files

| File | Role |
|------|------|
| `profiler/tests/test_run_pipeline_state_command.py` | Test with incomplete checkpoint setup |
| `profiler/management/commands/run_pipeline_state.py` | `_build_services()` has no hermetic fallback for tests |
| `connectors/google_sheets.py` | `build_google_service()` always calls `google.auth.default()` |

## Reproduction

```bash
# Without ADC
unset GOOGLE_APPLICATION_CREDENTIALS
.venv/bin/python -m pytest profiler/tests/test_run_pipeline_state_command.py::test_run_pipeline_state_resume -v
```

## Recommended fix

### Option A — fix the test (fastest)

Add `"deep_profile"` to `completed_phases` so the command skips the phase entirely, matching the test's intent:

```python
state.deep_profile_index.entries = [...]
state.completed_phases.append("deep_profile")  # <- missing
state.save_checkpoint(checkpoint)
```

### Option B — make `_build_services` testable

Allow `_build_services()` to return `(None, None)` when no credentials are available, and make callers handle that gracefully in test mode:

```python
def _build_services(self):
    try:
        ...
    except DefaultCredentialsError:
        return None, None
```

### Option C — refactor checkpoint seeding

Add a helper that creates a fully consistent partial checkpoint for tests, so every test that claims phases are complete actually marks them complete.

## Decision needed

Should `PipelineState` phases degrade gracefully without Google credentials, or should tests be required to mark every completed phase explicitly?

Until fixed, gate can be unblocked by adding `state.completed_phases.append("deep_profile")` to the test.
