"""Edge-case tests for bundle reader column handling."""

import csv
import os
import tempfile

import pytest

from importer.bundle_reader import iter_bundle_tab_rows


def _write_csv(rows, tmp_path, filename="test.csv"):
    """Write a CSV file and return its path."""
    filepath = tmp_path / filename
    with open(filepath, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for row in rows:
            writer.writerow(row)
    return str(filepath)


class TestBundleReaderMultiSource:
    """Multi-source column_map entries should NOT appear in normalized rows.

    They are handled in the generated import method's value-expression
    rendering, not by the bundle reader.
    """

    def test_multi_source_column_map_excluded_from_row(self, tmp_path):
        csv_path = _write_csv(
            [
                ["Name", "Short Notes", "Growing Season"],
                ["Danvers", "Good keeper", "Winter"],
            ],
            tmp_path,
        )
        tab_config = {
            "required_headers": ["Name"],
            "column_map": {
                "name": "Name",
                "full_description": ["Short Notes", "Growing Season"],
            },
        }
        _, row = next(iter_bundle_tab_rows(csv_path, tab_config))
        assert row.get("name") == "Danvers"
        assert "full_description" not in row

    def test_single_source_column_map_present_in_row(self, tmp_path):
        csv_path = _write_csv(
            [
                ["Name", "Region"],
                ["Sunny Acres", "Northeast"],
            ],
            tmp_path,
        )
        tab_config = {
            "required_headers": ["Name"],
            "column_map": {"name": "Name", "region": "Region"},
        }
        _, row = next(iter_bundle_tab_rows(csv_path, tab_config))
        assert row.get("name") == "Sunny Acres"
        assert row.get("region") == "Northeast"

    def test_default_values_fill_missing(self, tmp_path):
        csv_path = _write_csv(
            [
                ["Name"],
                ["Sunny Acres"],
            ],
            tmp_path,
        )
        tab_config = {
            "required_headers": ["Name"],
            "column_map": {"name": "Name"},
            "default_values": {"region": "Unknown", "is_active": "yes"},
        }
        _, row = next(iter_bundle_tab_rows(csv_path, tab_config))
        assert row.get("name") == "Sunny Acres"
        assert row.get("region") == "Unknown"
        assert row.get("is_active") == "yes"

    def test_aliases_resolve_differently_than_canonical(self, tmp_path):
        csv_path = _write_csv(
            [
                ["Crop Name", "Type"],
                ["Carrot", "Root"],
            ],
            tmp_path,
        )
        tab_config = {
            "required_headers": ["Name"],
            "aliases": {"Name": ["Crop Name"]},
            "column_map": {"name": "Name", "crop_type": "Type"},
        }
        _, row = next(iter_bundle_tab_rows(csv_path, tab_config))
        assert row.get("name") == "Carrot"
        assert row.get("crop_type") == "Root"

    def test_empty_cell_normalized_to_empty_string(self, tmp_path):
        csv_path = _write_csv(
            [
                ["Name", "Region"],
                ["Sunny Acres", ""],
            ],
            tmp_path,
        )
        tab_config = {
            "required_headers": ["Name"],
            "column_map": {"name": "Name", "region": "Region"},
        }
        _, row = next(iter_bundle_tab_rows(csv_path, tab_config))
        assert row.get("name") == "Sunny Acres"
        assert row.get("region") == ""