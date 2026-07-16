"""Tests for remaining command group extractions (e03s04).

Batch test: generate, deploy, vertical, ecosystem, drift.
All extracted from wb_cli.py into deployment/commands/*.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _deploy_manifest() -> str:
    """Return the path to a known-valid deployment manifest."""
    return str(_REPO_ROOT / "deploy" / "spaces.yml")


def _schema_contract() -> str:
    """Return the path to a known-valid schema contract."""
    return str(next(_REPO_ROOT.glob("example_data/*contract*.example.yaml")))


# ── generate ──────────────────────────────────────────────────────


def test_generate_module_imports() -> None:
    import deployment.commands.generate  # noqa: F401


def test_generate_module_has_build_generate_parser() -> None:
    import deployment.commands.generate as m
    assert callable(m.build_generate_parser)


def test_generate_module_has_all_handlers() -> None:
    import deployment.commands.generate as m
    for name in ["_generate_models", "_generate_admin", "_generate_import",
                 "_generate_manifest", "_generate_views"]:
        assert callable(getattr(m, name)), f"{name} not callable"


def test_generate_parser_registers_five_subcommands() -> None:
    import deployment.commands.generate as m
    parser = argparse.ArgumentParser(prog="wb")
    sub = parser.add_subparsers(dest="command")
    m.build_generate_parser(sub)
    # Each generate subcommand has different required args; provide stubs.
    cmd_args = {
        "models": ["--contract", "/dev/null"],
        "admin": ["--contract", "/dev/null"],
        "import": ["--contract", "/dev/null"],
        "manifest": ["--contract", "/dev/null"],
        "views": ["--contract", "/dev/null", "--out-dir", "/tmp"],
    }
    for cmd in ["models", "admin", "import", "manifest", "views"]:
        parsed = parser.parse_args(["generate", cmd] + cmd_args[cmd])
        assert hasattr(parsed, "func") and callable(parsed.func)


def test_generate_handler_reimport_identity() -> None:
    from deployment.commands.generate import (
        _generate_admin, _generate_import, _generate_manifest,
        _generate_models, _generate_views,
    )
    from deployment.wb_cli import (
        _generate_admin as w_admin,
        _generate_import as w_import,
        _generate_manifest as w_manifest,
        _generate_models as w_models,
        _generate_views as w_views,
    )
    assert _generate_admin is w_admin
    assert _generate_import is w_import
    assert _generate_manifest is w_manifest
    assert _generate_models is w_models
    assert _generate_views is w_views


# ── deploy ────────────────────────────────────────────────────────


def test_deploy_module_imports() -> None:
    import deployment.commands.deploy  # noqa: F401


def test_deploy_module_has_build_deploy_parser() -> None:
    import deployment.commands.deploy as m
    assert callable(m.build_deploy_parser)


def test_deploy_module_has_both_handlers() -> None:
    import deployment.commands.deploy as m
    assert callable(m._deploy_dry_run)
    assert callable(m._deploy_live)


def test_deploy_parser_registers_subcommand() -> None:
    import deployment.commands.deploy as m
    parser = argparse.ArgumentParser(prog="wb")
    sub = parser.add_subparsers(dest="command")
    m.build_deploy_parser(sub)
    parsed = parser.parse_args(["deploy", "test-space", "--env", "production", "--dry-run"])
    assert parsed.space == "test-space"
    assert hasattr(parsed, "func") and callable(parsed.func)


def test_deploy_dry_run_returns_int() -> None:
    import deployment.commands.deploy as m
    result = m._deploy_dry_run(argparse.Namespace(
        space="nonexistent-space", env="production",
        dry_run=True, live=False, local=False, verbose=False,
        manifest=_deploy_manifest(), json=True, django_settings=None,
    ))
    assert isinstance(result, int)


def test_deploy_live_returns_int() -> None:
    import deployment.commands.deploy as m
    result = m._deploy_live(argparse.Namespace(
        space="nonexistent-space", env="production",
        dry_run=False, live=True, local=False, verbose=False,
        manifest=_deploy_manifest(), json=True, django_settings=None,
    ))
    assert isinstance(result, int)


def test_deploy_handler_reimport_identity() -> None:
    from deployment.commands.deploy import _deploy_dry_run, _deploy_live
    from deployment.wb_cli import _deploy_dry_run as w_dry, _deploy_live as w_live
    assert _deploy_dry_run is w_dry
    assert _deploy_live is w_live


# ── vertical ──────────────────────────────────────────────────────


def test_vertical_module_imports() -> None:
    import deployment.commands.vertical  # noqa: F401


def test_vertical_module_has_build_vertical_parser() -> None:
    import deployment.commands.vertical as m
    assert callable(m.build_vertical_parser)


def test_vertical_module_has_both_handlers() -> None:
    import deployment.commands.vertical as m
    assert callable(m._vertical_list)
    assert callable(m._vertical_show)


def test_vertical_parser_registers_list_and_show() -> None:
    import deployment.commands.vertical as m
    parser = argparse.ArgumentParser(prog="wb")
    sub = parser.add_subparsers(dest="command")
    m.build_vertical_parser(sub)
    parsed = parser.parse_args(["vertical", "list"])
    assert hasattr(parsed, "func") and callable(parsed.func)
    parsed = parser.parse_args(["vertical", "show", "test-vertical"])
    assert hasattr(parsed, "func") and callable(parsed.func)


def test_vertical_list_returns_int() -> None:
    import deployment.commands.vertical as m
    result = m._vertical_list(argparse.Namespace(json=True))
    assert isinstance(result, int)


def test_vertical_handler_reimport_identity() -> None:
    from deployment.commands.vertical import _vertical_list, _vertical_show
    from deployment.wb_cli import _vertical_list as w_list, _vertical_show as w_show
    assert _vertical_list is w_list
    assert _vertical_show is w_show


# ── ecosystem ─────────────────────────────────────────────────────


def test_ecosystem_module_imports() -> None:
    import deployment.commands.ecosystem  # noqa: F401


def test_ecosystem_module_has_build_ecosystem_parser() -> None:
    import deployment.commands.ecosystem as m
    assert callable(m.build_ecosystem_parser)


def test_ecosystem_module_has_both_handlers() -> None:
    import deployment.commands.ecosystem as m
    assert callable(m._ecosystem_health)
    assert callable(m._ecosystem_ack)


def test_ecosystem_parser_registers_health_and_ack() -> None:
    import deployment.commands.ecosystem as m
    parser = argparse.ArgumentParser(prog="wb")
    sub = parser.add_subparsers(dest="command")
    m.build_ecosystem_parser(sub)
    parsed = parser.parse_args(["ecosystem", "health"])
    assert hasattr(parsed, "func") and callable(parsed.func)
    parsed = parser.parse_args(["ecosystem", "ack", "test-queue", "test-file"])
    assert hasattr(parsed, "func") and callable(parsed.func)


def test_ecosystem_handler_reimport_identity() -> None:
    from deployment.commands.ecosystem import _ecosystem_ack, _ecosystem_health
    from deployment.wb_cli import _ecosystem_ack as w_ack, _ecosystem_health as w_health
    assert _ecosystem_ack is w_ack
    assert _ecosystem_health is w_health


# ── drift ─────────────────────────────────────────────────────────


def test_drift_module_imports() -> None:
    import deployment.commands.drift  # noqa: F401


def test_drift_module_has_build_drift_parser() -> None:
    import deployment.commands.drift as m
    assert callable(m.build_drift_parser)


def test_drift_module_has_drift_check_handler() -> None:
    import deployment.commands.drift as m
    assert callable(m._drift_check)


def test_drift_parser_registers_check() -> None:
    import deployment.commands.drift as m
    parser = argparse.ArgumentParser(prog="wb")
    sub = parser.add_subparsers(dest="command")
    m.build_drift_parser(sub)
    # drift check requires --baseline and --new
    parsed = parser.parse_args(["drift", "check", "--baseline", "/dev/null", "--new", "/dev/null"])
    assert hasattr(parsed, "func") and callable(parsed.func)


def test_drift_handler_reimport_identity() -> None:
    from deployment.commands.drift import _drift_check
    from deployment.wb_cli import _drift_check as w_drift
    assert _drift_check is w_drift


# ── Full wb_cli integration ────────────────────────────────────────


def test_all_commands_still_dispatch_via_wb_cli() -> None:
    """All remaining command groups must dispatch through build_parser()."""
    from deployment.wb_cli import build_parser

    parser = build_parser()

    # generate
    args = parser.parse_args(["generate", "models", "--contract", _schema_contract()])
    assert args.generate_command == "models"

    # deploy
    args = parser.parse_args(["deploy", "test-space", "--env", "production",
                               "--dry-run", "--manifest", _deploy_manifest()])
    assert args.space == "test-space"

    # vertical
    args = parser.parse_args(["vertical", "list"])
    assert args.vertical_command == "list"

    # ecosystem
    args = parser.parse_args(["ecosystem", "health"])
    assert args.ecosystem_command == "health"

    # drift
    args = parser.parse_args(["drift", "check",
                               "--baseline", _schema_contract(),
                               "--new", _schema_contract()])
    assert args.drift_command == "check"
