from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_validate_domain_context_valid(tmp_path):
    ctx = tmp_path / "domain_context.yaml"
    ctx.write_text(
        "year_scope:\n  active: [2025, 2026]\nvocabulary:\n  operational: [planting]\n",
        encoding="utf-8",
    )
    out = StringIO()
    call_command("validate_domain_context", config=str(ctx), stdout=out)
    assert "valid" in out.getvalue()


def test_validate_domain_context_missing_file():
    with pytest.raises(CommandError, match="not found"):
        call_command("validate_domain_context", config="/nonexistent.yaml")


def test_validate_domain_context_bad_year_type(tmp_path):
    ctx = tmp_path / "domain_context.yaml"
    ctx.write_text("year_scope:\n  active: [\"2025\"]\n", encoding="utf-8")
    out = StringIO()
    with pytest.raises(CommandError, match="Validation failed"):
        call_command("validate_domain_context", config=str(ctx), stdout=out)


def test_validate_domain_context_strict_warning(tmp_path):
    ctx = tmp_path / "domain_context.yaml"
    ctx.write_text("year_scope:\n  active: [2025]\n", encoding="utf-8")
    out = StringIO()
    with pytest.raises(CommandError, match="strict"):
        call_command("validate_domain_context", config=str(ctx), strict=True, stdout=out)
