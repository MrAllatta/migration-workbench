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

from profiler.pipeline.phases._base import _build_google_services
from profiler.tools.pipeline_state import (
    PipelineState,
    _PHASE_ORDER,
    _is_scored_shortlist,
)

PHASES = (
    "discover",
    "score_and_select",
    "deep_profile",
    "derive_contracts",
    "scan_formulas",
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
        parser.add_argument(
            "--signals-output",
            default=None,
            help="Path for profiler-signals YAML artifact "
            "(default: alongside checkpoint as profiler-signals.yaml).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Suppress stale-artifact warning and proceed with profiling.",
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

        # Load domain context from --domain-context or config key
        domain_context = None
        domain_ctx_source = options.get("domain_context")
        if domain_ctx_source is None:
            domain_ctx_source = config.get("domain_context")
        if domain_ctx_source:
            from profiler.tools.domain_context import load_domain_context

            domain_context = load_domain_context(domain_ctx_source)

        state = PipelineState.load_or_create(
            config_path,
            checkpoint_path,
            domain_context=domain_context,
            out_dir=out_dir,
            date_stamp=date_stamp,
            force=options.get("force", False),
        )
        state.configure(
            config=config,
            out_dir=out_dir,
            date_stamp=date_stamp,
            signals_output_path=options.get("signals_output"),
        )

        # --force: remove target phase and all downstream phases from
        # completed_phases before execution.  This allows re-running a
        # specific phase and all phases that depend on its output.
        force = options.get("force", False)
        if force and phase != "all":
            if phase in _PHASE_ORDER:
                phase_index = _PHASE_ORDER.index(phase)
                downstream = set(_PHASE_ORDER[phase_index:])
                original = list(state.completed_phases)
                state.completed_phases = [
                    p for p in state.completed_phases if p not in downstream
                ]
                removed = set(original) - set(state.completed_phases)
                if removed:
                    self.stdout.write(
                        self.style.WARNING(
                            f"--force: removing completed phases "
                            f"{sorted(removed)} to re-run {phase}"
                        )
                    )
        elif force and phase == "all":
            # --force --phase all: clear all completed phases, re-run everything
            original_count = len(state.completed_phases)
            state.completed_phases.clear()
            if original_count:
                self.stdout.write(
                    self.style.WARNING(
                        f"--force: clearing {original_count} completed "
                        f"phases to re-run all"
                    )
                )

        if phase == "all":
            self._run_all(
                state,
                config,
                out_dir,
                date_stamp,
                checkpoint_path,
                stop_before_deep,
            )
        else:
            getattr(self, f"_run_{phase}")(
                state,
                config,
                out_dir,
                date_stamp,
                checkpoint_path,
                stop_before_deep,
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
        # --- discover ---
        # Check completed_phases registry first, fall back to sentinel for
        # backward compat with pre-v0.3.0 checkpoints.
        discover_done = "discover" in state.completed_phases
        if not discover_done:
            # Sentinel fallback: old behavior — source_tree is not None means
            # discover completed (even if source_tree is {} from an empty run).
            if state.discovery.source_tree is not None:
                discover_done = True

        if not discover_done:
            self._run_discover(
                state,
                config,
                out_dir,
                date_stamp,
                checkpoint_path,
                stop_before_deep,
            )
        else:
            self.stdout.write("[skip] discover already complete")

        # --- score_and_select ---
        # Check completed_phases first (authoritative after v0.3.0 migration).
        # Sentinel fallback (backward compat with manually constructed states):
        # only if shortlist entries are in re-scored format (score + scoring_rationale).
        # NOTE: discover() always writes to shortlist, so a plain "shortlist is not None"
        # check would conflate discover with score_and_select — that's the bug this fixes.
        sas_done = "score_and_select" in state.completed_phases
        if not sas_done:
            if state.discovery.shortlist is not None and _is_scored_shortlist(
                state.discovery.shortlist
            ):
                sas_done = True

        if not sas_done:
            self._run_score_and_select(
                state,
                config,
                out_dir,
                date_stamp,
                checkpoint_path,
                stop_before_deep,
            )
        else:
            self.stdout.write("[skip] score_and_select already complete")

        # --- deep_profile ---
        dp_done = "deep_profile" in state.completed_phases
        if not dp_done:
            if state.deep_profile_index.entries:
                dp_done = True

        if not dp_done:
            self._run_deep_profile(
                state,
                config,
                out_dir,
                date_stamp,
                checkpoint_path,
            )
        else:
            self.stdout.write("[skip] deep_profile already complete")

        # --- derive_contracts ---
        dc_done = "derive_contracts" in state.completed_phases
        if not dc_done:
            if state.schema_contract is not None:
                dc_done = True

        if not dc_done:
            self._run_derive_contracts(
                state,
                config,
                out_dir,
                date_stamp,
                checkpoint_path,
            )
        else:
            self.stdout.write("[skip] derive_contracts already complete")

        # --- scan_formulas ---
        sf_done = "scan_formulas" in state.completed_phases
        if not sf_done:
            if state.deep_profile_index.entries:
                self._run_scan_formulas(
                    state,
                    config,
                    out_dir,
                    date_stamp,
                    checkpoint_path,
                )
            else:
                self.stdout.write(
                    "[skip] scan_formulas — no deep profile data available"
                )
        else:
            self.stdout.write("[skip] scan_formulas already complete")

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
        if "discover" in state.completed_phases:
            self.stdout.write(
                "Checkpoint has completed_phases discover — skipping discover phase"
            )
            return
        if state.discovery.source_tree and state.discovery.approved_tabs:
            self.stdout.write("Checkpoint has approved_tabs — skipping discover phase")
            return

        self.stdout.write("Running Phase 0/1: Discovery and tab selection...")
        drive_service, sheets_service = _build_google_services()
        state.discover(drive_service, sheets_service)
        state.save_checkpoint(checkpoint_path)
        self.stdout.write(self.style.SUCCESS(f"discover complete — {checkpoint_path}"))

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
        if "score_and_select" in state.completed_phases:
            self.stdout.write(
                "Checkpoint has completed_phases score_and_select — "
                "skipping score_and_select phase"
            )
            return
        if not state.discovery.broad_inventory:
            self.stdout.write("No broad_inventory in checkpoint — cannot re-score")
            return

        self.stdout.write("Running score_and_select...")
        state.score_and_select()
        state.save_checkpoint(checkpoint_path)
        self.stdout.write(
            self.style.SUCCESS(f"score_and_select complete — {checkpoint_path}")
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
        if "deep_profile" in state.completed_phases:
            self.stdout.write(
                "Checkpoint has completed_phases deep_profile — "
                "skipping deep_profile phase"
            )
            return
        if not state.discovery.approved_tabs:
            self.stdout.write("No approved_tabs in checkpoint — run discover first")
            return

        self.stdout.write("Running deep_profile...")
        _drive, sheets_service = _build_google_services()
        state.deep_profile(sheets_service)
        state.save_checkpoint(checkpoint_path)
        self.stdout.write(
            self.style.SUCCESS(f"deep_profile complete — {checkpoint_path}")
        )

    def _run_derive_contracts(
        self,
        state: PipelineState,
        config: dict[str, Any],
        out_dir: Path,
        date_stamp: str,
        checkpoint_path: Path,
        stop_before_deep: bool = False,
    ) -> None:
        """Phase 4: Derive schema and interaction contracts."""
        if "derive_contracts" in state.completed_phases:
            self.stdout.write(
                "Checkpoint has completed_phases derive_contracts — "
                "skipping derive_contracts phase"
            )
            return
        if not state.deep_profile_index.entries:
            self.stdout.write("No deep profile data — run deep_profile first")
            return

        self.stdout.write("Running derive_contracts...")
        state.derive_contracts()
        state.save_checkpoint(checkpoint_path)
        self.stdout.write(
            self.style.SUCCESS(f"derive_contracts complete — {checkpoint_path}")
        )

    def _run_scan_formulas(
        self,
        state: PipelineState,
        config: dict[str, Any],
        out_dir: Path,
        date_stamp: str,
        checkpoint_path: Path,
        stop_before_deep: bool = False,
    ) -> None:
        """Phase: Scan approved workbooks for formula patterns."""
        if "scan_formulas" in state.completed_phases:
            self.stdout.write(
                "Checkpoint has completed_phases scan_formulas — "
                "skipping scan_formulas phase"
            )
            return
        if not state.deep_profile_index.entries:
            self.stdout.write("No deep profile data — run deep_profile first")
            return

        self.stdout.write("Running scan_formulas...")
        _drive, sheets_service = _build_google_services()
        state.scan_formulas(sheets_service=sheets_service)
        state.save_checkpoint(checkpoint_path)
        self.stdout.write(
            self.style.SUCCESS(f"scan_formulas complete — {checkpoint_path}")
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
