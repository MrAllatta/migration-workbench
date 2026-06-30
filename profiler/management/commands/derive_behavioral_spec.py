"""Management command: derive the behavioral specification from a PipelineState checkpoint."""

import os

from django.core.management.base import BaseCommand, CommandError

from profiler.tools.pipeline_state import PipelineState


class Command(BaseCommand):
    help = (
        "Derive the behavioral specification from an existing PipelineState checkpoint"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--checkpoint",
            default="build/pipeline-state.yaml",
            help="Path to PipelineState checkpoint YAML",
        )
        parser.add_argument(
            "--out",
            default="build/behavioral-spec.yaml",
            help="Output path for behavioral spec YAML",
        )

    def handle(self, *args, **options):
        checkpoint_path = options["checkpoint"]
        out_path = options["out"]

        base_dir = os.path.dirname(checkpoint_path)

        state = PipelineState.load(checkpoint_path)
        if state.behavioral_spec is not None:
            self.stdout.write(
                self.style.WARNING("Behavioral spec already exists. Overwriting.")
            )

        state.derive_behavioral_spec(base_dir=base_dir)
        if state.behavioral_spec is None:
            raise CommandError("Failed to derive behavioral spec")

        state.behavioral_spec.to_yaml(out_path)
        state.save_checkpoint(checkpoint_path)

        self.stdout.write(self.style.SUCCESS(f"Behavioral spec written to {out_path}"))
