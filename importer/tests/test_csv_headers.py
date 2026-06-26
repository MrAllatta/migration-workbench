"""Tests for the importer.csv_headers header detection utilities."""

from pathlib import Path

import pytest

from importer.csv_headers import (
    HeaderNotFoundError,
    HeaderRegistry,
    build_reader,
    find_header_row,
    iter_year_suffixed_csvs,
    normalize_field_name,
    register_preamble_prefix,
)

FIXTURES = Path(__file__).parent / "fixtures" / "csv_headers"


class TestNormalizeFieldName:
    """Coverage for ``normalize_field_name``."""

    def test_collapses_newlines(self) -> None:
        assert normalize_field_name("Total\nSupply") == "total supply"

    def test_strips_whitespace(self) -> None:
        assert normalize_field_name("  Qty   Storage  ") == "qty storage"

    def test_returns_empty_for_none(self) -> None:
        assert normalize_field_name(None) == ""

    def test_returns_empty_for_empty(self) -> None:
        assert normalize_field_name("") == ""

    def test_lowercases(self) -> None:
        assert normalize_field_name("Harvest Year") == "harvest year"


class TestFindHeaderRow:
    """Coverage for ``find_header_row``."""

    def test_clean_first_row(self) -> None:
        path = FIXTURES / "clean_header.csv"
        assert find_header_row(path, ["Harvest Year", "Crop"]) == 0

    def test_skips_metadata_preamble(self) -> None:
        path = FIXTURES / "metadata_preamble.csv"
        assert find_header_row(path, ["Harvest Year", "Crop"]) == 2

    def test_skips_field_year_config(self) -> None:
        path = FIXTURES / "field_year_config.csv"
        assert find_header_row(path, ["Harvest Year", "Crop"]) == 1

    def test_handles_embedded_newline_in_header(self) -> None:
        path = FIXTURES / "embedded_newline_header.csv"
        assert find_header_row(path, ["Harvest Year", "Crop"]) == 0

    def test_finds_header_inside_data_row(self) -> None:
        path = FIXTURES / "header_in_data_row.csv"
        assert find_header_row(path, ["Sales QTY Goal", "QTY Left To Pack"]) == 0

    def test_raises_when_not_found(self) -> None:
        path = FIXTURES / "header_not_found.csv"
        with pytest.raises(HeaderNotFoundError):
            find_header_row(path, ["Harvest Year"])

    def test_raises_value_error_on_empty_markers(self) -> None:
        path = FIXTURES / "clean_header.csv"
        with pytest.raises(ValueError, match="marker"):
            find_header_row(path, [])


class TestBuildReader:
    """Coverage for ``build_reader``."""

    def test_normalizes_fieldnames(self) -> None:
        path = FIXTURES / "embedded_newline_header.csv"
        reader = build_reader(path, ["Harvest Year", "Crop"])
        assert reader.fieldnames == [
            "harvest year",
            "harvest week",
            "crop",
            "total supply",
        ]
        rows = list(reader)
        assert rows[0]["harvest year"] == "2024"
        assert rows[0]["total supply"] == "100"

    def test_applies_aliases(self) -> None:
        path = FIXTURES / "aliases.csv"
        reader = build_reader(
            path,
            ["Harvest Year", "Crop"],
            aliases={"total supply": ["Total Supply"]},
        )
        assert "total supply" in reader.fieldnames
        rows = list(reader)
        assert rows[0]["total supply"] == "100"

    def test_strips_trailing_empty_columns(self) -> None:
        path = FIXTURES / "empty_trailing_columns.csv"
        reader = build_reader(path, ["Harvest Year", "Crop"])
        assert reader.fieldnames == ["harvest year", "harvest week", "crop"]
        rows = list(reader)
        assert rows[0]["crop"] == "Carrots"

    def test_reads_rows_after_header_in_data_row(self) -> None:
        path = FIXTURES / "header_in_data_row.csv"
        reader = build_reader(path, ["Sales QTY Goal", "QTY Left To Pack"])
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["sales qty goal"] == "3.4"

    def test_reads_metadata_preamble_file(self) -> None:
        path = FIXTURES / "metadata_preamble.csv"
        reader = build_reader(path, ["Harvest Year", "Crop"])
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["harvest year"] == "2024"


class TestRegisterPreamblePrefix:
    """Coverage for ``register_preamble_prefix``."""

    def test_registered_prefix_skips_row(self, tmp_path) -> None:
        csv_path = tmp_path / "test.csv"
        csv_path.write_text(
            "Welcome to the Farm Spreadsheet\n"
            "Harvest Year,Harvest Week,Crop\n"
            "2024,1,Carrots\n"
        )
        # Without registration, "Welcome" would not be skipped.
        register_preamble_prefix("welcome to")
        try:
            reader = build_reader(str(csv_path), ["Harvest Year", "Harvest Week"])
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["crop"] == "Carrots"
        finally:
            # Clean up so we don't affect other tests
            from importer.csv_headers import _INSTRUCTIVE_PREFIXES

            _INSTRUCTIVE_PREFIXES.remove("welcome to")

    def test_registered_prefix_case_insensitive(self) -> None:
        from importer.csv_headers import _INSTRUCTIVE_PREFIXES

        register_preamble_prefix("NOTE:")
        assert "note:" in _INSTRUCTIVE_PREFIXES
        _INSTRUCTIVE_PREFIXES.remove("note:")

    def test_empty_prefix_ignored(self) -> None:
        from importer.csv_headers import _INSTRUCTIVE_PREFIXES

        count_before = len(_INSTRUCTIVE_PREFIXES)
        register_preamble_prefix("")
        assert len(_INSTRUCTIVE_PREFIXES) == count_before

    def test_duplicate_not_added(self) -> None:
        from importer.csv_headers import _INSTRUCTIVE_PREFIXES

        count_before = len(_INSTRUCTIVE_PREFIXES)
        register_preamble_prefix("choose ")
        assert len(_INSTRUCTIVE_PREFIXES) == count_before


class TestIterYearSuffixedCSVs:
    """Coverage for ``iter_year_suffixed_csvs``."""

    def test_extracts_year_from_filename(self, tmp_path) -> None:
        (tmp_path / "available_2025.csv").write_text("a\nb\n")
        (tmp_path / "available_2026.csv").write_text("a\nb\n")
        (tmp_path / "other.csv").write_text("a\nb\n")

        pattern = str(tmp_path / "available_*.csv")
        results = iter_year_suffixed_csvs(pattern)
        assert len(results) == 2
        years = [year for _, year in results]
        assert 2025 in years
        assert 2026 in years

    def test_excludes_non_matching(self, tmp_path) -> None:
        (tmp_path / "data_no_year.csv").write_text("a\nb\n")
        pattern = str(tmp_path / "*.csv")
        results = iter_year_suffixed_csvs(pattern)
        assert len(results) == 0

    def test_default_year_includes_non_matching(self, tmp_path) -> None:
        (tmp_path / "no_year.csv").write_text("a\nb\n")
        pattern = str(tmp_path / "*.csv")
        results = iter_year_suffixed_csvs(pattern, default_year=2026)
        assert len(results) == 1
        path, year = results[0]
        assert year == 2026
        assert "no_year" in str(path)


class TestHeaderRegistry:
    """Coverage for ``HeaderRegistry``."""

    def test_build_reader_for_matches_pattern(self, tmp_path) -> None:
        csv_path = tmp_path / "available_2025.csv"
        csv_path.write_text("Harvest Year,Harvest Week,Crop\n2024,1,Carrots\n")

        registry = HeaderRegistry()
        registry.register("*available*", markers=["Harvest Year", "Crop"])
        reader = registry.build_reader_for(str(csv_path))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["crop"] == "Carrots"

    def test_longest_pattern_wins(self, tmp_path) -> None:
        csv_path = tmp_path / "pack_list_2024.csv"
        csv_path.write_text(
            "Crop,Var,Notes\n2024,1,first\nINVENTORY,ITEM,QTY\nCarrots,bunch,50\n"
        )

        registry = HeaderRegistry()
        # Shorter pattern: marker "Crop" -> finds row 0 -> 3 data rows
        registry.register("pack_list_*", markers=["Crop", "Var"])
        # Longer pattern: marker "INVENTORY" -> finds row 2 -> 1 data row
        registry.register("pack_list_*2024*", markers=["INVENTORY"])
        reader = registry.build_reader_for(str(csv_path))
        rows = list(reader)
        # The longer pattern should win, finding the row 2 header (INVENTORY,ITEM,QTY),
        # so only 1 data row with inventory="Carrots"
        assert len(rows) == 1
        assert rows[0]["inventory"] == "Carrots"
        assert rows[0]["item"] == "bunch"

    def test_missing_registration_raises_key_error(self, tmp_path) -> None:
        csv_path = tmp_path / "unknown.csv"
        csv_path.write_text("a,b\n1,2\n")
        registry = HeaderRegistry()
        with pytest.raises(KeyError, match="unknown"):
            registry.build_reader_for(str(csv_path))

    def test_default_registry_is_global_singleton(self) -> None:
        # The module-level ``header_registry`` is a global singleton.
        from importer.csv_headers import header_registry as default_registry

        assert isinstance(default_registry, HeaderRegistry)
