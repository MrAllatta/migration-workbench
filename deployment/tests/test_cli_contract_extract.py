"""Tests for deployment/commands/contract.py — extraction from wb_cli.py.

e03s03: Move contract subcommands (review, diff, safety, validate)
from wb_cli.py into their own module.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _schema_contract() -> Path:
    """Return the path to a known-valid schema contract fixture."""
    return next(
        (_REPO_ROOT / "example_data").glob("*contract*.example.yaml"),
        _REPO_ROOT / "example_data" / "schema-contract.example.yaml",
    )


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

    for cmd in ["review", "diff", "safety", "validate"]:
        parsed = parser.parse_args(["contract", cmd, "--help"])
        # Just parsing should succeed without error
        assert parsed.contract_command == cmd


def test_contract_review_returns_int() -> None:
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


def test_contract_diff_returns_int() -> None:
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


def test_contract_safety_returns_int() -> None:
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
    """_contract_validate must return an int exit code."""
    import argparse

    import deployment.commands.contract as c

    args = argparse.Namespace(
        contract="/nonexistent/contract.yaml",
        json=False,
        exit_zero=False,
        strict=False,
        django_settings=None,
    )
    result = c._contract_validate(args)
    assert isinstance(result, int)


def test_contract_commands_still_work_via_wb_cli() -> None:
    """All four contract commands must dispatch correctly through wb_cli.build_parser()."""
    import argparse

    from deployment.wb_cli import build_parser

    parser = build_parser()
    for cmd in ["review", "diff", "safety", "validate"]:
        args = parser.parse_args(["contract", cmd, "--help"])
        assert args.command == "contract"
        assert args.contract_command == cmd
        assert callable(getattr(args, "func", None) or getattr(args, "func", None))


def test_reimport_preserves_handler_identity() -> None:
    """The contract handlers accessible via wb_cli must live in commands.contract."""
    import deployment.commands.contract as contract_mod

    from deployment.wb_cli import (
        _contract_review,
        _contract_diff,
        _contract_safety,
        _contract_validate,
    )

    assert _contract_review.__module__ == "deployment.commands.contract"
    assert _contract_diff.__module__ == "deployment.commands.contract"
    assert _contract_safety.__module__ == "deployment.commands.contract"
    assert _contract_validate.__module__ == "deployment.commands.contract"
