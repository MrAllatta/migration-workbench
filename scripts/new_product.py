#!/usr/bin/env python3
"""Scaffold a product repository that embeds migration-workbench (farm/guitar-style layout)."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Ensure the project root is importable when this script is run directly.
_script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_script_dir.parent))

from workbook.makefile_targets import (
    MakeContext,
    phonies,
    full_targets_block,
    deploy_blocks,
)

PROVIDER_GOOGLE_SHEETS = "google_sheets"
PROVIDER_CODA = "coda"

PYTHON_IMAGE_DIGEST = (
    "sha256:ee710afcfb733f4a750d9be683cf054b5cd247b6c5f5237a6849ea568b90ab15"
)


def _validate_kebab(name: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", name):
        raise SystemExit(
            f"Invalid product name {name!r}: use lowercase kebab-case "
            "(e.g. jewelry, vizcarra-guitars)."
        )


def python_pkg_name(kebab: str) -> str:
    return kebab.replace("-", "_")


def model_class_prefix(kebab: str) -> str:
    parts = kebab.replace("-", "_").split("_")
    return "".join(p.title() for p in parts)


def write_file(path: Path, content: str, *, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        print(f"skip existing {path}")
        return
    path.write_text(content, encoding="utf-8")
    print(f"wrote {path}")


def copy_file(src: Path, dest: Path, *, force: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        print(f"skip existing {dest}")
        return
    shutil.copy2(src, dest)
    print(f"copied {dest}")


def _git_init_and_initial_commit(repo: Path) -> None:
    """Create a git repo and one commit so the scaffold has a clean baseline."""
    repo_s = str(repo.resolve())
    git = ("git", "-C", repo_s)

    def _run(
        args: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run((*git, *args), text=True, capture_output=True, **kwargs)

    try:
        has_git = _run(("rev-parse", "--git-dir"), check=False).returncode == 0
        if has_git:
            print(f"skip git commit: {repo} is already a git repository — scaffolded files are uncommitted")
            return

        init = _run(("init", "-b", "main"))
        if init.returncode != 0:
            print(
                f"warning: git init failed: {init.stderr.strip() or init.stdout}",
                file=sys.stderr,
            )
            return
        print(f"git init {repo}")

        add = _run(("add", "-A"))
        if add.returncode != 0:
            print(f"warning: git add failed: {add.stderr.strip()}", file=sys.stderr)
            return

        commit = subprocess.run(
            (
                "git",
                "-C",
                repo_s,
                "-c",
                "user.name=migration-workbench scaffold",
                "-c",
                "user.email=migration-workbench@local",
                "commit",
                "-m",
                "Initial scaffold from migration-workbench",
            ),
            text=True,
            capture_output=True,
        )
        if commit.returncode == 0:
            print(f"git commit initial scaffold in {repo}")
            return
        err = (commit.stderr or "").lower()
        if "nothing to commit" in err or "nothing added to commit" in err:
            print(f"git: nothing new to commit in {repo}")
            return
        print(f"warning: git commit failed: {commit.stderr.strip()}", file=sys.stderr)
    except FileNotFoundError:
        print("warning: git not found; skipped repository init", file=sys.stderr)


def render_manage_py() -> str:
    return '''#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
'''


def render_settings_py(user_model_name: str) -> str:
    # user_model_name e.g. JewelryUser
    return f"""import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.db.backends.signals import connection_created

from migration_workbench.sqlite_path import resolve_sqlite_database_path

BASE_DIR = Path(__file__).resolve().parent.parent
APPS_DIR = BASE_DIR / "apps"
if str(APPS_DIR) not in sys.path:
    sys.path.insert(0, str(APPS_DIR))

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-local-dev-key-change-me",
)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
PRODUCTION = os.environ.get("DJANGO_PRODUCTION", "0") == "1"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "connectors",
    "profiler",
    "importer",
    "workbook",
    "deployment",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {{
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {{
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        }},
    }},
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {{
    "default": {{
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": resolve_sqlite_database_path(BASE_DIR, os.environ.get("SQLITE_PATH")),
    }}
}}


def _configure_sqlite_pragmas(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")


connection_created.connect(_configure_sqlite_pragmas)

AUTH_PASSWORD_VALIDATORS = [
    {{"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"}},
    {{"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"}},
    {{"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"}},
    {{"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"}},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {{
    "default": {{
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    }},
    "staticfiles": {{
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }},
}}

if PRODUCTION:
    if DEBUG:
        raise ImproperlyConfigured("DJANGO_PRODUCTION=1 requires DJANGO_DEBUG=0.")
    if SECRET_KEY == "django-insecure-local-dev-key-change-me":
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production.")
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set in production.")
    if not CSRF_TRUSTED_ORIGINS:
        raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS must be set in production.")

    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "core.{user_model_name}"
"""


def render_urls_py() -> str:
    return """from django.contrib import admin
from django.urls import path
from migration_workbench.views import healthz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    path("healthz/", healthz),
]
"""


def render_wsgi_py() -> str:
    return '''"""
WSGI config for product backend.

It exposes the WSGI callable as a module-level variable named ``application``.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
'''


def render_apps_py(model_prefix: str) -> str:
    return f"""from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    label = "core"
    verbose_name = "{model_prefix} core"
"""


def render_models_py(model_prefix: str, user_model_name: str) -> str:
    return f"""from django.contrib.auth.models import AbstractUser
from django.db import models


class {user_model_name}(AbstractUser):
    pass
"""


def render_pyproject_toml(project_name: str, py_name: str) -> str:
    return f"""[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{py_name}"
version = "0.1.0"
description = "{project_name} — Django product with migration-workbench"
requires-python = ">=3.11"
dependencies = [
  "Django>=5.0,<6.0",
  "migration-workbench>=0.1.0,<1",
]

[project.optional-dependencies]
dev = [
  "pytest",
  "pytest-django",
]

[tool.setuptools]
py-modules = []

[tool.pytest.ini_options]
testpaths = ["backend"]
python_files = ["tests.py", "test_*.py", "*_tests.py"]
DJANGO_SETTINGS_MODULE = "config.settings"
"""


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
FLY_APP ?=""" + f" {product_kebab}-production" + "\n"
    )


def render_env_example(provider: str) -> str:
    shared_env = """DJANGO_DEBUG=1
DJANGO_SECRET_KEY=replace-me
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
# Production: set CSRF_TRUSTED_ORIGINS=https://your-app.fly.dev

# SQLite: relative paths resolve under backend/; use absolute path in production (e.g. /data/db.sqlite3).
SQLITE_PATH=db.sqlite3
"""

    if provider == PROVIDER_CODA:
        provider_env = """
# Coda profiling (see migration-workbench docs/coda.md).
# Never commit real tokens.
# CODA_API_TOKEN=
CODA_CORPUS_CONFIG=config/coda_corpus.json
# Comma-separated Coda doc IDs, positional with the docs array in the corpus config.
CODA_DOC_IDS=replace-me
# Optional override for make profile-coda-corpus output dir.
CODA_CORPUS_OUT_DIR=build/coda_corpus
# Optional pull_bundle config path for Coda-based bundles.
CODA_LIVE_CONFIG=config/coda_live.local.json
"""
    else:
        provider_env = """

# Google Drive / Sheets profiling (ADC + SA impersonation — see migration-workbench docs/google-auth.md).
GOOGLE_IMPERSONATE_SERVICE_ACCOUNT=replace-me
# Required for make profile-preflight / make profile-drive-folder.
COHORT_CORPUS_CONFIG=config/cohort_corpus.json
# Google Drive folder id for the corpus root folder.
DRIVE_FOLDER_ID=replace-me
# Optional override for make profile-drive-folder output.
DRIVE_FOLDER_OUT=data/profile_snapshots/drive_tree.json
"""

    return (
        shared_env
        + provider_env
        + """

# Optional chassis development only: WORKBENCH=/absolute/path/to/migration-workbench
"""
    )


def _render_agents_profile_section(provider: str) -> str:
    if provider == PROVIDER_CODA:
        return """### Profiling (read-only discovery)

Run after setting up `.env`. These commands inspect source data and produce artifacts that inform schema design — they never mutate Django models.

1. **Set `CODA_API_TOKEN`** and **`CODA_DOC_IDS`** in `.env` (see migration-workbench `docs/coda.md`).
2. **Configure heuristics** in `config/coda_corpus.json` with table score rules and column selectors.
3. **Run corpus profile:**
   ```bash
   make profile-coda-corpus
   ```
   Reads `CODA_CORPUS_CONFIG` from `.env`; outputs go to `CODA_CORPUS_OUT_DIR` (default: `build/coda_corpus`).

**Review the output** — profiler artifacts (JSON profiles, structure snapshots, formula inventories) land under the output directory. Read them before moving to schema design.
"""
    return """### Profiling (read-only discovery)

Run after setting up `.env`. These commands inspect source data and produce artifacts that inform schema design — they never mutate Django models.

Profiling follows a **3-phase workflow** to avoid expensive API calls until heuristic tuning is complete:

#### Phase 1 — Discovery + tab selection

1. **Set `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`** and **`DRIVE_FOLDER_ID`** in `.env` (see migration-workbench `docs/google-auth.md`).
2. **Run preflight** (validates config, checks Drive access):
   ```bash
   make profile-preflight
   ```
3. **Map the Drive folder** (enumerates workbooks):
   ```bash
   make profile-drive-folder
   ```
   Output: `DRIVE_FOLDER_OUT` (default: `data/profile_snapshots/drive_tree.json`).
4. **Inspect the drive tree, then configure heuristics** in `config/cohort_corpus.json` — review the tree output to set `workbook_id_regex`, `in_scope_workbooks`, tab score rules, and column selectors based on actual workbook names and structure. Available `tab_score` heuristics: `operational_tokens`, `reference_tokens`, `support_tokens`, `derived_tokens`, `tab_exclude_patterns` (regex-based tab blocking), `expansion_formula_penalty` and `expansion_formula_threshold` (formula-heavy tab downranking).
5. **Run Phase 1** (discovers workbooks, lists tabs, scores and selects, then stops before deep grid fetches):
   ```bash
   make profile-cohort-corpus-phase1
   ```
   Outputs go to `COHORT_CORPUS_OUT_DIR` (default: `data/profile_snapshots/cohort_corpus`). The key artifact is `tab_selection_<date>.json` — review which tabs were auto-selected.

#### Phase 2 — Heuristic refinement

After reviewing Phase 1 output, tune `tab_score_heuristics` and `tab_selection_overrides` in `config/cohort_corpus.json`, then re-run scoring without any API calls:

```bash
make profile-cohort-corpus-phase2
```

This re-reads the broad coverage data from disk and re-applies scoring/selection with the updated heuristics. Iterate as needed — no Drive or Sheets API calls are made.

#### Phase 3 — Deep profiling

Once tab selection is final (hand-edit `tab_selection_<date>.json` if desired), run the deep grid fetches and column scoring:

```bash
make profile-cohort-corpus-phase3
```

This skips Drive discovery and tab listing, going straight to deep profiling of the selected tabs.

**Review the full output** — profiler artifacts include column types, formula pattern classification (`raw`, `row_formula`, `expansion_formula`, `hybrid`, `empty`), and header snapshots. Read them before moving to schema design.
"""


def render_agents_md(provider: str) -> str:
    return f"""# Agent notes

## Repo identity

This is a **scaffolded product repository** built on [migration-workbench](https://pypi.org/project/migration-workbench/). It embeds the workbench as a PyPI dependency and provides its own Django project at `backend/` (`config.settings`, `manage.py`, `apps/core/`). The workbench apps (`connectors`, `profiler`, `importer`, `workbook`) are listed in `INSTALLED_APPS`.

Generated code (models, admin, import commands) lives under `backend/apps/core/`. Configuration and schema contracts live in `config/` and `docs/`.

## Setup & dev workflow

```bash
make install          # creates venv, installs product + migration-workbench from PyPI
make migrate          # makemigrations + migrate
make check            # Django system check
```

To use an editable workbench checkout instead of PyPI (for chassis co-development):
```bash
# Set WORKBENCH=/path/to/migration-workbench in .env, then:
make install-dev-workbench
```

To run the full workbench CI gate against that checkout:
```bash
make chassis-gate
```

## Environment basics

The Makefile loads `.env` via `-include .env` and exports select vars with `export VAR`. This has a practical consequence:

- `make <target>` — vars are available inside recipe shell commands.
- Raw `bash` — NOT available (.env is not sourced into the shell).

**For the agent:**

| Command | What it does |
|---------|-------------|
| `make check-env` | Verify critical `.env` vars are set (exit 1 if missing) |
| `make bash` | Drop into a bash shell with `.env` loaded |
| `grep ^KEY .env` | Check a value (read-only, safe) |

Never read or edit `.env` with file/write tools — it is gitignored and may contain secrets.

## Pipeline overview

Migration-workbench separates the work into five stages:

1. **Connectors** — provider adapters (Google Sheets / Coda) that authenticate and pull row data.
2. **Profiler** — read-only commands that inspect sources and write structure artifacts.
3. **Importer** — normalizes source rows into CSV bundles, then runs preflight/apply via `BaseImportCommand` subclasses.
4. **Workbook** — codegen that transforms profiler output + bundle config into schema contract YAML, generates Django models/admin/import code, and produces a view-manifest from bundle structure metadata that feeds the admin scaffold for richer UI configuration. Optionally, a discovery interview captures role ownership and workflow semantics.
5. **Deployment** — validates deployment manifests, records releases, deploys to Fly.io.

The governing workflow is the **Schema Design Loop** (see migration-workbench `docs/schema-design-loop.md`): **Profile → Observe → Draft → Decide → Author config → Author view manifest → Author importer → Gate → Drift check**.

{_render_agents_profile_section(provider)}

## Schema design & code generation

After profiling, the schema design loop requires human judgment at several points. The agent's job is to facilitate — never silently decide.

### Draft schema contract

Review profiler output, then build a schema contract YAML (`config/contract.yaml`) that maps source tabs to Django models and columns to fields. The workbench `scaffold_workbook_schema` command can produce a v1.0 draft from profile artifacts.

**Decisions to bring to the human:**
- Which source tabs become Django models? What names?
- Which columns become fields? What Django field types?
- Which columns reference other entities (FK relationships)?
- Which columns are formula-derived (computed, not stored)?

### Harden the contract

After the human reviews and edits the v1.0 draft, create a v1.1 hardened contract with explicit FK targets, field overrides, and import configuration.

### Generate Django code

Once the contract is hardened:

```bash
make generate-models   # backend/apps/core/models.py
make generate-admin    # backend/apps/core/admin.py
make generate-import   # backend/apps/core/imports.py
make generate          # all three
```

**After generation, ask the human to review the output** before migrating.

```bash
make migrate
make check
```

### Generate view manifest

After the contract is hardened and a bundle has been pulled from the source:

```bash
make pull-bundle           # produces build/bundle/structure.json
make generate-view-manifest  # config/view-manifest.yaml
```

The view-manifest YAML captures UI/workflow metadata per source tab:
`editable_fields` (non-formula columns), `computed_fields` (formula columns),
`filterable_by` (dropdown-validated columns), and an inferred `status_field`.
It also records `workflow_hints.tab_sequence` from tab position.

**Review the view manifest** before proceeding — verify entity binding, editable
vs computed splits, and status field detection. The manifest can be hand-edited.

Regenerate the admin to incorporate manifest hints:

```bash
make generate-admin   # now produces richer admin.py
```

### Discovery interview (optional)

To capture role ownership, status semantics, and weekly actions from operators:

```bash
make generate-discovery-interview   # writes build/discovery-interview.md
```

Have the operator fill in the Markdown answers, then:

```bash
make merge-discovery-notes  # patches view-manifest.yaml, writes build/discovery-summary.md
```

The merged manifest feeds `make generate-admin` for richer admin configuration
(role-appropriate `list_filter`, per-view notes in `readonly_fields`, etc.).

## Import pipeline

### Pull a bundle from source
```bash
# Set SOURCE_CONFIG in .env pointing to your provider config, then:
make pull-bundle
```

### Validate before applying
```bash
make import-preflight   # validate-only mode (transaction rolled back)
```

### Apply
```bash
make import-apply
```

### Combined pull + import
```bash
make pull-preflight   # pull then validate
make pull-apply       # pull then apply
```

Always **preflight before apply**. Keep bundle YAML and importer subclasses in this repo; avoid patching workbench internals.

## Deployment

See migration-workbench `docs/deployment.md` for the full runbook. In brief:

- **Docker:** `docker build -t product .` (uses the repo `Dockerfile`)
- **Fly.io:** Set Fly secrets (`DJANGO_SECRET_KEY`, `CODA_API_TOKEN` or Google SA, etc.), deploy via `flyctl deploy`
- **Database:** SQLite replicated via Litestream to Tigris object storage
- **Entrypoint:** `scripts/entrypoint_product.sh` handles migrations + Litestream + Gunicorn

## Human judgment points

These are the decisions the agent **must not make autonomously**. When reaching any of these points, pause and ask the human:

| # | Stage | Decision needed |
|---|-------|-----------------|
| 0 | Environment | Verify `.env` is configured. Run `make check-env`. Confirm DRIVE_FOLDER_ID, GOOGLE_IMPERSONATE_SERVICE_ACCOUNT (or CODA_API_TOKEN), and WORKBENCH (if dev mode) are set. |
| 1 | Post-profile | Review profiler output. Which tabs are in scope? Which are ignored? |
| 2 | Schema draft | What should each Django model be named? (source tab → entity name) |
| 3 | Schema draft | For each column: is it a stored field, a computed property, or irrelevant? |
| 4 | Schema draft | What Django field type fits? (CharField vs TextField? IntegerField vs DecimalField? DateField vs DateTimeField?) |
| 5 | Schema draft | Which columns are FK references to other entities? What is the target model + field? |
| 6 | Schema draft | Which columns have a fixed set of values (choices)? What are the valid values? |
| 7 | Schema draft | What should the import key be (natural key for idempotent re-import)? |
| 8 | Contract hardening | Review the v1.0 draft. Approve, modify, or reject each suggested model and field. |
| 9 | Post-codegen | Review generated `models.py`, `admin.py`, `imports.py` before committing. |
| 10 | Pre-import | Confirm import config (default values, alias mappings, row filters, transform rules). |
| 11 | Post-import | Review summary JSON output. Are row counts and error counts expected? |
| 12 | UI/Admin | Which fields should appear in `list_display`, `list_filter`, `search_fields`? Which are readonly? Which are editable? |
| 13 | Status/workflow | If there is a status field, what are the valid states and transitions? |
| 14 | Deployment | Confirm Fly app name, secrets, and Litestream replica bucket before deploy. |
| 15 | View manifest | Review entity binding, editable vs computed fields, status field detection, and tab sequence in the generated view manifest. |
| 16 | Discovery | Review role hints, weekly actions, and per-view notes from the merged discovery interview. |

## Provider authentication

- **Google Sheets:** Application Default Credentials (ADC) with service account impersonation (`GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`). See workbench `docs/google-auth.md`.
- **Coda:** `CODA_API_TOKEN` in `.env`. See workbench `docs/coda.md`.
- Profile heuristic config files (`.json` in `config/`) are tracked. Secrets (`DRIVE_FOLDER_ID`, `CODA_DOC_IDS`) go in `.env`.

## Naming & style

### Core rule: no throwaway labels

Never use single-letter names, alphabetic slice labels, or abstract positional placeholders in code, comments, or docstrings.

| Banned | Use instead |
|--------|-------------|
| `A`, `B`, `C`, `D` (standalone labels) | `source_contract`, `target_manifest`, `bundle_config`, `schema_contract` |
| `x`, `y`, `n`, `m`, `i` (loop/scratch) | `tab_row`, `column_entry`, `field_name`, `row_index`, `tab_count` |
| `tmp`, `res`, `val`, `obj` | `parsed_date`, `contract_dict`, `field_slug`, `worksheet_tab` |
| Type vars `T`, `K`, `V` | `RowT`, `ModelT`, `ConfigT`, `KeyT`, `ValueT` |

### Domain vocabulary

Draw identifiers, docstring references, and comments from the project's established vocabulary:

| Concept | Preferred names |
|---------|-----------------|
| Raw worksheet data pulled from a source | `bundle`, `bundle_tab`, `tab_row`, `bundle_config` |
| Profiler output characterising column types | `profile_doc`, `doc_profile`, `column_profile`, `profiler_output` |
| Structural map of tabs and columns | `structure`, `structure_artifact`, `tab_entry`, `column_entry` |
| Field/model name suggestions for Django | `schema_contract`, `contract_table`, `suggested_model_name`, `suggested_field_name`, `field_slug` |
| UI and workflow concerns for admin scaffolding | `view_manifest`, `view_entry`, `workflow_hints` |
| Generated Django model skeleton | `model_scaffold`, `admin_scaffold` |
| Discovery interview artefacts | `discovery_interview`, `discovery_summary`, `role_hints`, `weekly_actions`, `view_notes` |

### Code generation context

Most code in this repo is **generated** by workbench commands (`generate_models`, `generate_admin`, `generate_import`). When editing generated code, preserve its structural patterns and only make targeted changes. If a change requires modifying every generated file, revisit the schema contract instead.

## Patching upstream (migration-workbench)

When farm encounters a gap or bug in migration-workbench, fix it upstream rather than working around it in farm code.

### Decision criteria

| Situation | Where to fix |
|-----------|-------------|
| Bug in a workbench command, management command, template, or utility | Workbench |
| Missing feature that another scaffolded product would also need | Workbench |
| Column type inference misfires for a source format | Workbench |
| Import transform pipeline needs a new hook point | Workbench |
| Codegen output is malformed or incomplete | Workbench |
| Farm-specific display logic (admin config, list display, custom views) | Farm |
| Farm-specific data validation or business rules | Farm |
| One-off import transform for a unique source quirk | Farm |
| Schema contract or view manifest fields (the "what" not the "how") | Farm |

General principle: if the fix lives in workbench's domain (connectors, profiler, importer, workbook, codegen), it belongs in workbench. If it's specific to how farm uses the output, keep it in farm.

### Workflow

**1. Pinpoint the gap.** Identify the workbench module or management command involved. Note the symptom and the expected behavior.

**2. Switch to an editable checkout.**

```bash
# Add to .env (gitignored):
WORKBENCH=/path/to/migration-workbench

# Reinstall workbench from the checkout (editable):
make install-dev-workbench
```

**3. Fix upstream.** Edit files under `$WORKBENCH`. Because pip installed it in editable mode, changes take effect immediately — rerun the farm workflow that exposed the gap.

**4. Verify in farm.**

```bash
make check
```
Also rerun the specific farm command or workflow that triggered the discovery.

**5. Run the workbench gate.**

```bash
make chassis-gate
```
This runs the workbench repo's own test suite (lint, typecheck, pytest). Gate must pass before upstream PR.

**6. Commit and PR.**

In the `$WORKBENCH` checkout:
```
git checkout -b fix/descriptive-branch-name
git add <relevant-files>
git commit -m "fix(area): concise description of the fix"
```

Open a PR at https://github.com/anomalyco/migration-workbench. Include:
- What the gap was (describe the farm workflow that exposed it)
- What the fix does
- How it was verified (farm workflow + chassis gate)

**7. Cut back to PyPI after release.** Once the fix ships to PyPI:

```bash
# Bump the lower bound in pyproject.toml:
#   "migration-workbench>=<new-version>,<1"
make install          # reverts to PyPI
make check            # confirm nothing broke
```

### Version discipline

| Phase | Workbench source | Mechanism |
|-------|-----------------|-----------|
| Normal development | PyPI (as declared in pyproject.toml) | `make install` |
| Active patching | Local editable checkout | `make install-dev-workbench` + `WORKBENCH` in `.env` |
| Post-release | PyPI at the new version | `make install` (after bumping pyproject.toml) |

The editable checkout is **development-only**. CI and production always install from PyPI via the version pin in `pyproject.toml`.

### Anti-patterns

- **Don't vendor workbench code into farm.** No copying modules, no monkey-patching workbench internals. It creates a drift problem.
- **Don't create a permanent fork.** Farm should always consume workbench as a dependency, not a submodule or fork.
- **Don't pin to a git SHA in pyproject.toml.** That breaks standard pip installs and makes the package unfriendly. Use the editable checkout locally; wait for a release for CI/deployment.
- **Don't skip the chassis gate.** A fix that passes farm but breaks workbench's own tests will be rejected upstream.
"""


def render_readme_profile_section(provider: str) -> str:
    if provider == PROVIDER_CODA:
        return """## Discovery profiling from `.env`

Set these in `.env` before Coda corpus profiling:

```bash
CODA_CORPUS_CONFIG=config/coda_corpus.json
CODA_DOC_IDS=replace-with-comma-separated-doc-ids
CODA_CORPUS_OUT_DIR=build/coda_corpus  # optional (defaults to this path)
```

Then run:

```bash
make profile-coda-corpus
```

`make profile-coda-corpus` reads `CODA_CORPUS_CONFIG` and `CODA_DOC_IDS` from `.env`.
"""
    return """## Discovery profiling from `.env`

Set these in `.env` before Drive folder discovery:

```bash
COHORT_CORPUS_CONFIG=config/cohort_corpus.json
DRIVE_FOLDER_ID=replace-with-drive-folder-id
DRIVE_FOLDER_OUT=data/profile_snapshots/drive_tree.json  # optional (defaults to this path)
```

Then run:

```bash
make profile-preflight
make profile-drive-folder
```

`make profile-preflight` and `make profile-drive-folder` read `COHORT_CORPUS_CONFIG` and `DRIVE_FOLDER_ID` from `.env`.
"""


def render_readme_md(project_name: str, provider: str) -> str:
    profile_section = render_readme_profile_section(provider)
    return f"""# {project_name}

Django product repository built on **[migration-workbench](https://pypi.org/project/migration-workbench/)** — profiler, importer chassis, and workbook tooling for spreadsheet/Coda → app migrations.

## Quickstart

```bash
make install          # editable product package; migration-workbench from PyPI
make migrate && make check
```

Optional chassis development: set `WORKBENCH` in `.env` to a migration-workbench checkout, then `make install-dev-workbench` after `make install` to use that checkout instead of PyPI, or `make chassis-gate` to run the workbench repo gate.

{profile_section}

## Documentation

| Doc | Purpose |
|-----|---------|
| This README | Orientation |
| [docs/schema-contract.md](docs/schema-contract.md) | Entity and mapping decisions (fill in) |
| [docs/operator.md](docs/operator.md) | Routine commands and operational checklist |

Upstream chassis documentation lives with **[migration-workbench on PyPI](https://pypi.org/project/migration-workbench/)** — see package metadata for the source repository and files such as `docs/architecture.md`, `docs/deployment.md`, and `docs/schema-design-loop.md`.

## Layout

- `backend/` — Django project (`config.settings`, `manage.py`, `apps/core/`).
- `Dockerfile` / `scripts/entrypoint_product.sh` — Fly + SQLite + Litestream compatible image.

"""


def render_operator_md(project_name: str) -> str:
    return f"""# Operator notes — {project_name}

Single place for routine commands and decisions that do not belong in code.

## Local development

```bash
make install
make migrate
make check
```

## Profiling (read-only)

Set **`GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`** in `.env` when profiling Google Drive / Sheets with ADC (see migration-workbench **`docs/google-auth.md`**). Store artifacts under **`data/profile_snapshots/`** (gitignore large outputs if needed).

**Google Sheets multi-workbook corpus:** follow migration-workbench **`docs/google-corpus.md`** — `profile_preflight`, `profile_drive_folder`, inspect tree output to configure `in_scope_workbooks` and `workbook_id_regex`, then `profile_cohort_corpus`. Set `COHORT_CORPUS_CONFIG` and `DRIVE_FOLDER_ID` in `.env`; `make profile-preflight`, `make profile-drive-folder`, and `make profile-cohort-corpus` read them from the environment exported by the generated Makefile. Optionally set `DRIVE_FOLDER_OUT` and `COHORT_CORPUS_OUT_DIR` to override output paths.

Profiling uses a **3-phase workflow** to avoid expensive API calls during heuristic tuning:
- **Phase 1** (`make profile-cohort-corpus-phase1`): discovery + tab selection only, stops before deep grid fetches. Review `tab_selection_<date>.json`.
- **Phase 2** (`make profile-cohort-corpus-phase2`): re-run heuristics from broad coverage with no API calls. Iterate on `cohort_corpus.json` (token lists, `tab_exclude_patterns`, `expansion_formula_penalty`), then re-run.
- **Phase 3** (`make profile-cohort-corpus-phase3`): deep profile from hand-edited `tab_selection_<date>.json`. Output includes formula pattern classification per column.

**Coda:** migration-workbench **`docs/coda.md`**; set `CODA_CORPUS_CONFIG` and `CODA_DOC_IDS` in `.env`, then run `make profile-coda-corpus`.

## Imports

- Run validate-only / preflight before apply.
- Keep bundle YAML and importer subclasses in this repo; avoid editing workbench internals for client rules.

## Deploy

Fly secrets, Litestream, and CI/CD follow the same patterns as the workbench — see **migration-workbench** `docs/deployment.md` and your space entry in `deploy/spaces.yml` when wired.

## Log

(Add dated entries: imports run, profile refreshes, deploys, incidents.)
"""


def render_schema_contract_md(project_name: str) -> str:
    return f"""# Schema contract — {project_name}

Living document for entities, attributes, and sheet/tab mapping. Align with the **schema design loop** in migration-workbench (`docs/schema-design-loop.md`).

## Sources

- Profile snapshots: `data/profile_snapshots/`
- Bundle configs: `bundles/` (when present)

## Entities

(Add sections per entity: purpose, source tabs, key columns, formulas, FK targets.)

## Decisions

- Lift / modify / rebuild per area (record rationale).

## Drift

(Re-profile after source changes; note date and what changed.)
"""


def render_raw_notes_readme() -> str:
    return """# Raw client notes

Drop unedited exports, emails, scratch markdown, or other source material here.

Files in this directory are **not tracked** (see root `.gitignore`). Copy distilled facts into `docs/schema-contract.md`, `docs/operator.md`, or corpus config as they are validated.
"""


def render_gitignore() -> str:
    return """.venv/
__pycache__/
*.py[cod]
*$py.class
*.sqlite3
backend/db.sqlite3
backend/staticfiles/
.env
config/*.local.json
data/**
!data/raw_notes/
!data/raw_notes/README.md
dist/
*.egg-info/
.pytest_cache/
.mypy_cache/
"""


def render_dockerfile() -> str:
    return f"""# syntax=docker/dockerfile:1
# Product image: backend layout, migration-workbench from PyPI, Litestream-ready entrypoint.
# Pin digest: docker buildx imagetools inspect python:3.11-slim-bookworm

ARG PYTHON_IMAGE_DIGEST={PYTHON_IMAGE_DIGEST}

FROM python@${{PYTHON_IMAGE_DIGEST}} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PIP_NO_CACHE_DIR=1 \\
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY backend ./backend
COPY scripts ./scripts

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip setuptools wheel \\
    && pip install --no-cache-dir .

RUN DJANGO_SECRET_KEY=dummy-build-only-collectstatic DJANGO_DEBUG=0 \\
    DJANGO_SETTINGS_MODULE=config.settings \\
    python backend/manage.py collectstatic --noinput


FROM python@${{PYTHON_IMAGE_DIGEST}} AS runtime

ARG LITESTREAM_VERSION=v0.3.13
ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \\
    && apt-get install -y --no-install-recommends ca-certificates curl \\
    && curl -fsSL "https://github.com/benbjohnson/litestream/releases/download/${{LITESTREAM_VERSION}}/litestream-${{LITESTREAM_VERSION}}-linux-amd64.tar.gz" \\
        | tar -xz -C /usr/local/bin \\
    && chmod +x /usr/local/bin/litestream \\
    && test "$(/usr/local/bin/litestream version | tr -d '\\n')" = "${{LITESTREAM_VERSION}}" \\
    && apt-get purge -y curl \\
    && apt-get autoremove -y \\
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app

RUN groupadd --gid "${{APP_GID}}" app \\
    && useradd --uid "${{APP_UID}}" --gid app --no-create-home --shell /usr/sbin/nologin app \\
    && mkdir -p /data /data/media \\
    && chown -R app:app /data \\
    && chown -R app:app /app \\
    && chmod +x /app/scripts/entrypoint_product.sh

USER app

WORKDIR /app/backend

ENV HOME=/tmp
ENV DJANGO_SETTINGS_MODULE=config.settings
ENV WSGI_APP=config.wsgi:application
ENV SQLITE_PATH=/data/db.sqlite3

EXPOSE 8080

CMD ["/app/scripts/entrypoint_product.sh"]
"""


def scaffold_config_templates(
    output_dir: Path, script_dir: Path, provider: str, *, force: bool
) -> None:
    if provider == PROVIDER_CODA:
        copy_file(
            script_dir.parent / "example_data" / "coda_corpus.example.json",
            output_dir / "config" / "coda_corpus.json",
            force=force,
        )
        copy_file(
            script_dir.parent / "docs" / "examples" / "coda-live-config.example.json",
            output_dir / "config" / "coda_live.local.json",
            force=force,
        )
        return

    copy_file(
        script_dir.parent / "example_data" / "cohort_corpus.example.json",
        output_dir / "config" / "cohort_corpus.json",
        force=force,
    )


def render_deploy_manifest(product_kebab: str) -> str:
    """Render a minimal deploy/spaces.yml for the scaffolded product."""
    return f"""version: 1

profiles:
  default:
    cpu:
      cores: 1
      type: shared
    memory_mb: 256
    volume_gb: 1

replication_defaults:
  provider: tigris
  bucket_env: LITESTREAM_BUCKET
  snapshot_interval_minutes: 60
  retention_days: 14

spaces:
  {product_kebab}:
    owner: your-org
    project: {product_kebab}
    profile: default
    provider:
      type: fly
      primary_region: ewr
      regions:
        - ewr
      app_name_template: "{product_kebab}-{{environment}}"
    build:
      dockerfile: Dockerfile
      context: .
    runtime:
      internal_port: 8080
      processes:
        web: /app/scripts/entrypoint_product.sh
        release: python manage.py migrate
      healthcheck_path: /healthz
      healthcheck_timeout_s: 60
    storage:
      sqlite_path: /data/db.sqlite3
      media_path: /data/media
    replication:
      litestream_enabled: true
      replica_path_template: "{product_kebab}/{{environment}}"
    backup:
      predeploy_checkpoint:
        required: true
        method: litestream
      retention_days: 14
    secrets:
      required:
        - DJANGO_SECRET_KEY
        - DJANGO_ALLOWED_HOSTS
    environment:
      required:
        - SQLITE_PATH
    environments:
      production:
        branch_pattern: main
"""


def scaffold(
    product_kebab: str, output_dir: Path, provider: str, *, force: bool
) -> None:
    _validate_kebab(product_kebab)
    py_name = python_pkg_name(product_kebab)
    prefix = model_class_prefix(product_kebab)
    user_model_name = f"{prefix}User"

    script_dir = Path(__file__).resolve().parent
    entrypoint_src = script_dir / "entrypoint_product.sh"

    files: list[tuple[str, str]] = [
        ("backend/manage.py", render_manage_py()),
        ("backend/config/__init__.py", ""),
        ("backend/config/settings.py", render_settings_py(user_model_name)),
        ("backend/config/urls.py", render_urls_py()),
        ("backend/config/wsgi.py", render_wsgi_py()),
        ("backend/apps/__init__.py", ""),
        ("backend/apps/core/__init__.py", ""),
        ("backend/apps/core/apps.py", render_apps_py(prefix)),
        ("backend/apps/core/models.py", render_models_py(prefix, user_model_name)),
        ("backend/apps/core/migrations/__init__.py", ""),
        ("pyproject.toml", render_pyproject_toml(product_kebab, py_name)),
        ("Makefile", render_makefile(product_kebab)),
        (".env.example", render_env_example(provider)),
        ("AGENTS.md", render_agents_md(provider)),
        ("README.md", render_readme_md(product_kebab, provider)),
        ("docs/operator.md", render_operator_md(product_kebab)),
        ("docs/schema-contract.md", render_schema_contract_md(product_kebab)),
        ("data/raw_notes/README.md", render_raw_notes_readme()),
        (".gitignore", render_gitignore()),
        ("Dockerfile", render_dockerfile()),
        ("deploy/spaces.yml", render_deploy_manifest(product_kebab)),
    ]

    for rel, content in files:
        write_file(output_dir / rel, content, force=force)

    copy_file(
        entrypoint_src, output_dir / "scripts" / "entrypoint_product.sh", force=force
    )
    run_import_src = script_dir / "run_import.sh"
    if run_import_src.exists():
        copy_file(run_import_src, output_dir / "scripts" / "run_import.sh", force=force)

    scaffold_config_templates(output_dir, script_dir, provider, force=force)

    migrations_dir = output_dir / "backend" / "apps" / py_name / "migrations"
    initial_migration = migrations_dir / "0001_initial.py"
    if initial_migration.exists():
        initial_migration.unlink()

    manage = output_dir / "backend" / "manage.py"
    if manage.exists():
        manage.chmod(manage.stat().st_mode | 0o111)

    _git_init_and_initial_commit(output_dir)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "product",
        help="Product name in kebab-case (e.g. jewelry)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: ../<product> relative to cwd)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files",
    )
    provider_group = parser.add_mutually_exclusive_group()
    provider_group.add_argument(
        "--google-sheets",
        action="store_true",
        help="Scaffold Google Sheets profile config files and env defaults (default).",
    )
    provider_group.add_argument(
        "--coda",
        action="store_true",
        help="Scaffold Coda profile config files and env defaults.",
    )
    args = parser.parse_args(argv)
    provider = PROVIDER_CODA if args.coda else PROVIDER_GOOGLE_SHEETS

    out = args.output_dir
    if out is None:
        out = (Path.cwd().parent / args.product).resolve()
    else:
        out = args.output_dir.expanduser().resolve()

    scaffold(args.product, out, provider, force=args.force)
    print(f"\nDone. Next: cd {out} && make install && make migrate && make check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
