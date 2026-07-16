"""Drift command group (``wb drift ...``).

Extracted from ``deployment/wb_cli`` as part of e03s04
(cli-router-split). Owns:

- ``_drift_check`` — compare a baseline contract against a new contract
- ``build_drift_parser`` — wire the ``drift`` subparser
"""

from __future__ import annotations

import argparse


def _drift_check(args: argparse.Namespace) -> int:
    """Compare a baseline contract against a new contract and report drift.

    Delegates to ``diff_contracts`` and ``migration_safety_checks`` to detect
    structural changes and migration risks between the two contracts.
    """
    # Lazy imports avoid circular dependency with deployment.wb_cli
    from deployment.wb_cli import ERROR_CODES, _render_output, _setup_django  # noqa: PLC0415

    _setup_django(settings_module=getattr(args, "django_settings", None))
    from workbook.codegen.contract import (
        diff_contracts,
        load_contract,
        migration_safety_checks,
    )

    try:
        old_contract = load_contract(args.baseline)
    except Exception as exc:
        return _render_output(
            {"ok": False, "error_code": ERROR_CODES["unexpected"], "message": str(exc)},
            args.json,
        )
    try:
        new_contract = load_contract(args.new)
    except Exception as exc:
        return _render_output(
            {"ok": False, "error_code": ERROR_CODES["unexpected"], "message": str(exc)},
            args.json,
        )

    diffs = diff_contracts(old_contract, new_contract)
    safety = migration_safety_checks(diffs) if diffs else []

    if args.json:
        return _render_output(
            {
                "ok": not diffs,
                "error_code": None,
                "message": "No drift detected." if not diffs else "Drift detected.",
                "diffs": diffs or {},
                "safety": safety,
            },
            args.json,
        )

    if not diffs:
        print("No drift detected — contracts are identical.")
        return 0

    # Delegate to the contract diff handler (in the contract command module)
    from deployment.commands.contract import _contract_diff

    existing_diff_cmd_args = argparse.Namespace(
        json=False, old=args.baseline, new=args.new
    )
    _contract_diff(existing_diff_cmd_args)

    if safety:
        print()
        print("=== Migration safety risks ===")
        danger = [s for s in safety if s["severity"] == "DANGER"]
        warning = [s for s in safety if s["severity"] == "WARNING"]
        for item in danger:
            loc = (
                f"{item['model']}.{item['field']}"
                if item.get("field")
                else item["model"]
            )
            print(f"  DANGER: {loc}: {item['message']}")
        for item in warning:
            loc = (
                f"{item['model']}.{item['field']}"
                if item.get("field")
                else item["model"]
            )
            print(f"  WARNING: {loc}: {item['message']}")

    return 1  # drift detected


def build_drift_parser(sub: argparse._SubParsersAction) -> None:
    """Wire the ``drift`` subparser into *sub*."""
    drift_cmd = sub.add_parser("drift", help="Drift detection operations")
    drift_sub = drift_cmd.add_subparsers(dest="drift_command", required=True)
    check_cmd = drift_sub.add_parser(
        "check", help="Check for drift between two schema contracts"
    )
    check_cmd.add_argument(
        "--baseline", required=True, help="Path to baseline (old) contract YAML"
    )
    check_cmd.add_argument("--new", required=True, help="Path to new contract YAML")
    check_cmd.add_argument(
        "--django-settings",
        default=None,
        help="Django settings module (e.g. config.settings). Auto-detected for product repos.",
    )
    check_cmd.set_defaults(func=_drift_check)
