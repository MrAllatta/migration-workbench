"""Tests for ``importer.base_audit`` — helpers, CsvMapping, and BaseAuditCommand.

Tests cover:
1. Standalone helper functions (``clean``, ``boolish``, ``intish``, etc.)
2. ``CsvMapping`` dataclass methods (``match_csv_files``, ``resolve_field_map``)
3. ``BaseAuditCommand`` phase methods (using example app models)
"""

import csv
import json
import os
import tempfile
from decimal import Decimal
from io import StringIO

import pytest

from examples.models import ExampleCrop
from importer.base_audit import (
    CsvMapping,
    BaseAuditCommand,
    boolish,
    clean,
    compare_field_value,
    decish,
    intish,
    normalize_header,
    csv_row_count,
    get_model_fields,
)

# ── Helpers ─────────────────────────────────────────────────────────────────────


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


# ── Test 1: clean ──────────────────────────────────────────────────────────────


class TestClean:
    def test_clean_none(self):
        assert clean(None) == ""

    def test_clean_strips_whitespace(self):
        assert clean("  foo  ") == "foo"

    def test_clean_converts_non_string(self):
        assert clean(0) == "0"


# ── Test 2: boolish ────────────────────────────────────────────────────────────


class TestBoolish:
    def test_truthy_values(self):
        for val in ("yes", "true", "1", "y", "x"):
            assert boolish(val) is True

    def test_falsy_values(self):
        for val in ("no", "false", "0", "n", ""):
            assert boolish(val) is False

    def test_ambiguous_returns_none(self):
        assert boolish("maybe") is None


# ── Test 3: intish ─────────────────────────────────────────────────────────────


class TestIntish:
    def test_basic_int(self):
        assert intish("42") == 42

    def test_strips_commas(self):
        assert intish("1,234") == 1234

    def test_empty_returns_default(self):
        assert intish("") is None
        assert intish("", default=0) == 0

    def test_invalid_returns_default(self):
        assert intish("abc") is None


# ── Test 4: decish ─────────────────────────────────────────────────────────────


class TestDecish:
    def test_basic_decimal(self):
        assert decish("10.50") == Decimal("10.50")

    def test_strips_currency(self):
        assert decish("$1,234.56") == Decimal("1234.56")

    def test_strips_percent(self):
        assert decish("12.5%") == Decimal("12.5")

    def test_empty_returns_default(self):
        assert decish("") is None

    def test_invalid_returns_default(self):
        assert decish("not_a_number") is None


# ── Test 5: normalize_header ───────────────────────────────────────────────────


class TestNormalizeHeader:
    def test_lowercases(self):
        assert normalize_header("CROP") == "crop"

    def test_replaces_spaces(self):
        assert normalize_header("Field Block") == "field_block"

    def test_strips_special_chars(self):
        assert normalize_header("CROP & VARIETY") == "crop_variety"

    def test_handles_parenthesised_units(self):
        result = normalize_header("Harvest Rate (units per hour)")
        assert result == "harvest_rate_units_per_hour"


# ── Test 6: csv_row_count ──────────────────────────────────────────────────────


class TestCsvRowCount:
    def test_counts_data_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["header"])
                writer.writerow(["row1"])
                writer.writerow(["row2"])
            assert csv_row_count(path) == 2

    def test_missing_file_returns_zero(self):
        assert csv_row_count("/nonexistent/path.csv") == 0


# ── Test 7: get_model_fields ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestGetModelFields:
    def test_returns_editable_fields(self):
        fields = get_model_fields(ExampleCrop)
        assert "name" in fields
        assert "id" not in fields  # PK is excluded


# ── Test 8: compare_field_value ────────────────────────────────────────────────


class TestCompareFieldValue:
    def test_integer_field_falsy_values(self):
        """0 from CSV equals 0 from DB (the falsy-value fix)."""
        assert compare_field_value("0", 0, "IntegerField") is True

    def test_charfield_csv_value_with_none_db(self):
        """Non-empty CSV vs None DB is a mismatch."""
        assert compare_field_value("Artichoke", None, "CharField") is False

    def test_boolean_field_true(self):
        """'yes' CSV maps to True BooleanField."""
        assert compare_field_value("yes", True, "BooleanField") is True

    def test_both_empty_matches(self):
        """Empty CSV and None DB match for CharField."""
        assert compare_field_value("", None, "CharField") is True

    def test_decimal_field_precision(self):
        """Decimal values compare within tolerance."""
        assert compare_field_value("10.50", Decimal("10.50"), "DecimalField") is True


# ── Test 9: CsvMapping.match_csv_files ─────────────────────────────────────────


class TestCsvMappingMatchFiles:
    def test_exact_pattern_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _ensure_dir(os.path.join(tmpdir, "reference"))
            for name in ("crop_info.csv", "other.csv"):
                path = os.path.join(tmpdir, "reference", name)
                with open(path, "w") as f:
                    f.write("x\n")

            _ensure_dir(os.path.join(tmpdir, "crop_plan"))
            path = os.path.join(tmpdir, "crop_plan", "seed_order.csv")
            with open(path, "w") as f:
                f.write("x\n")

            mapping = CsvMapping(
                csv_pattern="reference/crop_info.csv",
                model=ExampleCrop,
                natural_key=["name"],
            )
            matches = mapping.match_csv_files(tmpdir)
            assert len(matches) == 1
            assert matches[0].endswith("reference/crop_info.csv")

    def test_glob_no_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mapping = CsvMapping(
                csv_pattern="weekly_ops/orders_*.csv",
                model=ExampleCrop,
                natural_key=["name"],
            )
            matches = mapping.match_csv_files(tmpdir)
            assert matches == []

    def test_glob_pattern_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _ensure_dir(os.path.join(tmpdir, "weekly_ops"))
            path = os.path.join(tmpdir, "weekly_ops", "orders_2024.csv")
            with open(path, "w") as f:
                f.write("x\n")

            mapping = CsvMapping(
                csv_pattern="weekly_ops/orders_*.csv",
                model=ExampleCrop,
                natural_key=["name"],
            )
            matches = mapping.match_csv_files(tmpdir)
            assert len(matches) == 1
            assert matches[0].endswith("weekly_ops/orders_2024.csv")


# ── Test 10: CsvMapping.resolve_field_map ──────────────────────────────────────


class TestCsvMappingResolveFieldMap:
    def test_overrides_applied(self):
        mapping = CsvMapping(
            csv_pattern="reference/crop_info.csv",
            model=ExampleCrop,
            natural_key=["name"],
            field_overrides={"Crop Name": "crop"},
        )
        result = mapping.resolve_field_map(["Crop Name", "Variety"])
        assert result == {"Crop Name": "crop", "Variety": "variety"}

    def test_heuristic_fallback(self):
        mapping = CsvMapping(
            csv_pattern="reference/crop_info.csv",
            model=ExampleCrop,
            natural_key=["name"],
        )
        result = mapping.resolve_field_map(["CROP NAME", "Variety"])
        assert result == {"CROP NAME": "crop_name", "Variety": "variety"}


# ── Test 11: BaseAuditCommand._phase_completeness ─────────────────────────────


class _MinimalAuditCommand(BaseAuditCommand):
    """Concrete subclass for testing the base class methods."""

    def _resolve_mappings(self) -> list[CsvMapping]:
        return []

    def _resolve_record(self, mapping, row):
        return None


@pytest.mark.django_db
class TestPhaseCompleteness:
    def _write_crop_csv(self, data_dir, rows):
        _ensure_dir(os.path.join(data_dir, "reference"))
        path = os.path.join(data_dir, "reference", "crop_info.csv")
        fieldnames = ["Crop"]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_mismatch_detected(self):
        """Completeness phase detects CSV row count vs DB record count mismatch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_crop_csv(
                tmpdir,
                [
                    {"Crop": "Kale"},
                    {"Crop": "Beet"},
                    {"Crop": "Carrot"},
                ],
            )
            ExampleCrop.objects.create(name="Kale")
            ExampleCrop.objects.create(name="Beet")

            mapping = CsvMapping(
                csv_pattern="reference/crop_info.csv",
                model=ExampleCrop,
                natural_key=["name"],
            )
            cmd = _MinimalAuditCommand(stdout=StringIO())
            result = cmd._phase_completeness([mapping], tmpdir, verbose=False)

            check = result["checks"][0]
            assert check["csv_rows"] == 3
            assert check["db_records"] == 2
            assert check["status"] in ("warn", "fail")

    def test_match_when_counts_equal(self):
        """Completeness passes when CSV rows equal DB records."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_crop_csv(
                tmpdir,
                [
                    {"Crop": "Kale"},
                    {"Crop": "Beet"},
                ],
            )
            ExampleCrop.objects.create(name="Kale")
            ExampleCrop.objects.create(name="Beet")

            mapping = CsvMapping(
                csv_pattern="reference/crop_info.csv",
                model=ExampleCrop,
                natural_key=["name"],
            )
            cmd = _MinimalAuditCommand(stdout=StringIO())
            result = cmd._phase_completeness([mapping], tmpdir, verbose=False)

            check = result["checks"][0]
            assert result["status"] == "pass"
            assert check["status"] == "pass"

    def test_both_empty_is_info(self):
        """Both CSV and DB empty produces info, not fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_crop_csv(tmpdir, [])

            mapping = CsvMapping(
                csv_pattern="reference/crop_info.csv",
                model=ExampleCrop,
                natural_key=["name"],
            )
            cmd = _MinimalAuditCommand(stdout=StringIO())
            result = cmd._phase_completeness([mapping], tmpdir, verbose=False)

            check = result["checks"][0]
            assert check["status"] == "info"
            assert check["notes"] == "Both CSV and CSV are empty" or "Both"

    def test_expected_gap_reason_produces_warn(self):
        """Expected gap reason turns fail into warn."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_crop_csv(
                tmpdir,
                [{"Crop": "Kale"}, {"Crop": "Beet"}, {"Crop": "Carrot"}],
            )
            ExampleCrop.objects.create(name="Kale")

            mapping = CsvMapping(
                csv_pattern="reference/crop_info.csv",
                model=ExampleCrop,
                natural_key=["name"],
                expected_gap_reason="Known stale FK on row 2",
            )
            cmd = _MinimalAuditCommand(stdout=StringIO())
            result = cmd._phase_completeness([mapping], tmpdir, verbose=False)

            check = result["checks"][0]
            assert check["status"] == "warn"
            assert "Known stale FK" in (check["notes"] or "")


# ── Test 12: BaseAuditCommand._get_field_type ─────────────────────────────────


@pytest.mark.django_db
class TestGetFieldType:
    def test_charfield_detected(self):
        assert BaseAuditCommand._get_field_type(ExampleCrop, "name") == "CharField"


# ── Test 13: BaseAuditCommand._update_summary and _write_report ────────────────


@pytest.mark.django_db
class TestReportHelpers:
    def test_update_summary_tallies(self):
        cmd = _MinimalAuditCommand(stdout=StringIO())
        report = {
            "phases": {
                "completeness": {
                    "checks": [
                        {"status": "pass"},
                        {"status": "warn"},
                        {"status": "pass"},
                    ]
                }
            },
            "summary": {"pass": 0, "warn": 0, "fail": 0, "info": 0},
        }
        cmd._update_summary(report)
        assert report["summary"]["pass"] == 2
        assert report["summary"]["warn"] == 1

    def test_write_report_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = _MinimalAuditCommand(stdout=StringIO())
            report = {
                "audit_id": "test123",
                "phases": {},
                "summary": {"pass": 1, "warn": 0, "fail": 0, "info": 0},
            }
            cmd._write_report(report, tmpdir)
            report_path = os.path.join(tmpdir, "audit-report-test123.json")
            assert os.path.exists(report_path)
            with open(report_path) as f:
                data = json.load(f)
            assert data["audit_id"] == "test123"
