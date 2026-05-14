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


def _contract_review(args: argparse.Namespace) -> int:
    _setup_django()
    from workbook.codegen.contract import load_contract, review_contract

    try:
        contract = load_contract(args.contract)
    except ValueError as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["unexpected"],
                "message": str(exc),
            },
            args.json,
        )

    issues = review_contract(contract)
    if not issues:
        return _render_output(
            {
                "ok": True,
                "error_code": None,
                "message": f"No issues found in {args.contract}.",
            },
            args.json,
        )

    if args.json:
        return _render_output(
            {
                "ok": False,
                "error_code": None,
                "message": f"{len(issues)} issue(s) found.",
                "details": issues,
            },
            args.json,
        )

    print(f"Found {len(issues)} issue(s) in {args.contract}:")
    for issue in issues:
        location = f"{issue['table']}.{issue['field']}" if issue["field"] else issue["table"]
        print(f"  - {location}: {issue['message']}")
    return 0 if not issues else 1


def _contract_diff(args: argparse.Namespace) -> int:
    _setup_django()
    from workbook.codegen.contract import diff_contracts, load_contract

    try:
        old_contract = load_contract(args.old)
        new_contract = load_contract(args.new)
    except ValueError as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["unexpected"],
                "message": str(exc),
            },
            args.json,
        )

    diffs = diff_contracts(old_contract, new_contract)

    if not diffs:
        return _render_output(
            {
                "ok": True,
                "error_code": None,
                "message": "Contracts are identical.",
            },
            args.json,
        )

    if args.json:
        return _render_output(
            {
                "ok": True,
                "error_code": None,
                "message": "Differences found.",
                "diffs": diffs,
            },
            args.json,
        )

    lines: list[str] = []

    if diffs.get("models_added") or diffs.get("models_removed"):
        lines.append("=== Models ===")
        if diffs.get("models_added"):
            lines.append(f"  Added:   {', '.join(diffs['models_added'])}")
        if diffs.get("models_removed"):
            lines.append(f"  Removed: {', '.join(diffs['models_removed'])}")
        lines.append("")

    for model_name in sorted(diffs.get("model_diffs") or {}):
        md = diffs["model_diffs"][model_name]
        lines.append(f"=== Model: {model_name} ===")

        if md.get("fields_added"):
            lines.append("  Fields added:")
            for f in md["fields_added"]:
                kwargs_str = _fmt_kwargs(f.get("kwargs", {}))
                lines.append(f"    + {f['name']} ({_short_class(f['class'])}{kwargs_str})")

        if md.get("fields_removed"):
            lines.append("  Fields removed:")
            for f in md["fields_removed"]:
                kwargs_str = _fmt_kwargs(f.get("kwargs", {}))
                lines.append(f"    - {f['name']} ({_short_class(f['class'])}{kwargs_str})")

        if md.get("fields_changed"):
            lines.append("  Fields changed:")
            for fc in md["fields_changed"]:
                parts = [f"~ {fc['name']}"]
                if fc.get("class") and fc["class"]["old"] != fc["class"]["new"]:
                    old_cls = _short_class(fc["class"]["old"])
                    new_cls = _short_class(fc["class"]["new"])
                    parts.append(f"{old_cls} -> {new_cls}")
                for kw, v in (fc.get("kwargs") or {}).items():
                    old_v = _fmt_value(v["old"])
                    new_v = _fmt_value(v["new"])
                    parts.append(f"{kw}: {old_v} -> {new_v}")
                lines.append("    " + ", ".join(parts))

        if md.get("meta_changed"):
            lines.append("  Meta changes:")
            for key, v in md["meta_changed"].items():
                old_v = _fmt_value(v["old"])
                new_v = _fmt_value(v["new"])
                lines.append(f"    ~ {key}: {old_v} -> {new_v}")

        lines.append("")

    print("\n".join(lines).rstrip())
    return 0


def _short_class(raw: str) -> str:
    return raw.removeprefix("models.")


def _fmt_kwargs(kwargs: dict) -> str:
    if not kwargs:
        return ""
    pairs = ", ".join(f"{k}={v!r}" for k, v in sorted(kwargs.items()))
    return f", {pairs}"


def _fmt_value(val: Any) -> str:
    if val is None:
        return "None"
    if isinstance(val, str):
        return val
    if isinstance(val, (list, dict)):
        return str(val)
    return repr(val)


def _contract_safety(args: argparse.Namespace) -> int:
    _setup_django()
    from workbook.codegen.contract import (
        diff_contracts,
        load_contract,
        migration_safety_checks,
    )

    try:
        old_contract = load_contract(args.old)
        new_contract = load_contract(args.new)
    except ValueError as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["unexpected"],
                "message": str(exc),
            },
            args.json,
        )

    diffs = diff_contracts(old_contract, new_contract)
    issues = migration_safety_checks(diffs)

    if args.json:
        return _render_output(
            {
                "ok": len(issues) == 0,
                "error_code": None,
                "message": (
                    f"{len(issues)} migration risk(s) found."
                    if issues else "No migration risks detected."
                ),
                "details": issues,
            },
            args.json,
        )

    if not issues:
        print("No migration risks detected — contracts are safe.")
        return 0

    danger = [i for i in issues if i["severity"] == "DANGER"]
    warning = [i for i in issues if i["severity"] == "WARNING"]

    if danger:
        print(f"=== DANGER ({len(danger)}) ===")
        for i in danger:
            loc = f"{i['model']}.{i['field']}" if i["field"] else i["model"]
            print(f"  {loc}: {i['message']}")
    if warning:
        print(f"=== WARNING ({len(warning)}) ===")
        for i in warning:
            loc = f"{i['model']}.{i['field']}" if i["field"] else i["model"]
            print(f"  {loc}: {i['message']}")

    print(f"\n{len(issues)} total migration risk(s) found.")
    return 0 if not danger else 1


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

    contract_cmd = sub.add_parser("contract", help="Schema contract operations")
    contract_sub = contract_cmd.add_subparsers(dest="contract_command", required=True)
    review_cmd = contract_sub.add_parser("review", help="Run design-review checklist on a schema contract YAML")
    review_cmd.add_argument("--contract", required=True, help="Path to schema-contract YAML")
    review_cmd.set_defaults(func=_contract_review)

    diff_cmd = contract_sub.add_parser(
        "diff", help="Compare two schema contracts and show differences"
    )
    diff_cmd.add_argument("--old", required=True, help="Path to older contract YAML")
    diff_cmd.add_argument("--new", required=True, help="Path to newer contract YAML")
    diff_cmd.set_defaults(func=_contract_diff)

    safety_cmd = contract_sub.add_parser(
        "safety", help="Check contract changes for migration safety risks"
    )
    safety_cmd.add_argument("--old", required=True, help="Path to older contract YAML")
    safety_cmd.add_argument("--new", required=True, help="Path to newer contract YAML")
    safety_cmd.set_defaults(func=_contract_safety)

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
