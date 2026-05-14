"""Tests for tab name sanitization utility."""

import pytest
from connectors.tab_name_utils import sanitize_tab_name


def test_pipe_replaced_with_underscore():
    result = sanitize_tab_name("i|Markets")
    assert result == "i_Markets"


def test_multiple_reserved_chars_replaced():
    result = sanitize_tab_name("orders|temp:2024")
    assert result == "orders_temp_2024"


def test_safe_name_unchanged():
    result = sanitize_tab_name("Crop Plan")
    assert result == "Crop Plan"


def test_all_reserved_chars():
    result = sanitize_tab_name('a|b:c\\d/e*f?g"h<i>j%k')
    assert result == "a_b_c_d_e_f_g_h_i_j_k"


def test_empty_string_returns_empty():
    result = sanitize_tab_name("")
    assert result == ""
