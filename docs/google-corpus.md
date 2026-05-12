# Google Drive / Sheets corpus profiling

Use when the source of truth is a **shared Google Drive folder** of **native Google Sheets** (not Coda). The multi-workbook pipeline is `**profile_cohort_corpus`**.

## Prerequisites

- Dedicated GCP project with Drive and Sheets APIs enabled, service account, and folder shared with that account (Viewer is enough). See [google-auth.md](google-auth.md).
- **Application Default Credentials** locally: `gcloud auth application-default login` and set the quota project (`gcloud auth application-default set-quota-project <project-id>`).

## Auth environment variables

Profiling commands do **not** accept a `--impersonate-service-account` CLI flag.

- Set `**GOOGLE_IMPERSONATE_SERVICE_ACCOUNT=<profiler-sa-email>`** in `.env` when using ADC without a JSON key. The connector reads this in `get_service_account_credentials` (`[connectors/google_sheets.py](../connectors/google_sheets.py)`).
- Alternatively, use `gcloud auth application-default login` and `gcloud config set auth/impersonate_service_account <email>` so ADC issues tokens for the shared service account.

Do not combine nested impersonation (see troubleshooting in [google-auth.md](google-auth.md)).

## Recommended sequence

1. **Smoke** — Validate credentials and folder read access (prefer config-driven flow):
  ```bash
   python manage.py profile_preflight --config path/to/cohort_corpus.json
  ```
   Standalone fallback:
  ```bash
   python manage.py profile_preflight --folder <folder-id-or-url>
  ```
2. **Tree** — Snapshot the folder tree (and optionally every spreadsheet’s tabs):
  ```bash
   python manage.py profile_drive_folder --config path/to/cohort_corpus.json --out build/drive_tree.json
  ```
   Standalone fallback:
  ```bash
   python manage.py profile_drive_folder --folder <folder-id-or-url> --out build/drive_tree.json
  ```
   A `.md` sibling is written next to the JSON for quick review.
3. **Corpus config** — Copy `[example_data/cohort_corpus.example.json](../example_data/cohort_corpus.example.json)`. Set:
  - `workbook_id_regex` — Must include a **capturing group**; group **1** is the workbook id compared to `in_scope_workbooks`.
  - `year_regex` — Optional override; default finds `20xx` years in folder or file names.
  - `in_scope_workbooks` — List of ids exactly as captured by group 1 of `workbook_id_regex`.
  - Set `DRIVE_FOLDER_ID` in `.env` with the Drive folder id or URL (not in the JSON config).
4. **Corpus run** — Outputs dated JSON under `--out-dir` (product repos often use `data/profile_snapshots/`):
  ```bash
   python manage.py profile_cohort_corpus --config path/to/cohort_corpus.json --out-dir data/profile_snapshots/cohort_run
  ```
   Or from the workbench repo root:
5. **Tab selection loop** — Review `tab_selection_<date>.json`. Hand-edit `**approved_tabs**` as needed, then re-run with the **same** `--out-dir` and `--date-stamp` as the full corpus run (`in_scope_workbook_index_<date>.json` must still sit beside tab selection):

  ```bash
   python manage.py profile_cohort_corpus \
     --config … \
     --out-dir … \
     --date-stamp 2026-05-07 \
     --resume-from-tab-selection
  ```

   Resume skips Drive discovery through tab shortlisting (no broad `list_tabs` sweep before deep profiling). After HTTP 429 throttling, add optional JSON keys **`deep_read_delay_seconds`** (float: sleep before each non-cached `fetch_tab_grid`) and **`deep_skip_existing`**, or pass CLI **`--skip-existing-deep`**, to reuse matching `deep/*.json` payloads instead of refetching.

6. **Deeper tooling** — For single spreadsheets or formula surveys, see [profiler/README.md](../profiler/README.md) (`profile_tab`, `scan_formula_patterns`). Align outputs with the [schema design loop](schema-design-loop.md).

## Naming contract

Every file name in corpus discovery must expose an id that `**workbook_id_regex`** extracts as **group 1**. Entries in `**in_scope_workbooks`** must match those strings exactly (e.g. if the regex captures `201`, include `"201"`, not a label like `"FarmPlan"` unless your regex captures that text).

Dry-run sanity: grep your `profile_drive_folder` markdown output against the regex you intend to use before a long corpus run.

## Native Google Sheets only

The Drive walker treats `**application/vnd.google-apps.spreadsheet`** as spreadsheets. `**.xlsx` and other Office files** are listed under `other_files` and are **not** included in `profile_cohort_corpus`. Convert uploads to Google Sheets first if they must participate.

## Makefile shortcut (workbench repo)


| Variable                | Required | Default               |
| ----------------------- | -------- | --------------------- |
| `COHORT_CORPUS_CONFIG`  | Yes      | —                     |
| `COHORT_CORPUS_OUT_DIR` | No       | `data/profile_snapshots/cohort_corpus` |


```bash
COHORT_CORPUS_CONFIG=example_data/cohort_corpus.example.json make profile-cohort-corpus
```

(`example_data/cohort_corpus.example.json` uses placeholders — replace `in_scope_workbooks` and set `DRIVE_FOLDER_ID` in `.env` before a real run.)

## Pointers

- Command reference: [profiler/README.md](../profiler/README.md)
- Coda equivalent: [coda.md](coda.md)

