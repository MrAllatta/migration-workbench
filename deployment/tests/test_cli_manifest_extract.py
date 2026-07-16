"""Tests for deployment/commands/manifest.py — extraction from wb_cli.py.

e03s02: Move manifest subcommands from wb_cli.py into their own module.
The new module must be importable, provide the parser builder, and
preserve the existing handler signature so wb_cli.py can dispatch to it.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _valid_manifest() -> Path:
    """Return the path to a known-valid manifest fixture."""
    return _REPO_ROOT / "deploy" / "spaces.yml"


def test_manifest_module_imports_cleanly() -> None:
    """deployment.commands.manifest must be importable after extraction."""
    import deployment.commands.manifest  # noqa: F401


def test_manifest_module_has_build_manifest_parser() -> None:
    """The module must expose a build_manifest_parser() callable."""
    import deployment.commands.manifest as manifest_mod

    assert callable(manifest_mod.build_manifest_parser)


def test_manifest_module_has_manifest_lint_handler() -> None:
    """The module must expose the _manifest_lint handler."""
    import deployment.commands.manifest as manifest_mod

    assert callable(manifest_mod._manifest_lint)


def test_build_manifest_parser_returns_subparser() -> None:
    """build_manifest_parser must add a 'manifest' parser with 'lint' subcommand."""
    import argparse

    import deployment.commands.manifest as manifest_mod

    parser = argparse.ArgumentParser(prog="wb")
    sub = parser.add_subparsers(dest="command")
    manifest_mod.build_manifest_parser(sub)

    parsed = parser.parse_args(["manifest", "lint"])
    assert parsed.manifest_command == "lint"
    assert callable(parsed.func)


def test_manifest_lint_handler_returns_int() -> None:
    """_manifest_lint must accept args and return an int exit code."""
    import argparse

    import deployment.commands.manifest as manifest_mod

    args = argparse.Namespace(
        manifest=str(_valid_manifest()),
        json=False,
    )
    result = manifest_mod._manifest_lint(args)
    assert isinstance(result, int)
    assert result == 0


def test_wb_manifest_lint_still_works_via_wb_cli() -> None:
    """``wb manifest lint`` must still dispatch correctly through wb_cli.build_parser()."""

    from deployment.wb_cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["--manifest", str(_valid_manifest()), "manifest", "lint"])
    assert args.manifest_command == "lint"
    assert callable(args.func)
    result = args.func(args)
    assert isinstance(result, int)
    assert result == 0


def test_reimport_preserves_handler_reference() -> None:
    """The _manifest_lint accessible via wb_cli must live in the commands module."""
    from deployment.wb_cli import _manifest_lint as wb_cli_ref

    assert wb_cli_ref.__module__ == "deployment.commands.manifest", (
        f"Expected _manifest_lint to live in deployment.commands.manifest, "
        f"but its __module__ is {wb_cli_ref.__module__}"
    )
