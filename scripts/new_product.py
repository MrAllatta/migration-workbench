#!/usr/bin/env python3
"""Scaffold a product repository that embeds migration-workbench (farm/vizcarra-style layout)."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

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
        if not has_git:
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


def render_makefile() -> str:
    return r"""-include .env
# migration-workbench is installed from PyPI via pyproject.toml when you run `make install`.
# Setting WORKBENCH in .env does not change that — use `make install-dev-workbench` after `make install`
# to replace the PyPI package with an editable install from your checkout (same venv as this project).
# WORKBENCH is also required for `chassis-gate` (runs the workbench repo gate in that checkout).
export WORKBENCH

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(PYTHON) -m pip
MANAGE = $(PYTHON) backend/manage.py

.PHONY: venv install install-dev-workbench migrate check shell chassis-gate profile-preflight profile-drive-folder profile-coda-corpus profile-cohort-corpus

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

check:
	$(MANAGE) check

shell:
	$(MANAGE) shell

chassis-gate:
	@test -n "$(WORKBENCH)" || (echo >&2 "Set WORKBENCH in .env to your migration-workbench checkout"; exit 1)
	$(MAKE) -C "$(WORKBENCH)" chassis-gate

profile-preflight:
	DB_ENGINE=sqlite $(MANAGE) profile_preflight --config "$${COHORT_CORPUS_CONFIG:?COHORT_CORPUS_CONFIG required}"

profile-drive-folder:
	DB_ENGINE=sqlite $(MANAGE) profile_drive_folder --config "$${COHORT_CORPUS_CONFIG:?COHORT_CORPUS_CONFIG required}" --out "$${DRIVE_FOLDER_OUT:-data/profile_snapshots/drive_tree.json}"

profile-coda-corpus:
	DB_ENGINE=sqlite $(MANAGE) profile_coda_corpus --config "$${CODA_CORPUS_CONFIG:?CODA_CORPUS_CONFIG required}" --out-dir "$${CODA_CORPUS_OUT_DIR:-build/coda_corpus}"

profile-cohort-corpus:
	DB_ENGINE=sqlite $(MANAGE) profile_cohort_corpus --config "$${COHORT_CORPUS_CONFIG:?COHORT_CORPUS_CONFIG required}" --out-dir "$${COHORT_CORPUS_OUT_DIR:-build/cohort_corpus}"
"""


def render_env_example() -> str:
    return """DJANGO_DEBUG=1
DJANGO_SECRET_KEY=replace-me
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
# Production: set CSRF_TRUSTED_ORIGINS=https://your-app.fly.dev

# SQLite: relative paths resolve under backend/; use absolute path in production (e.g. /data/db.sqlite3).
SQLITE_PATH=db.sqlite3

# Google Drive / Sheets profiling (ADC + SA impersonation — see migration-workbench docs/google-auth.md).
# GOOGLE_IMPERSONATE_SERVICE_ACCOUNT=mw-profiler@PROJECT.iam.gserviceaccount.com
# Required for make profile-preflight / make profile-drive-folder.
COHORT_CORPUS_CONFIG=config/cohort_corpus.local.json
# Optional override for make profile-drive-folder output.
DRIVE_FOLDER_OUT=data/profile_snapshots/drive_tree.json

# Optional chassis development only: WORKBENCH=/absolute/path/to/migration-workbench
"""


def render_agents_md() -> str:
    return """# Agent notes

- **Workbench:** `migration-workbench` is installed from **PyPI** via `make install`. Setting `WORKBENCH` in `.env` does not change that. After `make install`, run `make install-dev-workbench` to replace PyPI with an editable install from that checkout in this project's venv. `WORKBENCH` is also required for `make chassis-gate` (runs the gate in that checkout).
- **Runtime:** Prefer `make` from this repo root. Commands use **`.venv/bin/python backend/manage.py`** after `make install`.
- **Secrets:** `.env` is gitignored; never commit tokens or paste them into tracked files.
"""


def render_readme_md(project_name: str) -> str:
    return f"""# {project_name}

Django product repository built on **[migration-workbench](https://pypi.org/project/migration-workbench/)** — profiler, importer chassis, and workbook tooling for spreadsheet/Coda → app migrations.

## Quickstart

```bash
make install          # editable product package; migration-workbench from PyPI
make migrate && make check
```

Optional chassis development: set `WORKBENCH` in `.env` to a migration-workbench checkout, then `make install-dev-workbench` after `make install` to use that checkout instead of PyPI, or `make chassis-gate` to run the workbench repo gate.

## Discovery profiling from `.env`

Set these in `.env` before Drive folder discovery:

```bash
COHORT_CORPUS_CONFIG=config/cohort_corpus.local.json
DRIVE_FOLDER_OUT=data/profile_snapshots/drive_tree.json  # optional (defaults to this path)
```

Then run:

```bash
make profile-preflight
make profile-drive-folder
```

`COHORT_CORPUS_CONFIG` is the required folder-id discovery config consumed by both targets.

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

**Google Sheets multi-workbook corpus:** follow migration-workbench **`docs/google-corpus.md`** — `profile_preflight`, `profile_drive_folder`, then `profile_cohort_corpus` with a JSON config (`workbook_id_regex`, `in_scope_workbooks`, etc.). In `.env`, set required `COHORT_CORPUS_CONFIG` for `make profile-preflight`, `make profile-drive-folder`, and `make profile-cohort-corpus`; optionally set `DRIVE_FOLDER_OUT` and `COHORT_CORPUS_OUT_DIR` to override output paths.

**Coda:** migration-workbench **`docs/coda.md`**; multi-doc: `make profile-coda-corpus` with `CODA_CORPUS_CONFIG`.

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


def render_gitignore() -> str:
    return """.venv/
__pycache__/
*.py[cod]
*$py.class
*.sqlite3
backend/db.sqlite3
backend/staticfiles/
.env
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


def scaffold(product_kebab: str, output_dir: Path, *, force: bool) -> None:
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
        ("Makefile", render_makefile()),
        (".env.example", render_env_example()),
        ("AGENTS.md", render_agents_md()),
        ("README.md", render_readme_md(product_kebab)),
        ("docs/operator.md", render_operator_md(product_kebab)),
        ("docs/schema-contract.md", render_schema_contract_md(product_kebab)),
        (".gitignore", render_gitignore()),
        ("Dockerfile", render_dockerfile()),
    ]

    for rel, content in files:
        write_file(output_dir / rel, content, force=force)

    copy_file(
        entrypoint_src, output_dir / "scripts" / "entrypoint_product.sh", force=force
    )

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
    args = parser.parse_args(argv)

    out = args.output_dir
    if out is None:
        out = (Path.cwd().parent / args.product).resolve()
    else:
        out = args.output_dir.expanduser().resolve()

    scaffold(args.product, out, force=args.force)
    print(f"\nDone. Next: cd {out} && make install && make migrate && make check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
