"""Management command: validate the behavioral specification and compute coverage."""

from django.core.management.base import BaseCommand, CommandError

from profiler.tools.pipeline_state import PipelineState


class Command(BaseCommand):
    help = "Validate the behavioral specification and compute coverage metrics"

    def add_arguments(self, parser):
        parser.add_argument(
            "--checkpoint",
            default="build/pipeline-state.yaml",
            help="Path to PipelineState checkpoint YAML",
        )
        parser.add_argument(
            "--threshold",
            type=float,
            default=0.0,
            help="Coverage threshold (0.0-1.0)",
        )
        parser.add_argument(
            "--draft",
            action="store_true",
            help="Only check auto-derivable dimensions (data, structural, workflow)",
        )

    def handle(self, *args, **options):
        checkpoint_path = options["checkpoint"]
        threshold = options["threshold"]
        draft = options["draft"]

        state = PipelineState.load(checkpoint_path)
        if state.behavioral_spec is None:
            raise CommandError(
                "Behavioral spec not found. Run derive_behavioral_spec first."
            )

        state.validate_behavioral_spec()

        if state.coverage_report is None:
            raise CommandError("Failed to compute coverage report")

        report = state.coverage_report

        if draft:
            # In draft mode, only check auto-derivable dimensions
            auto_dims = report.auto_derivable_dimensions
            auto_values = [getattr(report, dim) for dim in auto_dims]
            self.stdout.write(f"Data coverage: {report.data_coverage:.2f}")
            self.stdout.write(f"Structural coverage: {report.structural_coverage:.2f}")
            self.stdout.write(f"Workflow coverage: {report.workflow_coverage:.2f}")

            if all(value >= threshold for value in auto_values):
                self.stdout.write(
                    self.style.SUCCESS(f"All auto-derivable dimensions >= {threshold}")
                )
                state.save_checkpoint(checkpoint_path)
            else:
                failing = [
                    dim
                    for dim, value in zip(auto_dims, auto_values)
                    if value < threshold
                ]
                self.stdout.write(
                    self.style.ERROR(
                        f"Failing auto-derivable dimensions below {threshold}: {', '.join(failing)}"
                    )
                )
                raise CommandError("Coverage validation failed")
        else:
            # Full validation - check all dimensions
            self.stdout.write(f"Data coverage: {report.data_coverage:.2f}")
            self.stdout.write(f"Formula coverage: {report.formula_coverage:.2f}")
            self.stdout.write(f"Structural coverage: {report.structural_coverage:.2f}")
            self.stdout.write(f"Workflow coverage: {report.workflow_coverage:.2f}")
            self.stdout.write(f"Exception coverage: {report.exception_coverage:.2f}")
            self.stdout.write(f"Report coverage: {report.report_coverage:.2f}")

            if report.is_acceptable(threshold=threshold):
                self.stdout.write(
                    self.style.SUCCESS(f"All coverage dimensions >= {threshold}")
                )
                state.save_checkpoint(checkpoint_path)
            else:
                failing = report.failing_dimensions(threshold=threshold)
                self.stdout.write(
                    self.style.ERROR(
                        f"Failing dimensions below {threshold}: {', '.join(failing)}"
                    )
                )
                raise CommandError("Coverage validation failed")
