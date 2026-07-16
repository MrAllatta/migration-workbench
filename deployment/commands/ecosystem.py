"""Ecosystem command group ("wb ecosystem ...").

Extracted from deployment/wb_cli as part of e03s04
(cli-router-split). Owns:

- ``_ecosystem_health`` — check filesystem queue protocol health
- ``_ecosystem_ack`` — acknowledge queue entries
- ``build_ecosystem_parser`` — wire the ``ecosystem`` subparser
"""

from __future__ import annotations

import argparse
import getpass


try:
    from workbook.tools.queue_protocol import QUEUE_LABELS as _QUEUE_LABELS
except ImportError:
    _QUEUE_LABELS: dict[str, str] = {}


_QUEUE_LABELS: dict[str, str]


def _ecosystem_health(args: argparse.Namespace) -> int:
    """Check health of the filesystem queue protocol.

    Reports entry counts, stale entries, and malformed entries per queue.
    """
    from deployment.wb_cli import _render_output  # noqa: PLC0415

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
    from deployment.wb_cli import _render_output  # noqa: PLC0415
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


def build_ecosystem_parser(sub: argparse._SubParsersAction) -> None:
    """Wire the ``ecosystem`` subparser into *sub*."""
    eco_cmd = sub.add_parser("ecosystem", help="Ecosystem operations")
    eco_sub = eco_cmd.add_subparsers(dest="ecosystem_command", required=True)

    health_cmd = eco_sub.add_parser("health", help="Check ecosystem health")
    health_cmd.add_argument("--json", action="store_true", help="Output as JSON")
    health_cmd.set_defaults(func=_ecosystem_health)

    ack_cmd = eco_sub.add_parser("ack", help="Acknowledge a queue entry")
    ack_cmd.add_argument("queue", help="Queue name to acknowledge")
    ack_cmd.add_argument("filename", help="Entry filename to acknowledge")
    ack_cmd.add_argument(
        "--django-settings",
        default=None,
        help="Django settings module (e.g. config.settings). "
        "Auto-detected for product repos.",
    )
    ack_cmd.set_defaults(func=_ecosystem_ack)
