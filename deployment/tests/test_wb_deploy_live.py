"""Tests for ``wb deploy`` live deploy routing."""

from __future__ import annotations

import subprocess
import sys

import yaml


def _minimal_manifest() -> dict:
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
            "test_space": {
                "owner": "test",
                "project": "test",
                "profile": "default",
                "provider": {
                    "type": "fly",
                    "primary_region": "ewr",
                    "regions": ["ewr"],
                    "app_name_template": "test-app",
                },
                "build": {"dockerfile": "Dockerfile", "context": "."},
                "runtime": {
                    "internal_port": 8080,
                    "processes": {
                        "web": "python manage.py runserver",
                        "release": "python manage.py migrate",
                    },
                    "healthcheck_path": "/healthz",
                    "healthcheck_timeout_s": 60,
                },
                "storage": {
                    "sqlite_path": "/data/db.sqlite3",
                    "media_path": "/data/media",
                },
                "replication": {
                    "litestream_enabled": True,
                    "replica_path_template": "test/{environment}",
                },
                "backup": {
                    "predeploy_checkpoint": {"required": True, "method": "litestream"},
                    "retention_days": 14,
                },
                "secrets": {
                    "required": ["DJANGO_SECRET_KEY", "DJANGO_ALLOWED_HOSTS"],
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


def test_deploy_rejects_neither_dry_run_nor_live(tmp_path):
    """Deploy without --dry-run or --live shows helpful error."""
    manifest_path = tmp_path / "spaces.yml"
    manifest_path.write_text(
        yaml.dump(_minimal_manifest(), sort_keys=False), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "deployment.wb_cli",
            "--json",
            "--manifest",
            str(manifest_path),
            "deploy",
            "test_space",
            "--env",
            "preview",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Specify --dry-run" in result.stdout or "Specify --dry-run" in result.stderr


def test_deploy_live_flag_accepted_but_fails_without_fly(tmp_path):
    """Deploy --live is accepted by parser without triggering 'Specify --dry-run' error."""
    manifest_path = tmp_path / "spaces.yml"
    manifest_path.write_text(
        yaml.dump(_minimal_manifest(), sort_keys=False), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "deployment.wb_cli",
            "--json",
            "--manifest",
            str(manifest_path),
            "deploy",
            "test_space",
            "--env",
            "preview",
            "--live",
        ],
        capture_output=True,
        text=True,
    )
    # Verify --live is routed differently from bare deploy (no dry-run/live error).
    assert "Specify --dry-run" not in result.stdout
    assert "Specify --dry-run" not in result.stderr
    # It will fail since fly CLI isn't available, but that's expected.
    assert result.returncode != 0
