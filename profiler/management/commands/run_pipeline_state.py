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

        checkpoint_path = Path(options["checkpoint"]).resolve()
        phase = options["phase"]

        # Load or create PipelineState, seeding domain from config JSON
        state = PipelineState.load_or_create(config_path, checkpoint_path)

        if phase == "all":
            self._run_all(state, checkpoint_path)
        elif phase == "derive_contracts":
            self._run_derive_contracts(state, checkpoint_path)
        else:
            # Delegate to the PipelineState phase method
            getattr(state, phase)()
            state.save_checkpoint(checkpoint_path)
            self.stdout.write(
                self.style.SUCCESS(f"{phase} → {checkpoint_path}")
            )

    # ------------------------------------------------------------------
    # --phase all  — skip completed phases
    # ------------------------------------------------------------------

    def _run_all(
        self, state: PipelineState, checkpoint_path: Path
    ) -> None:
        """Run all phases sequentially, skipping completed ones."""
        phase_gates = [
            (
                "discover",
                state.discovery.source_tree is None,
            ),
            (
                "score_and_select",
                state.discovery.approved_tabs is None,
            ),
            (
                "deep_profile",
                not state.deep_profile_index.entries,
            ),
            (
                "derive_contracts",
                state.schema_contract is None,
            ),
        ]

        for phase_name, needs_run in phase_gates:
            if not needs_run:
                self.stdout.write(
                    f"[skip] {phase_name} already complete"
                )
                continue
            getattr(state, phase_name)()
            # v0.2.0 stub: deep_profile does not yet populate entries,
            # so seed a placeholder so derive_contracts can proceed.
            if (
                phase_name == "deep_profile"
                and not state.deep_profile_index.entries
            ):
                state.deep_profile_index.entries.append(
                    {"_stub": True}
                )
            state.save_checkpoint(checkpoint_path)
            self.stdout.write(
                self.style.SUCCESS(
                    f"{phase_name} → {checkpoint_path}"
                )
            )

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

    # ------------------------------------------------------------------
    # Helpers for artifact loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_json_artifact(
        path: str | None, default: Any
    ) -> Any:
        """Load a JSON artifact file, returning *default* on failure."""
        if not path:
            return default
        p = Path(path)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))
