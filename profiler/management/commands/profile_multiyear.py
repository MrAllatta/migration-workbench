from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from connectors.google_sheets import DRIVE_READONLY_SCOPE, SHEETS_READONLY_SCOPE, build_google_service
from profiler.tools.farm.multiyear import run_multiyear


class Command(BaseCommand):
    help = "Run multi-year profiling pipeline for config-driven workbook sets."

    def add_arguments(self, parser):
        parser.add_argument("--config", required=True, help="JSON config path for multi-year profiling")
        parser.add_argument("--out-dir", required=True, help="Output directory for profiling artifacts")
        parser.add_argument("--date-stamp", default=None, help="Optional date stamp override (YYYY-MM-DD)")
        parser.add_argument("--smoke", action="store_true", help="Run without Google API calls")

    def handle(self, *args, **options):
        config_path = Path(options["config"]).resolve()
        if not config_path.exists():
            raise CommandError(f"Config not found: {config_path}")
        config = json.loads(config_path.read_text(encoding="utf-8"))

        out_dir = Path(options["out_dir"]).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        date_stamp = options.get("date_stamp") or datetime.now(UTC).date().isoformat()

        if options["smoke"]:
            smoke_payload = {
                "mode": "smoke",
                "config": str(config_path),
                "out_dir": str(out_dir),
                "date_stamp": date_stamp,
                "in_scope_count": len(config.get("in_scope_workbooks") or []),
            }
            out_path = out_dir / f"profile_multiyear_smoke_{date_stamp}.json"
            out_path.write_text(json.dumps(smoke_payload, indent=2), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"profile_multiyear smoke wrote {out_path}"))
            return

        scopes = [SHEETS_READONLY_SCOPE, DRIVE_READONLY_SCOPE]
        drive_service = build_google_service("drive", "v3", scopes)
        sheets_service = build_google_service("sheets", "v4", scopes)
        outputs = run_multiyear(
            drive_service=drive_service,
            sheets_service=sheets_service,
            config=config,
            out_dir=out_dir,
            date_stamp=date_stamp,
        )
        self.stdout.write(self.style.SUCCESS("profile_multiyear wrote artifacts:"))
        for key, path in outputs.items():
            self.stdout.write(f"- {key}: {path}")

