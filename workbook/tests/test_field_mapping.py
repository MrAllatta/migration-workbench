def test_is_valid_python_identifier_good():
    from workbook.field_mapping import is_valid_python_identifier

    assert is_valid_python_identifier("crop_variety")
    assert is_valid_python_identifier("name_2")


def test_is_valid_python_identifier_starts_with_digit():
    from workbook.field_mapping import is_valid_python_identifier

    assert not is_valid_python_identifier("1")
    assert not is_valid_python_identifier("201_unit")


def test_is_valid_python_identifier_keyword():
    from workbook.field_mapping import is_valid_python_identifier

    assert not is_valid_python_identifier("yield")
    assert not is_valid_python_identifier("class")
