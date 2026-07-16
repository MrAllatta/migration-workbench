"""Manifest command group (``wb manifest ...``).

Extracted from ``deployment/wb_cli`` as part of e03s02
(cli-router-split). Owns:

- ``_manifest_lint`` — validate the deployment manifest YAML
- ``build_manifest_parser`` — wire the ``manifest`` subparser into
  the parent ``wb`` parser

The handler reads ``args.manifest`` (the deployment manifest path)
and ``args.json`` (machine-readable output). It returns the same
exit-code contract that the parent ``main()`` function expects.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from deployment.manifest import (
    ManifestValidationError,
    ensure_manifest_valid,
    load_manifest,
)


def _manifest_lint(args: argparse.Namespace) -> int:
    """Validate ``args.manifest`` against the manifest schema.

    Returns 0 on success. On validation failure, returns the exit
    code produced by ``_render_output`` (typically 1) and prints
    a structured error payload.

    Implementation note: ``_render_output`` and ``ERROR_CODES`` are
    imported lazily to avoid a circular dependency with
    ``deployment.wb_cli`` (which imports from this module). By the
    time ``_manifest_lint`` is called at runtime, ``wb_cli`` has
    finished loading and the lookup is safe.
    """
    from deployment.wb_cli import _render_output, ERROR_CODES  # noqa: PLC0415

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


def build_manifest_parser(sub: argparse._SubParsersAction) -> None:
    """Wire the ``manifest`` subparser into *sub*.

    Adds a single ``lint`` subcommand. The ``--manifest`` flag is
    inherited from the parent ``wb`` parser (defined in
    ``deployment.wb_cli.build_parser``).
    """
    manifest_cmd = sub.add_parser("manifest", help="Manifest operations")
    manifest_sub = manifest_cmd.add_subparsers(dest="manifest_command", required=True)
    lint_cmd = manifest_sub.add_parser("lint", help="Validate deployment manifest")
    lint_cmd.set_defaults(func=_manifest_lint)
