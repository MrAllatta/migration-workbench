"""Base management command for tabular import pipelines.

:class:`BaseImportCommand` wires together :class:`~importer.chassis.ImporterChassisMixin`
and Django's ``BaseCommand`` to provide a single entry-point for all import
runs.  Concrete subclasses only need to implement
:meth:`~BaseImportCommand._run_import_pipeline`; everything else (argument
parsing, transaction management, summary writing, error reporting) is handled
here.

**Run modes**

``apply`` (default)
    Writes to the database inside a single ``SAVEPOINT`` (atomic by default).
    Pass ``--non-atomic-apply`` to disable the wrapping transaction.

``--validate-only`` / ``--preflight``
    Runs the full pipeline in a transaction that is always rolled back.
    Useful for CI smoke checks.  Implies ``atomic_apply=True``.

``--dry-run``
    Skips all database writes entirely (parse-only).  Mutually exclusive with
    ``--validate-only``; if both are supplied, ``--dry-run`` is silently
    dropped in favour of validate-only semantics.
"""

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
    """Foundation for tabular CSV import management commands.

    Subclasses must implement :meth:`_run_import_pipeline`.  All other
    lifecycle concerns (argument parsing, transaction wrapping, summary JSON
    emission, fatal error formatting) are handled by this class.

    Typical subclass pattern::

        class Command(BaseImportCommand):
            help = "Import crops from normalized CSVs."

            def _run_import_pipeline(self):
                self.tier("Crops", self._import_crops)

            def _import_crops(self):
                ...
    """

    help = "Base command for tabular import pipelines."

    def add_arguments(self, parser):
        """Register standard import CLI flags.

        Args:
            parser: :class:`argparse.ArgumentParser` provided by Django.
        """
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
        """Entry point called by Django's management command runner.

        Resolves run-mode flags, initialises chassis state, dispatches to
        :meth:`_run_import_pipeline`, and writes the summary artifact.  Exits
        with code ``1`` on any unhandled exception so CI pipelines fail loudly.

        Args:
            *args: Passed through from ``BaseCommand``.
            **options: Parsed argument dict from :meth:`add_arguments`.
        """
        self.data_dir = options["data_dir"]
        self.validate_only = bool(options["validate_only"] or options["preflight"])
        self.dry_run = bool(options["dry_run"])
        requested_non_atomic_apply = bool(options.get("non_atomic_apply"))

        # validate-only supersedes dry-run; the pipeline still runs but the
        # transaction is always rolled back, so "dry_run" would be redundant.
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
        """Execute all import tiers in order.

        Raises:
            NotImplementedError: Always; subclasses must override this method.
        """
        raise NotImplementedError("Subclasses must implement _run_import_pipeline")

    def resolve_summary_json_path(self, requested_path):
        """Return the summary JSON output path, defaulting to the artifact directory.

        Args:
            requested_path: Caller-supplied path string, or ``None``.

        Returns:
            str: Absolute-or-relative path where the summary JSON will be written.
        """
        if requested_path:
            return requested_path
        artifact_dir = Path(self.data_dir) / "_import_artifacts"
        return str(artifact_dir / f"import-summary-{self.run_id}.json")

    def tier(self, title, callback):
        """Print a titled section separator then invoke *callback*.

        Use this to visually group related import steps in the command output::

            self.tier("Crops", self._import_crops)

        Args:
            title: Section heading printed between separator lines.
            callback: Zero-argument callable that performs the import work.
        """
        self.stdout.write(self.style.SUCCESS("\n" + "=" * 70))
        self.stdout.write(f"{title}\n")
        self.stdout.write("=" * 70)
        callback()

    def print_summary(self):
        """Print per-model outcome counts and escalation buckets to stdout.

        Reads from :attr:`~importer.chassis.ImporterChassisMixin.stats` and
        :attr:`~importer.chassis.ImporterChassisMixin.row_errors` accumulated
        during :meth:`_run_import_pipeline`.
        """
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
        """Format a caught exception into a single-line string with run-mode context.

        Args:
            exc: The exception that caused the import run to abort.

        Returns:
            str: Message string of the form
            ``"ExcType: message [mode=..., atomic_apply=..., dry_run=...]"``.
        """
        mode = "validate-only" if self.validate_only else "apply"
        return (
            f"{exc.__class__.__name__}: {exc} "
            f"[mode={mode}, atomic_apply={self.atomic_apply}, dry_run={self.dry_run}]"
        )

    # ------------------------------------------------------------------
    # Convenience wrappers — delegate to module-level helpers so subclasses
    # can call self._int(...) rather than importing parsing directly.
    # ------------------------------------------------------------------

    def _resolve_fk_by_text(self, model, field_name, raw_value, label):
        """Resolve a FK reference using the shared chassis lookup cache.

        Args:
            model: Target Django model class.
            field_name: Field on *model* to match against.
            raw_value: Raw text from the source row.
            label: Human-readable model label for warning messages.

        Returns:
            Model instance or None.
        """
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
        """Coerce *value* to int.  See :func:`~importer.parsing.to_int`."""
        return to_int(value, default)

    def _int_or_none(self, value):
        """Coerce *value* to a positive int or ``None``.  See :func:`~importer.parsing.to_int_or_none`."""
        return to_int_or_none(value)

    def _dec(self, value, default="0"):
        """Coerce *value* to ``Decimal``.  See :func:`~importer.parsing.to_decimal`."""
        return to_decimal(value, default)

    def _dec_or_none(self, value):
        """Coerce *value* to a positive ``Decimal`` or ``None``.  See :func:`~importer.parsing.to_decimal_or_none`."""
        return to_decimal_or_none(value)

    def _parse_date(self, date_str):
        """Parse an ISO 8601 date string.  See :func:`~importer.parsing.parse_iso_date`."""
        return parse_iso_date(date_str)

    def _split_on(self, value, delimiter="//"):
        """Split *value* on *delimiter*.  See :func:`~importer.parsing.split_on`."""
        return split_on(value, delimiter)
