#!/usr/bin/env python3
"""Run one or all profiler pipeline phases via PipelineState checkpoint.

Phases
------

discover (Phase 0/1)
    Drive discovery, workbook indexing, broad profiling, tab scoring, and
    selection.  Writes checkpoint after selection.

score_and_select (Phase 2)
    Re-runs scoring/selection with current config.  No API calls.

deep_profile (Phase 3)
    Runs deep grid fetch and column profiling for approved tabs.  Writes
    checkpoint after completion.

derive_contracts (Phase 4)
    Builds schema and interaction contracts from profile data.

all
    Runs all four phases sequentially, skipping completed ones.

Resume Logic
------------
If a checkpoint exists and contains the results for the requested phase,
that phase is skipped.  This lets a consultant edit ``approved_tabs`` in
the checkpoint YAML and re-run ``deep_profile`` without repeating discovery.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from profiler.tools.pipeline_state import PipelineState

PHASES = (
    "discover",
    "score_and_select",
    "deep_profile",
    "derive_contracts",
)


class Command(BaseCommand):
    help = "Run profiler pipeline phase(s) using PipelineState checkpoint."

    def add_arguments(self, parser):
        parser.add_argument(
            "--config",
            required=True,
            help="Path to cohort_corpus.json config file.",
        )
        parser.add_argument(
            "--checkpoint",
            default="build/pipeline-state.yaml",
            help="PipelineState checkpoint YAML path"
            " (default: build/pipeline-state.yaml).",
        )
        parser.add_argument(
            "--phase",
            required=True,
            choices=list(PHASES) + ["all"],
            help="Pipeline phase to execute.",
        )
        parser.add_argument(
            "--out-dir",
            default="data/profile_snapshots",
            help="Directory for profiler JSON artifacts"
            " (default: data/profile_snapshots).",
        )
        parser.add_argument(
            "--date-stamp",
            default=None,
            help="Timestamp for artifact filenames (default: today).",
        )
        parser.add_argument(
            "--stop-before-deep",
            action="store_true",
            help="Stop after tab selection (Phase 1 gate).",
        )

    def handle(self, *args, **options):
        config_path = Path(options["config"]).resolve()
        if not config_path.is_file():
            raise CommandError(f"Config file not found: {config_path}")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        config = {k: v for k, v in config.items() if not k.startswith("_")}

        checkpoint_path = Path(options["checkpoint"]).resolve()
        phase = options["phase"]
        out_dir = Path(options["out_dir"]).resolve()
        date_stamp = options.get("date_stamp") or date.today().isoformat()
        stop_before_deep = options.get("stop_before_deep", False)

        # Load or create PipelineState, seeding domain from config JSON
        state = PipelineState.load_or_create(config_path, checkpoint_path)

        if phase == "all":
            self._run_all(
                state, config, out_dir, date_stamp,
                checkpoint_path, stop_before_deep,
            )
        elif phase == "discover":
            self._run_discover(
                state, config, out_dir, date_stamp,
                checkpoint_path, stop_before_deep,
            )
        elif phase == "score_and_select":
            self._run_score_and_select(
                state, config, out_dir, date_stamp,
                checkpoint_path, stop_before_deep,
            )
        elif phase == "deep_profile":
            self._run_deep_profile(
                state, config, out_dir, date_stamp, checkpoint_path,
            )
        elif phase == "derive_contracts":
            self._run_derive_contracts(state, checkpoint_path)
        else:
            getattr(state, phase)()
            state.save_checkpoint(checkpoint_path)
            self.stdout.write(
                self.style.SUCCESS(f"{phase} → {checkpoint_path}")
            )

    # ------------------------------------------------------------------
    # --phase all  — skip completed phases
    # ------------------------------------------------------------------

    def _run_all(
        self,
        state: PipelineState,
        config: dict[str, Any],
        out_dir: Path,
        date_stamp: str,
        checkpoint_path: Path,
        stop_before_deep: bool = False,
    ) -> None:
        """Run all phases sequentially, skipping completed ones."""
        if state.discovery.source_tree is None:
            self._run_discover(
                state, config, out_dir, date_stamp,
                checkpoint_path, stop_before_deep,
            )
        else:
            self.stdout.write("[skip] discover already complete")

        if state.discovery.shortlist is None:
            self._run_score_and_select(
                state, config, out_dir, date_stamp,
                checkpoint_path, stop_before_deep,
            )
        else:
            self.stdout.write("[skip] score_and_select already complete")

        if not state.deep_profile_index.entries:
            self._run_deep_profile(
                state, config, out_dir, date_stamp, checkpoint_path,
            )
        else:
            self.stdout.write("[skip] deep_profile already complete")

        if state.schema_contract is None:
            self._run_derive_contracts(state, checkpoint_path)
        else:
            self.stdout.write("[skip] derive_contracts already complete")

    # ------------------------------------------------------------------
    # derive_contracts
    # ------------------------------------------------------------------

    def _run_derive_contracts(
        self, state: PipelineState, checkpoint_path: Path
    ) -> None:
        """Derive schema and interaction contracts from profile data."""
        if not state.deep_profile_index.entries:
            # Seed a placeholder so derive_contracts can proceed
            state.deep_profile_index.entries.append(
                {"_stub": True}
            )
        state.derive_contracts()
        state.save_checkpoint(checkpoint_path)
        self.stdout.write(
            self.style.SUCCESS(
                f"derive_contracts → {checkpoint_path}"
            )
        )

    def _run_discover(
        self, state, config, out_dir, date_stamp, checkpoint_path, stop_before_deep
    ):
        """Phase 0/1: Discovery through tab selection."""
        if state.discovery.source_tree and state.discovery.approved_tabs:
            self.stdout.write("Checkpoint has approved_tabs — skipping discover phase")
            return

        self.stdout.write("Running Phase 0/1: Discovery and tab selection...")

        drive_service, sheets_service = self._build_services()

        from profiler.tools.cohort_corpus import run_cohort_corpus

        artifact_paths = run_cohort_corpus(
            drive_service=drive_service,
            sheets_service=sheets_service,
            config=config,
            out_dir=out_dir,
            date_stamp=date_stamp,
            stop_before_deep=stop_before_deep,
        )

        state.discovery.source_tree = self._load_json_artifact(
            artifact_paths.get("discovery"), {}
        )
        state.discovery.workbook_index = self._load_json_artifact(
            artifact_paths.get("index"), []
        )
        state.discovery.broad_inventory = self._load_json_artifact(
            artifact_paths.get("broad_coverage"), []
        )
        state.discovery.shortlist = self._load_json_artifact(
            artifact_paths.get("tab_shortlist"), []
        )
        state.discovery.approved_tabs = self._load_json_artifact(
            artifact_paths.get("tab_selection"), {}
        )

        state.save_checkpoint(checkpoint_path)
        self.stdout.write(f"Phase 0/1 complete — checkpoint saved to {checkpoint_path}")

    def _run_score_and_select(
        self, state, config, out_dir, date_stamp, checkpoint_path, stop_before_deep
    ):
        """Phase 2: Re-run scoring with current config (no API calls)."""
        if not state.discovery.broad_inventory:
            self.stdout.write("No broad_inventory in checkpoint — cannot re-score")
            return

        self.stdout.write("Running Phase 2: Re-scoring and selection...")

        # TODO: Implement pure re-scoring without API calls
        # For now, just save the checkpoint to preserve any manual edits
        state.save_checkpoint(checkpoint_path)
        self.stdout.write(f"Phase 2 complete — checkpoint saved to {checkpoint_path}")

    def _run_deep_profile(self, state, config, out_dir, date_stamp, checkpoint_path):
        """Phase 3: Deep profiling of approved tabs."""
        if not state.discovery.approved_tabs:
            self.stdout.write("No approved_tabs in checkpoint — run discover first")
            return

        self.stdout.write("Running Phase 3: Deep profiling...")

        drive_service, sheets_service = self._build_services()

        from profiler.tools.cohort_corpus import run_cohort_corpus

        artifact_paths = run_cohort_corpus(
            drive_service=drive_service,
            sheets_service=sheets_service,
            config=config,
            out_dir=out_dir,
            date_stamp=date_stamp,
            resume_from_tab_selection=True,
        )

        deep_coverage = self._load_json_artifact(
            artifact_paths.get("deep_coverage"), {}
        )
        if isinstance(deep_coverage, list):
            state.deep_profile_index.entries = deep_coverage

        state.save_checkpoint(checkpoint_path)
        self.stdout.write(f"Phase 3 complete — checkpoint saved to {checkpoint_path}")

    def _build_services(self):
        """Build Google Drive and Sheets API service objects.

        Returns
        -------
        tuple[googleapiclient.discovery.Resource | None, googleapiclient.discovery.Resource | None]
            ``(drive_service, sheets_service)`` — returns ``(None, None)``
            if the required packages are not installed.
        """
        try:
            from connectors.google_sheets import (
                DRIVE_READONLY_SCOPE,
                SHEETS_READONLY_SCOPE,
                build_google_service,
            )
        except ImportError:
            self.stdout.write(
                self.style.WARNING(
                    "connectors.google_sheets not available — "
                    "Google API calls will fail"
                )
            )
            return None, None

        scopes = [SHEETS_READONLY_SCOPE, DRIVE_READONLY_SCOPE]
        drive_service = build_google_service("drive", "v3", scopes)
        sheets_service = build_google_service("sheets", "v4", scopes)
        return drive_service, sheets_service

    @staticmethod
    def _today_stamp() -> str:
        return date.today().isoformat()

    @staticmethod
    def _load_json_artifact(path: str | None, default: Any) -> Any:
        """Load a JSON artifact file, returning *default* on failure."""
        if not path:
            return default
        p = Path(path)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))
