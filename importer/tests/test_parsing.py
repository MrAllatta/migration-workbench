import pytest

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
    with pytest.raises(ValueError, match="does not match any supported format"):
        parse_iso_date("not-a-date")


def test_parse_iso_date_whitespace_stripped():
    assert parse_iso_date("  2025-02-20  ") == date(2025, 2, 20)


def test_parse_iso_date_month_day_no_year():
    result = parse_iso_date("6/13")
    assert result.month == 6
    assert result.day == 13
    assert result.year == date.today().year


def test_parse_iso_date_dash_format_short_year():
    assert parse_iso_date("6-20-23") == date(2023, 6, 20)


def test_parse_iso_date_dash_format_full_year():
    assert parse_iso_date("6-22-2023") == date(2023, 6, 22)


def test_parse_iso_date_dash_format_leading_zeros():
    assert parse_iso_date("06-20-2023") == date(2023, 6, 20)


def test_parse_iso_date_all_supported_formats():
    assert parse_iso_date("2023-01-05") == date(2023, 1, 5)
    assert parse_iso_date("01/05/2023") == date(2023, 1, 5)
    assert parse_iso_date("1/5/23") == date(2023, 1, 5)
    assert parse_iso_date("6/13").year == date.today().year
    assert parse_iso_date("6-20-23") == date(2023, 6, 20)
    assert parse_iso_date("06-20-2023") == date(2023, 6, 20)


def test_parse_iso_date_february_29_leap_year():
    assert parse_iso_date("02/29/2024") == date(2024, 2, 29)


def test_parse_iso_date_still_rejects_garbage():
    with pytest.raises(ValueError, match="does not match any supported format"):
        parse_iso_date("not-a-date-at-all")


def test_parse_iso_date_single_digit_month_day():
    assert parse_iso_date("1/5/2023") == date(2023, 1, 5)
