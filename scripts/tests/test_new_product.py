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


def test_corpus_codegen_report_is_report_only():
    """The corpus-codegen-report target uses --exit-zero so a non-zero
    contract review does not fail the build."""
    content = render_makefile()
    assert "--exit-zero" in content
    for rule_line in content.splitlines():
        if rule_line.startswith("corpus-codegen-report:"):
            assert "--exit-zero" not in rule_line
    codegen_lines = [
        line
        for line in content.splitlines()
        if "wb contract review" in line and "--contract" in line
    ]
    codegen_report_line = [
        line for line in codegen_lines if line.strip().startswith("wb")
    ]
    assert any("--exit-zero" in line for line in codegen_report_line)


def test_generate_admin_does_not_require_manifest_file():
    """The generate-admin target runs with or without a view-manifest file
    by using a shell conditional instead of a hard guard."""
    content = render_makefile()
    assert "if [ -f \"$(VIEW_MANIFEST)\" ]; then" in content
    assert "--manifest \"$(VIEW_MANIFEST)\"" in content
    generate_admin_section = content[
        content.index("generate-admin:") :
    ]
    assert "else" in generate_admin_section
    assert "--manifest" not in generate_admin_section.split("else")[1].split("fi")[0]
