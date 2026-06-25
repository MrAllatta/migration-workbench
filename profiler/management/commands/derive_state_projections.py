"""Management command: derive state projections from the operational model."""

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError

from profiler.tools.pipeline_state import PipelineState


class Command(BaseCommand):
    help = "Derive state projections (schema_contract, test_scaffold, doc_scaffold) from operational model"

    def add_arguments(self, parser):
        parser.add_argument(
            "--checkpoint",
            default="build/pipeline-state.yaml",
            help="Path to PipelineState checkpoint YAML",
        )
        parser.add_argument(
            "--projection",
            default="schema_contract",
            choices=["schema_contract", "test_scaffold", "doc_scaffold"],
            help="Which projection to derive",
        )
        parser.add_argument(
            "--out",
            default="build/schema-contract.yaml",
            help="Output path for projection artifact",
        )

    def handle(self, *args, **options):
        checkpoint_path = options["checkpoint"]
        projection = options["projection"]
        out_path = options["out"]

        state = PipelineState.load(checkpoint_path)
        if state.operational_model is None:
            raise CommandError(
                "Operational model not found. Run derive_operational_model first."
            )

        state.derive_state_projections(projection=projection)

        if projection == "schema_contract":
            if state.schema_contract:
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                Path(out_path).write_text(
                    yaml.safe_dump(
                        state.schema_contract, sort_keys=False, allow_unicode=True
                    ),
                    encoding="utf-8",
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Schema contract written to {out_path}")
                )
            else:
                self.stdout.write(self.style.WARNING("No schema contract generated."))
        elif projection == "test_scaffold":
            if state.test_scaffold:
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                Path(out_path).write_text(
                    state.test_scaffold,
                    encoding="utf-8",
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Test scaffold written to {out_path}")
                )
            else:
                self.stdout.write(self.style.WARNING("No test scaffold generated."))
        elif projection == "doc_scaffold":
            if state.doc_scaffold:
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                Path(out_path).write_text(
                    state.doc_scaffold,
                    encoding="utf-8",
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Doc scaffold written to {out_path}")
                )
            else:
                self.stdout.write(self.style.WARNING("No doc scaffold generated."))

        state.save_checkpoint(checkpoint_path)
