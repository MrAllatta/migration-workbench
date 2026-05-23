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

Use Approach B (implicit year discovery) as the default, with Approach A (`--year` flag) as an explicit override. This maximizes operator convenience: a simple `import_core_data` with no flags discovers years automatically, while `--year 2023 2024` pins the run to specific years.

**Year resolution (`_resolve_years`):**

```python
def _resolve_years(self) -> list[int]:
    """Return years to import, from --year flag or filesystem discovery."""
    if self.years:  # --year CLI args
        return sorted(self.years)
    # Auto-discover: scan data_dir for year_YYYY/ subdirectories
    discovered = []
    for entry in self.data_dir.iterdir():
        match = re.match(r"^year_(\d{4})$", entry.name)
        if match and entry.is_dir():
            discovered.append(int(match.group(1)))
    if not discovered:
        raise CommandError(
            f"No year_YYYY/ directories found in {self.data_dir}. "
            "Pass --year explicitly or run pull_bundle first."
        )
    return sorted(discovered)
```

**Path resolution (`_resolve_path`):**

`{year}` is the only placeholder. Substitution uses Python `str.format_map`:

```python
def _resolve_path(self, path_template: str, year: int) -> Path:
    """Substitute {year} in a path template."""
    return Path(path_template.format_map({"year": year}))
```

This is intentionally minimal. If other placeholders are needed later (e.g. `{sheet}`, `{quarter}`), they can be added to the `format_map` dict without changing the method signature.

**Generated output example:**

```python
class Command(BaseImportCommand):
    help = "Import core data from pulled bundles"

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument("--year", type=int, nargs="*", dest="years",
                            help="Years to import (default: auto-detect from data_dir)")

    def handle(self, *args, **options):
        self.years = options.get("years") or []
        super().handle(*args, **options)

    def _resolve_years(self) -> list[int]:
        if self.years:
            return sorted(self.years)
        discovered = []
        for entry in self.data_dir.iterdir():
            match = re.match(r"^year_(\d{4})$", entry.name)
            if match and entry.is_dir():
                discovered.append(int(match.group(1)))
        if not discovered:
            raise CommandError(
                f"No year_YYYY/ directories found in {self.data_dir}. "
                "Pass --year explicitly or run pull_bundle first."
            )
        return sorted(discovered)

    def _resolve_path(self, path_template: str, year: int) -> Path:
        return Path(path_template.format_map({"year": year}))

    def _run_import_pipeline(self):
        for year in self._resolve_years():
            self._run_year(year)

    def _run_year(self, year: int):
        self.stdout.write(f"--- Importing year {year} ---")
        # Per-tier imports, with bundle_path resolved via _resolve_path
        tier1_path = self._resolve_path("{year}/crops.csv", year)
        self._import_tier1(tier1_path)
        tier2_path = self._resolve_path("{year}/livestock.csv", year)
        self._import_tier2(tier2_path)
```

**`--validate-only` + multi-year:**

When `--validate-only` is passed alongside multi-year, the import command validates every discovered year before importing any. Specifically:

1. `_resolve_years()` determines the year list.
2. For each year, `_resolve_path` resolves the expected bundle paths.
3. The command checks that each resolved path exists. Missing paths are reported as errors.
4. If any year has missing bundles, the command exits with an error listing the missing paths.
5. If all bundles are present, the command proceeds with per-year import.

This means `--validate-only` is a dry-run that iterates all years — it confirms every `{year}/...` path resolves to an existing file.

**Changes in `import_generator.py`:**

1. Add `_render_resolve_years()` producing the discovery + `--year` override code.
2. Add `_render_resolve_path()` producing the `format_map` substitution helper.
3. `_render_import_method()` gains `self.years = options.get("years") or []` in `handle()`.
4. Template changes in `_render_import_py()` — the top-level `_run_import_pipeline()` calls `self._resolve_years()` and iterates.
5. Each tier call in `_run_year()` uses `self._resolve_path(bundle_path_template, year)` instead of a static path.
6. `add_arguments` includes `--year` (nargs="*", type=int).
7. `_render_import_py()` emits `--year` in `add_arguments` when the contract's `import_config` contains `{year}` in any `bundle_path`.

**Changes in `pipeline_manifest.py`:**

No changes needed. `output_pattern` already uses `{year}` substitution, `default_values` already includes `source_bundle_year: "{year}"`.

**Changes in `generate_import.py` CLI:**

No changes needed at the CLI level. The `--year` argument is added to the **generated** import command, not to `generate_import` itself. `generate_import` already reads `import_config` from the contract; if `bundle_path` contains `{year}`, the generator emits the year-loop scaffold.

**Tests:**
- Unit: `render_import_py` produces expected year-loop code when `import_config.bundle_path` contains `{year}`.
- Unit: `render_import_py` produces single-year code (existing behavior) when `import_config.bundle_path` has no `{year}` placeholder.
- Integration: generated import command iterates over mock `year_2023/`, `year_2024/` directories.
- Integration: `--validate-only` with `--year 2023 2024` reports missing files without importing.
- Integration: explicit `--year 2024` skips auto-discovery and only imports that year.
- Regression: existing import fixture (3-model test data, no `{year}` in `bundle_path`) produces output identical to current generated code.

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

Fix 1 is a runtime-crash bug and should land in its own PR immediately, ahead of the other two fixes.

| Fix | Type | Risk | PR |
|-----|------|------|----|
| 1: import path + arg mapping | Bugfix | Low (one-line import change + kwarg pass-through) | **PR 1: immediate hotfix** |
| 2: multi-year import loop | Feature | Medium (touches generated output contract) | PR 2: after Fix 1 lands |
| 3: end-to-end runbook | Docs | Low (no code, validates via execution) | PR 2 (same as Fix 2) |

Fix 2 and Fix 3 can share a PR because the runbook is the validation gate for the multi-year feature. The runbook is validated by executing it against farm and fixing any gaps found. Those gaps become additional fixes or makefile targets.
