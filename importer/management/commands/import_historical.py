"""Management command for importing historical bundle data.

Iterates year-named subdirectories under a given bundle directory, reads all CSV
files from each year, injects ``source_bundle_year`` into every row, and
delegates per-model import logic to a configurable import strategy.

Also supports bundle directories organised by tab name (rather than by year),
where CSV filenames carry a year suffix::

    data/bundles/
        2020/
            CropPlanner.csv
            FieldLog.csv
        crop_plan/
            crop_plan_2025.csv
            crop_plan_2026.csv
        harvest_log/
            harvest_log_2025.csv

"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from importer.base import BaseImportCommand
from importer.summary import write_summary_json

YEAR_DIR_PATTERN = re.compile(r"^\d{4}(?:_.*)?$")
YEAR_SUFFIX_PATTERN = re.compile(r".*_(\d{4})\.csv$")


class Command(BaseImportCommand):
    """Import historical bundle data from year-based or tab-based directory structure.

    This command wraps the standard import loop with a year-iteration outer
    loop: it discovers year subdirectories within *bundle_dir*, and for each
    year directory it reads all ``*.csv`` files, adds a ``source_bundle_year``
    column to each row, and runs the import tiers defined in
    :meth:`_run_import_pipeline`.

    It also supports tab-named subdirectories (e.g. ``crop_plan/``,
    ``harvest_log/``) where CSV filenames carry a ``_YYYY`` year suffix.
    For these directories, ``source_bundle_year`` is extracted from the
    filename rather than from the directory name.

    Subclasses may override :meth:`_read_csv_rows` to customise row processing
    and :meth:`_run_import_pipeline` to define year-specific import tiers.
    """

    # Instance variables set dynamically in handle().
    bundle_dir: str = ""  # Path to the parent of year subdirectories.
    source_bundle_year: str = ""  # Current year from the year directory name.

    help = "Import historical bundle data from year-based directory structure."

    def add_arguments(self, parser):
        """Register CLI flags for the historical import command.

        Args:
            parser: :class:`argparse.ArgumentParser` provided by Django.
        """
        parser.add_argument(
            "--bundle-dir",
            required=True,
            type=str,
            help="Parent directory containing year subdirectories (e.g. 2020/, 2021/)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse-only checks with no database writes",
        )
        parser.add_argument(
            "--validate-only",
            action="store_true",
            help="Run full flow inside a rollback transaction",
        )
        parser.add_argument(
            "--preflight",
            action="store_true",
            help="Alias for --validate-only",
        )
        parser.add_argument(
            "--summary-json",
            type=str,
            help="Write summary artifact to this path",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Detailed per-year output",
        )

    def handle(self, *args, **options):
        """Entry point — iterates year directories and tab directories.

        Discovers year-named subdirectories (``2020/``, ``2021/``) and
        tab-named subdirectories (``crop_plan/``, ``harvest_log/``) and
        runs the import pipeline for each.

        Args:
            *args: Passed through from ``BaseCommand``.
            **options: Parsed argument dict from :meth:`add_arguments`.
        """
        self.bundle_dir = options["bundle_dir"]
        self.validate_only = bool(
            options.get("validate_only") or options.get("preflight")
        )
        self.dry_run = bool(options.get("dry_run"))
        self.verbose = options.get("verbose", False)

        # Resolve atomic mode — same contract as BaseImportCommand.handle().
        if self.validate_only:
            self.atomic_apply = True
        elif self.dry_run:
            self.atomic_apply = False
        else:
            self.atomic_apply = True  # apply mode wraps in atomic by default

        self.write_disabled = self.dry_run
        self.run_started_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )
        self.run_id = self.run_started_at.strftime("%Y%m%dT%H%M%S%f")
        self.data_dir = self.bundle_dir
        requested_summary_path = options.get("summary_json")
        self.summary_json_path = self.resolve_summary_json_path(requested_summary_path)
        self.setup_runtime()

        if not os.path.isdir(self.bundle_dir):
            from workbench.exceptions import UserFacingError

            raise UserFacingError(
                f"Bundle directory not found: {self.bundle_dir}",
                action="Create the directory or pass a valid --bundle-dir path.",
                check_id="IMPORTER-HISTORICAL-001",
            )

        year_subdirs = self._discover_year_dirs()
        tab_dirs = self._discover_tab_dirs()

        if not year_subdirs and not tab_dirs:
            self.stderr.write(
                f"No year or tab subdirectories found in {self.bundle_dir}\n"
            )
            write_summary_json(self, status="ok")
            return

        for year_dir in year_subdirs:
            self._import_single_year(year_dir)

        for tab_dir in tab_dirs:
            csv_files = self._csv_files_in(str(tab_dir))
            for csv_path in csv_files:
                year = self._extract_year_from_filename(csv_path.name)
                if year is None:
                    continue
                self._import_tab_csv(tab_dir, csv_path, year)

        self.print_summary()
        write_summary_json(self, status="ok")

    # ------------------------------------------------------------------
    # Transaction helper
    # ------------------------------------------------------------------

    def _run_with_transaction(self, callback, year_label=""):
        """Execute *callback* with the configured transaction mode.

        Wraps the callback in an atomic transaction for apply and validate-only
        modes.  Errors are caught and reported without halting further years.

        Args:
            callback: Zero-argument callable performing the import work.
            year_label: Optional label for error reporting (e.g. ``"2022"``).
        """
        try:
            if self.validate_only:
                from django.db import transaction

                with transaction.atomic():
                    callback()
                    transaction.set_rollback(True)
            elif not self.dry_run:
                from django.db import transaction

                with transaction.atomic():
                    callback()
            else:
                callback()
        except Exception as exc:
            fatal_error = self.format_fatal_error(exc)
            label_str = f" [{year_label}]" if year_label else ""
            self.stderr.write(
                self.style.ERROR(f"\nFATAL ERROR{label_str}: {fatal_error}")
            )
            if self.verbose:
                import traceback

                traceback.print_exc()

    def _print_year_header(self, year_label: str) -> None:
        """Print a banner separator for a year import section.

        Args:
            year_label: Label to display in the banner (e.g. ``"2022"``).
        """
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'=' * 70}\nImporting year: {year_label}\n{'=' * 70}"
            )
        )

    def _import_single_year(self, year_dir: Path) -> None:
        """Run the import pipeline for a single year directory.

        Sets :attr:`data_dir` and :attr:`source_bundle_year` before delegating
        to :meth:`_run_import_pipeline`.

        Args:
            year_dir: Path to the year subdirectory.
        """
        year_str = year_dir.name
        self.data_dir = str(year_dir)
        self.source_bundle_year = year_str
        self._print_year_header(year_str)
        self._run_with_transaction(self._run_import_pipeline, year_str)

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------

    def _discover_year_dirs(self) -> list[Path]:
        """Find and return year subdirectories sorted in ascending order.

        Matches directory names that are either exactly four digits (``2020``)
        or four digits followed by an underscore and a suffix (``2020_phase2``).

        Returns:
            list[Path]: Year directory paths sorted by name ascending.
        """
        subdirs: list[Path] = []
        for entry in os.scandir(self.bundle_dir):
            if entry.is_dir() and YEAR_DIR_PATTERN.match(entry.name):
                subdirs.append(Path(entry.path))
        return sorted(subdirs, key=lambda d: d.name)

    def _discover_tab_dirs(self) -> list[Path]:
        """Find and return tab-named subdirectories sorted in ascending order.

        Matches directory names that are NOT year-pattern directories
        (e.g. ``crop_plan/``, ``harvest_log/``, ``field_block/``).

        Returns:
            list[Path]: Tab directory paths sorted by name ascending.
        """
        subdirs: list[Path] = []
        for entry in os.scandir(self.bundle_dir):
            if entry.is_dir() and not YEAR_DIR_PATTERN.match(entry.name):
                subdirs.append(Path(entry.path))
        return sorted(subdirs, key=lambda d: d.name)

    def _parse_year_from_dir(self, year_dir: Path) -> str:
        """Extract the year portion from a directory name.

        For names like ``2020`` or ``2020_phase2``, returns the four-digit year
        string (e.g. ``"2020"``).

        Args:
            year_dir: Path to the year subdirectory.

        Returns:
            str: The four-digit year string.
        """
        return year_dir.name[:4]

    def _extract_year_from_filename(self, filename: str) -> str | None:
        """Extract a four-digit year suffix from a CSV filename.

        Matches filenames ending with ``_YYYY.csv`` like
        ``harvest_forecast_2025.csv`` and returns the year string.

        Args:
            filename: The CSV filename to inspect.

        Returns:
            str | None: The four-digit year string, or ``None`` if no
            year suffix is found.
        """
        match = YEAR_SUFFIX_PATTERN.match(filename)
        if match:
            return match.group(1)
        return None

    def _import_tab_csv(self, tab_dir: Path, csv_path: Path, year: str) -> None:
        """Import a single year-suffixed CSV from a tab-named directory.

        Sets :attr:`data_dir` to the tab directory and
        :attr:`source_bundle_year` to the extracted year from the filename.
        Only the specified CSV is imported (not all CSVs in the directory).

        Args:
            tab_dir: Path to the tab-named subdirectory.
            csv_path: Path to the CSV file to import.
            year: Four-digit year string extracted from the filename.
        """
        self.data_dir = str(self.bundle_dir)
        self.source_bundle_year = year
        year_label = f"{tab_dir.name}/{csv_path.name}"
        self._print_year_header(year_label)
        self._run_with_transaction(lambda: self._import_csv_file(csv_path), year_label)

    # ------------------------------------------------------------------
    # CSV reading helpers
    # ------------------------------------------------------------------

    def _csv_files_in(self, directory: str) -> list[Path]:
        """Return sorted list of CSV file paths in *directory*.

        Args:
            directory: Path string to scan for CSV files.

        Returns:
            list[Path]: Sorted CSV file paths.
        """
        return sorted(Path(directory).glob("*.csv"))

    def _read_csv_rows(self, csv_path: str) -> list[tuple[int, dict[str, str]]]:
        """Read rows from a CSV file and inject ``source_bundle_year``.

        Each returned row dict gains a ``source_bundle_year`` key set to the
        current year string from :attr:`source_bundle_year`.

        Args:
            csv_path: Path to the CSV file to read.

        Returns:
            list[tuple[int, dict[str, str]]]: ``(row_number, row_dict)`` pairs
            where *row_number* is 1-based.
        """
        rows: list[tuple[int, dict[str, str]]] = []
        with open(csv_path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row_index, row in enumerate(reader, start=1):
                row["source_bundle_year"] = self.source_bundle_year
                rows.append((row_index, row))
        return rows

    def _run_import_pipeline(self):
        """Import all CSV files in the current year directory.

        Subclasses override this to provide year-specific import tiers.
        Default implementation iterates CSV files in the year directory and
        calls :meth:`_import_csv_file` for each one.

        When called, :attr:`self.data_dir` points to the current year directory
        and :attr:`self.source_bundle_year` holds the four-digit year string.
        """
        csv_files = self._csv_files_in(self.data_dir)
        for csv_path in csv_files:
            self._import_csv_file(csv_path)

    def _import_csv_file(self, csv_path: Path) -> None:
        """Read a CSV, inject ``source_bundle_year``, and process each row.

        Subclasses override :meth:`_process_row` to define how each row maps
        to database models.  The default implementation tracks counts only.

        Args:
            csv_path: Path to the CSV file to import.
        """
        csv_name = csv_path.stem
        rows = self._read_csv_rows(str(csv_path))
        for row_index, row in rows:
            self._process_row(csv_name, row_index, row)

    def _process_row(self, csv_name: str, row_index: int, row: dict[str, str]) -> None:
        """Process a single row from a CSV file.

        Subclasses override this for model-specific creation logic.  The
        default implementation counts the row as processed (skipped in
        dry-run mode).

        Args:
            csv_name: Stem of the CSV file (e.g. ``"CropPlanner"``).
            row_index: 1-based row number from the CSV.
            row: Dict of column values.  Always contains a
                ``"source_bundle_year"`` key set to the current year.
        """
        if self.write_disabled:
            self.stats[csv_name]["processed"] += 1
            return
        self.stats[csv_name]["processed"] += 1
