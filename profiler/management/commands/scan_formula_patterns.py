from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from googleapiclient.errors import HttpError

from connectors.google_sheets import SHEETS_READONLY_SCOPE, build_google_service


def execute_with_retry(request, max_retries: int = 8):
    delay = 5.0
    for attempt in range(max_retries):
        try:
            return request.execute()
        except TimeoutError:
            if attempt + 1 >= max_retries:
                raise
            time.sleep(delay)
            delay = min(delay * 1.6, 120.0)
        except HttpError as err:
            if err.resp.status != 429 or attempt + 1 >= max_retries:
                raise
            time.sleep(delay)
            delay = min(delay * 1.6, 120.0)


def load_patterns(config: dict) -> list[tuple[str, re.Pattern[str]]]:
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
    workbooks = config.get("workbooks", [])
    if not workbooks:
        raise CommandError("Config must include a non-empty 'workbooks' list")
    return [(item["name"], item["spreadsheet_id"]) for item in workbooks]


def scan_workbook(svc, spreadsheet_id: str, patterns: list[tuple[str, re.Pattern[str]]]):
    sheets_resp = execute_with_retry(
        svc.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets(properties(title))")
    )
    sheet_titles = [s["properties"]["title"] for s in sheets_resp.get("sheets", [])]
    matches = []
    for title in sheet_titles:
        escaped_title = title.replace("'", "''")
        values_resp = execute_with_retry(
            svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"'{escaped_title}'")
        )
        for row_idx, row in enumerate(values_resp.get("values", []), start=1):
            for col_idx, value in enumerate(row, start=1):
                if not isinstance(value, str) or not value.startswith("="):
                    continue
                for name, pattern in patterns:
                    if pattern.search(value):
                        matches.append(
                            {
                                "sheet": title,
                                "row": row_idx,
                                "col": col_idx,
                                "pattern": name,
                                "formula": value,
                            }
                        )
    return matches


class Command(BaseCommand):
    help = "Scan configured workbooks for formula regex patterns"

    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument("--config", required=True, help="JSON config with workbooks and patterns")
        parser.add_argument("--out", required=True, help="Output JSON path")
        parser.add_argument("--smoke", action="store_true", help="Run without network calls")

    def handle(self, *args, **options):
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
            self.stdout.write(self.style.SUCCESS(f"scan_formula_patterns smoke wrote {out_path}"))
            return

        service = build_google_service("sheets", "v4", [SHEETS_READONLY_SCOPE])
        results = []
        for name, spreadsheet_id in workbooks:
            results.append(
                {
                    "workbook": name,
                    "spreadsheet_id": spreadsheet_id,
                    "matches": scan_workbook(service, spreadsheet_id, patterns),
                }
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"wrote {out_path}"))
