"""Management command: validate the operational model and compute coverage."""

from django.core.management.base import BaseCommand, CommandError

from profiler.tools.pipeline_state import PipelineState


class Command(BaseCommand):
    help = "Validate the operational model and compute coverage metrics"

    def add_arguments(self, parser):
        parser.add_argument(
            "--checkpoint",
            default="build/pipeline-state.yaml",
            help="Path to PipelineState checkpoint YAML",
        )
        parser.add_argument(
            "--threshold",
            type=float,
            default=0.80,
            help="Coverage threshold (0.0-1.0)",
        )

    def handle(self, *args, **options):
        checkpoint_path = options["checkpoint"]
        threshold = options["threshold"]

        state = PipelineState.load(checkpoint_path)
        if state.operational_model is None:
            raise CommandError(
                "Operational model not found. Run derive_operational_model first."
            )

        state.validate_operational_model()

        if state.coverage_report is None:
            raise CommandError("Failed to compute coverage report")

        report = state.coverage_report
        self.stdout.write(f"Data coverage: {report.data_coverage:.2f}")
        self.stdout.write(f"Workflow coverage: {report.workflow_coverage:.2f}")
        self.stdout.write(f"Event coverage: {report.event_coverage:.2f}")
        self.stdout.write(f"Invariant coverage: {report.invariant_coverage:.2f}")

        if report.is_acceptable(threshold=threshold):
            self.stdout.write(
                self.style.SUCCESS(f"All coverage dimensions >= {threshold}")
            )
        else:
            failing = report.failing_dimensions(threshold=threshold)
            self.stdout.write(
                self.style.ERROR(
                    f"Failing dimensions below {threshold}: {', '.join(failing)}"
                )
            )
            raise CommandError("Coverage validation failed")

        state.save_checkpoint(checkpoint_path)
