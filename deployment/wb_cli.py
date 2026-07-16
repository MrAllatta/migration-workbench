"""Command-line interface for workbench deployment operations.

Entry point: the ``wb`` script installed by ``pyproject.toml``
(``[project.scripts] wb = "deployment.wb_cli:main"``).

**Available subcommands**

``wb manifest lint [--manifest PATH]``
    Validate ``deploy/spaces.yml`` against the full manifest schema.

``wb deploy <space> --env <env> --dry-run``
    Record a dry-run release event for *space*/*env* without deploying.

``wb deploy <space> --env <env> --live``
    Perform a live deploy with health-check polling and release recording.

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
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from deployment.commands.contract import (  # noqa: F401
    _contract_diff,
    _contract_review,
    _contract_safety,
    _contract_validate,
    build_contract_parser,
)
from deployment.commands.deploy import (  # noqa: F401
    _deploy_dry_run,
    _deploy_live,
    build_deploy_parser,
)
from deployment.commands.drift import _drift_check, build_drift_parser  # noqa: F401
from deployment.commands.ecosystem import (  # noqa: F401
    _ecosystem_ack,
    _ecosystem_health,
    build_ecosystem_parser,
)
from deployment.commands.generate import (  # noqa: F401
    _generate_admin,
    _generate_import,
    _generate_manifest,
    _generate_models,
    _generate_views,
    build_generate_parser,
)
from deployment.commands.manifest import _manifest_lint, build_manifest_parser  # noqa: F401
from deployment.commands.vertical import (  # noqa: F401
    _vertical_list,
    _vertical_show,
    build_vertical_parser,
)

ERROR_CODES = {
    "manifest_invalid": "WB-MANIFEST-1001",
    "space_not_found": "WB-DEPLOY-2001",
    "environment_not_found": "WB-DEPLOY-2002",
    "unexpected": "WB-GENERAL-9001",
    "vertical_not_found": "WB-VERTICAL-4001",
    "ecosystem_health": "WB-ECOSYSTEM-3001",
    "ecosystem_not_found": "WB-ECOSYSTEM-3002",
    "ecosystem_invalid": "WB-ECOSYSTEM-3003",
    "ecosystem_failed": "WB-ECOSYSTEM-3004",
}


def _setup_django(settings_module: str | None = None) -> None:
    if settings_module:
        os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
    elif "DJANGO_SETTINGS_MODULE" not in os.environ:
        backend_config = Path("backend/config/settings.py")
        if backend_config.is_file():
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
            backend_dir = str(backend_config.parent.parent.resolve())
            if backend_dir not in sys.path:
                sys.path.insert(0, backend_dir)
        else:
            os.environ.setdefault(
                "DJANGO_SETTINGS_MODULE", "migration_workbench.settings"
            )
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


def build_parser() -> argparse.ArgumentParser:
    """Construct and return the ``wb`` argument parser.

    Returns:
        argparse.ArgumentParser: Fully configured parser with all subcommands
        and flags registered.
    """
    parser = argparse.ArgumentParser(
        prog="wb", description="Migration workbench deployment CLI"
    )
    parser.add_argument(
        "--json", action="store_true", help="Return machine-readable JSON output."
    )
    parser.add_argument(
        "--manifest",
        default="deploy/spaces.yml",
        help="Path to deployment manifest (default: deploy/spaces.yml).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Manifest command group extracted to deployment.commands.manifest
    # in e03s02. See deployment/commands/manifest.py for the
    # implementation and specs/inventory/cli-router.yaml for the
    # extraction roadmap.
    build_manifest_parser(sub)
    build_contract_parser(sub)

    build_drift_parser(sub)

    build_deploy_parser(sub)

    build_generate_parser(sub)

    # Vertical subcommands
    build_vertical_parser(sub)

    # Ecosystem subcommands
    build_ecosystem_parser(sub)
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
        if args.command == "deploy":
            if args.dry_run and getattr(args, "live", False):
                return _render_output(
                    {
                        "ok": False,
                        "error_code": ERROR_CODES["unexpected"],
                        "message": "Cannot use --dry-run with --live. Choose one.",
                    },
                    args.json,
                )
            if getattr(args, "live", False):
                args.func = _deploy_live
            elif not args.dry_run:
                return _render_output(
                    {
                        "ok": False,
                        "error_code": ERROR_CODES["unexpected"],
                        "message": "Specify --dry-run for dry-run or --live for live deploy.",
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
