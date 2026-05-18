"""Tests for the new_product scaffold generator."""
from scripts.new_product import render_makefile, render_models_py, render_env_example


def test_makefile_has_validate_contract_target():
    """The scaffolded Makefile includes a validate-contract target."""
    content = render_makefile("test-product")
    assert "validate-contract:" in content


def test_validate_aggregate_includes_contract_review():
    """The validate target chains check and validate-contract."""
    content = render_makefile("test-product")
    assert "validate: check validate-contract" in content


def test_corpus_codegen_report_is_report_only():
    """The corpus-codegen-report target uses --exit-zero so a non-zero
    contract review does not fail the build."""
    content = render_makefile("test-product")
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
    content = render_makefile("test-product")
    assert "if [ -f \"$(VIEW_MANIFEST)\" ]; then" in content
    assert "--manifest \"$(VIEW_MANIFEST)\"" in content
    generate_admin_section = content[
        content.index("generate-admin:") :
    ]
    assert "else" in generate_admin_section
    assert "--manifest" not in generate_admin_section.split("else")[1].split("fi")[0]


def test_render_urls_py_redirects_root_to_admin():
    """Root URL / redirects to /admin/."""
    from scripts.new_product import render_urls_py
    content = render_urls_py()
    assert 'RedirectView.as_view(url="/admin/"' in content
    assert 'path("", RedirectView' in content


def test_makefile_has_createsuperuser_target():
    """The scaffolded Makefile includes a createsuperuser target."""
    content = render_makefile("test-product")
    assert "createsuperuser:" in content
    assert "DJANGO_SUPERUSER_USERNAME" in content
    assert "DJANGO_SUPERUSER_PASSWORD" in content


def test_env_example_has_superuser_vars():
    """The scaffolded .env.example includes DJANGO_SUPERUSER_* variables."""
    content = render_env_example("google_sheets")
    assert "DJANGO_SUPERUSER_USERNAME" in content
    assert "DJANGO_SUPERUSER_PASSWORD" in content


def test_render_models_py_includes_stub_marker():
    """The scaffolded models.py includes the custom-models marker and auto import."""
    content = render_models_py("core", "FarmUser")
    assert "from .models_auto import *  # noqa: F401, F403" in content
    assert "# --- custom models below this line ---" in content
    assert "class FarmUser(AbstractUser):" in content


def test_schema_contract_md_includes_entity_guidance():
    """The scaffolded schema-contract.md has structured entity guidance, not just headings."""
    from scripts.new_product import render_schema_contract_md
    content = render_schema_contract_md("test-product")
    assert "**Purpose**" in content
    assert "**Source tabs**" in content
    assert "**Import key**" in content
    assert "domain-knowledge.yaml" in content


def test_domain_knowledge_example_yaml_includes_entities():
    """The domain-knowledge example YAML has populated entity examples."""
    from scripts.new_product import render_domain_knowledge_example_yaml
    content = render_domain_knowledge_example_yaml()
    assert "entities:" in content
    assert "Season:" in content
    assert "Planting:" in content
    assert "import_key:" in content
    assert "fk_to:" in content
    assert "ForeignKey" in content
