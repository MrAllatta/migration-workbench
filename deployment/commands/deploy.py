"""Deploy command group ("wb deploy ...").

Extracted from deployment/wb_cli as part of e03s04
(cli-router-split). Owns:

- ``_deploy_dry_run`` — dry-run a deployment
- ``_deploy_live`` — execute a live deployment
- ``build_deploy_parser`` — wire the ``deploy`` subparser
"""

from __future__ import annotations

import argparse
import getpass
import json
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any


from deployment.manifest import (
    ManifestValidationError,
    ensure_manifest_valid,
    load_manifest,
)


def _deploy_dry_run(args: argparse.Namespace) -> int:
    """Perform a dry-run deployment."""
    from deployment.wb_cli import (
        ERROR_CODES,
        _get_git_sha,
        _render_output,
        _setup_django,
    )  # noqa: PLC0415

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

    _setup_django(settings_module=getattr(args, "django_settings", None))
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
            "app_name_template": (space_cfg.get("provider") or {}).get(
                "app_name_template"
            ),
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


def _deploy_live(args: argparse.Namespace) -> int:
    """Perform a live deploy: validate manifest, deploy, health-check, record."""
    from deployment.wb_cli import (
        ERROR_CODES,
        _get_git_sha,
        _render_output,
        _setup_django,
    )  # noqa: PLC0415
    from deployment.health import wait_for_healthy
    from deployment.release_store import record_release_event

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

    _setup_django(settings_module=getattr(args, "django_settings", None))

    app_name_base = (space_cfg.get("provider") or {}).get("app_name_template", "app")
    app_name = app_name_base.replace("{environment}", args.env)
    git_sha = _get_git_sha()
    actor = getpass.getuser()
    healthcheck_path = (space_cfg.get("runtime") or {}).get(
        "healthcheck_path", "/healthz"
    )
    health_url = f"https://{app_name}.fly.dev{healthcheck_path}"

    release_id = f"live-{uuid.uuid4().hex[:8]}"
    is_local = getattr(args, "local", False)
    build_strategy: str = "local" if is_local else "remote"

    if not shutil.which("fly"):
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["unexpected"],
                "message": "fly CLI not found. Install from https://fly.io/docs/hands-on/install-flyctl/",
            },
            args.json,
        )

    record_release_event(
        space=args.space,
        environment=args.env,
        release_id=release_id,
        git_sha=git_sha,
        actor=actor,
        outcome="deploy_start",
        is_healthy=False,
        metadata={"build_strategy": build_strategy},
        durable_log_path=Path("build/deploy/release-events.jsonl"),
    )

    build_flag = "--local-only" if is_local else "--remote-only"
    deploy_result = subprocess.run(
        ["fly", "deploy", build_flag, "--app", app_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if getattr(args, "verbose", False):
        if deploy_result.stdout:
            print(deploy_result.stdout, file=sys.stderr, flush=True)
        if deploy_result.stderr:
            print(deploy_result.stderr, file=sys.stderr, flush=True)

    if deploy_result.returncode != 0:
        stderr_tail = deploy_result.stderr[-1000:] if deploy_result.stderr else ""
        message = f"fly deploy failed (exit {deploy_result.returncode}):\n{stderr_tail}"
        record_release_event(
            space=args.space,
            environment=args.env,
            release_id=release_id,
            git_sha=git_sha,
            actor=actor,
            outcome="deploy_failed",
            is_healthy=False,
            metadata={
                "deploy_stderr": (
                    deploy_result.stderr[-2000:] if deploy_result.stderr else ""
                ),
                "deploy_stdout": (
                    deploy_result.stdout[-2000:] if deploy_result.stdout else ""
                ),
                "build_strategy": build_strategy,
            },
            durable_log_path=Path("build/deploy/release-events.jsonl"),
        )
        return _render_output(
            {"ok": False, "error_code": ERROR_CODES["unexpected"], "message": message},
            args.json,
        )

    release_secret_result = subprocess.run(
        ["fly", "secrets", "set", f"RELEASE_ID={release_id}", "--app", app_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if release_secret_result.returncode != 0:
        print(
            f"Warning: failed to set RELEASE_ID secret: {release_secret_result.stderr[:500]}",
            file=sys.stderr,
        )

    healthy = wait_for_healthy(health_url, timeout=120, interval=5)

    machine_states: list[dict] = []
    if not healthy:
        machine_list = subprocess.run(
            ["fly", "machine", "list", "--app", app_name, "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        if machine_list.returncode == 0 and machine_list.stdout:
            try:
                machines = json.loads(machine_list.stdout)
                if isinstance(machines, list):
                    machine_states = [
                        {
                            "id": m.get("id"),
                            "state": m.get("state"),
                            "region": m.get("region"),
                        }
                        for m in machines
                    ]
            except (json.JSONDecodeError, TypeError, AttributeError, KeyError):
                pass

    outcome = "deploy_succeeded_healthy" if healthy else "deploy_succeeded_unhealthy"
    metadata: dict[str, Any] = {"build_strategy": build_strategy}
    if not healthy:
        metadata["machine_states"] = machine_states

    record_release_event(
        space=args.space,
        environment=args.env,
        release_id=release_id,
        git_sha=git_sha,
        actor=actor,
        outcome=outcome,
        is_healthy=healthy,
        metadata=metadata,
        durable_log_path=Path("build/deploy/release-events.jsonl"),
    )

    message = f"Deploy {release_id}: {'healthy' if healthy else 'unhealthy'}"
    if not healthy and machine_states:
        message += f" | machine states: {machine_states}"

    return _render_output(
        {
            "ok": healthy,
            "error_code": None,
            "message": message,
            "release_id": release_id,
        },
        args.json,
    )


def build_deploy_parser(sub: argparse._SubParsersAction) -> None:
    """Wire the ``deploy`` subparser into *sub*."""
    deploy_cmd = sub.add_parser("deploy", help="Deploy operations")
    deploy_cmd.add_argument("space", help="Space name from manifest.")
    deploy_cmd.add_argument(
        "--env", required=True, help="Environment name (preview or production)."
    )
    deploy_cmd.add_argument(
        "--dry-run", action="store_true", help="Only plan and record release metadata."
    )
    deploy_cmd.add_argument(
        "--live", action="store_true", help="Perform a live deploy with health check."
    )
    deploy_cmd.add_argument(
        "--local",
        action="store_true",
        help="Build locally with Docker instead of using Fly remote builder.",
    )
    deploy_cmd.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Stream fly deploy output and health check logs to stderr.",
    )
    deploy_cmd.add_argument(
        "--django-settings",
        default=None,
        help="Django settings module (e.g. config.settings). Auto-detected for product repos.",
    )
    deploy_cmd.add_argument(
        "--manifest", default="deploy/spaces.yml", help="Path to spaces manifest"
    )
    deploy_cmd.add_argument("--json", action="store_true", help="Output as JSON")
    # The deploy subcommand has special dispatch in main() for --live; the
    # default handler is dry-run, and main() swaps in _deploy_live for --live.
    deploy_cmd.set_defaults(func=_deploy_dry_run)
