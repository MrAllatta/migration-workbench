"""Multi-year integration test for the historical import pipeline.

Creates a test fixture with 3 year directories (2022, 2023, 2024), each
containing CSV files that mirror the ExampleFarm schema.  A concrete subclass
of ``import_historical.Command`` imports the data, and assertions verify that
``source_bundle_year`` is injected correctly, row counts are aggregated
properly, and no unexpected errors occur.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime

import pytest
from django.core.management import call_command

from examples.models import ExampleFarm
from importer.management.commands import import_historical

# ---------------------------------------------------------------------------
# Test fixture — 3 year directories with farm CSV data
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_year_bundle(tmp_path):
    """Create a temp bundle with 3 year directories of farm data.

    2022: 2 farms, 3 fields
    2023: 1 farm, 2 fields
    2024: 1 farm (update), 1 field
    """
    years_data: dict[str, list[tuple[str, list[str], list[list[str]]]]] = {
        "2022": [
            (
                "farms.csv",
                ["Farm Name", "Region", "Established"],
                [
                    ["Sunny Acres", "Northeast", "2020-05-15"],
                    ["Green Hollow", "West Coast", "2018-03-22"],
                ],
            ),
            (
                "fields.csv",
                ["Field Name", "Farm", "Acreage", "Active"],
                [
                    ["North Field", "Sunny Acres", "12.5", "yes"],
                    ["South Field", "Sunny Acres", "8.0", "no"],
                    ["Hillside", "Green Hollow", "15.3", "yes"],
                ],
            ),
        ],
        "2023": [
            (
                "farms.csv",
                ["Farm Name", "Region", "Established"],
                [
                    ["River Bend", "Midwest", "2019-07-01"],
                ],
            ),
            (
                "fields.csv",
                ["Field Name", "Farm", "Acreage", "Active"],
                [
                    ["Lowlands", "River Bend", "20.0", "yes"],
                    ["Meadow", "River Bend", "5.5", "yes"],
                ],
            ),
        ],
        "2024": [
            (
                "farms.csv",
                ["Farm Name", "Region", "Established"],
                [
                    ["Sunny Acres", "Northeast (Expanded)", "2020-05-15"],
                ],
            ),
            (
                "fields.csv",
                ["Field Name", "Farm", "Acreage", "Active"],
                [
                    ["East Field", "Sunny Acres", "10.0", "yes"],
                ],
            ),
        ],
    }

    for year_name, files in years_data.items():
        year_dir = tmp_path / year_name
        year_dir.mkdir(parents=True)
        for filename, headers, rows in files:
            filepath = year_dir / filename
            with open(filepath, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)
                for row in rows:
                    writer.writerow(row)

    return str(tmp_path), years_data


def _count_csv_rows(
    years_data: dict,
) -> dict[str, dict[str, int]]:
    """Count rows per CSV per year from the fixture data structure.

    Returns:
        dict[str, dict[str, int]]: ``{year: {csv_name: row_count}}``.
    """
    counts: dict[str, dict[str, int]] = {}
    for year_name, files in years_data.items():
        counts[year_name] = {}
        for filename, _headers, rows in files:
            counts[year_name][filename] = len(rows)
    return counts


# ---------------------------------------------------------------------------
# Test command — concrete subclass that imports ExampleFarm
# ---------------------------------------------------------------------------


class HistoricalFarmCommand(import_historical.Command):
    """Concrete import_historical subclass for ExampleFarm data.

    Records ``(source_bundle_year, row_data)`` for each row processed so
    tests can verify that the year was injected correctly.
    """

    def __init__(self):
        super().__init__()
        self.processed_rows: list[tuple[str, dict[str, str]]] = []

    def _run_import_pipeline(self):
        """Import ``farms.csv`` from the current year directory."""
        csv_path = os.path.join(self.data_dir, "farms.csv")
        if not os.path.exists(csv_path):
            return
        for row_index, row in self._read_csv_rows(csv_path):
            self._import_farm_row(row_index, row)

    def _import_farm_row(self, row_index: int, row: dict[str, str]) -> None:
        """Create or update an ExampleFarm from a single CSV row.

        Args:
            row_index: 1-based CSV row number.
            row: Column dict with ``source_bundle_year`` injected.
        """
        name = (row.get("Farm Name") or "").strip()
        if not name:
            self.record_missing_required("ExampleFarm", row_index, "name", "Farm Name")
            self.stats["ExampleFarm"]["errors"] += 1
            return

        year = row.get("source_bundle_year", "")

        defaults: dict[str, object] = {
            "region": (row.get("Region") or "").strip(),
        }
        established_str = (row.get("Established") or "").strip()
        if established_str:
            try:
                defaults["established_date"] = datetime.strptime(
                    established_str, "%Y-%m-%d"
                ).date()
            except ValueError:
                self.record_row_error(
                    "ExampleFarm",
                    row_index,
                    "type_mismatch",
                    "established_date",
                    f"Invalid date: {established_str}",
                )
                self.stats["ExampleFarm"]["errors"] += 1
                return

        self.processed_rows.append((year, dict(row)))

        if self.write_disabled:
            self.stats["ExampleFarm"]["processed"] += 1
            return

        _, created = ExampleFarm.objects.update_or_create(name=name, defaults=defaults)
        stats_key = "created" if created else "updated"
        self.stats["ExampleFarm"][stats_key] += 1


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHistoricalFarmImporter:
    """Integration tests for the multi-year historical import pipeline."""

    def test_imports_all_years_with_correct_counts(self, db, multi_year_bundle):
        bundle_dir, years_data = multi_year_bundle
        csv_counts = _count_csv_rows(years_data)

        total_farm_rows = sum(
            csv_counts[year].get("farms.csv", 0) for year in csv_counts
        )

        cmd = HistoricalFarmCommand()
        call_command(
            cmd,
            bundle_dir=bundle_dir,
        )

        assert (
            cmd.stats["ExampleFarm"]["errors"] == 0
        ), f"Expected 0 errors, got {cmd.stats['ExampleFarm']['errors']}"

        total_imported = (
            cmd.stats["ExampleFarm"]["created"] + cmd.stats["ExampleFarm"]["updated"]
        )
        assert (
            total_imported == total_farm_rows
        ), f"Imported {total_imported} farm rows, expected {total_farm_rows}"

    def test_all_years_have_no_errors(self, db, multi_year_bundle):
        bundle_dir, _years_data = multi_year_bundle

        cmd = HistoricalFarmCommand()
        call_command(
            cmd,
            bundle_dir=bundle_dir,
        )

        assert (
            cmd.stats["ExampleFarm"]["errors"] == 0
        ), f"Expected 0 errors, got {cmd.stats['ExampleFarm']['errors']}"

    def test_source_bundle_year_is_injected_per_row(self, db, multi_year_bundle):
        bundle_dir, years_data = multi_year_bundle
        _expected_totals = _count_csv_rows(years_data)

        cmd = HistoricalFarmCommand()
        call_command(
            cmd,
            bundle_dir=bundle_dir,
        )

        farm_rows = [(year, row_data) for year, row_data in cmd.processed_rows]

        for year_name, files in years_data.items():
            for filename, _headers, rows in files:
                if filename != "farms.csv":
                    continue
                year_rows = [rd for y, rd in farm_rows if y == year_name]
                assert len(year_rows) == len(
                    rows
                ), f"Expected {len(rows)} rows for {year_name}, got {len(year_rows)}"
                for row_data in year_rows:
                    assert row_data.get("source_bundle_year") == year_name, (
                        f"Row missing correct source_bundle_year: "
                        f"got {row_data.get('source_bundle_year')!r}, "
                        f"expected {year_name!r}"
                    )

    def test_dry_run_processes_all_rows_no_db_writes(self, db, multi_year_bundle):
        bundle_dir, years_data = multi_year_bundle

        cmd = HistoricalFarmCommand()
        call_command(
            cmd,
            bundle_dir=bundle_dir,
            dry_run=True,
        )

        farm_count = ExampleFarm.objects.count()
        assert (
            farm_count == 0
        ), f"Dry run should not create DB records, found {farm_count}"

        total_farm_rows = sum(
            _count_csv_rows(years_data)[year].get("farms.csv", 0) for year in years_data
        )
        processed = cmd.stats["ExampleFarm"]["processed"]
        assert (
            processed == total_farm_rows
        ), f"Dry run processed {processed}, expected {total_farm_rows}"

    def test_validate_only_rolls_back(self, db, multi_year_bundle):
        bundle_dir, _years_data = multi_year_bundle

        cmd = HistoricalFarmCommand()
        call_command(
            cmd,
            bundle_dir=bundle_dir,
            validate_only=True,
        )

        farm_count = ExampleFarm.objects.count()
        assert (
            farm_count == 0
        ), f"Validate-only should roll back, found {farm_count} records"

    def test_displays_year_headings(self, multi_year_bundle, capsys):
        bundle_dir, _years_data = multi_year_bundle

        call_command(
            "import_historical",
            bundle_dir=bundle_dir,
            dry_run=True,
        )
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "Importing year: 2022" in output
        assert "Importing year: 2023" in output
        assert "Importing year: 2024" in output

    def test_farm_records_created_with_correct_data(self, db, multi_year_bundle):
        bundle_dir, _years_data = multi_year_bundle

        cmd = HistoricalFarmCommand()
        call_command(
            cmd,
            bundle_dir=bundle_dir,
        )

        sunny = ExampleFarm.objects.get(name="Sunny Acres")
        assert sunny.region == "Northeast (Expanded)"
        assert str(sunny.established_date) == "2020-05-15"

        green = ExampleFarm.objects.get(name="Green Hollow")
        assert green.region == "West Coast"

        river = ExampleFarm.objects.get(name="River Bend")
        assert river.region == "Midwest"
        assert str(river.established_date) == "2019-07-01"
