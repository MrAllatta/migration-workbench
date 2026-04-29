from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from connectors.coda_source import build_coda_session
from profiler.tools.coda_corpus import write_json


class Command(BaseCommand):
    help = "Run multi-doc Coda profiling pipeline (discovery → index → broad → deep → column candidates)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--config", required=True, help="JSON config path for Coda corpus profiling"
        )
        parser.add_argument(
            "--out-dir", required=True, help="Output directory for profiling artifacts"
        )
        parser.add_argument(
            "--date-stamp",
            default=None,
            help="Optional date stamp override (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--smoke", action="store_true", help="Run without Coda API calls"
        )
        parser.add_argument(
            "--resume-from-table-selection",
            action="store_true",
            help=(
                "Skip table selection generation and read table_selection_<date>.json from --out-dir "
                "to drive the deep-profile pass. Use after hand-editing the table selection file."
            ),
        )

    def handle(self, *args, **options):
        config_path = Path(options["config"]).resolve()
        if not config_path.exists():
            raise CommandError(f"Config not found: {config_path}")
        config = json.loads(config_path.read_text(encoding="utf-8"))

        out_dir = Path(options["out_dir"]).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        date_stamp = options.get("date_stamp") or datetime.now(UTC).date().isoformat()

        if options["smoke"]:
            docs = config.get("docs") or []
            if not docs:
                raise CommandError("Config must include a non-empty 'docs' list")
            discovery_path = out_dir / f"coda_discovery_{date_stamp}.json"
            index_path = out_dir / f"coda_table_index_{date_stamp}.json"
            discovery_payload = {
                "mode": "smoke",
                "date_stamp": date_stamp,
                "config": str(config_path),
                "docs": [
                    {
                        "name": d.get("name"),
                        "doc_url": d.get("doc_url"),
                        "doc_id": d.get("doc_id"),
                    }
                    for d in docs
                ],
            }
            write_json(discovery_path, discovery_payload)
            write_json(
                index_path,
                {
                    "mode": "smoke",
                    "generated_from": discovery_path.name,
                    "base_tables": [],
                    "views": [],
                },
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"profile_coda_corpus smoke wrote {discovery_path} and {index_path}"
                )
            )
            return

        from profiler.tools.coda_corpus import run_coda_corpus

        session = build_coda_session()
        outputs = run_coda_corpus(
            session=session,
            config=config,
            out_dir=out_dir,
            date_stamp=date_stamp,
            resume_from_table_selection=options.get(
                "resume_from_table_selection", False
            ),
        )
        self.stdout.write(self.style.SUCCESS("profile_coda_corpus wrote artifacts:"))
        for key, path in outputs.items():
            self.stdout.write(f"- {key}: {path}")
