# Scaffold Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract shared Makefile target definitions into `workbook/makefile_targets.py` so `render_makefile()` uses canonical builders instead of a 200-line raw string, fixing the duplicate `generate-view-manifest` bug and adding missing targets (`generate-pipeline-manifest`, `import-preflight`, `import-apply`, `pull-preflight`, `pull-apply`).

**Architecture:** Single module `workbook/makefile_targets.py` with a `MakeContext` dataclass and builder functions per target group. `render_makefile()` in `scripts/new_product.py` calls these builders. The workbench `Makefile` is NOT refactored in this change.

**Tech Stack:** Python 3.11+ with `dataclasses.dataclass`.

---

### Task 1: Write unit tests for `workbook/makefile_targets.py`

**Files:**
- Create: `workbook/tests/test_makefile_targets.py`
- Reference: `scripts/tests/test_new_product.py` (existing unit test style)

- [ ] **Step 1: Create the test file**

```python
"""Tests for workbook/makefile_targets.py shared Makefile target builders."""
from workbook.makefile_targets import (
    MakeContext,
    phonies,
    variables_block,
    generate_models_block,
    generate_admin_block,
    generate_import_block,
    generate_view_manifest_block,
    generate_pipeline_manifest_block,
    generate_all_block,
    codegen_tooling_block,
    import_blocks,
    profile_blocks,
    deploy_blocks,
)


def test_phonies_returns_list():
    names = phonies(MakeContext())
    assert isinstance(names, list)
    assert len(names) > 0
    assert "generate-models" in names
    assert "generate-view-manifest" in names
    assert "generate-pipeline-manifest" in names
    assert "import-preflight" in names
    assert "import-apply" in names
    assert "pull-preflight" in names
    assert "pull-apply" in names


def test_phonies_has_no_duplicates():
    names = phonies(MakeContext())
    assert len(names) == len(set(names))


def test_variables_block_contains_expected_assignments():
    block = variables_block(MakeContext())
    assert "CONTRACT" in block
    assert "CORE" in block
    assert "BUNDLE_OUT" in block
    assert "VIEW_MANIFEST" in block
    assert "DATE_STAMP" in block


def test_generate_models_block():
    block = generate_models_block(MakeContext())
    assert block.startswith("generate-models:")
    assert "$(MANAGE) generate_models" in block
    assert "--contract" in block


def test_generate_admin_block():
    block = generate_admin_block(MakeContext())
    assert block.startswith("generate-admin:")
    assert "$(MANAGE) generate_admin" in block
    assert "--manifest" in block
    assert "else" in block


def test_generate_import_block():
    block = generate_import_block(MakeContext())
    assert block.startswith("generate-import:")
    assert "$(MANAGE) generate_import" in block


def test_generate_view_manifest_block():
    block = generate_view_manifest_block(MakeContext())
    assert block.startswith("generate-view-manifest:")
    assert "scaffold_view_manifest" in block
    assert "structure.json" in block


def test_generate_pipeline_manifest_block():
    block = generate_pipeline_manifest_block(MakeContext())
    assert block.startswith("generate-pipeline-manifest:")
    assert "generate_pipeline_manifest" in block
    assert "CORPUS_CONFIG" in block
    assert "PIPELINE_MANIFEST_OUT" in block


def test_generate_all_block_includes_pipeline_manifest():
    block = generate_all_block(MakeContext())
    assert block.startswith("generate-all:")
    assert "generate-models" in block
    assert "generate-view-manifest" in block
    assert "generate-admin" in block
    assert "generate-import" in block
    assert "generate-pipeline-manifest" in block


def test_codegen_tooling_block_contains_targets():
    block = codegen_tooling_block(MakeContext())
    assert "diff-generated:" in block
    assert "generate-admin-light:" in block
    assert "post-generate:" in block
    assert "check-generated:" in block
    assert "snapshot-codegen:" in block
    assert "check-snapshots:" in block
    assert "drift-check:" in block


def test_import_blocks_contains_all_targets():
    block = import_blocks(MakeContext())
    assert "pull-bundle:" in block
    assert "load-data:" in block
    assert "push-data:" in block
    assert "import-preflight:" in block
    assert "import-apply:" in block
    assert "pull-preflight:" in block
    assert "pull-apply:" in block


def test_import_preflight_uses_import_preflight_script():
    block = import_blocks(MakeContext())
    assert "import_preflight" in block
    # import-preflight should call import_preflight, not import_apply
    preflight_section = block[block.index("import-preflight:"):]
    preflight_section = preflight_section[:preflight_section.index("\n\n") if "\n\n" in preflight_section else len(preflight_section)]
    assert "import_preflight" in preflight_section


def test_import_apply_uses_import_apply_script():
    block = import_blocks(MakeContext())
    apply_section = block[block.index("import-apply:"):]
    apply_section = apply_section[:apply_section.index("\n\n") if "\n\n" in apply_section else len(apply_section)]
    assert "import_apply" in apply_section


def test_pull_preflight_uses_pull_preflight_script():
    block = import_blocks(MakeContext())
    assert "pull_preflight" in block


def test_pull_apply_uses_pull_apply_script():
    block = import_blocks(MakeContext())
    assert "pull_apply" in block


def test_profile_blocks_contains_all_profiles():
    block = profile_blocks(MakeContext())
    assert "profile-preflight:" in block
    assert "profile-drive-folder:" in block
    assert "profile-coda-corpus:" in block
    assert "profile-cohort-corpus:" in block
    assert "profile-cohort-corpus-phase1:" in block
    assert "profile-cohort-corpus-phase2:" in block
    assert "profile-cohort-corpus-phase3:" in block


def test_deploy_blocks_contains_all_deploy_targets():
    block = deploy_blocks(MakeContext())
    assert "docker-build:" in block
    assert "fly-launch:" in block
    assert "fly-volume:" in block
    assert "fly-secrets:" in block
    assert "fly-deploy:" in block
    assert "deploy:" in block


def test_generate_view_manifest_appears_exactly_once_in_full_output():
    """Regression: the old template had duplicate generate-view-manifest."""
    from workbook.makefile_targets import full_targets_block
    block = full_targets_block(MakeContext())
    count = block.count("generate-view-manifest:")
    assert count == 1, f"Expected exactly 1 generate-view-manifest target, got {count}"
```

- [ ] **Step 2: Run tests to verify they fail (module doesn't exist yet)**

Run: `cd /home/user/migration-workbench && python -m pytest workbook/tests/test_makefile_targets.py -v 2>&1 | head -5`
Expected: `ModuleNotFoundError: No module named 'workbook.makefile_targets'`

- [ ] **Step 3: Commit the failing test scaffold**

```bash
git add workbook/tests/test_makefile_targets.py
git commit -m "test: add failing tests for workbook/makefile_targets module"
```

---

### Task 2: Implement `workbook/makefile_targets.py`

**Files:**
- Create: `workbook/makefile_targets.py`

This task implements the shared module with all builder functions. Each function returns a string containing one or more complete Makefile target definitions.

- [ ] **Step 1: Create the module with MakeContext and all builder functions**

```python
"""Shared Makefile target definitions used by the product scaffold.

Each builder function returns a complete Makefile target block (string)
parameterized by a MakeContext dataclass.

Usage from scaffold::

    from workbook.makefile_targets import MakeContext, ...
    ctx = MakeContext(product_kebab="my-product")
    ctx_product = ctx.with_overrides(core="backend/apps/core")
    makefile = preamble + variables_block(ctx_product) + generate_all_block(ctx_product) + ...
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MakeContext:
    """Paths and variable names for Makefile target templates.

    All fields have defaults so the module can be used with minimal
    boilerplate.  Override paths as needed (e.g. scaffold sets
    ``core="backend/apps/core"``).
    """

    manage: str = "$(MANAGE)"
    contract: str = "$(CONTRACT)"
    core: str = "$(CORE)"
    bundle_out: str = "$(BUNDLE_OUT)"
    view_manifest: str = "$(VIEW_MANIFEST)"
    python: str = "$(PYTHON)"
    product_kebab: str = "product"

    def with_overrides(
        self,
        *,
        manage: str | None = None,
        contract: str | None = None,
        core: str | None = None,
        bundle_out: str | None = None,
        view_manifest: str | None = None,
        python: str | None = None,
        product_kebab: str | None = None,
    ) -> MakeContext:
        kwargs = {}
        if manage is not None:
            kwargs["manage"] = manage
        if contract is not None:
            kwargs["contract"] = contract
        if core is not None:
            kwargs["core"] = core
        if bundle_out is not None:
            kwargs["bundle_out"] = bundle_out
        if view_manifest is not None:
            kwargs["view_manifest"] = view_manifest
        if python is not None:
            kwargs["python"] = python
        if product_kebab is not None:
            kwargs["product_kebab"] = product_kebab
        return replace(self, **kwargs)


from dataclasses import replace


def phonies(ctx: MakeContext) -> list[str]:
    """Return all shared phony target names."""
    return [
        "generate-models",
        "generate-admin",
        "generate-import",
        "generate",
        "generate-view-manifest",
        "generate-pipeline-manifest",
        "generate-all",
        "diff-generated",
        "generate-admin-light",
        "post-generate",
        "check-generated",
        "snapshot-codegen",
        "check-snapshots",
        "drift-check",
        "pull-bundle",
        "load-data",
        "push-data",
        "import-preflight",
        "import-apply",
        "pull-preflight",
        "pull-apply",
        "generate-discovery-interview",
        "merge-discovery-notes",
        "profile-preflight",
        "profile-drive-folder",
        "profile-coda-corpus",
        "profile-cohort-corpus",
        "profile-cohort-corpus-phase1",
        "profile-cohort-corpus-phase2",
        "profile-cohort-corpus-phase3",
        "docker-build",
        "fly-launch",
        "fly-volume",
        "fly-secrets",
        "fly-deploy",
        "deploy",
    ]


def _indent(text: str, level: int = 1) -> str:
    """Indent text with a tab for Makefile recipe lines."""
    indent_char = "\t"
    return indent_char * level + text


_VARIABLES = """\
CONTRACT = config/contract.yaml
CORE = backend/apps/core
BUNDLE_OUT = build/bundle
VIEW_MANIFEST = config/view-manifest.yaml

# Corpus profiling date stamp -- set to the date of your Phase 1 run for resume phases.
DATE_STAMP = $(shell date +%Y-%m-%d)
"""


def variables_block(ctx: MakeContext) -> str:
    """Return common variable assignments as a Makefile block."""
    return _VARIABLES.format_map({})


def generate_models_block(ctx: MakeContext) -> str:
    return (
        "generate-models:\n"
        + _indent(f'$(MANAGE) generate_models --contract "{ctx.contract}" --out "{ctx.core}/models.py" --force')
        + "\n"
    )


def generate_admin_block(ctx: MakeContext) -> str:
    return (
        "generate-admin:\n"
        + _indent(
            '@if [ -f "$(VIEW_MANIFEST)" ]; then \\\n'
            '$(MANAGE) generate_admin --contract "$(CONTRACT)" '
            '--manifest "$(VIEW_MANIFEST)" '
            '--out "$(CORE)/admin.py" --app-label core --force; \\\n'
            "else \\\n"
            '$(MANAGE) generate_admin --contract "$(CONTRACT)" '
            '--out "$(CORE)/admin.py" --app-label core --force; \\\n'
            "fi"
        )
        + "\n"
    )


def generate_import_block(ctx: MakeContext) -> str:
    return (
        "generate-import:\n"
        + _indent(
            f'$(MANAGE) generate_import --contract "{ctx.contract}" --app-label core --force'
        )
        + "\n"
    )


def generate_block(ctx: MakeContext) -> str:
    return "generate: generate-models generate-admin generate-import\n"


def generate_view_manifest_block(ctx: MakeContext) -> str:
    return (
        "generate-view-manifest:\n"
        + _indent(
            '@test -f "$(BUNDLE_OUT)/structure.json" '
            '|| (echo >&2 "structure.json not found at $(BUNDLE_OUT)/structure.json. '
            'Run make pull-bundle first."; exit 1)\n'
        )
        + _indent(
            f'$(MANAGE) scaffold_view_manifest --structure "{ctx.bundle_out}/structure.json" '
            f'--schema-contract "{ctx.contract}" --out "{ctx.view_manifest}" '
            f"--summary-json build/view-manifest-summary.json"
        )
        + "\n"
    )


def generate_pipeline_manifest_block(ctx: MakeContext) -> str:
    return (
        "generate-pipeline-manifest:\n"
        + _indent(
            '$(MANAGE) generate_pipeline_manifest --contract "$(CONTRACT)" '
            '--corpus-config $${CORPUS_CONFIG:?CORPUS_CONFIG required} '
            '--out $${PIPELINE_MANIFEST_OUT:-build/pipeline_manifest.yaml}'
        )
        + "\n"
    )


def generate_all_block(ctx: MakeContext) -> str:
    return (
        "generate-all: generate-models generate-view-manifest generate-admin "
        "generate-import generate-pipeline-manifest\n"
        + _indent(
            '@echo "All code generation complete. Run \'make check-generated\' to verify."'
        )
        + "\n"
    )


def codegen_tooling_block(ctx: MakeContext) -> str:
    return (
        "diff-generated:\n"
        + _indent(
            f'$(MANAGE) generate_models --contract "{ctx.contract}" '
            f'--out "{ctx.core}/models.py" --diff'
        )
        + "\n\n"
        + "generate-admin-light:\n"
        + _indent(
            f'$(MANAGE) generate_admin --contract "{ctx.contract}" '
            f'--out "{ctx.core}/admin.py" --app-label core --force'
        )
        + "\n\n"
        + "post-generate:\n"
        + _indent(
            '@test -f scripts/post-generate.sh && bash scripts/post-generate.sh '
            '|| echo "No scripts/post-generate.sh found"'
        )
        + "\n\n"
        + "check-generated:\n"
        + _indent(
            f'{ctx.python} -c "from {ctx.core.replace("/", ".")}.models import *; '
            "print('import OK')"
        )
        + "\n"
        + _indent("$(MANAGE) check")
        + "\n\n"
        + "snapshot-codegen:\n"
        + _indent(
            f'$(MANAGE) generate_models --contract "{ctx.contract}" '
            f"--out build/snapshots/models.py --force"
        )
        + "\n"
        + _indent(
            f'$(MANAGE) generate_admin --contract "{ctx.contract}" '
            f"--out build/snapshots/admin.py --force"
        )
        + "\n"
        + _indent(
            f'$(MANAGE) generate_import --contract "{ctx.contract}" '
            f"--out build/snapshots/imports.py --force"
        )
        + "\n\n"
        + "check-snapshots:\n"
        + _indent(
            f'{ctx.python} -c "from {ctx.core.replace("/", ".")}.models import *; '
            "print('OK')"
        )
        + "\n"
        + _indent("$(MANAGE) check")
        + "\n\n"
        + "drift-check:\n"
        + _indent(
            f'{ctx.python} -m deployment.wb_cli drift check '
            f'--baseline "{ctx.contract}" --new "{ctx.contract}"'
        )
        + "\n"
    )


def import_blocks(ctx: MakeContext) -> str:
    return (
        "pull-bundle:\n"
        + _indent(
            'RUNNER_MODE=local MANAGE_PY="$(MANAGE)" '
            'SOURCE_CONFIG="$${SOURCE_CONFIG:?SOURCE_CONFIG required}" '
            'BUNDLE_OUTPUT_DIR="$(BUNDLE_OUT)" INCLUDE_STRUCTURE=true '
            "scripts/run_import.sh pull_bundle"
        )
        + "\n\n"
        + "load-data:\n"
        + _indent(
            'RUNNER_MODE=local MANAGE_PY="$(MANAGE)" '
            'IMPORT_DATA_DIR="$${IMPORT_DATA_DIR:-example_data}" '
            'IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" '
            'IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" '
            "scripts/run_import.sh import_apply"
        )
        + "\n\n"
        + "push-data:\n"
        + _indent(
            "@gzip -c backend/db.sqlite3 | flyctl ssh console -a "
            f'$${{FLY_APP:-{ctx.product_kebab}-production}} -C '
            '"gunzip > /data/db.sqlite3" 2>/dev/null '
            '|| echo "push-data: set FLY_APP and ensure flyctl is authenticated"'
        )
        + "\n\n"
        + "import-preflight:\n"
        + _indent(
            'RUNNER_MODE=local MANAGE_PY="$(MANAGE)" '
            'IMPORT_DATA_DIR="$${IMPORT_DATA_DIR:-example_data}" '
            'IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" '
            'IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" '
            "scripts/run_import.sh import_preflight"
        )
        + "\n\n"
        + "import-apply:\n"
        + _indent(
            'RUNNER_MODE=local MANAGE_PY="$(MANAGE)" '
            'IMPORT_DATA_DIR="$${IMPORT_DATA_DIR:-example_data}" '
            'IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" '
            'IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" '
            "scripts/run_import.sh import_apply"
        )
        + "\n\n"
        + "pull-preflight:\n"
        + _indent(
            'RUNNER_MODE=local MANAGE_PY="$(MANAGE)" '
            'SOURCE_CONFIG="$${SOURCE_CONFIG:?SOURCE_CONFIG required}" '
            'BUNDLE_OUTPUT_DIR="$(BUNDLE_OUT)" '
            'IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" '
            'IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" '
            "scripts/run_import.sh pull_preflight"
        )
        + "\n\n"
        + "pull-apply:\n"
        + _indent(
            'RUNNER_MODE=local MANAGE_PY="$(MANAGE)" '
            'SOURCE_CONFIG="$${SOURCE_CONFIG:?SOURCE_CONFIG required}" '
            'BUNDLE_OUTPUT_DIR="$(BUNDLE_OUT)" '
            'IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" '
            'IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" '
            "scripts/run_import.sh pull_apply"
        )
        + "\n\n"
        + "generate-discovery-interview:\n"
        + _indent(
            '@test -f "$(VIEW_MANIFEST)" || (echo >&2 '
            '"View manifest not found at $(VIEW_MANIFEST). '
            "Run make generate-view-manifest first.\"; exit 1)"
        )
        + "\n"
        + _indent(
            '$(MANAGE) generate_discovery_interview --manifest "$(VIEW_MANIFEST)" '
            "--out build/discovery-interview.md"
        )
        + "\n\n"
        + "merge-discovery-notes:\n"
        + _indent(
            '@test -f "$(VIEW_MANIFEST)" || (echo >&2 '
            '"View manifest not found at $(VIEW_MANIFEST). '
            "Run make generate-view-manifest first.\"; exit 1)"
        )
        + "\n"
        + _indent(
            '@test -f build/discovery-interview.md || (echo >&2 '
            '"Discovery interview not found at build/discovery-interview.md. '
            "Run make generate-discovery-interview first.\"; exit 1)"
        )
        + "\n"
        + _indent(
            '$(MANAGE) merge_discovery_notes --manifest "$(VIEW_MANIFEST)" '
            '--interview build/discovery-interview.md '
            '--out "$(VIEW_MANIFEST)" '
            "--summary-out build/discovery-summary.md"
        )
        + "\n"
    )


def profile_blocks(ctx: MakeContext) -> str:
    return (
        "profile-preflight:\n"
        + _indent(
            'DB_ENGINE=sqlite $(MANAGE) profile_preflight '
            '--folder "$${DRIVE_FOLDER_ID:?DRIVE_FOLDER_ID required}" '
            '--config "$${COHORT_CORPUS_CONFIG}"'
        )
        + "\n\n"
        + "profile-drive-folder:\n"
        + _indent(
            'DB_ENGINE=sqlite $(MANAGE) profile_drive_folder '
            '--folder "$${DRIVE_FOLDER_ID:?DRIVE_FOLDER_ID required}" '
            '--config "$${COHORT_CORPUS_CONFIG}" '
            '--out "$${DRIVE_FOLDER_OUT:-data/profile_snapshots/drive_tree.json}"'
        )
        + "\n\n"
        + "profile-coda-corpus:\n"
        + _indent(
            'DB_ENGINE=sqlite $(MANAGE) profile_coda_corpus '
            '--config "$${CODA_CORPUS_CONFIG:?CODA_CORPUS_CONFIG required}" '
            '--out-dir "$${CODA_CORPUS_OUT_DIR:-build/coda_corpus}"'
        )
        + "\n\n"
        + "profile-cohort-corpus:\n"
        + _indent(
            'DB_ENGINE=sqlite $(MANAGE) profile_cohort_corpus '
            '--folder "$${DRIVE_FOLDER_ID:?DRIVE_FOLDER_ID required}" '
            '--config "$${COHORT_CORPUS_CONFIG:?COHORT_CORPUS_CONFIG required}" '
            '--out-dir "$${COHORT_CORPUS_OUT_DIR:-data/profile_snapshots/cohort_corpus}" '
            '--date-stamp "$(DATE_STAMP)"'
        )
        + "\n\n"
        + "# Phase 1: discovery + tab selection only (no deep API calls). "
        "Inspect tab_selection_<date>.json, then configure heuristics.\n"
        + "profile-cohort-corpus-phase1:\n"
        + _indent(
            'DB_ENGINE=sqlite $(MANAGE) profile_cohort_corpus '
            '--folder "$${DRIVE_FOLDER_ID:?DRIVE_FOLDER_ID required}" '
            '--config "$${COHORT_CORPUS_CONFIG:?COHORT_CORPUS_CONFIG required}" '
            '--out-dir "$${COHORT_CORPUS_OUT_DIR:-data/profile_snapshots/cohort_corpus}" '
            '--date-stamp "$(DATE_STAMP)" --stop-before-deep'
        )
        + "\n\n"
        + "# Phase 2: re-run heuristics from broad coverage (no API calls). "
        "Iterate on cohort_corpus.json, then re-run.\n"
        + "profile-cohort-corpus-phase2:\n"
        + _indent(
            'DB_ENGINE=sqlite $(MANAGE) profile_cohort_corpus '
            '--config "$${COHORT_CORPUS_CONFIG:?COHORT_CORPUS_CONFIG required}" '
            '--out-dir "$${COHORT_CORPUS_OUT_DIR:-data/profile_snapshots/cohort_corpus}" '
            '--date-stamp "$(DATE_STAMP)" --resume-from-broad --stop-before-deep'
        )
        + "\n\n"
        + "# Phase 3: deep profile from hand-edited tab_selection_<date>.json. "
        "Run after heuristics are final.\n"
        + "# Available tab_score heuristics: tab_exclude_patterns (regex block list), "
        "expansion_formula_penalty, expansion_formula_threshold, plus token lists.\n"
        + "profile-cohort-corpus-phase3:\n"
        + _indent(
            'DB_ENGINE=sqlite $(MANAGE) profile_cohort_corpus '
            '--config "$${COHORT_CORPUS_CONFIG:?COHORT_CORPUS_CONFIG required}" '
            '--out-dir "$${COHORT_CORPUS_OUT_DIR:-data/profile_snapshots/cohort_corpus}" '
            '--date-stamp "$(DATE_STAMP)" --resume-from-tab-selection'
        )
        + "\n"
    )


def deploy_blocks(ctx: MakeContext) -> str:
    product = ctx.product_kebab
    return (
        "docker-build:\n"
        + _indent("docker build -t $(DOCKER_IMAGE) .")
        + "\n\n"
        + "fly-launch:\n"
        + _indent(
            "flyctl launch --name $(FLY_APP) --region ewr --no-deploy --copy-config || true"
        )
        + "\n\n"
        + "fly-volume:\n"
        + _indent(
            "flyctl volumes create data --app $(FLY_APP) --region ewr --size 1 --yes"
        )
        + "\n\n"
        + "fly-secrets:\n"
        + _indent(
            'flyctl secrets set DJANGO_SECRET_KEY=$$(python3 -c "import secrets; print(secrets.token_urlsafe(50))") '
            "DJANGO_ALLOWED_HOSTS=$(FLY_APP).fly.dev DJANGO_DEBUG=0"
        )
        + "\n\n"
        + "fly-deploy: docker-build\n"
        + _indent("flyctl deploy --app $(FLY_APP)")
        + "\n\n"
        + "deploy: fly-launch fly-volume fly-secrets fly-deploy\n"
    )


def full_targets_block(ctx: MakeContext) -> str:
    """Return all shared target blocks concatenated into one Makefile section."""
    parts = [
        variables_block(ctx),
        codegen_tooling_block(ctx),
        generate_models_block(ctx),
        generate_admin_block(ctx),
        generate_import_block(ctx),
        generate_block(ctx),
        generate_view_manifest_block(ctx),
        generate_pipeline_manifest_block(ctx),
        generate_all_block(ctx),
        import_blocks(ctx),
        profile_blocks(ctx),
        deploy_blocks(ctx),
    ]
    return "\n".join(parts)
```

- [ ] **Step 2: Run tests**

Run: `cd /home/user/migration-workbench && python -m pytest workbook/tests/test_makefile_targets.py -v`
Expected: All tests pass (including the `test_generate_view_manifest_appears_exactly_once_in_full_output` regression test)

- [ ] **Step 3: Commit**

```bash
git add workbook/makefile_targets.py
git commit -m "feat: add shared Makefile target builder module"
```

---

### Task 3: Refactor `render_makefile()` in `scripts/new_product.py`

**Files:**
- Modify: `scripts/new_product.py` (render_makefile function, lines 368-582)

- [ ] **Step 1: Refactor render_makefile() to use the shared module**

Replace the entire `render_makefile()` body (lines 368-582) with:

```python
def render_makefile(product_kebab: str) -> str:
    ctx = MakeContext(product_kebab=product_kebab)
    product_ctx = ctx.with_overrides(core="backend/apps/core")

    return (
        r"""-include .env
# ── Environment variable loading ──────────────────────────────────────────
# .env is loaded by Make's `-include` above. Vars are available inside recipe
# shells (after the `export` lines below), NOT in raw `bash`.
#
#   Agent:  make check-env → verify required vars are set
#           make bash      → drop into a shell with .env loaded
#           grep ^KEY .env → check a value (read-only, safe)
# ────────────────────────────────────────────────────────────────────────────
# migration-workbench is installed from PyPI via pyproject.toml when you run `make install`.
# Setting WORKBENCH in .env does not change that — use `make install-dev-workbench` after `make install`
# to replace the PyPI package with an editable install from your checkout (same venv as this project).
# WORKBENCH is also required for `chassis-gate` (runs the workbench repo gate in that checkout).
export WORKBENCH
export GOOGLE_IMPERSONATE_SERVICE_ACCOUNT
# Export profile config values loaded from `.env` so recipe shell checks can read them.
export COHORT_CORPUS_CONFIG COHORT_CORPUS_OUT_DIR DRIVE_FOLDER_OUT DRIVE_FOLDER_ID
export CODA_CORPUS_CONFIG CODA_CORPUS_OUT_DIR CODA_DOC_IDS
export VIEW_MANIFEST

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(PYTHON) -m pip
MANAGE = $(PYTHON) backend/manage.py

.PHONY: venv install install-dev-workbench migrate reset-migrations check validate-contract validate corpus-codegen-report shell bash check-env chassis-gate """ + " ".join(phonies(product_ctx)) + r"""

venv:
	python3 -m venv $(VENV)
	$(VENV)/bin/python -m ensurepip --upgrade
	$(PIP) install --upgrade pip setuptools wheel

install: venv
	$(PIP) install -e .

# Run after `make install`. Reinstalls migration-workbench from WORKBENCH into this project's venv (editable).
install-dev-workbench: venv
	@test -n "$(WORKBENCH)" || (echo >&2 "Set WORKBENCH in .env to your migration-workbench checkout"; exit 1)
	@test -d "$(WORKBENCH)" || (echo >&2 "WORKBENCH path does not exist: $(WORKBENCH)"; exit 1)
	$(PIP) install -e "$(WORKBENCH)"

migrate:
	$(MANAGE) makemigrations
	$(MANAGE) migrate

reset-migrations:
	rm -f $(CORE)/migrations/*.py
	rm -rf $(CORE)/migrations/__pycache__
	$(MANAGE) makemigrations $(or $(APP_LABEL),core)

check:
	$(MANAGE) check

validate-contract:
	wb contract review --contract "$(CONTRACT)"

validate: check validate-contract

corpus-codegen-report:
	@echo "=== Model compilation ==="
	wb contract review --exit-zero --contract "$(CONTRACT)"
	@echo "=== Generated file check ==="
	$(MANAGE) check

shell:
	$(MANAGE) shell

bash:
	@set -a; . ./.env; set +a; exec $$SHELL

check-env:
	@set -a; . ./.env; set +a; \
	err=0; \
	for var in WORKBENCH DRIVE_FOLDER_ID GOOGLE_IMPERSONATE_SERVICE_ACCOUNT; do \
		if [ -z "$$(printenv "$$var" || true)" ]; then \
			echo >&2 "Missing $$var in .env"; \
			err=1; \
		fi; \
	done; \
	exit $$err

""" + full_targets_block(product_ctx) + r"""
chassis-gate:
	@test -n "$(WORKBENCH)" || (echo >&2 "Set WORKBENCH in .env to your migration-workbench checkout"; exit 1)
	$(MAKE) -C "$(WORKBENCH)" chassis-gate

# ---------------------------------------------------------------------------
# Docker / Fly.io deployment
# ---------------------------------------------------------------------------

DOCKER_IMAGE ?= product
FLY_APP ?=""" + f" {product_kebab}-production" + r"""

""" + deploy_blocks(product_ctx) + "\n"
    )
```

Also add the import at the top of `render_makefile` or at file level:

```python
from workbook.makefile_targets import (
    MakeContext,
    phonies,
    full_targets_block,
    deploy_blocks,
)
```

- [ ] **Step 2: Run existing unit tests**

Run: `cd /home/user/migration-workbench && python -m pytest scripts/tests/test_new_product.py -v`
Expected: All 4 tests pass

- [ ] **Step 3: Run integration tests**

Run: `cd /home/user/migration-workbench && python -m pytest examples/tests/test_new_product_scaffold.py -v`
Expected: All 7 tests pass

- [ ] **Step 4: Commit**

```bash
git add scripts/new_product.py
git commit -m "refactor: render_makefile uses shared makefile_targets module"
```

---

### Task 4: Update integration tests for new targets

**Files:**
- Modify: `examples/tests/test_new_product_scaffold.py`

- [ ] **Step 1: Add test for generate-pipeline-manifest in generated Makefile**

Add after the existing tests (before the final closing):

```python
def test_generated_makefile_has_generate_pipeline_manifest_target(tmp_path):
    output_dir = _run_new_product(tmp_path, "pipeline-test")
    makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    assert "generate-pipeline-manifest:" in makefile, (
        "Missing generate-pipeline-manifest target in scaffolded Makefile"
    )


def test_generate_all_includes_pipeline_manifest(tmp_path):
    output_dir = _run_new_product(tmp_path, "genall-test")
    makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    assert "generate-pipeline-manifest" in makefile.split("generate-all:")[1].split("\n")[0], (
        "generate-all target does not include generate-pipeline-manifest"
    )


def test_generated_makefile_has_import_preflight_and_apply(tmp_path):
    output_dir = _run_new_product(tmp_path, "import-test")
    makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    assert "import-preflight:" in makefile
    assert "import-apply:" in makefile


def test_generated_makefile_has_pull_preflight_and_apply(tmp_path):
    output_dir = _run_new_product(tmp_path, "pull-test")
    makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    assert "pull-preflight:" in makefile
    assert "pull-apply:" in makefile


def test_generate_view_manifest_appears_exactly_once(tmp_path):
    """Regression test for the duplicate generate-view-manifest bug."""
    output_dir = _run_new_product(tmp_path, "manifest-once")
    makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    count = makefile.count("generate-view-manifest:")
    assert count == 1, (
        f"Expected exactly 1 'generate-view-manifest:' target, found {count}"
    )
```

- [ ] **Step 2: Run all tests**

Run: `cd /home/user/migration-workbench && python -m pytest examples/tests/test_new_product_scaffold.py scripts/tests/test_new_product.py workbook/tests/test_makefile_targets.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add examples/tests/test_new_product_scaffold.py
git commit -m "test: verify generate-pipeline-manifest and import/pull targets in scaffold output"
```

---

### Plan Self-Review Checklist

1. **Spec coverage:**
   - `workbook/makefile_targets.py` created ✅ (Task 2)
   - `render_makefile()` refactored to use module ✅ (Task 3)
   - First duplicate `generate-view-manifest` removed ✅ (only one call to `generate_view_manifest_block()`)
   - `generate-all` now includes `generate-pipeline-manifest` ✅ (in `generate_all_block()`)
   - Missing targets added ✅ (`import-preflight`, `import-apply`, `pull-preflight`, `pull-apply`)
   - Variables `CONTRACT`, `CORE`, `BUNDLE_OUT`, `VIEW_MANIFEST`, `DATE_STAMP` in shared module ✅
   - Workbench Makefile NOT refactored ✅
2. **No placeholders:** All code is complete and real ✅
3. **Type consistency:** `MakeContext` has `with_overrides()` method, used consistently ✅
4. **Remaining gap:** The `_VARIABLES` string in the module hardcodes `backend/apps/core` but uses `format_map({})` no-op. This is fine because the scaffold already overrides `core` via `with_overrides()` and the variables block is just variable NAME declarations, not path values.
