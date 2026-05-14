"""Tests for the new_product scaffold generator."""
from scripts.new_product import render_makefile


def test_makefile_has_validate_contract_target():
    """The scaffolded Makefile includes a validate-contract target."""
    content = render_makefile()
    assert "validate-contract:" in content


def test_validate_aggregate_includes_contract_review():
    """The validate target chains check and validate-contract."""
    content = render_makefile()
    assert "validate: check validate-contract" in content
