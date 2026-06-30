"""Management command to import an edited behavioral-spec YAML into a PipelineState checkpoint."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from profiler.tools.behavioral_spec import BehavioralSpec
from profiler.tools.pipeline_state import PipelineState


class Command(BaseCommand):
    """Import an edited behavioral-spec YAML into a PipelineState checkpoint.

    Usage::

        python manage.py import_behavioral_spec \\\
            --checkpoint build/pipeline-state.yaml \\\
            --spec build/behavioral-spec.yaml

    This command loads an edited behavioral-spec YAML, validates it by
    parsing through ``BehavioralSpec.from_yaml()``, and injects the result
    into an existing PipelineState checkpoint.
    """

    help = "Import an edited behavioral-spec YAML into a PipelineState checkpoint"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--checkpoint",
            required=True,
            help="Path to the PipelineState checkpoint YAML file",
        )
        parser.add_argument(
            "--spec",
            required=True,
            help="Path to the edited behavioral-spec YAML file",
        )
        parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help="Skip confirmation prompt",
        )

    def handle(self, *args: str, **options: str) -> str | None:
        checkpoint_path = Path(options["checkpoint"])
        spec_path = Path(options["spec"])
        skip_confirm = options.get("yes", False)

        # Validate paths exist
        if not spec_path.exists():
            raise CommandError(f"Spec file not found: {spec_path}")
        if not checkpoint_path.exists():
            raise CommandError(f"Checkpoint file not found: {checkpoint_path}")

        # Load and parse the edited spec
        self.stdout.write(f"Loading behavioral spec from {spec_path}...")
        try:
            spec = BehavioralSpec.from_yaml(str(spec_path))
        except Exception as exc:
            raise CommandError(f"Failed to parse behavioral spec: {exc}") from exc

        placeholders = spec.placeholders()
        if placeholders:
            self.stdout.write(
                self.style.WARNING(
                    f"Spec contains {len(placeholders)} unresolved "
                    f"elicitation placeholder(s). Consider running "
                    f"`derive_behavioral_spec --checkpoint` to fill them."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("No unresolved placeholders detected.")
            )

        # Report what's in the spec
        self.stdout.write(
            f"  Actors: {len(spec.actors)}, "
            f"Events: {len(spec.events)}, "
            f"Workflows: {len(spec.workflows)}, "
            f"Decisions: {len(spec.decisions)}, "
            f"Exceptions: {len(spec.exceptions)}, "
            f"Reports: {len(spec.reports)}"
        )

        # Confirm
        if not skip_confirm:
            self.stdout.write(f"This will inject the spec into {checkpoint_path}.")
            answer = input("Continue? [y/N] ")
            if answer.lower() not in ("y", "yes"):
                self.stdout.write(self.style.WARNING("Aborted."))
                return None

        # Load checkpoint and inject spec
        self.stdout.write(f"Loading checkpoint from {checkpoint_path}...")
        try:
            state = PipelineState.load(str(checkpoint_path))
        except Exception as exc:
            raise CommandError(
                f"Failed to load PipelineState checkpoint: {exc}"
            ) from exc

        state.behavioral_spec = spec

        # Write updated checkpoint
        self.stdout.write("Writing updated checkpoint...")
        try:
            state.save_checkpoint(str(checkpoint_path))
        except Exception as exc:
            raise CommandError(f"Failed to write checkpoint: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(f"Behavioral spec injected into {checkpoint_path}")
        )
        return None
