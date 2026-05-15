import pytest
from datetime import date
from decimal import Decimal

from importer.parsing import (
    parse_iso_date,
    split_on,
    to_bool,
    to_decimal,
    to_decimal_or_none,
    to_int,
    to_int_or_none,
)


class TestToInt:
    def test_float_string(self):
        assert to_int("4.0") == 4

    def test_empty_string_returns_default(self):
        assert to_int("") == 0
        assert to_int("", 5) == 5

    def test_whitespace_only_returns_default(self):
        assert to_int("   ") == 0

    def test_na_returns_default(self):
        assert to_int("N/A", 0) == 0
        assert to_int("na", 0) == 0

    def test_dash_returns_default(self):
        assert to_int("-", 0) == 0

    def test_none_returns_default(self):
        assert to_int(None, 0) == 0

    def test_negative(self):
        assert to_int("-3") == -3

    def test_integer_string(self):
        assert to_int("42") == 42


class TestToIntOrNone:
    def test_zero_returns_none(self):
        assert to_int_or_none("0") is None

    def test_empty_returns_none(self):
        assert to_int_or_none("") is None

    def test_positive(self):
        assert to_int_or_none("5") == 5

    def test_float_string(self):
        assert to_int_or_none("3.0") == 3

    def test_na_returns_none(self):
        assert to_int_or_none("NA") is None


class TestToDecimal:
    def test_currency(self):
        assert to_decimal("$1,200.50") == Decimal("1200.50")

    def test_empty_returns_default(self):
        assert to_decimal("") == Decimal("0")
        assert to_decimal("", "10") == Decimal("10")

    def test_whitespace_returns_default(self):
        assert to_decimal("   ") == Decimal("0")

    def test_na_returns_default(self):
        assert to_decimal("N/A") == Decimal("0")

    def test_dash_returns_default(self):
        assert to_decimal("-") == Decimal("0")

    def test_none_returns_default(self):
        assert to_decimal(None) == Decimal("0")


class TestToDecimalOrNone:
    def test_na_returns_none(self):
        assert to_decimal_or_none("na") is None

    def test_positive(self):
        assert to_decimal_or_none("5.50") == Decimal("5.50")

    def test_zero_returns_none(self):
        assert to_decimal_or_none("0") is None


class TestToBool:
    def test_truthy_strings(self):
        for val in ("yes", "Yes", "YES", "true", "True", "1", "y", "x"):
            assert to_bool(val) is True

    def test_falsy_strings(self):
        for val in ("no", "No", "NO", "false", "False", "0", "n", ""):
            assert to_bool(val) is False

    def test_none_returns_default(self):
        assert to_bool(None) is False
        assert to_bool(None, default=True) is True

    def test_unrecognized_returns_default(self):
        assert to_bool("maybe") is False
        assert to_bool("maybe", default=True) is True

    def test_python_bool_passthrough(self):
        assert to_bool(True) is True
        assert to_bool(False) is False


class TestParseIsoDate:
    def test_valid_date(self):
        assert parse_iso_date("2023-05-15") == date(2023, 5, 15)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_iso_date("not-a-date")

    def test_whitespace_stripped(self):
        assert parse_iso_date("  2023-01-01  ") == date(2023, 1, 1)


class TestSplitOn:
    def test_basic(self):
        assert split_on("Crop // Variety") == ("Crop", "Variety")

    def test_no_delimiter(self):
        assert split_on("Crop only") == ("Crop only", "")

    def test_none_value(self):
        assert split_on(None) == ("", "")

    def test_custom_delimiter(self):
        assert split_on("left | right", delimiter="|") == ("left", "right")