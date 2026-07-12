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
from dataclasses import asdict
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
import uuid

from deployment.manifest import (
    ManifestValidationError,
    ensure_manifest_valid,
    load_manifest,
)

from workbook.tools.vertical_registry import discover_verticals, load_vertical

try:
    from workbook.tools.queue_protocol import QUEUE_LABELS as _QUEUE_LABELS
except ImportError:
    _QUEUE_LABELS = {}

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


def _contract_diff(args: argparse.Namespace) -> int:
    _setup_django(settings_module=getattr(args, "django_settings", None))
    from workbook.codegen.contract import diff_contracts, load_contract

    try:
        old_contract = load_contract(args.old)
        new_contract = load_contract(args.new)
    except Exception as exc:
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
            {
                "ok": False,
                "error_code": ERROR_CODES["drift_check"],
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
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command

    kwargs = {"contract": args.contract}
    if getattr(args, "strict", False):
        kwargs["strict"] = True
    if getattr(args, "dump_json", False):
        kwargs["dump_json"] = True
    try:
        call_command("validate_contract", **kwargs)
        return 0
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


def _generate_models(args: argparse.Namespace) -> int:
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command

    kwargs = {
        "contract": args.contract,
        "out": args.out,
        "app_label": args.app_label,
        "force": args.force,
        "diff": args.diff,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command("generate_models", **kwargs)
    return 0


def _generate_admin(args: argparse.Namespace) -> int:
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command

    kwargs = {
        "contract": args.contract,
        "manifest": args.manifest,
        "codegen_manifest": getattr(args, "codegen_manifest", None),
        "out": args.out,
        "app_label": args.app_label,
        "force": args.force,
        "diff": args.diff,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command("generate_admin", **kwargs)
    return 0


def _generate_import(args: argparse.Namespace) -> int:
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command

    kwargs = {
        "contract": args.contract,
        "out": args.out,
        "app_label": args.app_label,
        "force": args.force,
        "diff": args.diff,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command("generate_import", **kwargs)
    return 0


def _generate_manifest(args: argparse.Namespace) -> int:
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command

    kwargs = {
        "structure": args.structure,
        "out": args.out,
    }
    if args.contract:
        kwargs["schema_contract"] = args.contract
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command("scaffold_view_manifest", **kwargs)
    return 0


def _generate_views(args: argparse.Namespace) -> int:
    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command

    kwargs: dict[str, Any] = {
        "contract": args.contract,
        "out_dir": args.out_dir,
    }
    if getattr(args, "app_label", None):
        kwargs["app_label"] = args.app_label
    if getattr(args, "archetype_checklist", None):
        kwargs["archetype_checklist"] = args.archetype_checklist
    if getattr(args, "archetype_landing", None):
        kwargs["archetype_landing"] = args.archetype_landing
    if getattr(args, "archetype_dashboard", None):
        kwargs["archetype_dashboard"] = args.archetype_dashboard
    if getattr(args, "template_package", None):
        kwargs["template_package"] = args.template_package
    if getattr(args, "force", None):
        kwargs["force"] = args.force
    if getattr(args, "validate", None):
        kwargs["validate"] = args.validate
    call_command("generate_views", **kwargs)
    return 0


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


def _vertical_list(args: argparse.Namespace) -> int:
    """List available vertical templates."""
    try:
        verticals = discover_verticals()
        if args.json:
            return _render_output(
                {
                    "ok": True,
                    "error_code": None,
                    "message": f"Found {len(verticals)} vertical(s).",
                    "verticals": verticals,
                },
                args.json,
            )

        if not verticals:
            print("No vertical templates found.")
            return 0

        # Print table header
        print(f"{'Name':<15} {'Version':<10} {'Confidence':<12} {'Description'}")
        print("-" * 80)
        for v in verticals:
            name = v.get("name", "")
            version = v.get("version", "")
            confidence = v.get("confidence", "")
            description = v.get("description", "")
            # Truncate description if too long
            if len(description) > 50:
                description = description[:47] + "..."
            print(f"{name:<15} {version:<10} {confidence:<12} {description}")
        return 0
    except Exception as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["unexpected"],
                "message": str(exc),
            },
            args.json,
        )


def _vertical_show(args: argparse.Namespace) -> int:
    """Show details of a vertical template."""
    try:
        vertical = load_vertical(args.name)
        if args.json:
            # Convert VerticalTemplate to dict for JSON output
            from dataclasses import asdict

            return _render_output(
                {
                    "ok": True,
                    "error_code": None,
                    "message": f"Vertical '{args.name}' details.",
                    "vertical": asdict(vertical),
                },
                args.json,
            )

        # Pretty print vertical details
        print(f"Name: {vertical.name}")
        print(f"Version: {vertical.version}")
        print(f"Description: {vertical.description}")
        print(f"Confidence: {vertical.confidence}")

        if vertical.domain_context:
            print("\nDomain Context:")
            if vertical.domain_context.get("vocabulary"):
                print("  Vocabulary:")
                for category, terms in vertical.domain_context["vocabulary"].items():
                    print(f"    {category}: {', '.join(terms)}")
            if vertical.domain_context.get("glossary"):
                print("  Glossary:")
                for term, definition in vertical.domain_context["glossary"].items():
                    print(f"    {term}: {definition}")
            if vertical.domain_context.get("entities"):
                print("  Entities:")
                for entity in vertical.domain_context["entities"]:
                    print(
                        f"    - {entity.get('name', 'Unknown')}: {entity.get('description', '')}"
                    )

        if vertical.entity_templates:
            print("\nEntity Templates:")
            for entity_name, template in vertical.entity_templates.items():
                print(f"  {entity_name}:")
                if template.get("model_meta"):
                    meta = template["model_meta"]
                    if meta.get("verbose_name"):
                        print(f"    verbose_name: {meta['verbose_name']}")
                    if meta.get("verbose_name_plural"):
                        print(f"    verbose_name_plural: {meta['verbose_name_plural']}")
                    if meta.get("ordering"):
                        print(f"    ordering: {meta['ordering']}")
                if template.get("columns"):
                    print(f"    Columns ({len(template['columns'])}):")
                    for col in template["columns"]:
                        col_name = col.get("name", "unknown")
                        data_type = col.get("data_type", "unknown")
                        nullable = "NULL" if col.get("null", True) else "NOT NULL"
                        print(f"      - {col_name} ({data_type}, {nullable})")
                if template.get("admin"):
                    admin = template["admin"]
                    if admin.get("list_display"):
                        print(f"    list_display: {admin['list_display']}")
                    if admin.get("search_fields"):
                        print(f"    search_fields: {admin['search_fields']}")
                    if admin.get("list_filter"):
                        print(f"    list_filter: {admin['list_filter']}")
                if template.get("import_config"):
                    import_config = template["import_config"]
                    if import_config.get("unique_on"):
                        print(f"    unique_on: {import_config['unique_on']}")
                    if import_config.get("fk_lookup"):
                        print(f"    fk_lookup: {import_config['fk_lookup']}")

        if vertical.interaction_defaults:
            print("\nInteraction Defaults:")
            if vertical.interaction_defaults.get("roles"):
                print("  Roles:")
                for role, config in vertical.interaction_defaults["roles"].items():
                    print(f"    {role}:")
                    print(f"      archetype: {config.get('archetype', 'unknown')}")
                    print(f"      tabs: {config.get('tabs', [])}")

        if vertical.signal_thresholds:
            print("\nSignal Thresholds:")
            for key, value in vertical.signal_thresholds.items():
                print(f"  {key}: {value}")

        return 0
    except FileNotFoundError:
        return _render_output(
            {
                "ok": False,
                "error_code": "WB-VERTICAL-4001",
                "message": f"Vertical template '{args.name}' not found.",
            },
            args.json,
        )
    except Exception as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["unexpected"],
                "message": str(exc),
            },
            args.json,
        )


def _ecosystem_health(args: argparse.Namespace) -> int:
    """Check health of the filesystem queue protocol.

    Reports entry counts, stale entries, and malformed entries per queue.
    """
    from workbook.tools.queue_protocol import check_queue_health

    try:
        reports = check_queue_health()
    except FileNotFoundError as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": "WB-ECOSYSTEM-3001",
                "message": str(exc),
            },
            args.json,
        )

    if args.json:
        return _render_output(
            {
                "ok": True,
                "error_code": None,
                "message": f"Checked {len(reports)} queue(s).",
                "queues": [r.to_dict() for r in reports],
            },
            args.json,
        )

    total_stale = 0
    total_malformed = 0
    for report in reports:
        label = _QUEUE_LABELS.get(report.queue_name, report.queue_name)

        if report.by_status:
            status_parts = " | ".join(
                f"{s}: {c}" for s, c in sorted(report.by_status.items())
            )
        else:
            status_parts = "empty"

        print(f"{report.queue_name:<12} {status_parts}")
        print(f"  {label}")
        print(f"  {report.total_entries} total")

        if report.oldest_unconsumed_name and report.oldest_unconsumed_hours is not None:
            print(
                f"  Oldest unconsumed: {report.oldest_unconsumed_name} "
                f"({report.oldest_unconsumed_hours:.1f}h)"
            )

        if report.stale_entries:
            total_stale += len(report.stale_entries)
            print(f"  STALE ({len(report.stale_entries)}):")
            for entry in report.stale_entries:
                print(
                    f"    - {entry['filename']} ({entry['status']}, "
                    f"{entry['age_hours']}h / {entry['timeout_hours']}h timeout)"
                )

        if report.malformed_entries:
            total_malformed += len(report.malformed_entries)
            print(f"  MALFORMED ({len(report.malformed_entries)}):")
            for malformed in report.malformed_entries:
                print(f"    - {malformed}")

        if report.validation_errors:
            print(f"  CONSISTENCY ERRORS ({len(report.validation_errors)}):")
            for validation_error in report.validation_errors:
                print(f"    - {validation_error}")

        print()

    if total_stale:
        print(f"Total stale: {total_stale}")
    if total_malformed:
        print(f"Total malformed: {total_malformed}")
    return 0


def _ecosystem_ack(args: argparse.Namespace) -> int:
    """Acknowledge a queue entry as consumed (or active).

    Usage: wb ecosystem ack <queue> <filename> [--status active|consumed]
    """
    from workbook.tools.queue_protocol import (
        acknowledge_activation,
        acknowledge_consumption,
        find_omo_root,
    )

    try:
        omo_root = find_omo_root()
    except FileNotFoundError as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": "WB-ECOSYSTEM-3001",
                "message": str(exc),
            },
            args.json,
        )

    queue_dir = omo_root / args.queue
    target_path = queue_dir / args.filename

    if not target_path.is_file():
        return _render_output(
            {
                "ok": False,
                "error_code": "WB-ECOSYSTEM-3002",
                "message": f"File not found: {target_path}",
            },
            args.json,
        )

    new_status = getattr(args, "status", "consumed")
    try:
        if new_status == "active":
            acknowledge_activation(target_path, actor=getpass.getuser())
        elif new_status == "consumed":
            acknowledge_consumption(target_path, actor=getpass.getuser())
        else:
            return _render_output(
                {
                    "ok": False,
                    "error_code": "WB-ECOSYSTEM-3003",
                    "message": f"Invalid status '{new_status}'. Use 'active' or 'consumed'.",
                },
                args.json,
            )
    except Exception as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": "WB-ECOSYSTEM-3004",
                "message": f"Failed to acknowledge: {exc}",
            },
            args.json,
        )

    return _render_output(
        {
            "ok": True,
            "error_code": None,
            "message": f"Acknowledged '{args.filename}' in '{args.queue}' as {new_status}.",
        },
        args.json,
    )


def _deploy_live(args: argparse.Namespace) -> int:
    """Perform a live deploy: validate manifest, deploy, health-check, record."""
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


def _drift_check(args: argparse.Namespace) -> int:
    """Compare a baseline contract against a new contract and report drift.

    Delegates to ``diff_contracts`` and ``migration_safety_checks`` to detect
    structural changes and migration risks between the two contracts.
    """
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


def _build_generate_parser(sub: argparse._SubParsersAction) -> None:
    """Add 'generate {models,admin,import,manifest}' subcommands to *sub*."""
    gen_cmd = sub.add_parser("generate", help="Generate code from a schema contract")
    gen_sub = gen_cmd.add_subparsers(dest="generate_command", required=True)

    models_cmd = gen_sub.add_parser("models", help="Generate Django models.py")
    models_cmd.add_argument("--contract", required=True)
    models_cmd.add_argument("--out", default=None)
    models_cmd.add_argument("--app-label", default=None)
    models_cmd.add_argument("--force", action="store_true")
    models_cmd.add_argument("--diff", action="store_true")
    models_cmd.add_argument("--django-settings", default=None)
    models_cmd.set_defaults(func=_generate_models)

    admin_cmd = gen_sub.add_parser("admin", help="Generate Django admin.py")
    admin_cmd.add_argument("--contract", required=True)
    admin_cmd.add_argument("--manifest", default=None)
    admin_cmd.add_argument("--codegen-manifest", default=None)
    admin_cmd.add_argument("--out", default=None)
    admin_cmd.add_argument("--app-label", default=None)
    admin_cmd.add_argument("--force", action="store_true")
    admin_cmd.add_argument("--diff", action="store_true")
    admin_cmd.add_argument("--django-settings", default=None)
    admin_cmd.set_defaults(func=_generate_admin)

    import_cmd = gen_sub.add_parser("import", help="Generate Django import command")
    import_cmd.add_argument("--contract", required=True)
    import_cmd.add_argument("--out", default=None)
    import_cmd.add_argument("--app-label", default=None)
    import_cmd.add_argument("--force", action="store_true")
    import_cmd.add_argument("--diff", action="store_true")
    import_cmd.add_argument("--django-settings", default=None)
    import_cmd.set_defaults(func=_generate_import)

    manifest_cmd = gen_sub.add_parser("manifest", help="Generate view manifest")
    manifest_cmd.add_argument("--contract", required=True)
    manifest_cmd.add_argument("--out", default=None)
    manifest_cmd.add_argument("--structure", default=None)
    manifest_cmd.add_argument("--django-settings", default=None)
    manifest_cmd.set_defaults(func=_generate_manifest)

    views_cmd = gen_sub.add_parser("views", help="Generate Django views, templates, and URLs")
    views_cmd.add_argument("--contract", required=True)
    views_cmd.add_argument("--out-dir", required=True)
    views_cmd.add_argument("--app-label", default=None)
    views_cmd.add_argument("--archetype-checklist", default=None)
    views_cmd.add_argument("--archetype-landing", default=None)
    views_cmd.add_argument("--archetype-dashboard", default=None)
    views_cmd.add_argument("--template-package", default=None)
    views_cmd.add_argument("--force", action="store_true")
    views_cmd.add_argument("--validate", action="store_true")
    views_cmd.add_argument("--django-settings", default=None)
    views_cmd.set_defaults(func=_generate_views)


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

    manifest_cmd = sub.add_parser("manifest", help="Manifest operations")
    manifest_sub = manifest_cmd.add_subparsers(dest="manifest_command", required=True)
    lint_cmd = manifest_sub.add_parser("lint", help="Validate deployment manifest")
    lint_cmd.set_defaults(func=_manifest_lint)

    contract_cmd = sub.add_parser("contract", help="Schema contract operations")
    contract_sub = contract_cmd.add_subparsers(dest="contract_command", required=True)
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

    validate_cmd = contract_sub.add_parser(
        "validate", help="Validate a schema contract (structural checks)"
    )
    validate_cmd.add_argument("--contract", required=True)
    validate_cmd.add_argument("--json", action="store_true")
    validate_cmd.add_argument("--exit-zero", action="store_true")
    validate_cmd.add_argument("--strict", action="store_true")
    validate_cmd.add_argument("--django-settings", default=None)
    validate_cmd.set_defaults(func=_contract_validate)

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
    deploy_cmd.set_defaults(func=_deploy_dry_run)

    _build_generate_parser(sub)

    # Vertical subcommands
    vertical_cmd = sub.add_parser("vertical", help="Vertical template operations")
    vertical_sub = vertical_cmd.add_subparsers(dest="vertical_command", required=True)

    # wb vertical list
    list_cmd = vertical_sub.add_parser("list", help="List available vertical templates")
    list_cmd.add_argument(
        "--json", action="store_true", help="Return machine-readable JSON output."
    )
    list_cmd.set_defaults(func=_vertical_list)

    # wb vertical show <name>
    show_cmd = vertical_sub.add_parser(
        "show", help="Show details of a vertical template"
    )
    show_cmd.add_argument("name", help="Name of the vertical template to show")
    show_cmd.add_argument(
        "--json", action="store_true", help="Return machine-readable JSON output."
    )
    show_cmd.set_defaults(func=_vertical_show)

    # Ecosystem subcommands
    ecosystem_cmd = sub.add_parser("ecosystem", help="Ecosystem protocol operations")
    ecosystem_sub = ecosystem_cmd.add_subparsers(
        dest="ecosystem_command", required=True
    )

    health_cmd = ecosystem_sub.add_parser("health", help="Check queue protocol health")
    health_cmd.set_defaults(func=_ecosystem_health)

    ack_cmd = ecosystem_sub.add_parser(
        "ack", help="Acknowledge a queue entry (mark as consumed or active)"
    )
    ack_cmd.add_argument(
        "queue", help="Queue name (next, ready, exercise, results, etc.)"
    )
    ack_cmd.add_argument("filename", help="Queue entry filename")
    ack_cmd.add_argument(
        "--status",
        choices=["active", "consumed"],
        default="consumed",
        help="Lifecycle status to set (default: consumed)",
    )
    ack_cmd.set_defaults(func=_ecosystem_ack)
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
