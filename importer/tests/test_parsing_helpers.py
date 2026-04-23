from importer.parsing import split_on, to_decimal, to_decimal_or_none, to_int, to_int_or_none


def test_parsing_helpers():
    assert to_int("4.0") == 4
    assert to_int_or_none("0") is None
    assert str(to_decimal("$1,200.50")) == "1200.50"
    assert to_decimal_or_none("na") is None
    assert split_on("Crop // Variety") == ("Crop", "Variety")
