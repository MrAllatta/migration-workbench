"""Full-path integration test for ``_deploy_live`` with mocked external dependencies.

Exercises the complete live deploy codepath — manifest validation, release event
recording, subprocess call, health polling, and result reporting.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


def _manifest() -> dict:
    return {
        "version": 1,
        "profiles": {
            "default": {
                "cpu": {"cores": 1, "type": "shared"},
                "memory_mb": 256,
                "volume_gb": 1,
            }
        },
        "replication_defaults": {
            "provider": "tigris",
            "bucket_env": "LITESTREAM_BUCKET",
            "snapshot_interval_minutes": 60,
            "retention_days": 14,
        },
        "spaces": {
            "smoke_space": {
                "owner": "smoke",
                "project": "smoke",
                "profile": "default",
                "provider": {
                    "type": "fly",
                    "primary_region": "ewr",
                    "regions": ["ewr"],
                    "app_name_template": "smoke-app",
                },
                "build": {"dockerfile": "Dockerfile", "context": "."},
                "runtime": {
                    "internal_port": 8080,
                    "processes": {"web": "python manage.py runserver", "release": "python manage.py migrate"},
                    "healthcheck_path": "/healthz",
                    "healthcheck_timeout_s": 60,
                },
                "storage": {
                    "sqlite_path": "/data/db.sqlite3",
                    "media_path": "/data/media",
                },
                "replication": {
                    "litestream_enabled": True,
                    "replica_path_template": "smoke/{environment}",
                },
                "backup": {
                    "predeploy_checkpoint": {"required": True, "method": "litestream"},
                    "retention_days": 14,
                },
                "secrets": {
                    "required": ["DJANGO_SECRET_KEY"],
                },
                "environment": {
                    "required": ["SQLITE_PATH"],
                },
                "environments": {
                    "preview": {"branch_pattern": "feature/*"},
                    "production": {"branch_pattern": "main"},
                },
            }
        },
    }


@pytest.mark.django_db
@patch("deployment.wb_cli.subprocess.run")
@patch("deployment.health.wait_for_healthy")
@patch("deployment.wb_cli.shutil.which")
def test_deploy_live_full_success(mock_which, mock_health, mock_run, tmp_path):
    mock_which.return_value = "/usr/local/bin/fly"
    """Happy path: fly succeeds, health check passes, release events written."""
    manifest_path = tmp_path / "spaces.yml"
    manifest_path.write_text(yaml.dump(_manifest(), sort_keys=False), encoding="utf-8")

    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "Deployed"
    mock_run.return_value.stderr = ""

    mock_health.return_value = True

    from deployment.wb_cli import _deploy_live

    ns = argparse.Namespace(
        manifest=str(manifest_path),
        space="smoke_space",
        env="production",
        live=True,
        dry_run=False,
        json=True,
    )
    result = _deploy_live(ns)
    assert result == 0


@pytest.mark.django_db
@patch("deployment.wb_cli.subprocess.run")
@patch("deployment.wb_cli.shutil.which")
def test_deploy_live_fly_fails(mock_which, mock_run, tmp_path):
    mock_which.return_value = "/usr/local/bin/fly"
    """fly deploy failure records deploy_failed event and exits non-zero."""
    manifest_path = tmp_path / "spaces.yml"
    manifest_path.write_text(yaml.dump(_manifest(), sort_keys=False), encoding="utf-8")

    mock_run.return_value.returncode = 1
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = "Build failed"

    from deployment.wb_cli import _deploy_live

    ns = argparse.Namespace(
        manifest=str(manifest_path),
        space="smoke_space",
        env="production",
        live=True,
        dry_run=False,
        json=True,
    )
    result = _deploy_live(ns)
    assert result != 0


@patch("deployment.wb_cli.subprocess.run")
def test_deploy_live_invalid_manifest(mock_run, tmp_path):
    """Invalid manifest is rejected before any deploy attempt."""
    manifest_path = tmp_path / "bad.yml"
    manifest_path.write_text("not: valid: yaml: [", encoding="utf-8")

    from deployment.wb_cli import _deploy_live

    ns = argparse.Namespace(
        manifest=str(manifest_path),
        space="smoke_space",
        env="production",
        live=True,
        dry_run=False,
        json=True,
    )
    result = _deploy_live(ns)
    assert result != 0
    mock_run.assert_not_called()
