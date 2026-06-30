"""
Base management command and helpers for auditing CSV import completeness and accuracy.

Provides the :class:`BaseAuditCommand` chassis, the :class:`CsvMapping`
dataclass, and standalone utility functions for comparing CSV source data
against Django model records.  Product repos subclass the command and
supply their own CSV mapping definitions and record-resolution logic.

Usage pattern in a product repo::

    from importer.base_audit import BaseAuditCommand, CsvMapping

    CSV_MAPPINGS: list[CsvMapping] = [
        CsvMapping(csv_pattern="reference/crop_info.csv", model=Crop, natural_key=["name"]),
    ]

    class Command(BaseAuditCommand):
        def _resolve_mappings(self) -> list[CsvMapping]:
            return CSV_MAPPINGS

        def _resolve_record(self, mapping: CsvMapping, row: dict):
            # Farm-specific FK lookups
            ...

        def _run_custom_phases(self, mappings, bundle_dir, verbose) -> dict:
            return self._phase_routing(mappings, bundle_dir, verbose)
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Model
from django.utils.dateparse import parse_date
from django.utils.timezone import now as tz_now

# ── CSV cell helpers ──────────────────────────────────────────────────────────────


def clean(val: object) -> str:
    """Strip whitespace from a CSV cell value."""
    if val is None:
        return ""
    return str(val).strip()


def boolish(val: object) -> bool | None:
    """Convert a CSV cell value to boolean / ``None``.

    Truthy values: ``yes``, ``true``, ``1``, ``y``, ``x`` (case-insensitive).
    Falsy values: ``no``, ``false``, ``0``, ``n``, ``""``.
    Anything else returns ``None``.
    """
    v = clean(val).lower()
    if v in ("yes", "true", "1", "y", "x"):
        return True
    if v in ("no", "false", "0", "n", ""):
        return False
    return None


def intish(val: object, default: int | None = None) -> int | None:
    """Convert a CSV cell value to ``int`` or return *default*."""
    v = clean(val)
    if not v:
        return default
    try:
        return int(v.replace(",", ""))
    except (ValueError, TypeError):
        return default


def decish(val: object, default: Decimal | None = None) -> Decimal | None:
    """Convert a CSV cell value to ``Decimal`` or return *default*.

    Strips currency symbols (``$``), commas, percent signs, and whitespace
    before parsing.
    """
    v = clean(val)
    if not v:
        return default
    cleaned = re.sub(r"[$,%\s]", "", v)
    if not cleaned:
        return default
    try:
        return Decimal(cleaned)
    except (ValueError, TypeError, InvalidOperation):
        return default


def parse_date_cell(val: object) -> date | None:
    """Try to parse a date string from a CSV cell.

    Attempts ISO 8601 first (via Django's ``parse_date``), then falls back to
    ``%Y-%m-%d``, ``%m/%d/%Y``, ``%m/%d/%y``, ``%d/%m/%Y``.
    """
    v = clean(val)
    if not v:
        return None
    parsed = parse_date(v)
    if parsed:
        return parsed
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def normalize_header(header: str) -> str:
    """Normalise a CSV header to a snake_case model field name.

    Steps: lowercase, replace spaces with underscores,
    strip non-alphanumeric characters (keeping underscores),
    collapse repeated underscores.
    """
    s = header.lower()
    s = s.replace(" ", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def csv_row_count(csv_path: str) -> int:
    """Return the number of data rows in a CSV file (excluding header).

    Returns 0 (with a warning) if the file cannot be read.
    """
    try:
        count = 0
        with open(csv_path, "r", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for _ in reader:
                count += 1
        return count
    except (FileNotFoundError, UnicodeDecodeError, csv.Error) as exc:
        import warnings

        warnings.warn(f"Cannot read {csv_path}: {exc}")
        return 0


def get_model_fields(model: type[Model]) -> set[str]:
    """Return editable field names for *model*, excluding relation types and auto fields.

    Keeps forward FK fields (``many_to_one``).  Skips O2O, M2M, reverse
    relations, auto-created fields, PK-only fields, and non-editable fields.
    """
    fields: set[str] = set()
    for f in model._meta.get_fields():
        if f.is_relation:
            if not f.many_to_one:
                continue
            if f.one_to_many:
                continue
        if getattr(f, "auto_created", False):
            continue
        if getattr(f, "primary_key", False):
            continue
        if not getattr(f, "editable", True):
            continue
        fields.add(f.name)
    return fields


def compare_field_value(csv_value: str, db_value: Any, field_type_name: str) -> bool:
    """Compare a CSV cell value to a Django model field value with type-appropriate tolerance.

    Handles Boolean, Decimal/Float, and DateField comparisons with
    appropriate type coercion.  Defaults to case-insensitive string comparison
    for other field types.

    Args:
        csv_value: Raw string from the CSV cell.
        db_value: Value from the Django model instance field.
        field_type_name: Django field class name (e.g. ``"BooleanField"``).

    Returns:
        ``True`` when the values match within tolerance.
    """
    csv_str = clean(csv_value)
    db_str = clean(str(db_value) if db_value is not None else "")

    # Both empty/null — match
    if not csv_str and db_value in (None, "", 0, Decimal("0"), False):
        return True

    if "Boolean" in field_type_name or field_type_name == "NullBooleanField":
        csv_bool = boolish(csv_str)
        db_bool = bool(db_value) if db_value is not None else None
        return csv_bool == db_bool

    if "Decimal" in field_type_name or "Float" in field_type_name:
        csv_dec = decish(csv_str)
        if csv_dec is None and db_value is None:
            return True
        if csv_dec is not None and db_value is not None:
            return abs(csv_dec - Decimal(str(db_value))) <= Decimal("0.01")
        return False

    if field_type_name == "DateField":
        csv_date = parse_date_cell(csv_str)
        db_date = db_value
        return csv_date == db_date

    # Default: case-insensitive string comparison, trimmed
    return csv_str.lower() == db_str.lower()


# ── CsvMapping dataclass ────────────────────────────────────────────────────────


@dataclass
class CsvMapping:
    """Describes how a CSV file pattern maps to a Django model.

    Attributes:
        csv_pattern: Glob pattern relative to the bundle directory.
        model: Target Django model class.
        natural_key: List of field names that form a unique natural
            key for ``update_or_create`` lookups.
        source_tab: Optional source-tab label (for display / docs).
        field_overrides: Optional dict mapping CSV column headers
            (as they appear in the file) to model field names when
            the default ``normalize_header`` heuristic is wrong.
        expected_gap_reason: Optional explanation when the expected
            row count is known to differ from the DB row count.
    """

    csv_pattern: str
    model: type[Model]
    natural_key: list[str]
    source_tab: str | None = None
    field_overrides: dict | None = None
    expected_gap_reason: str | None = None

    def match_csv_files(self, bundle_dir: str) -> list[str]:
        """Return all CSV file paths under *bundle_dir* matching *csv_pattern*."""
        search_path = os.path.join(bundle_dir, self.csv_pattern)
        return sorted(glob.glob(search_path))

    def resolve_field_map(self, csv_headers: list[str]) -> dict[str, str]:
        """Build a dict mapping each CSV header to a model field name.

        Uses *field_overrides* when available; otherwise falls back
        to ``normalize_header``.
        """
        overrides = self.field_overrides or {}
        mapping: dict[str, str] = {}
        for header in csv_headers:
            if header in overrides:
                mapping[header] = overrides[header]
            else:
                mapping[header] = normalize_header(header)
        return mapping


# ── Base audit command ─────────────────────────────────────────────────────────


class BaseAuditCommand(BaseCommand):
    """Chassis for auditing import completeness, accuracy, and routing.

    Subclasses must implement:

    * :meth:`_resolve_mappings` — return the list of :class:`CsvMapping` to audit.
    * :meth:`_resolve_record` — look up a DB record by natural key from parsed CSV row data.

    Optionally override :meth:`_run_custom_phases` to add farm-specific
    routing or schema-evolution checks beyond the built-in phases.
    """

    help = "Audit import completeness, accuracy, and routing for bundle CSVs."

    def add_arguments(self, parser):
        """Register standard audit CLI flags."""
        parser.add_argument(
            "--bundle",
            default="build/bundle",
            help="Path to the bundle directory (default: build/bundle)",
        )
        parser.add_argument(
            "--model",
            default=None,
            help="Only audit mappings for this model name (case-insensitive)",
        )
        parser.add_argument(
            "--output",
            default="build/audit",
            help="Directory for audit report output (default: build/audit)",
        )
        parser.add_argument(
            "--phase",
            default=None,
            choices=["completeness", "accuracy", "routing"],
            help="Run a single phase only (default: all)",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            default=False,
            help="Print status for every mapping as it is processed",
        )
        parser.add_argument(
            "--fatal",
            action="store_true",
            default=False,
            help="Raise CommandError if any mapping has warn/fail status",
        )

    def handle(self, *args, **options):
        """Entry point called by Django's management command runner."""
        self.bundle_dir = options["bundle"]
        self.output_dir = options["output"]
        self.model_filter = options["model"]
        self.phase_filter = options["phase"]
        self.verbose = options["verbose"]
        self.fatal = options["fatal"]

        os.makedirs(self.output_dir, exist_ok=True)
        if not os.path.isdir(self.bundle_dir):
            raise CommandError(f"Bundle directory not found: {self.bundle_dir}")

        audit_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        report: dict = {
            "audit_id": audit_id,
            "bundle_dir": os.path.abspath(self.bundle_dir),
            "started_at": tz_now().isoformat(),
            "phases": {},
            "summary": {
                "pass": 0,
                "warn": 0,
                "fail": 0,
                "info": 0,
            },
        }

        mappings = self._resolve_mappings()

        if not self.phase_filter or self.phase_filter == "completeness":
            report["phases"]["completeness"] = self._phase_completeness(
                mappings, self.bundle_dir, self.verbose
            )

        if not self.phase_filter or self.phase_filter == "accuracy":
            report["phases"]["accuracy"] = self._phase_accuracy(
                mappings, self.bundle_dir, self.verbose
            )

        if not self.phase_filter or self.phase_filter == "routing":
            custom = self._run_custom_phases(mappings, self.bundle_dir, self.verbose)
            if custom:
                report["phases"].update(custom)

        report["finished_at"] = tz_now().isoformat()

        self._update_summary(report)
        self._write_report(report, self.output_dir)

        # Surface the overall status
        summary = report["summary"]
        overall_status = "pass"
        if summary.get("fail", 0) > 0:
            overall_status = "fail"
        elif summary.get("warn", 0) > 0:
            overall_status = "warn"

        if self.fatal and overall_status in ("warn", "fail"):
            raise CommandError(f"Audit {overall_status}. See report.")

    # ── Abstract methods ────────────────────────────────────────────────────────

    def _resolve_mappings(self) -> list[CsvMapping]:
        """Return the list of :class:`CsvMapping` instances to audit.

        Subclasses must implement this.  When ``--model`` is passed, the
        implementation should filter to only mappings whose model name matches.

        Raises:
            NotImplementedError: If not overridden.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _resolve_mappings()"
        )

    def _resolve_record(self, mapping: CsvMapping, row: dict):
        """Look up a DB record by natural key from parsed CSV row data.

        Subclasses must implement this.  The implementation should inspect
        ``mapping.natural_key``, extract values from *row* using the same
        CSV header→field conventions the import command uses, and return the
        matching model instance (or ``None`` if not found).

        Args:
            mapping: The :class:`CsvMapping` that matched this CSV file.
            row: A single CSV data row as a ``dict`` of ``{header: value}``.

        Returns:
            A model instance or ``None`` when the record cannot be resolved.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _resolve_record()"
        )

    # ── Optional hooks ─────────────────────────────────────────────────────────

    def _run_custom_phases(
        self, mappings: list[CsvMapping], bundle_dir: str, verbose: bool
    ) -> dict:
        """Hook for farm-specific phase implementations.

        Subclasses can override this to add phases beyond the built-in
        ``completeness`` and ``accuracy`` checks (e.g. routing rules,
        schema-evolution checks).  Return a dict keyed by phase name
        (e.g. ``{"routing": {...}}``) or an empty dict when no custom
        phases are defined.

        The default implementation returns an empty dict.
        """
        return {}

    # ── Report helpers ──────────────────────────────────────────────────────────

    def _update_summary(self, report: dict) -> None:
        """Tally phase check statuses into the report summary."""
        summary = report.get("summary", {"pass": 0, "warn": 0, "fail": 0, "info": 0})
        for phase_name, phase in report.get("phases", {}).items():
            for check in phase.get("checks", []):
                status = check.get("status", "info")
                if status in summary:
                    summary[status] += 1

    def _write_report(self, report: dict, output_dir: str) -> None:
        """Write the audit report JSON to disk and print a status summary."""
        audit_id = report["audit_id"]
        report_path = os.path.join(output_dir, f"audit-report-{audit_id}.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        self.stdout.write(f"Audit report written to {report_path}")
        summary = report["summary"]
        self.stdout.write(
            f"Status: "
            f"{'PASS' if summary['fail'] == 0 and summary['warn'] == 0 else 'WARN' if summary['fail'] == 0 else 'FAIL'}"
            f" (pass={summary['pass']}, warn={summary['warn']}, fail={summary['fail']}, info={summary['info']})"
        )

    # ── Phase 1: Completeness ──────────────────────────────────────────────────

    def _phase_completeness(
        self, mappings: list[CsvMapping], bundle_dir: str, verbose: bool
    ) -> dict:
        """Compare CSV row counts to DB record counts per CsvMapping.

        Args:
            mappings: List of CSV mappings to audit.
            bundle_dir: Path to the bundle directory.
            verbose: When ``True``, print status for every mapping.

        Returns:
            Dict with ``"status"`` and ``"checks"`` keys.
        """
        checks: list[dict] = []
        has_warn = False
        has_fail = False

        for mapping in mappings:
            csv_files = mapping.match_csv_files(bundle_dir)
            if not csv_files:
                checks.append(
                    {
                        "csv": mapping.csv_pattern,
                        "model": mapping.model.__name__,
                        "csv_rows": 0,
                        "db_records": 0,
                        "status": "info",
                        "notes": f"No CSV files matched '{mapping.csv_pattern}' — optional import",
                    }
                )
                continue

            total_csv_rows = sum(csv_row_count(f) for f in csv_files)
            db_count = mapping.model.objects.count()

            status = "pass"
            notes: str | None = None

            if total_csv_rows == 0 and db_count == 0:
                status = "info"
                notes = "Both CSV and DB are empty"
            elif total_csv_rows != db_count:
                if mapping.expected_gap_reason:
                    status = "warn"
                    notes = f"{mapping.expected_gap_reason} (CSV={total_csv_rows}, DB={db_count})"
                else:
                    status = "fail"
                    notes = f"CSV has {total_csv_rows} rows, DB has {db_count} records"

            if status == "warn":
                has_warn = True
            elif status == "fail":
                has_fail = True

            if verbose:
                symbol = (
                    "\u2713"
                    if status == "pass"
                    else (
                        "\u26a0"
                        if status == "warn"
                        else "\u2717" if status == "fail" else "\u2139"
                    )
                )
                self.stdout.write(
                    f"  {symbol} {mapping.model.__name__}: "
                    f"{total_csv_rows} CSV rows \u2192 {db_count} DB records  [{status}]"
                    + (f" \u2014 {notes}" if notes else "")
                )

            checks.append(
                {
                    "csv": mapping.csv_pattern,
                    "model": mapping.model.__name__,
                    "csv_rows": total_csv_rows,
                    "db_records": db_count,
                    "status": status,
                    "notes": notes,
                }
            )

        overall_status = "fail" if has_fail else "warn" if has_warn else "pass"
        return {"status": overall_status, "checks": checks}

    # ── Phase 2: Accuracy ──────────────────────────────────────────────────────

    def _phase_accuracy(
        self, mappings: list[CsvMapping], bundle_dir: str, verbose: bool
    ) -> dict:
        """Compare field values from CSV rows against DB records.

        Args:
            mappings: List of CSV mappings to audit.
            bundle_dir: Path to the bundle directory.
            verbose: When ``True``, print per-field mismatch details.

        Returns:
            Dict with ``"status"`` and ``"checks"`` keys.
        """
        checks: list[dict] = []
        has_mismatch = False

        for mapping in mappings:
            csv_files = mapping.match_csv_files(bundle_dir)
            if not csv_files:
                continue

            # Build field map from first CSV headers
            with open(csv_files[0], "r", encoding="utf-8-sig") as handle:
                sample_reader = csv.DictReader(handle)
                csv_headers = list(sample_reader.fieldnames or [])

            field_map = mapping.resolve_field_map(csv_headers)
            tier = "override" if mapping.field_overrides else "heuristic"
            unmatched = sorted(h for h in csv_headers if h not in field_map)

            # Determine sample strategy
            db_count = mapping.model.objects.count()
            if db_count > 500 and not verbose:
                sample_pct = 0.1
            else:
                sample_pct = 1.0

            mismatches = 0
            total_sampled = 0
            error_count = 0

            for csv_file in csv_files:
                try:
                    with open(csv_file, "r", encoding="utf-8-sig") as handle:
                        reader = csv.DictReader(handle)
                        for row_number, row in enumerate(reader, start=1):
                            # Deterministic sampling via hash on (file, row)
                            if (
                                sample_pct < 1.0
                                and hash(f"{csv_file}:{row_number}") % 100
                                > sample_pct * 100
                            ):
                                continue

                            db_obj = self._resolve_record(mapping, row)
                            if db_obj is None:
                                error_count += 1
                                continue

                            total_sampled += 1
                            for csv_header, model_field in field_map.items():
                                csv_val = row.get(csv_header, "")
                                db_val = getattr(db_obj, model_field, None)
                                field_type_name = self._get_field_type(
                                    mapping.model, model_field
                                )

                                if not compare_field_value(
                                    csv_val, db_val, field_type_name
                                ):
                                    mismatches += 1
                                    if verbose:
                                        self.stdout.write(
                                            f"  MISMATCH {mapping.model.__name__}.{model_field}: "
                                            f"CSV='{csv_val}' DB='{db_val}' "
                                            f"(row {row_number}, {os.path.basename(csv_file)})"
                                        )
                except (FileNotFoundError, UnicodeDecodeError, csv.Error) as exc:
                    error_count += 1
                    if verbose:
                        self.stdout.write(f"  ERROR reading {csv_file}: {exc}")
                    continue

            status = "pass"
            notes: str | None = None
            if error_count > 0 and total_sampled == 0:
                status = "fail"
                notes = f"Could not read any data ({error_count} errors)"
                has_mismatch = True
            elif mismatches > 0:
                status = "warn"
                notes = f"{mismatches} field mismatches in {total_sampled} sampled rows"
                has_mismatch = True
            elif total_sampled == 0:
                status = "info"
                notes = "No records to sample"

            if verbose:
                symbol = (
                    "\u2713"
                    if status == "pass"
                    else (
                        "\u26a0"
                        if status == "warn"
                        else "\u2717" if status == "fail" else "\u2139"
                    )
                )
                self.stdout.write(
                    f"  {symbol} {mapping.model.__name__}: {total_sampled} rows sampled, "
                    f"{mismatches} mismatches, {error_count} errors [tier={tier}]"
                )

            checks.append(
                {
                    "model": mapping.model.__name__,
                    "sample_size": db_count,
                    "sampled": total_sampled,
                    "tier": tier,
                    "mismatches": mismatches,
                    "errors": error_count,
                    "unmatched_columns": unmatched,
                    "status": status,
                    "notes": notes,
                }
            )

        overall_status = (
            "fail"
            if has_mismatch and any(c["status"] == "fail" for c in checks)
            else "warn" if has_mismatch else "pass"
        )
        return {"status": overall_status, "checks": checks}

    @staticmethod
    def _get_field_type(model: type[Model], field_name: str) -> str:
        """Return the Django field class name for *field_name* on *model*."""
        try:
            field = model._meta.get_field(field_name)
            return field.__class__.__name__
        except Exception:
            return "CharField"
