"""Tests for wb generate manifest command routing."""

import argparse
from unittest.mock import patch


def test_generate_manifest_forwards_contract_as_schema_contract():
    """_generate_manifest should forward --contract as --schema-contract to scaffold_view_manifest."""
    from deployment.wb_cli import _generate_manifest

    args = argparse.Namespace(
        structure="build/structure.json",
        contract="build/schema-contract.yaml",
        out="build/view-manifest.yaml",
        django_settings=None,
    )

    with patch("django.core.management.call_command") as mock_call:
        with patch("deployment.wb_cli._setup_django"):
            _generate_manifest(args)

    call_kwargs = mock_call.call_args[1]
    assert call_kwargs.get("schema_contract") == "build/schema-contract.yaml", (
        f"Expected schema_contract kwarg to be forwarded, got: {call_kwargs}"
    )


def test_generate_manifest_imports_scaffold_not_generate():
    """_generate_manifest should import scaffold_view_manifest, not generate_view_manifest."""
    from deployment import wb_cli

    with patch("django.core.management.call_command"):
        with patch("deployment.wb_cli._setup_django"):
            with patch(
                "workbook.management.commands.scaffold_view_manifest.Command"
            ) as mock_cmd:
                args = argparse.Namespace(
                    structure="build/structure.json",
                    contract="build/schema-contract.yaml",
                    out="build/view-manifest.yaml",
                    django_settings=None,
                )
                wb_cli._generate_manifest(args)
