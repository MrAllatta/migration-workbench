from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from connectors.coda_source import (
    build_coda_session,
    formula_text,
    list_columns,
    list_tables,
    resolve_doc_id,
)
from profiler.management.commands.scan_formula_patterns import load_patterns


def load_coda_workbooks(session, config: dict) -> list[tuple[str, str]]:
    workbooks = config.get("workbooks", [])
    if not workbooks:
        raise CommandError("Config must include a non-empty 'workbooks' list")
    resolved: list[tuple[str, str]] = []
    for item in workbooks:
        name = item.get("name") or "workbook"
        raw = item.get("doc_url") or item.get("doc_id")
        doc_id = resolve_doc_id(session, raw) if raw else None
        if not doc_id:
            raise CommandError(f"workbook {name!r} needs doc_url or doc_id")
        resolved.append((name, doc_id))
    return resolved


def scan_doc_for_formula_columns(session, doc_id: str, patterns: list[tuple[str, re.Pattern[str]]]):
    matches = []
    tables = list_tables(session, doc_id)
    for table in tables:
        tid = table.get("id")
        tname = table.get("name")
        if not tid:
            continue
        columns = list_columns(session, doc_id, tid)
        for col in columns:
            ft = formula_text(col)
            if not str(ft).strip():
                continue
            for pname, pattern in patterns:
                if pattern.search(ft):
                    matches.append(
                        {
                            "table": tname,
                            "table_id": tid,
                            "column": col.get("name"),
                            "column_id": col.get("id"),
                            "pattern": pname,
                            "formula_text": ft,
                        }
                    )
    return matches


class Command(BaseCommand):
    help = "Scan Coda docs for column-level formula text matching regex patterns"

    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument("--config", required=True, help="JSON config with workbooks (doc_url) and patterns")
        parser.add_argument("--out", required=True, help="Output JSON path")
        parser.add_argument("--smoke", action="store_true", help="Run without network calls")

    def handle(self, *args, **options):
        config_path = Path(options["config"]).resolve()
        out_path = Path(options["out"]).resolve()
        if not config_path.exists():
            raise CommandError(f"Config not found: {config_path}")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        patterns = load_patterns(config)

        if options["smoke"]:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            workbooks = config.get("workbooks", [])
            if not workbooks:
                raise CommandError("Config must include a non-empty 'workbooks' list")
            names = [item.get("name") or "workbook" for item in workbooks]
            out_path.write_text(
                json.dumps(
                    {
                        "mode": "smoke",
                        "workbooks": names,
                        "pattern_count": len(patterns),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            self.stdout.write(self.style.SUCCESS(f"scan_coda_formula_columns smoke wrote {out_path}"))
            return

        session = build_coda_session()
        workbooks = load_coda_workbooks(session, config)
        results = []
        for name, doc_id in workbooks:
            results.append(
                {
                    "workbook": name,
                    "doc_id": doc_id,
                    "matches": scan_doc_for_formula_columns(session, doc_id, patterns),
                }
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"wrote {out_path}"))
