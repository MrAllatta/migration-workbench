"""Command-line interface for workbench deployment operations.

Entry point: the ``wb`` script installed by ``pyproject.toml``
(``[project.scripts] wb = "deployment.wb_cli:main"``).

**Available subcommands**

``wb manifest lint [--manifest PATH]``
    Validate ``deploy/spaces.yml`` against the full manifest schema.

``wb deploy <space> --env <env> --dry-run``
    Record a dry-run release event for *space*/*env* (live deploys are not yet
    implemented; ``--dry-run`` is required until they are).

All subcommands accept ``--json`` to emit machine-readable JSON so CI scripts
can parse results without screen-scraping.

**Error codes**

``WB-MANIFEST-1001``
    Manifest failed schema validation.

``WB-DEPLOY-2001``
    Space name not found in manifest.

``WB-DEPLOY-2002``
    Environment name not found for the given space.

``WB-GENERAL-9001``
    Unexpected exception.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import getpass
import json
import os
from pathlib import Path
import subprocess
from typing import Any
import uuid

from deployment.manifest import ManifestValidationError, ensure_manifest_valid, load_manifest


ERROR_CODES = {
    "manifest_invalid": "WB-MANIFEST-1001",
    "space_not_found": "WB-DEPLOY-2001",
    "environment_not_found": "WB-DEPLOY-2002",
    "unexpected": "WB-GENERAL-9001",
}


def _setup_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "migration_workbench.settings")
    import django

    django.setup()


def _get_git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _render_output(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if payload["ok"]:
            print(payload["message"])
        else:
            print(f"{payload['error_code']}: {payload['message']}")
            if payload.get("details"):
                for detail in payload["details"]:
                    print(f"- {detail}")
    return 0 if payload["ok"] else 1


def _manifest_lint(args: argparse.Namespace) -> int:
    try:
        payload = load_manifest(Path(args.manifest))
        ensure_manifest_valid(payload)
    except ManifestValidationError as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["manifest_invalid"],
                "message": "Manifest validation failed.",
                "details": str(exc).splitlines()[1:],
            },
            args.json,
        )
    return _render_output(
        {
            "ok": True,
            "error_code": None,
            "message": f"Manifest is valid: {args.manifest}",
        },
        args.json,
    )


def _deploy_dry_run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    try:
        payload = load_manifest(manifest_path)
        ensure_manifest_valid(payload)
    except ManifestValidationError as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["manifest_invalid"],
                "message": "Manifest validation failed.",
                "details": str(exc).splitlines()[1:],
            },
            args.json,
        )

    space_cfg = (payload.get("spaces") or {}).get(args.space)
    if not space_cfg:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["space_not_found"],
                "message": f"Space '{args.space}' not found in manifest.",
            },
            args.json,
        )
    env_cfg = (space_cfg.get("environments") or {}).get(args.env)
    if not env_cfg:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["environment_not_found"],
                "message": f"Environment '{args.env}' not found for '{args.space}'.",
            },
            args.json,
        )

    _setup_django()
    from deployment.release_store import record_release_event

    release_id = f"dryrun-{uuid.uuid4().hex[:8]}"
    git_sha = _get_git_sha()
    actor = getpass.getuser()
    event = record_release_event(
        space=args.space,
        environment=args.env,
        release_id=release_id,
        git_sha=git_sha,
        actor=actor,
        outcome="dry_run",
        is_healthy=True,
        metadata={
            "manifest_path": str(manifest_path),
            "provider": (space_cfg.get("provider") or {}).get("type"),
            "app_name_template": (space_cfg.get("provider") or {}).get("app_name_template"),
            "branch_pattern": env_cfg.get("branch_pattern"),
            "planned_actions": [
                "resolve_manifest",
                "validate_secrets_presence",
                "build_image_or_resolve_image",
                "checkpoint_backup",
                "run_release_process",
                "verify_health_gate",
            ],
        },
        durable_log_path=Path("build/deploy/release-events.jsonl"),
    )
    return _render_output(
        {
            "ok": True,
            "error_code": None,
            "message": f"Dry run recorded for {args.space}/{args.env} as {release_id}.",
            "release": {
                **asdict(event),
                "created_at": event.created_at.isoformat(),
            },
        },
        args.json,
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct and return the ``wb`` argument parser.

    Returns:
        argparse.ArgumentParser: Fully configured parser with all subcommands
        and flags registered.
    """
    parser = argparse.ArgumentParser(prog="wb", description="Migration workbench deployment CLI")
    parser.add_argument("--json", action="store_true", help="Return machine-readable JSON output.")
    parser.add_argument(
        "--manifest",
        default="deploy/spaces.yml",
        help="Path to deployment manifest (default: deploy/spaces.yml).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    manifest_cmd = sub.add_parser("manifest", help="Manifest operations")
    manifest_sub = manifest_cmd.add_subparsers(dest="manifest_command", required=True)
    lint_cmd = manifest_sub.add_parser("lint", help="Validate deployment manifest")
    lint_cmd.set_defaults(func=_manifest_lint)

    deploy_cmd = sub.add_parser("deploy", help="Deploy operations")
    deploy_cmd.add_argument("space", help="Space name from manifest.")
    deploy_cmd.add_argument("--env", required=True, help="Environment name (preview or production).")
    deploy_cmd.add_argument("--dry-run", action="store_true", help="Only plan and record release metadata.")
    deploy_cmd.set_defaults(func=_deploy_dry_run)
    return parser


def main() -> int:
    """Parse arguments and dispatch to the appropriate subcommand handler.

    Returns:
        int: Exit code — ``0`` on success, ``1`` on failure.  Designed to be
        passed directly to :func:`sys.exit`.

    Example::

        if __name__ == "__main__":
            raise SystemExit(main())
    """
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "deploy" and not args.dry_run:
            return _render_output(
                {
                    "ok": False,
                    "error_code": ERROR_CODES["unexpected"],
                    "message": "Only --dry-run is implemented in this release.",
                },
                args.json,
            )
        return args.func(args)
    except Exception as exc:  # pragma: no cover
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["unexpected"],
                "message": f"Unexpected failure: {exc}",
            },
            args.json,
        )


if __name__ == "__main__":
    raise SystemExit(main())
