#!/usr/bin/env python3
"""Run one or all profiler pipeline phases via PipelineState checkpoint."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from django.core.management.base import BaseCommand, CommandError

if TYPE_CHECKING:
    from profiler.tools.pipeline_state import PipelineState

PHASES = ("discover", "score_and_select", "deep_profile", "derive_contracts")


class Command(BaseCommand):
    help = "Run profiler pipeline phase(s) using PipelineState checkpoint."

    def add_arguments(self, parser):
        parser.add_argument(
            "--config",
            required=True,
            help="Path to cohort_corpus.json config file.",
        )
        parser.add_argument(
            "--phase",
            required=True,
            choices=list(PHASES) + ["all"],
            help="Pipeline phase to execute.",
        )
        parser.add_argument(
            "--checkpoint",
            default="pipeline-state.yaml",
            help="Checkpoint YAML path (default: pipeline-state.yaml).",
        )

    def handle(self, *args, **options):
        # Lazy import so the module is not required for unrelated commands.
        from profiler.tools.pipeline_state import PipelineState

        config_path = Path(options["config"])
        if not config_path.exists():
            raise CommandError(f"Config file not found: {config_path}")

        checkpoint_path = Path(options["checkpoint"])
        phase = options["phase"]

        state = PipelineState.load_or_create(config_path, checkpoint_path)

        if phase == "all":
            self._run_all(state, checkpoint_path)
        else:
            getattr(state, phase)()
            state.save_checkpoint(checkpoint_path)
            self.stdout.write(
                self.style.SUCCESS(f"{phase} → {checkpoint_path}")
            )

    # ------------------------------------------------------------------
    # --phase all  — skip completed phases
    # ------------------------------------------------------------------

    def _run_all(self, state: "PipelineState", checkpoint_path: Path) -> None:
        phases = [
            ("discover", state.discovery.source_tree is not None),
            ("score_and_select", state.discovery.approved_tabs is not None),
            ("deep_profile", bool(state.deep_profile_index.entries)),
            ("derive_contracts", state.schema_contract is not None),
        ]

        for phase_name, already_done in phases:
            if already_done:
                self.stdout.write(f"[skip] {phase_name} already complete")
                continue
            getattr(state, phase_name)()
            # v0.1 stub: deep_profile doesn't populate entries yet.
            # Seed a placeholder so derive_contracts can proceed.
            if phase_name == "deep_profile" and not state.deep_profile_index.entries:
                state.deep_profile_index.entries.append({"_stub": True})
            state.save_checkpoint(checkpoint_path)
            self.stdout.write(
                self.style.SUCCESS(f"{phase_name} → {checkpoint_path}")
            )
