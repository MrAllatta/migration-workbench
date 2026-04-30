from pathlib import Path

from deployment.manifest import ensure_manifest_valid, load_manifest, validate_manifest


def test_spaces_manifest_is_valid():
    manifest_path = Path(__file__).resolve().parents[2] / "deploy" / "spaces.yml"
    payload = load_manifest(manifest_path)
    ensure_manifest_valid(payload)


def test_validate_manifest_rejects_storage_volume_override():
    payload = {
        "version": 1,
        "profiles": {"tiny": {"cpu": {"cores": 1, "type": "shared"}, "memory_mb": 256, "volume_gb": 5}},
        "replication_defaults": {
            "provider": "s3",
            "bucket_env": "LITESTREAM_BUCKET",
            "snapshot_interval_minutes": 15,
            "retention_days": 14,
        },
        "spaces": {
            "demo": {
                "owner": "platform",
                "project": "demo",
                "profile": "tiny",
                "provider": {
                    "type": "fly",
                    "primary_region": "ewr",
                    "regions": ["ewr"],
                    "app_name_template": "demo-{env}",
                },
                "build": {"dockerfile": "Dockerfile", "context": ".", "image": None},
                "runtime": {
                    "internal_port": 8080,
                    "processes": {"web": "gunicorn app.wsgi:application", "release": "python manage.py migrate"},
                    "healthcheck_path": "/healthz",
                    "healthcheck_timeout_s": 60,
                },
                "storage": {"sqlite_path": "/data/db.sqlite3", "media_path": "/data/media", "volume_gb": 10},
                "replication": {"litestream_enabled": True, "replica_path_template": "demo/{env}"},
                "backup": {
                    "predeploy_checkpoint": {"required": True, "method": "litestream_snapshot"},
                    "retention_days": 7,
                },
                "secrets": {"required": ["DJANGO_SECRET_KEY"]},
                "environments": {
                    "preview": {"branch_pattern": "preview/*"},
                    "production": {"branch_pattern": "main"},
                },
            }
        },
    }

    issues = validate_manifest(payload)
    assert any(issue.path == "spaces.demo.storage.volume_gb" for issue in issues)
