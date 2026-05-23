# Pre-Farm Pipeline Fixes

Three targeted fixes needed before the next end-to-end farm attempt.

---

## Fix 1: `wb generate manifest` import path and arg mapping

**File:** `deployment/wb_cli.py`

**Problem:** Two errors in `_generate_manifest()`.

1. **Wrong import path** (line 434): imports `workbook.management.commands.generate_view_manifest`. The actual module is `scaffold_view_manifest`. This causes `ModuleNotFoundError` at runtime.

2. **Missing `--schema-contract` mapping** (lines 436–439): `_generate_manifest()` only passes `structure` and `out` to the Command class. The CLI parser collects `--contract` (line 824) but it's never forwarded. The actual command (`scaffold_view_manifest`) accepts `--schema-contract` for entity binding — without it, view manifests have unbound entity names.

**Fix:**

```python
def _generate_manifest(args: argparse.Namespace) -> int:
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command
    from workbook.management.commands.scaffold_view_manifest import Command

    kwargs = {
        "structure": args.structure,
        "out": args.out,
    }
    if args.contract:
        kwargs["schema_contract"] = args.contract
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command(Command, **kwargs)
    return 0
```

**Tests:**
- Existing deploy smoke test should cover this path; verify it passes after fix.
- Add assertion that `wb generate manifest --contract x --structure y --out z` exits 0.

---

## Fix 2: Multi-year import loop

**Files:**
- `workbook/codegen/import_generator.py` — generated import command
- `workbook/pipeline_manifest.py` — per-year output_pattern and spreadsheet mapping
- `workbook/management/commands/generate_import.py` — CLI for import codegen

**Problem:** `_render_import_method()` (line 383) reads a single static `bundle_path` from `import_config`. The pipeline manifest knows about per-year spreadsheet IDs and produces `output_pattern` values like `{year}/crops.csv`. The `pull_bundle` command already produces `year_YYYY/` bundle directories. But the generated import command has no concept of years — it reads one file, imports once.

**Design:**

The generated `_run_import_pipeline()` gains a year loop. Two approaches considered:

**Approach A — `--year` flag on the import command (simpler, explicit):**

The import command accepts `--year` (repeatable, default: discover from data_dir). When called with explicit years, it iterates those years, resolving `bundle_path` via a per-year substitution.

```python
# Generated _run_import_pipeline:
def _run_import_pipeline(self):
    years = self._resolve_years()
    for year in years:
        self._run_year(year)
```

The `_run_year(year)` method wraps each tier call, temporarily setting `self.year = year` and resolving paths via `self._resolve_path(path_template)` which substitutes `{year}` with the current year value.

**Approach B — Implicit year discovery from data_dir (automatic):**

Scan `data_dir` for `year_YYYY/` subdirectories, sort by year, iterate. No CLI change needed — the import command discovers years automatically.

Both can coexist: explicit `--year` list takes precedence; fall back to filesystem discovery.

**Changes in `import_generator.py`:**

1. Add a `_render_year_loop()` function that wraps the existing per-table import logic in a year iterator.
2. `_render_import_method()` learns to accept a `year` parameter in generated method signatures (optional, for per-year path resolution).
3. Template changes in `_render_import_py()` — the top-level `_run_import_pipeline()` gains the year loop.
4. `bundle_path` in the contract's `import_config` supports `{year}` placeholder. Default: `{year}/{model_name}.csv`.

**Changes in `pipeline_manifest.py`:**

Already correct — `output_pattern` uses `{year}` substitution, `default_values` includes `source_bundle_year: "{year}"`. No changes needed here.

**Changes in `generate_import.py` CLI:**

Add `--year` argument (repeatable, type int). If omitted, the generated command auto-discovers years from data_dir.

**Tests:**
- Unit: `render_import_py` produces expected year-loop code.
- Integration: generated import command iterates over mock `year_YYYY/` directories.
- Existing import fixture (3-model test data) runs in single-year mode unchanged.

---

## Fix 3: End-to-end coupling validation

**No code changes** — this is a documentation and runbook task.

**Problem:** Each pipeline stage works in isolation but the data flow between them has never been validated as a chain. Specifically:

1. `scaffold_workbook_schema` → contract YAML: columns are mapped from profiler output with inferred types. The contract may contain stale or incorrect field mappings that only surface during import.
2. Contract → `generate_import`: the generated import command hardcodes `bundle_path` from `import_config`. If the bundle path doesn't match what `pull_bundle` produces, the import silently reads an empty file or crashes.
3. `pipeline_manifest` → `pull_bundle`: the pipeline manifest's `output_pattern` and the pull config's `tabs[].output_path` must agree on where CSVs land.
4. Import summary → human review: the summary JSON contains error counts, but there's no documented threshold for "acceptable errors" vs "pipeline failed."

**Output: end-to-end runbook**

Write a single Markdown document (`docs/farm-end-to-end-runbook.md`) that:

1. Lists every command to run, in order, with example arguments.
2. For each command, lists: input files it reads, output files it writes, expected exit code.
3. For each generated file, lists what to review before proceeding (e.g., "Review contract YAML for correct FK targets," "Review import summary JSON: expected 0 row errors").
4. Documents the full farm: `profile_cohort_corpus` → `scaffold_workbook_schema` → hand-harden contract → `generate_models` + `generate_admin` + `generate_import` → `pull_bundle` → `import_core_data --validate-only` → `import_core_data` → `scaffold_view_manifest` → `generate_discovery_interview` → merge → `generate_admin` (final) → `wb deploy --live`.

The runbook is validated by executing it against farm and fixing any gaps found. Those gaps become additional fixes or makefile targets.

**Emergency exits** documented alongside each step: what to do when a command fails mid-pipeline. In most cases the answer is "fix the input, rerun" — the resilient scaffold flags (`--continue-on-error`) and `--validate-only` import mode already exist for this.

---

## Delivery

All three fixes land in a single PR:

| Fix | Type | Risk |
|-----|------|------|
| 1: import path + arg mapping | Bugfix | Low (one-line import change + kwarg pass-through) |
| 2: multi-year import loop | Feature | Medium (touches generated output contract) |
| 3: end-to-end runbook | Docs | Low (no code, validates via execution) |

The runbook is the gate: Fixes 1 and 2 are verified by executing the runbook against farm. If the runbook passes, the pipeline is proven for farm.
