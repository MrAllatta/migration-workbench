# Scaffold Sync Design

`scripts/new_product.py` renders a Makefile template inline in
`render_makefile()`. This template duplicates shared target definitions
(pull-bundle, generate-models, etc.) that also exist in the workbench Makefile
at `/Makefile`. The duplication has already drifted: the scaffold is missing
`generate-pipeline-manifest`, and `generate-all` doesn't include it. It also
has a duplicate `generate-view-manifest` target.

Extract the overlapping target definitions into a shared Python module so
the scaffold always picks up new targets when the workbench adds them.

## Problem

The scaffold's generated Makefile (`make new-product`) is outdated relative
to the workbench Makefile:

| Target | Workbench | Scaffold |
|--------|-----------|----------|
| `generate-pipeline-manifest` | ✅ | ❌ missing |
| `generate-all` prereqs | includes `generate-pipeline-manifest` | missing it |
| `generate-view-manifest` | ✅ single | ❌ appears twice |
| `import-preflight` | ✅ | ❌ missing |
| `import-apply` | ✅ | ❌ missing |
| `pull-preflight` | ✅ | ❌ missing |
| `pull-apply` | ✅ | ❌ missing |

Manual editing of the 200-line raw string in `render_makefile()` is the root
cause — each new feature needs a corresponding edit that's easy to miss.

## Approach

Extract shared targets into `workbook/makefile_targets.py`. Each target is a
Python function parameterized by a `MakeContext` dataclass (paths, variable
names, product name). `render_makefile()` calls these functions instead of
inlining raw text.

The workbench `Makefile` itself is NOT refactored in this change — it
continues to define its targets directly. The shared module serves the
scaffold; the workbench Makefile is a future consumer.

## Architecture

```
workbook/makefile_targets.py   ← canonical target builders
    │
    └── scripts/new_product.py  ← render_makefile() calls it
```

### `MakeContext` dataclass

```python
@dataclass(frozen=True)
class MakeContext:
    manage: str = "$(MANAGE)"
    contract: str = "$(CONTRACT)"
    core: str = "$(CORE)"
    bundle_out: str = "$(BUNDLE_OUT)"
    view_manifest: str = "$(VIEW_MANIFEST)"
    python: str = "$(PYTHON)"
    product_kebab: str | None = None
```

All fields have defaults so unit tests and the future workbench consumer can
use the module with minimal boilerplate.

### Module API — `workbook/makefile_targets.py`

Each function accepts a `MakeContext` and returns the Makefile text block
(target header + recipe lines). Variable assignments (`CONTRACT = ...`) and
the `.PHONY` line are returned separately.

```python
def phonies(ctx: MakeContext) -> list[str]:
    """Return all phony target names shared by scaffold and workbench."""

def variables_block(ctx: MakeContext) -> str:
    """Return common variable assignments (CONTRACT, CORE, BUNDLE_OUT, etc.)."""

def generate_models_block(ctx: MakeContext) -> str:
def generate_admin_block(ctx: MakeContext) -> str:
def generate_import_block(ctx: MakeContext) -> str:
def generate_view_manifest_block(ctx: MakeContext) -> str:
def generate_pipeline_manifest_block(ctx: MakeContext) -> str:
def generate_all_block(ctx: MakeContext) -> str:
def codegen_tooling_block(ctx: MakeContext) -> str:
    """diff-generated, generate-admin-light, post-generate, check-generated,
       snapshot-codegen, check-snapshots, drift-check"""
def import_blocks(ctx: MakeContext) -> str:
    """pull-bundle, load-data, push-data, import-preflight, import-apply,
       pull-preflight, pull-apply"""
def profile_blocks(ctx: MakeContext) -> str:
    """All profile-* targets (preflight, drive-folder, coda-corpus,
       cohort-corpus, phases 1-3)"""
def deploy_blocks(ctx: MakeContext) -> str:
    """docker-build, fly-launch, fly-volume, fly-secrets, fly-deploy, deploy"""
```

### `render_makefile()` becomes a thin wrapper

```python
def render_makefile(product_kebab: str) -> str:
    ctx = MakeContext(product_kebab=product_kebab)
    product_ctx = replace(ctx, core="backend/apps/core")

    preamble = r"""-include .env
...
"""
    # Header/preamble (env exports, venv vars, check-env) stays inline —
    # these are product-scaffold concerns, not shared.

    return (
        preamble
        + variables_block(product_ctx)
        + codegen_tooling_block(product_ctx)
        + generate_models_block(product_ctx)
        + generate_admin_block(product_ctx)
        + generate_import_block(product_ctx)
        + generate_view_manifest_block(product_ctx)
        + generate_pipeline_manifest_block(product_ctx)
        + generate_all_block(product_ctx)
        + import_blocks(product_ctx)
        + profile_blocks(product_ctx)
        + deploy_blocks(product_ctx)
    )
```

## Changes

### `workbook/makefile_targets.py` (new, ~120 lines)

- `MakeContext` dataclass with path/variable defaults
- `phonies()` — returns all shared phony names
- `variables_block()` — `CONTRACT`, `CORE`, `BUNDLE_OUT`, `VIEW_MANIFEST`, `DATE_STAMP`
- One builder function per target block listed above

### `scripts/new_product.py` (refactor)

- `render_makefile()` imports from `workbook.makefile_targets`
- Eliminates the ~180-line raw string body
- Drops the first duplicate `generate-view-manifest` (now only emitted once by `generate_view_manifest_block()`)
- `generate-all` automatically includes `generate-pipeline-manifest`
- Adds `import-preflight`, `import-apply`, `pull-preflight`, `pull-apply` targets
- Variables `CONTRACT`, `CORE`, `BUNDLE_OUT`, `VIEW_MANIFEST`, `DATE_STAMP` come from `variables_block()` instead of inline

### What stays inline in `render_makefile()`

- `.env` header comments
- `export` lines (product-specific env vars)
- `VENV`, `PYTHON`, `PIP`, `MANAGE` variable assignments
- `venv`, `install`, `install-dev-workbench`, `migrate`, `reset-migrations` targets (purely product-scaffold concerns)
- `check`, `validate-contract`, `validate`, `corpus-codegen-report`, `shell`, `bash`, `check-env` targets
- `chassis-gate` target (references `WORKBENCH` from product `.env`)
- Docker/Fly deployment preamble and variable assignments

## Verification

1. Run `make new-product PRODUCT=verify-test`, inspect generated Makefile:
   - `generate-view-manifest` appears exactly once
   - `generate-pipeline-manifest` target exists
   - `generate-all` includes `generate-pipeline-manifest` in prereqs
   - `import-preflight`, `import-apply`, `pull-preflight`, `pull-apply` exist
2. `make test` in workbench passes
3. `make new-product` still produces a valid, self-consistent Makefile
