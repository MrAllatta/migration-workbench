#!/usr/bin/env python3
"""Extract workbook codes from a drive tree and optionally update corpus config."""

from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Extract workbook codes from drive tree JSON and optionally update config."

    def add_arguments(self, parser):
        parser.add_argument(
            "--drive-tree", required=True, help="Path to drive_tree.json"
        )
        parser.add_argument(
            "--config", required=True, help="Path to cohort_corpus.json"
        )
        parser.add_argument(
            "--update-config",
            action="store_true",
            help="Rewrite in_scope_workbooks in config",
        )
        parser.add_argument("--smoke", action="store_true", help="Smoke test mode")

    def handle(self, *args, **options):
        drive_tree_path = Path(options["drive_tree"]).resolve()
        config_path = Path(options["config"]).resolve()

        if options["smoke"]:
            self.stdout.write(self.style.SUCCESS("extract_workbook_codes smoke ok"))
            return

        if not drive_tree_path.exists():
            raise CommandError(f"Drive tree not found: {drive_tree_path}")
        if not config_path.exists():
            raise CommandError(f"Config not found: {config_path}")

        tree = json.loads(drive_tree_path.read_text(encoding="utf-8"))
        config = json.loads(config_path.read_text(encoding="utf-8"))

        regex_str = config.get("workbook_id_regex", r"\\b(\\d{3})\\b")
        try:
            pattern = re.compile(regex_str)
        except re.error as exc:
            raise CommandError(f"Invalid workbook_id_regex: {exc}") from exc

        codes: set[str] = set()

        def walk(node: dict):
            for sheet in node.get("spreadsheets", []):
                name = sheet.get("name", "")
                match = pattern.search(name)
                if match and match.groups():
                    codes.add(match.group(1))
            for sub in node.get("folders", []):
                walk(sub)

        walk(tree)
        sorted_codes = sorted(codes)

        self.stdout.write(f"Found {len(sorted_codes)} workbook code(s):")
        for code in sorted_codes:
            self.stdout.write(f"  {code}")

        if options["update_config"]:
            config["in_scope_workbooks"] = sorted_codes
            bak_path = config_path.with_suffix(".json.bak")
            bak_path.write_text(
                config_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            config_path.write_text(
                json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            self.stdout.write(
                self.style.SUCCESS(f"Updated {config_path} (backup: {bak_path})")
            )
