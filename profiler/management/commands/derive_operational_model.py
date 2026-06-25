"""Management command: derive the operational model from a PipelineState checkpoint."""

import os

from django.core.management.base import BaseCommand, CommandError

from profiler.tools.pipeline_state import PipelineState


class Command(BaseCommand):
    help = "Derive the operational model from an existing PipelineState checkpoint"

    def add_arguments(self, parser):
        parser.add_argument(
            "--checkpoint",
            default="build/pipeline-state.yaml",
            help="Path to PipelineState checkpoint YAML",
        )
        parser.add_argument(
            "--out",
            default="build/operational-model.yaml",
            help="Output path for operational model YAML",
        )

    def handle(self, *args, **options):
        checkpoint_path = options["checkpoint"]
        out_path = options["out"]

        base_dir = os.path.dirname(checkpoint_path)

        state = PipelineState.load(checkpoint_path)
        if state.operational_model is not None:
            self.stdout.write(
                self.style.WARNING("Operational model already exists. Overwriting.")
            )

        state.derive_operational_model(base_dir=base_dir)
        if state.operational_model is None:
            raise CommandError("Failed to derive operational model")

        state.operational_model.to_yaml(out_path)
        state.save_checkpoint(checkpoint_path)

        self.stdout.write(
            self.style.SUCCESS(f"Operational model written to {out_path}")
        )
