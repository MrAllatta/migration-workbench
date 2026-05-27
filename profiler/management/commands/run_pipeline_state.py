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
    "validate",
)


class Command(BaseCommand):
    """Run profiler pipeline phase(s) using PipelineState checkpoint.

    Each ``_run_*`` method is a thin wrapper: it calls the corresponding
    ``PipelineState`` phase method (which owns all the business logic,
    guard clauses, and decision recording), then saves a checkpoint.
    """

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
        parser.add_argument(
            "--domain-context",
            default=None,
            help="Path to domain_context.yaml for scoring. "
            "If not provided, falls back to the 'domain_context' key "
            "in the config file, then to config/domain_context.yaml.",
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

        # Load domain context from --domain-context, config, or default path
        domain_context = None
        domain_ctx_source = options.get("domain_context")
        if domain_ctx_source is None:
            domain_ctx_source = config.get("domain_context", "config/domain_context.yaml")
        if domain_ctx_source:
            from profiler.tools.domain_context import load_domain_context
            domain_context = load_domain_context(domain_ctx_source)

        state = PipelineState.load_or_create(
            config_path,
            checkpoint_path,
            domain_context=domain_context,
            out_dir=out_dir,
            date_stamp=date_stamp,
        )
        state.configure(config=config, out_dir=out_dir, date_stamp=date_stamp)

        if phase == "all":
            self._run_all(
                state, config, out_dir, date_stamp,
                checkpoint_path, stop_before_deep,
            )
        else:
            getattr(self, f"_run_{phase}")(
                state, config, out_dir, date_stamp,
                checkpoint_path, stop_before_deep,
            )

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

    def _run_discover(
        self,
        state: PipelineState,
        config: dict[str, Any],
        out_dir: Path,
        date_stamp: str,
        checkpoint_path: Path,
        stop_before_deep: bool = False,
    ) -> None:
        """Phase 0/1: Discovery through tab selection."""
        if state.discovery.source_tree and state.discovery.approved_tabs:
            self.stdout.write(
                "Checkpoint has approved_tabs — skipping discover phase"
            )
            return

        self.stdout.write(
            "Running Phase 0/1: Discovery and tab selection..."
        )
        drive_service, sheets_service = self._build_services()
        state.discover(drive_service, sheets_service)
        state.save_checkpoint(checkpoint_path)
        self.stdout.write(
            self.style.SUCCESS(
                f"discover complete — {checkpoint_path}"
            )
        )

    def _run_score_and_select(
        self,
        state: PipelineState,
        config: dict[str, Any],
        out_dir: Path,
        date_stamp: str,
        checkpoint_path: Path,
        stop_before_deep: bool = False,
    ) -> None:
        """Phase 2: Re-score tabs using domain knowledge (no API calls)."""
        if not state.discovery.broad_inventory:
            self.stdout.write(
                "No broad_inventory in checkpoint — cannot re-score"
            )
            return

        self.stdout.write("Running score_and_select...")
        state.score_and_select()
        state.save_checkpoint(checkpoint_path)
        self.stdout.write(
            self.style.SUCCESS(
                f"score_and_select complete — {checkpoint_path}"
            )
        )

    def _run_deep_profile(
        self,
        state: PipelineState,
        config: dict[str, Any],
        out_dir: Path,
        date_stamp: str,
        checkpoint_path: Path,
        stop_before_deep: bool = False,
    ) -> None:
        """Phase 3: Deep profiling of approved tabs."""
        if not state.discovery.approved_tabs:
            self.stdout.write(
                "No approved_tabs in checkpoint — run discover first"
            )
            return

        self.stdout.write("Running deep_profile...")
        _drive, sheets_service = self._build_services()
        state.deep_profile(sheets_service)
        state.save_checkpoint(checkpoint_path)
        self.stdout.write(
            self.style.SUCCESS(
                f"deep_profile complete — {checkpoint_path}"
            )
        )

    def _run_derive_contracts(
        self,
        state: PipelineState,
        checkpoint_path: Path,
    ) -> None:
        """Phase 4: Derive schema and interaction contracts."""
        if not state.deep_profile_index.entries:
            self.stdout.write(
                "No deep profile data — run deep_profile first"
            )
            return

        self.stdout.write("Running derive_contracts...")
        state.derive_contracts()
        state.save_checkpoint(checkpoint_path        )
        self.stdout.write(
            self.style.SUCCESS(
                f"derive_contracts complete — {checkpoint_path}"
            )
        )

    def _run_validate(
        self,
        state: PipelineState,
        config: dict[str, Any],
        out_dir: Path,
        date_stamp: str,
        checkpoint_path: Path,
        stop_before_deep: bool = False,
    ) -> None:
        """Validate checkpoint internal consistency."""
        self.stdout.write("Validating checkpoint...")
        errors = state.validate()
        if not errors:
            summary = self._checkpoint_summary(state)
            self.stdout.write(self.style.SUCCESS(f"Checkpoint valid: {summary}"))
        else:
            for error in errors:
                self.stdout.write(self.style.ERROR(f"  {error}"))
            raise CommandError(f"Checkpoint validation failed: {len(errors)} error(s)")

    def _checkpoint_summary(self, state: PipelineState) -> str:
        """Return a human-readable summary of checkpoint contents."""
        parts = []
        workbook_count = len(state.discovery.workbook_index)
        parts.append(f"{workbook_count} workbooks")

        approved = state.discovery.approved_tabs
        if approved and isinstance(approved, dict):
            tab_count = sum(len(v) for v in approved.values())
            parts.append(f"{tab_count} approved tabs")
        else:
            parts.append("no approved tabs")

        parts.append(f"{len(state.decisions)} decisions")
        return ", ".join(parts)

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
