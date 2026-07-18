"""Contract command group (``wb contract ...``).

Extracted from ``deployment/wb_cli`` as part of e03s03
(cli-router-split). Owns four subcommands:

- ``review`` — design-review checklist on a schema contract
- ``diff`` — compare two schema contracts
- ``safety`` — migration safety checks
- ``validate`` — structural validation
"""

from __future__ import annotations

import argparse
import json
from typing import Any


def _contract_review(args: argparse.Namespace) -> int:
    """Run design-review checklist on *args.contract*."""
    # Lazy imports avoid circular dependency with deployment.wb_cli
    from deployment.wb_cli import (
        _render_output,
        ERROR_CODES,
        _setup_django,
    )  # noqa: PLC0415

    _setup_django(settings_module=getattr(args, "django_settings", None))
    from workbook.codegen.contract import load_contract, review_contract

    try:
        contract = load_contract(args.contract)
    except Exception as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["unexpected"],
                "message": str(exc),
            },
            args.json,
        )

    dependency_artifact = None
    if args.dependency_artifact:
        with open(args.dependency_artifact) as f:
            dependency_artifact = json.load(f)

    issues = review_contract(contract, dependency_artifact=dependency_artifact)
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
        message = (
            f"{len(issues)} issue(s) found (exit-zero)."
            if args.exit_zero
            else f"{len(issues)} issue(s) found."
        )
        return _render_output(
            {
                "ok": args.exit_zero,
                "error_code": None,
                "message": message,
                "details": issues,
            },
            args.json,
        )

    print(f"Found {len(issues)} issue(s) in {args.contract}:")
    for issue in issues:
        location = (
            f"{issue['table']}.{issue['field']}" if issue["field"] else issue["table"]
        )
        print(f"  - {location}: {issue['message']}")
    return 0 if args.exit_zero else 1


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


def _contract_diff(args: argparse.Namespace) -> int:
    """Compare two schema contracts and show differences."""
    from deployment.wb_cli import (
        _render_output,
        ERROR_CODES,
        _setup_django,
    )  # noqa: PLC0415

    _setup_django(settings_module=getattr(args, "django_settings", None))
    from workbook.codegen.contract import diff_contracts, load_contract

    try:
        old_contract = load_contract(args.old)
        new_contract = load_contract(args.new)
    except Exception as exc:
        return _render_output(
            {"ok": False, "error_code": ERROR_CODES["unexpected"], "message": str(exc)},
            args.json,
        )

    diffs = diff_contracts(old_contract, new_contract)
    if not diffs:
        return _render_output(
            {"ok": True, "error_code": None, "message": "Contracts are identical."},
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
                lines.append(
                    f"    + {f['name']} ({_short_class(f['class'])}{kwargs_str})"
                )
        if md.get("fields_removed"):
            lines.append("  Fields removed:")
            for f in md["fields_removed"]:
                kwargs_str = _fmt_kwargs(f.get("kwargs", {}))
                lines.append(
                    f"    - {f['name']} ({_short_class(f['class'])}{kwargs_str})"
                )
        if md.get("fields_changed"):
            lines.append("  Fields changed:")
            for fc in md["fields_changed"]:
                parts = [f"~ {fc['name']}"]
                if fc.get("class") and fc["class"]["old"] != fc["class"]["new"]:
                    parts.append(
                        f"{_short_class(fc['class']['old'])} -> {_short_class(fc['class']['new'])}"
                    )
                for kw, v in (fc.get("kwargs") or {}).items():
                    parts.append(
                        f"{kw}: {_fmt_value(v['old'])} -> {_fmt_value(v['new'])}"
                    )
                lines.append("    " + ", ".join(parts))
        if md.get("meta_changed"):
            lines.append("  Meta changes:")
            for key, v in md["meta_changed"].items():
                lines.append(
                    f"    ~ {key}: {_fmt_value(v['old'])} -> {_fmt_value(v['new'])}"
                )
        lines.append("")
    print("\n".join(lines).rstrip())
    return 0


def _contract_safety(args: argparse.Namespace) -> int:
    """Check contract changes for migration safety risks."""
    from deployment.wb_cli import (
        _render_output,
        ERROR_CODES,
        _setup_django,
    )  # noqa: PLC0415

    _setup_django(settings_module=getattr(args, "django_settings", None))
    from workbook.codegen.contract import (
        diff_contracts,
        load_contract,
        migration_safety_checks,
    )

    try:
        old_contract = load_contract(args.old)
        new_contract = load_contract(args.new)
    except Exception as exc:
        return _render_output(
            {"ok": False, "error_code": ERROR_CODES["unexpected"], "message": str(exc)},
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
                    if issues
                    else "No migration risks detected."
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


def _contract_validate(args: argparse.Namespace) -> int:
    """Validate a schema contract (structural checks)."""
    from deployment.wb_cli import _setup_django  # noqa: PLC0415

    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command, CommandError

    kwargs = {"contract": args.contract}
    if getattr(args, "strict", False):
        kwargs["strict"] = True
    if getattr(args, "dump_json", False):
        kwargs["dump_json"] = True
    try:
        call_command("validate_contract", **kwargs)
        return 0
    except (SystemExit, CommandError) as exc:
        if isinstance(exc, SystemExit):
            return exc.code if isinstance(exc.code, int) else 1
        return 1


def build_contract_parser(sub: argparse._SubParsersAction) -> None:
    """Wire the ``contract`` subparser into *sub*.

    Adds four subcommands: review, diff, safety, validate.
    """
    contract_cmd = sub.add_parser("contract", help="Schema contract operations")
    contract_sub = contract_cmd.add_subparsers(dest="contract_command", required=True)

    # review
    review_cmd = contract_sub.add_parser(
        "review", help="Run design-review checklist on a schema contract YAML"
    )
    review_cmd.add_argument(
        "--contract", required=True, help="Path to schema-contract YAML"
    )
    review_cmd.add_argument(
        "--exit-zero",
        action="store_true",
        help="Return exit code 0 even when issues are found.",
    )
    review_cmd.add_argument(
        "--django-settings",
        default=None,
        help="Django settings module (e.g. config.settings). Auto-detected for product repos.",
    )
    review_cmd.add_argument(
        "--dependency-artifact",
        type=str,
        default=None,
        help="Path to a dependency artifact JSON from the profiler, for FK validation",
    )
    review_cmd.set_defaults(func=_contract_review)

    # diff
    diff_cmd = contract_sub.add_parser(
        "diff", help="Compare two schema contracts and show differences"
    )
    diff_cmd.add_argument("--old", required=True, help="Path to older contract YAML")
    diff_cmd.add_argument("--new", required=True, help="Path to newer contract YAML")
    diff_cmd.add_argument(
        "--django-settings",
        default=None,
        help="Django settings module (e.g. config.settings). Auto-detected for product repos.",
    )
    diff_cmd.set_defaults(func=_contract_diff)

    # safety
    safety_cmd = contract_sub.add_parser(
        "safety", help="Check contract changes for migration safety risks"
    )
    safety_cmd.add_argument("--old", required=True, help="Path to older contract YAML")
    safety_cmd.add_argument("--new", required=True, help="Path to newer contract YAML")
    safety_cmd.add_argument(
        "--django-settings",
        default=None,
        help="Django settings module (e.g. config.settings). Auto-detected for product repos.",
    )
    safety_cmd.set_defaults(func=_contract_safety)

    # validate
    validate_cmd = contract_sub.add_parser(
        "validate", help="Validate a schema contract (structural checks)"
    )
    validate_cmd.add_argument("--contract", required=True)
    validate_cmd.add_argument("--json", action="store_true")
    validate_cmd.add_argument("--exit-zero", action="store_true")
    validate_cmd.add_argument("--strict", action="store_true")
    validate_cmd.add_argument("--django-settings", default=None)
    validate_cmd.set_defaults(func=_contract_validate)
