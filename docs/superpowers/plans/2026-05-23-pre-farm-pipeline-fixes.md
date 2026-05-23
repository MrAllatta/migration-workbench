# Pre-Farm Pipeline Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `wb generate manifest` import path and missing `--contract` mapping, add multi-year import loop support, and write an end-to-end farm runbook.

**Architecture:** Fix 1 is a one-line import change plus kwarg forwarding in `deployment/wb_cli.py`. Fix 2 adds year-loop scaffolding to `import_generator.py` — when `bundle_path` contains `{year}`, the generated command gains `_resolve_years()`, `_resolve_path()`, and a `_run_year()` loop; otherwise existing single-year behavior is unchanged. Fix 3 is documentation only.

**Tech Stack:** Python 3.11, Django management commands, argparse, pytest.

**Worktree:** `plan/2026-05-23-pre-farm-pipeline-fixes` branched from `master`.

---

## Task 1: Fix wb generate manifest import path and arg mapping

**Files:**
- Modify: `deployment/wb_cli.py` (lines 431-440)
- Test: `deployment/tests/test_wb_contract_review_exit_zero.py` (or add new test file)

- [ ] **Step 1: Write a failing test for _generate_manifest**

Create `deployment/tests/test_wb_generate_manifest.py`:

```python
"""Tests for wb generate manifest command routing."""

import argparse
from unittest.mock import patch, MagicMock


def test_generate_manifest_forwards_contract_as_schema_contract():
    """_generate_manifest should forward --contract as --schema-contract to scaffold_view_manifest."""
    from deployment.wb_cli import _generate_manifest

    args = argparse.Namespace(
        structure="build/structure.json",
        contract="build/schema-contract.yaml",
        out="build/view-manifest.yaml",
        django_settings=None,
    )

    with patch("deployment.wb_cli.call_command") as mock_call:
        mock_call.return_value = None
        with patch("deployment.wb_cli._setup_django"):
            _generate_manifest(args)

    call_kwargs = mock_call.call_args[1]
    assert call_kwargs.get("schema_contract") == "build/schema-contract.yaml", (
        f"Expected schema_contract kwarg to be forwarded, got: {call_kwargs}"
    )


def test_generate_manifest_imports_scaffold_not_generate():
    """_generate_manifest should import scaffold_view_manifest, not generate_view_manifest."""
    from deployment import wb_cli

    with patch("deployment.wb_cli.call_command"):
        with patch("deployment.wb_cli._setup_django"):
            with patch("workbook.management.commands.scaffold_view_manifest.Command") as mock_cmd:
                args = argparse.Namespace(
                    structure="build/structure.json",
                    contract="build/schema-contract.yaml",
                    out="build/view-manifest.yaml",
                    django_settings=None,
                )
                wb_cli._generate_manifest(args)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest deployment/tests/test_wb_generate_manifest.py -v`
Expected: FAIL — the current code imports `generate_view_manifest` (wrong module) and doesn't forward `schema_contract`.

- [ ] **Step 3: Fix the import path and arg mapping in wb_cli.py**

In `deployment/wb_cli.py`, find `_generate_manifest` (around line 431). Current code:

```python
def _generate_manifest(args: argparse.Namespace) -> int:
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command
    from workbook.management.commands.generate_view_manifest import Command

    kwargs = {
        "structure": args.structure,
        "out": args.out,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command(Command, **kwargs)
    return 0
```

Replace with:

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

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest deployment/tests/test_wb_generate_manifest.py -v`
Expected: PASS.

- [ ] **Step 5: Run broader deployment tests**

Run: `.venv/bin/python -m pytest deployment/tests/ -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add deployment/wb_cli.py deployment/tests/test_wb_generate_manifest.py
git commit -m "fix: correct wb generate manifest import path and forward --contract as --schema-contract"
```

---

## Task 2: Add year-loop detection to import_generator

**Files:**
- Modify: `workbook/codegen/import_generator.py`
- Modify: `workbook/tests/test_import_generator.py`

This task adds the year-loop logic to `render_import_py`. When any table's `bundle_path` contains `{year}`, the generated command gains `_resolve_years()`, `_resolve_path()`, `--year` argument, and a `_run_year()` loop wrapper. When no table uses `{year}`, output is identical to the current generated code.

- [ ] **Step 1: Write failing tests for year-loop detection**

In `workbook/tests/test_import_generator.py`, add these tests:

```python
def test_render_import_py_year_loop_generated_when_bundle_path_has_year():
    """When bundle_path contains {year}, the generated command includes year-loop methods."""
    contract = {
        "version": "1.3",
        "source": {},
        "tables": [
            {
                "model_name": "Crop",
                "columns": [
                    {"suggested_field_name": "name", "django_field_class": "models.CharField",
                     "django_field_kwargs": {"max_length": 200}},
                ],
                "import_config": {
                    "bundle_path": "{year}/crops.csv",
                    "unique_on": ["name"],
                },
            },
        ],
    }
    source = render_import_py(contract, app_label="core")
    assert "_resolve_years" in source, f"Expected _resolve_years in generated code"
    assert "_resolve_path" in source, f"Expected _resolve_path in generated code"
    assert "_run_year" in source, f"Expected _run_year in generated code"
    assert "--year" in source, f"Expected --year argument in generated code"


def test_render_import_py_no_year_loop_when_bundle_path_is_static():
    """When no bundle_path contains {year}, no year-loop methods are generated."""
    contract = {
        "version": "1.3",
        "source": {},
        "tables": [
            {
                "model_name": "Crop",
                "columns": [
                    {"suggested_field_name": "name", "django_field_class": "models.CharField",
                     "django_field_kwargs": {"max_length": 200}},
                ],
                "import_config": {
                    "bundle_path": "crops.csv",
                    "unique_on": ["name"],
                },
            },
        ],
    }
    source = render_import_py(contract, app_label="core")
    assert "_resolve_years" not in source, f"Should not include _resolve_years for static bundle_path"
    assert "_run_year" not in source, f"Should not include _run_year for static bundle_path"


def test_render_import_py_resolve_path_substitutes_year():
    """_resolve_path should substitute {year} in path templates."""
    contract = {
        "version": "1.3",
        "source": {},
        "tables": [
            {
                "model_name": "Crop",
                "columns": [
                    {"suggested_field_name": "name", "django_field_class": "models.CharField",
                     "django_field_kwargs": {"max_length": 200}},
                ],
                "import_config": {
                    "bundle_path": "{year}/crops.csv",
                    "unique_on": ["name"],
                },
            },
        ],
    }
    source = render_import_py(contract, app_label="core")
    assert 'self._resolve_path(' in source, f"Expected _resolve_path call in _import_crop"
    assert '{year}' not in source.split('_run_import_pipeline')[0], (
        "Year template should be resolved at runtime, not hardcoded"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest workbook/tests/test_import_generator.py::test_render_import_py_year_loop_generated_when_bundle_path_has_year -v`
Expected: FAIL — `_resolve_years` not in current output.

- [ ] **Step 3: Add helper to detect year-aware contracts**

In `workbook/codegen/import_generator.py`, add this helper function near the top (after the existing imports):

```python
def _contract_has_year_bundle_path(contract: dict[str, Any]) -> bool:
    """Return True if any table's bundle_path contains {year}."""
    for table in contract.get("tables") or []:
        cfg = table.get("import_config")
        if cfg and "{year}" in (cfg.get("bundle_path") or ""):
            return True
    return False
```

- [ ] **Step 4: Add year-loop rendering helpers**

Add these rendering functions to `workbook/codegen/import_generator.py` (after `_default_value`):

```python
def _render_resolve_years(indent: int = 4) -> str:
    """Render the _resolve_years method for year-loop imports."""
    pad = " " * indent
    lines = [
        "",
        f"{pad}def _resolve_years(self) -> list[int]:",
        f'{pad}    """Return years to import, from --year flag or filesystem discovery."""',
        f"{pad}    if self.years:",
        f"{pad}        return sorted(self.years)",
        f"{pad}    discovered = []",
        f"{pad}    for entry in self.data_dir.iterdir():",
        f'{pad}        match = re.match(r"^year_(\\d{{4}})$", entry.name)',
        f"{pad}        if match and entry.is_dir():",
        f"{pad}            discovered.append(int(match.group(1)))",
        f"{pad}    if not discovered:",
        f"{pad}        from django.core.management.base import CommandError",
        f"{pad}        raise CommandError(",
        f'{pad}            f"No year_YYYY/ directories found in {{self.data_dir}}. "',
        f'{pad}            "Pass --year explicitly or run pull_bundle first."',
        f"{pad}        )",
        f"{pad}    return sorted(discovered)",
    ]
    return "\n".join(lines)


def _render_resolve_path(indent: int = 4) -> str:
    """Render the _resolve_path method for {year} placeholder substitution."""
    pad = " " * indent
    lines = [
        "",
        f"{pad}def _resolve_path(self, path_template: str, year: int):",
        f'{pad}    """Substitute {{year}} in a path template."""',
        f"{pad}    from pathlib import Path",
        f'{pad}    return Path(path_template.format_map({{"year": year}}))',
    ]
    return "\n".join(lines)


def _render_year_argument(indent: int = 8) -> str:
    """Render the --year argument for add_arguments."""
    pad = " " * indent
    lines = [
        f'{pad}parser.add_argument("--year", type=int, nargs="*", dest="years",',
        f'{pad}                    help="Years to import (default: auto-detect from data_dir)")',
    ]
    return "\n".join(lines)


def _render_run_import_pipeline_year_loop(tier_calls: list[str], indent: int = 4) -> str:
    """Render _run_import_pipeline with year loop for multi-year imports."""
    pad = " " * indent
    inner_pad = " " * (indent + 4)
    lines = [
        "",
        f"{pad}def _run_import_pipeline(self):",
        f"{pad}    for year in self._resolve_years():",
        f"{pad}        self._run_year(year)",
        "",
        f"{pad}def _run_year(self, year: int):",
        f'{pad}    self.stdout.write(f"--- Importing year {{year}} ---")',
    ]
    for call in tier_calls:
        lines.append(f"{inner_pad}{call}")
    return "\n".join(lines)
```

- [ ] **Step 5: Modify render_import_py to conditionally emit year-loop code**

In `render_import_py`, find the section that emits `_run_import_pipeline` (around line 641). Modify the logic to:

1. Check `_contract_has_year_bundle_path(contract)` before building the tier calls.
2. If year-aware: emit `add_arguments` with `--year`, `handle` with `self.years`, `_resolve_years`, `_resolve_path`, `_run_import_pipeline` with year loop, and `_run_year`.
3. If not year-aware: emit current code unchanged.

Find the section starting at line 640:

```python
    # _run_import_pipeline with tier calls.
    parts.append("    def _run_import_pipeline(self):")
    for tier, name, _ in candidates:
        parts.append(
            f'        self.tier("TIER {tier}: {name}s", self._import_{name.lower()})'
        )
    parts.append("")
```

Replace with:

```python
    year_aware = _contract_has_year_bundle_path(contract)

    if year_aware:
        # Emit year-loop methods.
        tier_calls = []
        for tier, name, _ in candidates:
            tier_calls.append(
                f'self.tier("TIER {tier}: {name}s", self._import_{name.lower()})'
            )
        parts.append("")
        parts.append(_render_resolve_years())
        parts.append("")
        parts.append(_render_resolve_path())
        parts.append(_render_run_import_pipeline_year_loop(tier_calls))
    else:
        # Standard single-year pipeline.
        parts.append("    def _run_import_pipeline(self):")
        for tier, name, _ in candidates:
            parts.append(
                f'        self.tier("TIER {tier}: {name}s", self._import_{name.lower()})'
            )
        parts.append("")
```

Also modify the method rendering: when `year_aware` is true, `_render_import_method` should emit `self._resolve_path(bundle_path, year)` instead of the static `bundle_path` string.

Find the line in `_render_import_method` (around line 412):

```python
    lines.append(
        f"    for row_number, row in self.read_bundle_tab({bundle_path!r}, tab_config):"
    )
```

Replace with conditional logic. In `_render_import_method`, add a `year_aware: bool = False` parameter to the function signature:

```python
def _render_import_method(
    model_name: str,
    contract_fields: list[dict[str, Any]],
    import_cfg: dict[str, Any],
    indent: int = 4,
    year_aware: bool = False,
) -> str:
```

Then change the `read_bundle_tab` line:

```python
    if year_aware and "{year}" in bundle_path:
        lines.append(
            f"    for row_number, row in self.read_bundle_tab(str(self._resolve_path({bundle_path!r}, year)), tab_config):"
        )
    else:
        lines.append(
            f"    for row_number, row in self.read_bundle_tab({bundle_path!r}, tab_config):"
        )
```

And pass `year_aware` through the call site. Find where `_render_import_method` is called (near line 652):

```python
    for _, name, table in candidates:
        fields = get_fields(table)
        cfg = get_import_config(table)
        parts.append(_render_import_method(name, fields, cfg))
```

Replace with:

```python
    for _, name, table in candidates:
        fields = get_fields(table)
        cfg = get_import_config(table)
        parts.append(_render_import_method(name, fields, cfg, year_aware=year_aware))
```

Now update the imports section to conditionally include `import re` and `from pathlib import Path` when `year_aware`. Find the imports block in `render_import_py` (around line 593-608):

```python
    parts.extend(
        [
            "from typing import Any",
            "from django.db import IntegrityError",
            "from importer.base import BaseImportCommand",
            f"from {app_label}.models import {', '.join(model_names)}",
            "",
            "",
            f"class {base_class_name}(BaseImportCommand):",
            f'    help = "Import {app_label} data from normalized bundles."',
            "",
            "    # -- Override hooks ---------------------------------------------------",
            "",
            "    def _prepare_row(self, data: dict) -> dict:",
            '        """Hook: transform the defaults dict before update_or_create."""',
            "        return data",
            "",
            "    def _before_save(self, obj, data: dict) -> None:",
            '        """Hook: called after each update_or_create."""',
            "        pass",
            "",
        ]
    )
```

Replace with conditional imports:

```python
    import_lines = ["from typing import Any", "from django.db import IntegrityError", "from importer.base import BaseImportCommand"]
    if year_aware:
        import_lines.extend(["import re", "from pathlib import Path"])
    import_lines.append(f"from {app_label}.models import {', '.join(model_names)}")

    parts.extend(
        import_lines
        + ["", ""]
        + [
            f"class {base_class_name}(BaseImportCommand):",
            f'    help = "Import {app_label} data from normalized bundles."',
            "",
            "    # -- Override hooks ---------------------------------------------------",
            "",
            "    def _prepare_row(self, data: dict) -> dict:",
            '        """Hook: transform the defaults dict before update_or_create."""',
            "        return data",
            "",
            "    def _before_save(self, obj, data: dict) -> None:",
            '        """Hook: called after each update_or_create."""',
            "        pass",
            "",
        ]
    )
```

Note: `year_aware` must be computed before this imports section. Move the `_contract_has_year_bundle_path(contract)` check to before the imports. Find the line where `candidates` is built and `if not candidates` check completes (around line 567-588), and add the `year_aware` variable right after `model_names = sorted(...)`:

```python
    model_names = sorted({name for _, name, _ in candidates})
    year_aware = _contract_has_year_bundle_path(contract)
```

- [ ] **Step 6: Run the new tests**

Run: `.venv/bin/python -m pytest workbook/tests/test_import_generator.py -v -k "year_loop"`
Expected: All year-loop tests PASS.

- [ ] **Step 7: Run the full import generator test suite**

Run: `.venv/bin/python -m pytest workbook/tests/test_import_generator.py -v`
Expected: All PASS (including existing tests for non-year-aware generation).

- [ ] **Step 8: Commit**

```bash
git add workbook/codegen/import_generator.py workbook/tests/test_import_generator.py
git commit -m "feat: add year-loop scaffolding to import generator when bundle_path contains {year}"
```

---

## Task 3: Add --year flag to generate_import CLI

**Files:**
- Modify: `workbook/management/commands/generate_import.py`

The `--year` flag on the **generated** command (not on `generate_import` itself) is handled by the generator emitting `add_arguments` with `--year`. The `generate_import` CLI command does NOT need a `--year` argument — it reads `bundle_path` from the contract and conditionally emits the year-loop code.

This task verifies that `generate_import` command still works for both year-aware and static contracts.

- [ ] **Step 1: Write integration test for year-aware generated command structure**

Append to `workbook/tests/test_generate_import_command.py`:

```python
def test_generate_import_year_aware_contract(tmp_path):
    """When contract has {year} in bundle_path, generated command includes year-loop."""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        yaml.safe_dump({
            "version": "1.3",
            "tables": [
                {
                    "model_name": "Crop",
                    "columns": [
                        {
                            "suggested_field_name": "name",
                            "django_field_class": "models.CharField",
                            "django_field_kwargs": {"max_length": 200},
                        },
                    ],
                    "import_config": {
                        "bundle_path": "{year}/crops.csv",
                        "unique_on": ["name"],
                    },
                },
            ],
        })
    )
    out_path = tmp_path / "import_core.py"
    call_command(
        "generate_import",
        contract=str(contract_path),
        out=str(out_path),
        force=True,
    )
    source = out_path.read_text()
    assert "_resolve_years" in source
    assert "_resolve_path" in source
    assert "_run_year" in source
    assert "--year" in source


def test_generate_import_static_bundle_path_unchanged(tmp_path):
    """When contract has static bundle_path, generated command matches existing format."""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        yaml.safe_dump({
            "version": "1.3",
            "tables": [
                {
                    "model_name": "Crop",
                    "columns": [
                        {
                            "suggested_field_name": "name",
                            "django_field_class": "models.CharField",
                            "django_field_kwargs": {"max_length": 200},
                        },
                    ],
                    "import_config": {
                        "bundle_path": "crops.csv",
                        "unique_on": ["name"],
                    },
                },
            ],
        })
    )
    out_path = tmp_path / "import_core.py"
    call_command(
        "generate_import",
        contract=str(contract_path),
        out=str(out_path),
        force=True,
    )
    source = out_path.read_text()
    assert "_resolve_years" not in source
    assert "_run_year" not in source
    assert "read_bundle_tab('crops.csv'" in source
```

- [ ] **Step 2: Run the integration tests**

Run: `.venv/bin/python -m pytest workbook/tests/test_generate_import_command.py -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add workbook/tests/test_generate_import_command.py
git commit -m "test: add year-loop integration tests for generate_import command"
```

---

## Task 4: Write end-to-end farm runbook

**Files:**
- Create: `docs/farm-end-to-end-runbook.md`

This is a documentation-only task. No code changes.

- [ ] **Step 1: Write the runbook**

Create `docs/farm-end-to-end-runbook.md`:

```markdown
# Farm End-to-End Runbook

Step-by-step instructions for running the full migration-workbench pipeline against a product repo (farm).

---

## Prerequisites

- `.env` configured with provider credentials (Google Sheets API key, etc.)
- Product repo cloned and `migration-workbench` installed as a dependency
- Django settings configured for the product repo

---

## Step 1: Profile the source data

**Command:**
```bash
python manage.py profile_cohort_corpus --corpus path/to/cohort_corpus.json --out build/profiles/
```

**Input:** `cohort_corpus.json`
**Output:** `build/profiles/` directory with per-tab JSON profiles
**Expected exit code:** 0

**Review checkpoint:** Verify that all tabs in scope are profiled. Check for unexpected tab names, empty profiles, or tabs with all-null columns.

**Emergency exit:** If profiling fails, check credentials and corpus config. Re-run with `--verbose` for detailed error output.

---

## Step 2: Scaffold the schema contract

**Command:**
```bash
python manage.py scaffold_workbook_schema build/profiles/ --out build/schema-contract.yaml
```

**Input:** `build/profiles/`
**Output:** `build/schema-contract.yaml`
**Expected exit code:** 0

**With `--continue-on-error`:**
```bash
python manage.py scaffold_workbook_schema build/profiles/ --out build/schema-contract.yaml --continue-on-error --pivot-detection-threshold 0.5
```

**Review checkpoint:** Open `build/schema-contract.yaml` and review:
- Model names are sensible (rename if needed)
- Field types match domain expectations
- FK targets are correct
- Computed fields are specified
- No pivot tables slipped through

If `--continue-on-error` was used, check `build/schema-contract-rejected.yaml` for rejected tables.

**Emergency exit:** If scaffold fails, check profile output. If certain tabs cause errors, exclude them from the corpus config and re-profile.

---

## Step 3: Hand-harden the contract

**No command.** Manual editing of `build/schema-contract.yaml`.

**Review:**
- Rename `suggested_model_name` values to desired model names
- Adjust `django_field_class` for columns that need different types
- Add `model_meta` for verbose names, ordering, unique_together
- Add `import_config` blocks with `bundle_path` values
- For multi-year data, use `{year}` placeholder in `bundle_path`

---

## Step 4: Generate models + admin + import

**Commands:**
```bash
python manage.py generate_models --contract build/schema-contract.yaml --app-label core --force --out backend/apps/core/models_auto.py
python manage.py generate_admin --contract build/schema-contract.yaml --app-label core --force
python manage.py generate_import --contract build/schema-contract.yaml --app-label core --force
```

**With `--continue-on-error` (generates partial output):**
```bash
python manage.py generate_models --contract build/schema-contract.yaml --app-label core --force --continue-on-error
```

**Input:** `build/schema-contract.yaml`
**Output:** `models_auto.py`, `admin_auto.py`, `import_core.py`
**Expected exit code:** 0

For each generated file, check:
- `build/models_auto-rejected.yaml` (only if `--continue-on-error`)
- `build/admin_auto-rejected.yaml`
- `build/import_core-rejected.yaml`

**Review checkpoint:** Verify generated imports reference correct model names and bundle paths.

**Emergency exit:** Fix the contract and re-generate. Generated files are deterministic — re-running overwrites.

---

## Step 5: Pull bundle data

**Command:**
```bash
python manage.py pull_bundle --config path/to/pull_config.yaml --data-dir data/
```

**Input:** `pull_config.yaml`
**Output:** `data/year_YYYY/` directories with CSV files
**Expected exit code:** 0

**Review checkpoint:** Verify CSV files exist at expected paths. Check row counts match source data.

**Emergency exit:** If pull fails, check provider credentials and config. Individual tab failures can be retried.

---

## Step 6: Validate import (dry run)

**Command:**
```bash
python manage.py import_core_data --validate-only
```

**For multi-year imports:**
```bash
python manage.py import_core_data --validate-only --year 2023 2024
```

**Input:** `data/year_YYYY/` directories
**Output:** Validation summary to stdout
**Expected exit code:** 0

**Review checkpoint:** No row errors expected. If errors appear, check bundle paths and column mappings.

**Emergency exit:** Fix bundle data or contract `import_config` and re-validate.

---

## Step 7: Run import

**Command:**
```bash
python manage.py import_core_data
```

**For multi-year imports:**
```bash
python manage.py import_core_data --year 2023 2024
```

Or omit `--year` to auto-discover from `data/` directory.

**Input:** `data/year_YYYY/` directories
**Output:** Import summary JSON
**Expected exit code:** 0

**Review checkpoint:** Check import summary JSON. Expected: 0 row errors. Row counts should match source data.

**Emergency exit:** If import has errors, check the summary JSON for specific row errors. Fix source data or contract and re-run with `--validate-only` first.

---

## Step 8: Scaffold view manifest

**Command:**
```bash
python manage.py scaffold_view_manifest --structure build/structure.json --contract build/schema-contract.yaml --out build/view-manifest.yaml
```

**Input:** `build/structure.json`, `build/schema-contract.yaml`
**Output:** `build/view-manifest.yaml`
**Expected exit code:** 0

**Review checkpoint:** Verify view entries match expected admin views. Check editable vs computed fields.

---

## Step 9: Generate discovery interview + merge

**Command:**
```bash
python manage.py generate_discovery_interview --manifest build/view-manifest.yaml --out build/discovery-interview.yaml
```

**Input:** `build/view-manifest.yaml`
**Output:** `build/discovery-interview.yaml`
**Expected exit code:** 0

**Review checkpoint:** Fill in discovery interview with role ownership, status semantics, and weekly actions for each view.

Then merge:
```bash
python manage.py merge_discovery --manifest build/view-manifest.yaml --interview build/discovery-interview.yaml --out build/view-manifest-merged.yaml
```

---

## Step 10: Generate final admin + deploy

**Command:**
```bash
python manage.py generate_admin --contract build/schema-contract.yaml --manifest build/view-manifest-merged.yaml --app-label core --force
```

**Then:**
```bash
wb deploy --live
```

**Expected exit code:** 0

---

## Acceptable error thresholds

| Stage | Acceptable errors | Action if exceeded |
|-------|------------------|--------------------|
| Profile | 0 | Re-profile with adjusted corpus config |
| Scaffold | 0 (without `--continue-on-error`) | Fix contract manually; with `--continue-on-error`, check rejected tables |
| Generate | 0 | Fix contract and re-generate |
| Validate import | 0 | Fix bundle path or column mapping |
| Import | 0 row errors | Check summary JSON; fix data or mapping |
```

- [ ] **Step 2: Commit**

```bash
git add docs/farm-end-to-end-runbook.md
git commit -m "docs: add farm end-to-end runbook"
```

---

## Task 5: Full regression test

**Files:**
- No new files — this task runs the existing test suite.

- [ ] **Step 1: Run the full chassis gate**

Run: `make chassis-gate`
Expected: All tests pass, lint clean, doc coverage met.

- [ ] **Step 2: Fix any failures before proceeding**

If any tests fail, debug and fix. Common issues:
- Import path references in `test_wb_generate_manifest.py` may need Django setup.
- `render_import_py` output changes may break snapshot-style tests in `test_import_generator.py`.

- [ ] **Step 3: Final commit if fixes were needed**

```bash
git add -A
git commit -m "fix: integration test adjustments for pipeline fixes"
```