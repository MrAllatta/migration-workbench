"""
Contract tests for WhiteNoise / static-files configuration.

Guards against accidental reversion of the staticfiles storage backend or middleware
order drift. These are the canonical strings from the project configuration contract:
  - Middleware: whitenoise.middleware.WhiteNoiseMiddleware immediately after
    django.middleware.security.SecurityMiddleware.
  - Static backend: whitenoise.storage.CompressedManifestStaticFilesStorage via
    STORAGES["staticfiles"]["BACKEND"] (Django 5+ style; no parallel STATICFILES_STORAGE).
  - Collected output directory: staticfiles (STATIC_ROOT = BASE_DIR / "staticfiles").
"""

from pathlib import Path

import pytest
from django.conf import settings


SECURITY_MW = "django.middleware.security.SecurityMiddleware"
WHITENOISE_MW = "whitenoise.middleware.WhiteNoiseMiddleware"
WHITENOISE_BACKEND = "whitenoise.storage.CompressedManifestStaticFilesStorage"


def test_whitenoise_middleware_present():
    assert WHITENOISE_MW in settings.MIDDLEWARE, (
        f"{WHITENOISE_MW!r} missing from MIDDLEWARE"
    )


def test_whitenoise_middleware_immediately_after_security():
    mw = settings.MIDDLEWARE
    sec_idx = mw.index(SECURITY_MW)
    wn_idx = mw.index(WHITENOISE_MW)
    assert wn_idx == sec_idx + 1, (
        f"{WHITENOISE_MW!r} must be immediately after {SECURITY_MW!r} "
        f"(positions: security={sec_idx}, whitenoise={wn_idx})"
    )


def test_storages_staticfiles_backend():
    backend = settings.STORAGES["staticfiles"]["BACKEND"]
    assert backend == WHITENOISE_BACKEND, (
        f"STORAGES['staticfiles']['BACKEND'] is {backend!r}; "
        f"expected {WHITENOISE_BACKEND!r}"
    )


def test_no_legacy_staticfiles_storage_setting():
    assert not hasattr(settings, "STATICFILES_STORAGE"), (
        "STATICFILES_STORAGE is set alongside STORAGES — remove the duplicate; "
        "STORAGES['staticfiles']['BACKEND'] is the single source of truth for Django 5+"
    )


def test_static_root_dirname():
    """STATIC_ROOT must point to a directory named 'staticfiles' (matches .gitignore and Dockerfile)."""
    assert settings.STATIC_ROOT is not None, "STATIC_ROOT is not configured"
    assert Path(settings.STATIC_ROOT).name == "staticfiles", (
        f"STATIC_ROOT directory name must be 'staticfiles', got {Path(settings.STATIC_ROOT).name!r}"
    )
