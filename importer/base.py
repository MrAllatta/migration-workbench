import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from importer.chassis import ImporterChassisMixin
from importer.lookups import resolve_fk_by_text
from importer.parsing import parse_iso_date, split_on, to_decimal, to_decimal_or_none, to_int, to_int_or_none
from importer.sample_guard import live12_block_message_for_sample_into_dev_sqlite
from importer.summary import build_escalation_summary, build_failure_signatures, normalized_outcomes, write_summary_json


class BaseImportCommand(ImporterChassisMixin, BaseCommand):
    help = "Base command for tabular import pipelines."

    def add_arguments(self, parser):
        parser.add_argument("data_dir", type=str, help="Directory containing normalized import files")
        parser.add_argument("--dry-run", action="store_true", help="Parse-only checks with no writes")
        parser.add_argument("--validate-only", action="store_true", help="Run full flow in rollback transaction")
        parser.add_argument("--preflight", action="store_true", help="Alias for --validate-only")
        parser.add_argument(
            "--non-atomic-apply",
            action="store_true",
            help="Disable atomic transaction wrapping for apply mode",
        )
        parser.add_argument("--summary-json", type=str, help="Write summary artifact to this path")
        parser.add_argument("--verbose", action="store_true", help="Detailed output")

    def handle(self, *args, **options):
        self.data_dir = options["data_dir"]
        self.validate_only = bool(options["validate_only"] or options["preflight"])
        self.dry_run = bool(options["dry_run"])
        requested_non_atomic_apply = bool(options.get("non_atomic_apply"))
        if self.validate_only and self.dry_run:
            self.dry_run = False
        if self.validate_only:
            self.atomic_apply = True
        elif self.dry_run:
            self.atomic_apply = False
        else:
            self.atomic_apply = not requested_non_atomic_apply
        self.write_disabled = self.dry_run
        self.verbose = options["verbose"]
        self.run_started_at = datetime.now(timezone.utc)
        self.run_id = self.run_started_at.strftime("%Y%m%dT%H%M%S%f")
        requested_summary_path = options.get("summary_json")
        self.summary_json_path = self.resolve_summary_json_path(requested_summary_path)
        self.setup_runtime()

        if not os.path.isdir(self.data_dir):
            raise ValueError(f"Data directory not found: {self.data_dir}")

        try:
            if self.validate_only:
                with transaction.atomic():
                    self._run_import_pipeline()
                    transaction.set_rollback(True)
            elif self.atomic_apply and not self.dry_run:
                with transaction.atomic():
                    self._run_import_pipeline()
            else:
                self._run_import_pipeline()
            self.print_summary()
            write_summary_json(self, status="ok")
        except Exception as exc:
            fatal_error = self.format_fatal_error(exc)
            self.stderr.write(self.style.ERROR(f"\nFATAL ERROR: {fatal_error}"))
            write_summary_json(self, status="failed", fatal_error=fatal_error)
            if self.verbose:
                import traceback

                traceback.print_exc()
            sys.exit(1)

    def _run_import_pipeline(self):
        raise NotImplementedError("Subclasses must implement _run_import_pipeline")

    def resolve_summary_json_path(self, requested_path):
        if requested_path:
            return requested_path
        artifact_dir = Path(self.data_dir) / "_import_artifacts"
        return str(artifact_dir / f"import-summary-{self.run_id}.json")

    def tier(self, title, callback):
        self.stdout.write(self.style.SUCCESS("\n" + "=" * 70))
        self.stdout.write(f"{title}\n")
        self.stdout.write("=" * 70)
        callback()

    def print_summary(self):
        self.stdout.write("\nSUMMARY\n")
        total_created = total_updated = total_skipped = total_error = 0
        for model_name in sorted(self.stats.keys()):
            normalized = normalized_outcomes(
                self.stats[model_name], write_disabled=(self.validate_only or self.dry_run)
            )
            total_created += normalized["created"]
            total_updated += normalized["updated"]
            total_skipped += normalized["skipped"]
            total_error += normalized["error"]
            status = "ok" if normalized["error"] == 0 else "warn"
            self.stdout.write(
                f"  {status} {model_name:25} created={normalized['created']:3} "
                f"updated={normalized['updated']:3} skipped={normalized['skipped']:3} "
                f"error={normalized['error']:3}"
            )
        self.stdout.write(
            f"\n  TOTALS: created={total_created:3} updated={total_updated:3} "
            f"skipped={total_skipped:3} error={total_error:3}\n"
        )
        if total_error > 0:
            signatures = build_failure_signatures(self.row_errors, "ok", None)
            for bucket in build_escalation_summary(signatures):
                self.stdout.write(
                    f"  - {bucket['severity']} | {bucket['owner_team']} | count={bucket['count']}"
                )

    def format_fatal_error(self, exc):
        mode = "validate-only" if self.validate_only else "apply"
        return (
            f"{exc.__class__.__name__}: {exc} "
            f"[mode={mode}, atomic_apply={self.atomic_apply}, dry_run={self.dry_run}]"
        )

    def _resolve_fk_by_text(self, model, field_name, raw_value, label):
        return resolve_fk_by_text(
            model,
            field_name,
            raw_value,
            label,
            self.normalized_lookup_indexes,
            self.stdout,
            self.style,
            write_disabled=self.write_disabled,
        )

    def _int(self, value, default=0):
        return to_int(value, default)

    def _int_or_none(self, value):
        return to_int_or_none(value)

    def _dec(self, value, default="0"):
        return to_decimal(value, default)

    def _dec_or_none(self, value):
        return to_decimal_or_none(value)

    def _parse_date(self, date_str):
        return parse_iso_date(date_str)

    def _split_on(self, value, delimiter="//"):
        return split_on(value, delimiter)
