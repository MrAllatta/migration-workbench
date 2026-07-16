"""Tests for deployment/commands/manifest.py — extraction from wb_cli.py.

e03s02: Move manifest subcommands from wb_cli.py into their own module.
The new module must be importable, provide the parser builder, and
preserve the existing handler signature so wb_cli.py can dispatch to it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def test_manifest_module_imports_cleanly() -> None:
    """deployment.commands.manifest must be importable after extraction."""
    import deployment.commands.manifest as manifest_mod

    importlib.reload(manifest_mod)


def test_manifest_module_has_build_manifest_parser() -> None:
    """The module must expose a build_manifest_parser() callable."""
    import deployment.commands.manifest as manifest_mod

    importlib.reload(manifest_mod)
    assert callable(manifest_mod.build_manifest_parser)


def test_manifest_module_has_manifest_lint_handler() -> None:
    """The module must expose the _manifest_lint handler."""
    import deployment.commands.manifest as manifest_mod

    importlib.reload(manifest_mod)
    assert callable(manifest_mod._manifest_lint)


def test_build_manifest_parser_returns_subparser() -> None:
    """build_manifest_parser must add a 'manifest' parser with 'lint' subcommand."""
    import argparse

    import deployment.commands.manifest as manifest_mod

    importlib.reload(manifest_mod)

    parser = argparse.ArgumentParser(prog="wb")
    sub = parser.add_subparsers(dest="command")
    manifest_mod.build_manifest_parser(sub)

    # Should parse 'manifest lint' without error
    parsed = parser.parse_args(["manifest", "lint"])
    assert parsed.manifest_command == "lint"
    assert callable(parsed.func)


def test_manifest_lint_handler_returns_int(tmp_path: Path) -> None:
    """_manifest_lint must accept args and return an int exit code."""
    import argparse

    import deployment.commands.manifest as manifest_mod

    importlib.reload(manifest_mod)

    # Use the project's own deploy/spaces.yml as a known-valid fixture.
    # This avoids re-declaring the manifest schema in the test.
    repo_root = Path(__file__).resolve().parents[2]
    real_manifest = repo_root / "deploy" / "spaces.yml"
    assert real_manifest.exists(), f"Fixture manifest missing: {real_manifest}"

    args = argparse.Namespace(
        manifest=str(real_manifest),
        json=False,
    )
    result = manifest_mod._manifest_lint(args)
    assert isinstance(result, int)
    # A valid manifest should succeed
    assert result == 0


def test_wb_manifest_lint_still_works_via_wb_cli(tmp_path: Path) -> None:
    """``wb manifest lint`` must still dispatch correctly through wb_cli.build_parser()."""
    import argparse

    from deployment.wb_cli import build_parser

    repo_root = Path(__file__).resolve().parents[2]
    real_manifest = repo_root / "deploy" / "spaces.yml"
    assert real_manifest.exists(), f"Fixture manifest missing: {real_manifest}"

    parser = build_parser()
    args = parser.parse_args(["--manifest", str(real_manifest), "manifest", "lint"])
    assert args.manifest_command == "lint"
    assert callable(args.func)
    result = args.func(args)
    assert isinstance(result, int)
    assert result == 0


def test_reimport_preserves_handler_reference() -> None:
    """The _manifest_lint accessible via wb_cli must be the same function."""
    from deployment.wb_cli import _manifest_lint as original_ref

    import deployment.commands.manifest as manifest_mod

    importlib.reload(manifest_mod)

    # After extraction, wb_cli should re-export or directly reference the same function
    assert original_ref is manifest_mod._manifest_lint
