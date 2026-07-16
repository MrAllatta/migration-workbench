"""Tests for wb generate views command routing.

These tests verify that the wb CLI correctly forwards arguments to the
``generate_views`` management command.
"""

import argparse
from unittest.mock import patch


def test_generate_views_forwards_all_arguments():
    """_generate_views should forward all standard arguments to generate_views."""
    from deployment.wb_cli import _generate_views

    args = argparse.Namespace(
        contract="build/schema-contract.yaml",
        out_dir="build/_out/views",
        app_label="core",
        archetype_checklist="auto",
        archetype_landing="config/landing-config.yaml",
        archetype_dashboard="config/dashboard-config.yaml",
        template_package="config/templates",
        force=True,
        validate=True,
        django_settings=None,
    )

    with patch("django.core.management.call_command") as mock_call:
        with patch("deployment.wb_cli._setup_django"):
            _generate_views(args)

    call_kwargs = mock_call.call_args[1]
    assert call_kwargs["contract"] == "build/schema-contract.yaml"
    assert call_kwargs["out_dir"] == "build/_out/views"
    assert call_kwargs["app_label"] == "core"
    assert call_kwargs["archetype_checklist"] == "auto"
    assert call_kwargs["archetype_landing"] == "config/landing-config.yaml"
    assert call_kwargs["archetype_dashboard"] == "config/dashboard-config.yaml"
    assert call_kwargs["template_package"] == "config/templates"
    assert call_kwargs["force"] is True
    assert call_kwargs["validate"] is True


def test_generate_views_minimal_arguments():
    """_generate_views works with only required arguments."""
    from deployment.wb_cli import _generate_views

    args = argparse.Namespace(
        contract="build/schema-contract.yaml",
        out_dir="build/_out/views",
        app_label=None,
        archetype_checklist=None,
        archetype_landing=None,
        archetype_dashboard=None,
        template_package=None,
        force=False,
        validate=False,
        django_settings=None,
    )

    with patch("django.core.management.call_command") as mock_call:
        with patch("deployment.wb_cli._setup_django"):
            _generate_views(args)

    call_kwargs = mock_call.call_args[1]
    assert call_kwargs["contract"] == "build/schema-contract.yaml"
    assert call_kwargs["out_dir"] == "build/_out/views"
    # Optional flags should NOT be forwarded when not set.
    assert "app_label" not in call_kwargs
    assert "archetype_checklist" not in call_kwargs
    assert "archetype_landing" not in call_kwargs
    assert "archetype_dashboard" not in call_kwargs
    assert "template_package" not in call_kwargs
    assert "force" not in call_kwargs
    assert "validate" not in call_kwargs


def test_generate_views_invokes_generate_views_command():
    """_generate_views should call the generate_views management command."""
    from deployment import wb_cli

    args = argparse.Namespace(
        contract="build/schema-contract.yaml",
        out_dir="build/_out/views",
        app_label="core",
        archetype_checklist="auto",
        archetype_landing=None,
        archetype_dashboard=None,
        template_package=None,
        force=True,
        validate=False,
        django_settings=None,
    )

    with patch("django.core.management.call_command") as mock_call:
        with patch("deployment.wb_cli._setup_django"):
            wb_cli._generate_views(args)

    mock_call.assert_called_once()
    command_name = mock_call.call_args[0][0]
    assert command_name == "generate_views"
