"""Scan configured workbooks for formula regex patterns."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from connectors.google_sheets import SHEETS_READONLY_SCOPE, build_google_service
from profiler.tools.formula_scanner import scan_workbook_patterns


def load_patterns(config: dict) -> list[tuple[str, re.Pattern[str]]]:
    """Load regex pattern tuples from a scan config dict. Returns list of ``(name, compiled_pattern)`` pairs."""
    pattern_items = config.get("patterns", [])
    if not pattern_items:
        raise CommandError("Config must include a non-empty 'patterns' list")
    return [
        (
            item["name"],
            re.compile(item["regex"], re.I if item.get("ignore_case", True) else 0),
        )
        for item in pattern_items
    ]


def load_workbooks(config: dict) -> list[tuple[str, str]]:
    """Load workbook ID/title pairs from a scan config dict."""
    workbooks = config.get("workbooks", [])
    if not workbooks:
        raise CommandError("Config must include a non-empty 'workbooks' list")
    return [(item["name"], item["spreadsheet_id"]) for item in workbooks]


class Command(BaseCommand):
    """Scan configured workbooks for formula regex patterns."""

    help = "Scan configured workbooks for formula regex patterns"

    def add_arguments(self, parser: argparse.ArgumentParser):
        """Add command-line arguments for scan_formula_patterns."""
        parser.add_argument(
            "--config", required=True, help="JSON config with workbooks and patterns"
        )
        parser.add_argument("--out", required=True, help="Output JSON path")
        parser.add_argument(
            "--smoke", action="store_true", help="Run without network calls"
        )

    def handle(self, *args, **options):
        """Execute the formula scan pipeline. Reads workbook and pattern config, scans each workbook cell for pattern matches, and writes results to ``--out``."""
        config_path = Path(options["config"]).resolve()
        out_path = Path(options["out"]).resolve()
        if not config_path.exists():
            raise CommandError(f"Config not found: {config_path}")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        workbooks = load_workbooks(config)
        patterns = load_patterns(config)

        if options["smoke"]:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(
                    {
                        "mode": "smoke",
                        "workbooks": [name for name, _ in workbooks],
                        "pattern_count": len(patterns),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            self.stdout.write(
                self.style.SUCCESS(f"scan_formula_patterns smoke wrote {out_path}")
            )
            return

        service = build_google_service("sheets", "v4", [SHEETS_READONLY_SCOPE])
        results = []
        for name, spreadsheet_id in workbooks:
            results.append(
                {
                    "workbook": name,
                    "spreadsheet_id": spreadsheet_id,
                    "matches": scan_workbook_patterns(
                        service, spreadsheet_id, patterns
                    ),
                }
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"wrote {out_path}"))
