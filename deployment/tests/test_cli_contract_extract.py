"""Tests for deployment/commands/contract.py — extraction from wb_cli.py.

e03s03: Move contract subcommands (review, diff, safety, validate)
from wb_cli.py into their own module.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _example_contract() -> Path:
    """Return the path to a known-valid schema contract fixture."""
    candidates = sorted(_REPO_ROOT.glob("example_data/*contract*.example.yaml"))
    return candidates[0]


def test_contract_module_imports_cleanly() -> None:
    """deployment.commands.contract must be importable after extraction."""
    import deployment.commands.contract  # noqa: F401


def test_contract_module_has_build_contract_parser() -> None:
    """The module must expose a build_contract_parser() callable."""
    import deployment.commands.contract as c

    assert callable(c.build_contract_parser)


def test_contract_module_has_all_handlers() -> None:
    """The module must expose all four contract handlers."""
    import deployment.commands.contract as c

    assert callable(c._contract_review)
    assert callable(c._contract_diff)
    assert callable(c._contract_safety)
    assert callable(c._contract_validate)


def test_build_contract_parser_has_four_subcommands() -> None:
    """build_contract_parser must register review, diff, safety, validate."""
    import argparse

    import deployment.commands.contract as c

    parser = argparse.ArgumentParser(prog="wb")
    sub = parser.add_subparsers(dest="command")
    c.build_contract_parser(sub)

    # Parse each subcommand with its required arguments
    # Note: cmd='review' requires --contract; diff/safety need --old/--new;
    # validate needs --contract. We provide dummy values.
    cmd_args_map = {
        "review": ["--contract", "/dev/null"],
        "diff": ["--old", "/dev/null", "--new", "/dev/null"],
        "safety": ["--old", "/dev/null", "--new", "/dev/null"],
        "validate": ["--contract", "/dev/null"],
    }
    for cmd in ["review", "diff", "safety", "validate"]:
        parsed = parser.parse_args(["contract", cmd] + cmd_args_map[cmd])
        assert parsed.contract_command == cmd
        assert callable(getattr(parsed, "func", None))


def test_contract_review_returns_int_on_missing_file() -> None:
    """_contract_review must return an int exit code on error (missing file)."""
    import argparse

    import deployment.commands.contract as c

    args = argparse.Namespace(
        contract="/nonexistent/contract.yaml",
        json=True,
        exit_zero=False,
        django_settings=None,
        dependency_artifact=None,
    )
    result = c._contract_review(args)
    assert isinstance(result, int)


def test_contract_diff_returns_int_on_missing_files() -> None:
    """_contract_diff must return an int exit code on error (missing files)."""
    import argparse

    import deployment.commands.contract as c

    args = argparse.Namespace(
        old="/nonexistent/old.yaml",
        new="/nonexistent/new.yaml",
        json=True,
        django_settings=None,
    )
    result = c._contract_diff(args)
    assert isinstance(result, int)


def test_contract_safety_returns_int_on_missing_files() -> None:
    """_contract_safety must return an int exit code on error (missing files)."""
    import argparse

    import deployment.commands.contract as c

    args = argparse.Namespace(
        old="/nonexistent/old.yaml",
        new="/nonexistent/new.yaml",
        json=True,
        django_settings=None,
    )
    result = c._contract_safety(args)
    assert isinstance(result, int)


def test_contract_validate_returns_int() -> None:
    """_contract_validate must return an int exit code.

    Uses a known-valid contract fixture to avoid CommandError from
    Django's validate_contract when the file doesn't exist.
    """
    import argparse

    import deployment.commands.contract as c

    contract_path = _example_contract()
    args = argparse.Namespace(
        contract=str(contract_path),
        json=False,
        exit_zero=False,
        strict=False,
        django_settings=None,
    )
    result = c._contract_validate(args)
    assert isinstance(result, int)


def test_contract_commands_still_work_via_wb_cli() -> None:
    """All four contract commands must dispatch through wb_cli.build_parser()."""
    import argparse

    from deployment.wb_cli import build_parser

    parser = build_parser()
    cmd_args_map = {
        "review": ["--contract", "/dev/null"],
        "diff": ["--old", "/dev/null", "--new", "/dev/null"],
        "safety": ["--old", "/dev/null", "--new", "/dev/null"],
        "validate": ["--contract", "/dev/null"],
    }
    for cmd in ["review", "diff", "safety", "validate"]:
        args = parser.parse_args(["contract", cmd] + cmd_args_map[cmd])
        assert args.command == "contract"
        assert args.contract_command == cmd
        assert callable(getattr(args, "func", None))


def test_reimport_preserves_handler_identity() -> None:
    """The contract handlers via wb_cli must live in deployment.commands.contract."""
    import deployment.commands.contract as contract_mod

    from deployment.wb_cli import (
        _contract_diff,
        _contract_review,
        _contract_safety,
        _contract_validate,
    )

    assert _contract_review.__module__ == "deployment.commands.contract"
    assert _contract_diff.__module__ == "deployment.commands.contract"
    assert _contract_safety.__module__ == "deployment.commands.contract"
    assert _contract_validate.__module__ == "deployment.commands.contract"
