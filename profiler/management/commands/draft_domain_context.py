#!/usr/bin/env python3
"""Draft a domain_context.yaml from drive tree and optional raw notes."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError

_STARTER_KEYWORDS = {
    "operational": ["planting", "harvest", "order", "sale", "purchase", "delivery"],
    "reference": ["variety", "crop", "farm", "field", "block", "customer", "product"],
    "support": ["index", "lookup", "validation", "helper", "config"],
    "derived": ["summary", "pivot", "rollup", "total", "report", "dashboard"],
}

_YEAR_RE = re.compile(r"\b(20\d{2})\b")


class Command(BaseCommand):
    """Draft a ``domain_context.yaml`` from a drive tree JSON and optional raw notes."""

    help = "Draft domain_context.yaml from drive tree and optional raw notes."

    def add_arguments(self, parser):
        """Add CLI arguments for the ``draft_domain_context`` command."""
        parser.add_argument(
            "--drive-tree", required=True, help="Path to drive_tree.json"
        )
        parser.add_argument(
            "--raw-notes-dir", default=None, help="Directory with .md/.txt raw notes"
        )
        parser.add_argument("--out", default=None, help="Output path (default: stdout)")
        parser.add_argument("--smoke", action="store_true", help="Smoke test mode")

    def handle(self, *args, **options):
        """Walk the drive tree, extract years and vocabulary, then write domain context YAML."""
        if options["smoke"]:
            self.stdout.write(self.style.SUCCESS("draft_domain_context smoke ok"))
            return

        tree_path = Path(options["drive_tree"]).resolve()
        if not tree_path.exists():
            raise CommandError(f"Drive tree not found: {tree_path}")

        tree = json.loads(tree_path.read_text(encoding="utf-8"))

        years: set[int] = set()

        def walk(node: dict):
            """Recursively extract years from folder/spreadsheet names in the drive tree."""
            name = node.get("name", "")
            for m in _YEAR_RE.finditer(name):
                years.add(int(m.group(1)))
            for sheet in node.get("spreadsheets", []):
                sheet_name = sheet.get("name", "")
                for m in _YEAR_RE.finditer(sheet_name):
                    years.add(int(m.group(1)))
            for sub in node.get("folders", []):
                walk(sub)

        walk(tree)
        sorted_years = sorted(years)

        if len(sorted_years) >= 2:
            active_years = sorted_years[-2:]
            archived_years = sorted_years[:-2]
        else:
            active_years = sorted_years
            archived_years = []

        vocabulary = {k: [] for k in _STARTER_KEYWORDS}

        raw_notes_dir = options.get("raw_notes_dir")
        if raw_notes_dir:
            raw_path = Path(raw_notes_dir).resolve()
            if raw_path.exists():
                all_words: list[str] = []
                for fp in raw_path.rglob("*"):
                    if fp.is_file() and fp.suffix in (".md", ".txt"):
                        text = fp.read_text(encoding="utf-8", errors="ignore")
                        words = re.findall(r"[a-zA-Z]{3,}", text.lower())
                        all_words.extend(words)

                freq = Counter(all_words)
                for category, starters in _STARTER_KEYWORDS.items():
                    hits = [
                        (word, count)
                        for word, count in freq.most_common(200)
                        if word in starters
                    ]
                    vocabulary[category] = [word for word, _count in hits[:5]]

        payload = {
            "_documentation": {
                "generated": "draft — review required",
                "domain": "Short slug for the business domain",
                "year_scope": "Populate from drive tree inspection",
            },
            "domain": "",
            "description": "",
            "year_scope": {
                "active": active_years,
                "archived": archived_years,
                "forward": [],
            },
            "deduplication": {
                "strategy": "latest_year",
                "exceptions": [{"tab_title": "", "reason": ""}],
            },
            "entities": [],
            "vocabulary": vocabulary,
            "glossary": {},
            "scope_notes": "",
        }

        yaml_text = yaml.dump(
            payload, default_flow_style=False, sort_keys=False, allow_unicode=True
        )

        out_path = options.get("out")
        if out_path:
            Path(out_path).write_text(yaml_text, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Draft written to {out_path}"))
        else:
            self.stdout.write(yaml_text)
