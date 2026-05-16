from importer.parsing import parse_iso_date
from datetime import date


def test_parse_iso_date_iso_format():
    assert parse_iso_date("2025-02-20") == date(2025, 2, 20)


def test_parse_iso_date_us_style():
    assert parse_iso_date("2/20/2025") == date(2025, 2, 20)


def test_parse_iso_date_us_short_year():
    assert parse_iso_date("2/20/25") == date(2025, 2, 20)


def test_parse_iso_date_leading_zeros():
    assert parse_iso_date("02/20/2025") == date(2025, 2, 20)


def test_parse_iso_date_invalid_format():
    import pytest
    with pytest.raises(ValueError, match="does not match any supported format"):
        parse_iso_date("not-a-date")


def test_parse_iso_date_whitespace_stripped():
    assert parse_iso_date("  2025-02-20  ") == date(2025, 2, 20)
