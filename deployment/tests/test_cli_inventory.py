"""Tests for the wb_cli.py command inventory.

This test suite verifies that the cli-router-split work has produced
a structured inventory of every top-level command group, subcommand,
and handler function in deployment/wb_cli.py. The inventory is the
shared contract between the discovery phase (e03s01) and the
extraction phase (e03s02-e03s05).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

INVENTORY_PATH = Path("specs/inventory/cli-router.yaml")
WB_CLI_PATH = Path("deployment/wb_cli.py")

#: Top-level command groups present in build_parser() at the time
#: of the cli-router-split epic. Each entry has a parser name, the
#: handler(s) it dispatches to, and the subcommands it owns.
EXPECTED_GROUPS = {
    "manifest": {
        "subcommands": ["lint"],
        "handlers": ["_manifest_lint"],
    },
    "contract": {
        "subcommands": ["review", "diff", "safety", "validate"],
        "handlers": [
            "_contract_review",
            "_contract_diff",
            "_contract_safety",
            "_contract_validate",
        ],
    },
    "drift": {
        "subcommands": ["check"],
        "handlers": ["_drift_check"],
    },
    "deploy": {
        "subcommands": ["<args>"],
        "handlers": ["_deploy_dry_run", "_deploy_live"],
    },
    "generate": {
        "subcommands": ["models", "admin", "import", "manifest", "views"],
        "handlers": [
            "_generate_models",
            "_generate_admin",
            "_generate_import",
            "_generate_manifest",
            "_generate_views",
        ],
    },
    "vertical": {
        "subcommands": ["list", "show"],
        "handlers": ["_vertical_list", "_vertical_show"],
    },
    "ecosystem": {
        "subcommands": ["health", "ack"],
        "handlers": ["_ecosystem_health", "_ecosystem_ack"],
    },
}


def _read_inventory() -> str:
    """Read the inventory YAML file. Asserts file exists."""
    assert INVENTORY_PATH.exists(), (
        f"Inventory file missing: {INVENTORY_PATH}. "
        "e03s01 requires the inventory before e03s02-e03s05 can begin."
    )
    return INVENTORY_PATH.read_text()


def _extract_top_level_groups(inventory_text: str) -> set[str]:
    """Parse the top-level command group keys from the inventory.

    Recognises a simple top-level key list: lines that start with
    two-space indent followed by a non-`-` non-`"` character and a
    colon. Good enough for the inventory format this story produces.
    """
    groups: set[str] = set()
    for line in inventory_text.splitlines():
        stripped = line.rstrip()
        if stripped.startswith("  ") and not stripped.startswith("   "):
            key = stripped.strip().rstrip(":")
            # Top-level keys are simple identifiers (no leading `-` or `"`)
            if key and re.fullmatch(r"[a-z_]+", key):
                groups.add(key)
    return groups


def test_inventory_file_exists() -> None:
    """Inventory file must exist before the cli-router-split can proceed."""
    assert INVENTORY_PATH.exists(), f"Inventory missing: {INVENTORY_PATH}"


def test_inventory_has_yaml_extension() -> None:
    """Inventory must be a YAML file (machine-readable)."""
    assert INVENTORY_PATH.suffix == ".yaml"


def test_inventory_covers_all_command_groups() -> None:
    """Every top-level command group from build_parser() must be in the inventory."""
    inventory_text = _read_inventory()
    listed_groups = _extract_top_level_groups(inventory_text)

    expected = set(EXPECTED_GROUPS.keys())
    missing = expected - listed_groups
    assert not missing, f"Inventory missing command groups: {sorted(missing)}"


def test_inventory_handlers_exist_in_wb_cli() -> None:
    """Every handler named in the inventory must be defined in wb_cli.py."""
    inventory_text = _read_inventory()
    wb_cli_source = WB_CLI_PATH.read_text()

    # Find every ``def _xxx(`` line in wb_cli.py
    defined = set(re.findall(r"^def\s+(_[a-z_][a-z0-9_]*)\s*\(", wb_cli_source, re.MULTILINE))

    # Find every handler reference in the inventory (rough but sufficient)
    referenced = set(re.findall(r"_(?:[a-z]+_[a-z_]+)\b", inventory_text))
    # Only keep the ones that look like handlers (start with underscore + lowercase)
    handler_like = {h for h in referenced if h.startswith("_") and h[1:].islower()}

    # Cross-check: any handler mentioned in inventory that does NOT exist in wb_cli.py
    missing = handler_like - defined
    assert not missing, f"Inventory references handlers not defined in wb_cli.py: {sorted(missing)}"


def test_wb_cli_baseline_line_count() -> None:
    """Baseline: wb_cli.py is the file being split. Pin its current line count.

    This guard lets e03s02-e03s05 detect a successful split: the line
    count of wb_cli.py must drop below the baseline.
    """
    baseline = 1420
    actual = sum(1 for _ in WB_CLI_PATH.open())
    assert actual == baseline, (
        f"wb_cli.py is {actual} lines; expected {baseline} baseline. "
        "If you intentionally changed the file, update the baseline."
    )


def test_wb_cli_still_works_after_inventory() -> None:
    """Sanity: ``python -c "import deployment.wb_cli"`` still imports cleanly.

    The inventory is a documentation artifact. It must not change
    runtime behaviour.
    """
    import importlib

    mod = importlib.import_module("deployment.wb_cli")
    importlib.reload(mod)
    assert callable(mod.main)
    assert callable(mod.build_parser)
