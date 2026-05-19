"""Run cohort-corpus profiling pipeline for config-driven workbook sets."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from connectors.google_sheets import (
    DRIVE_READONLY_SCOPE,
    SHEETS_READONLY_SCOPE,
    build_google_service,
)
from profiler.tools.cohort_corpus import run_cohort_corpus


class Command(BaseCommand):
    """Run cohort-corpus profiling pipeline for config-driven workbook sets."""

    help = "Run cohort-corpus profiling pipeline for config-driven workbook sets."

    def add_arguments(self, parser):
        """Add command-line arguments for profile_cohort_corpus."""
        parser.add_argument(
            "--config",
            required=True,
            help="JSON config path for cohort-corpus profiling",
        )
        parser.add_argument(
            "--folder", help="Drive folder id or URL (default: DRIVE_FOLDER_ID env)"
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
            "--smoke", action="store_true", help="Run without Google API calls"
        )
        parser.add_argument(
            "--resume-from-tab-selection",
            action="store_true",
            help=(
                "Read tab_selection_<date>.json and in_scope_workbook_index_<date>.json from "
                "--out-dir from a prior full run, skipping Drive discovery and broad tab listing "
                "before deep profiling. Use after hand-editing tab_selection_<date>.json."
            ),
        )
        parser.add_argument(
            "--stop-before-deep",
            action="store_true",
            help=(
                "Stop after writing tab selection; skip deep grid fetches and "
                "column scoring. Use for Phase 1 (discovery + tab selection) "
                "before committing to expensive deep API calls."
            ),
        )
        parser.add_argument(
            "--resume-from-broad",
            action="store_true",
            help=(
                "Phase 2 mode: re-read broad_profile_coverage_<date>.json and "
                "in_scope_workbook_index_<date>.json from disk, then re-run tab "
                "scoring and selection using current config heuristics. No Drive "
                "or Sheets API calls. Combine with --stop-before-deep to stop after "
                "selection, or omit it to continue into deep profiling."
            ),
        )
        parser.add_argument(
            "--skip-existing-deep",
            action="store_true",
            help=(
                "Reuse existing per-tab payloads under deep/ when filenames match pending jobs "
                "instead of refetching Sheets grid data—useful together with backoff after 429 "
                'throttling or with JSON "deep_skip_existing": true.'
            ),
        )

    def handle(self, *args, **options):
        """Execute the cohort-corpus profiling pipeline. Discovers, scores, and profiles workbook tabs across multiple years, writing artifacts to ``--out-dir``."""
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
                "folder_id": config.get("folder_id"),
                "in_scope_count": len(config.get("in_scope_workbooks") or []),
            }
            out_path = out_dir / f"profile_cohort_corpus_smoke_{date_stamp}.json"
            out_path.write_text(json.dumps(smoke_payload, indent=2), encoding="utf-8")
            self.stdout.write(
                self.style.SUCCESS(f"profile_cohort_corpus smoke wrote {out_path}")
            )
            return

        folder_id = options.get("folder") or os.environ.get("DRIVE_FOLDER_ID")
        if not folder_id:
            raise CommandError(
                "A Drive folder id is required. Pass --folder or set DRIVE_FOLDER_ID in .env"
            )
        from connectors.google_sheets import extract_drive_folder_id

        folder_id = extract_drive_folder_id(folder_id)

        scopes = [SHEETS_READONLY_SCOPE, DRIVE_READONLY_SCOPE]
        drive_service = build_google_service("drive", "v3", scopes)
        sheets_service = build_google_service("sheets", "v4", scopes)
        outputs = run_cohort_corpus(
            drive_service=drive_service,
            sheets_service=sheets_service,
            folder_id=folder_id,
            config=config,
            out_dir=out_dir,
            date_stamp=date_stamp,
            resume_from_tab_selection=options.get("resume_from_tab_selection", False),
            resume_from_broad=options.get("resume_from_broad", False),
            stop_before_deep=options.get("stop_before_deep", False),
            skip_existing_deep=options.get("skip_existing_deep", False),
        )
        self.stdout.write(self.style.SUCCESS("profile_cohort_corpus wrote artifacts:"))
        for key, path in outputs.items():
            self.stdout.write(f"- {key}: {path}")
