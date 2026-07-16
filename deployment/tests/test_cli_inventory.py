"""Tests for the wb_cli.py command inventory.

This test suite verifies that the cli-router-split work has produced
a structured inventory of every top-level command group, subcommand,
and handler function in deployment/wb_cli.py. The inventory is the
shared contract between the discovery phase (e03s01) and the
extraction phase (e03s02-e03s05).
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
import yaml

INVENTORY_PATH = Path("specs/inventory/cli-router.yaml")
WB_CLI_PATH = Path("deployment/wb_cli.py")

#: Top-level command groups present in build_parser() at the time
#: of the cli-router-split epic. Each entry lists the parser name,
#: the subcommands it owns, and the handler functions it dispatches to.
EXPECTED_GROUPS: dict[str, dict[str, list[str]]] = {
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
        "subcommands": ["deploy"],
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


def _load_inventory() -> dict:
    """Load and parse the inventory YAML file.

    Returns the parsed YAML as a dict. Asserts the file exists and
    is parseable.
    """
    assert INVENTORY_PATH.exists(), (
        f"Inventory file missing: {INVENTORY_PATH}. "
        "e03s01 requires the inventory before e03s02-e03s05 can begin."
    )
    return yaml.safe_load(INVENTORY_PATH.read_text())


def _defined_handlers() -> set[str]:
    """Return the set of every ``def _xxx(`` defined in wb_cli.py."""
    source = WB_CLI_PATH.read_text()
    return set(re.findall(r"^def\s+(_[a-z_][a-z0-9_]*)\s*\(", source, re.MULTILINE))


def test_inventory_file_exists() -> None:
    """Inventory file must exist before the cli-router-split can proceed."""
    assert INVENTORY_PATH.exists(), f"Inventory missing: {INVENTORY_PATH}"


def test_inventory_is_valid_yaml() -> None:
    """Inventory must be a parseable YAML file (machine-readable)."""
    assert INVENTORY_PATH.suffix == ".yaml"
    data = yaml.safe_load(INVENTORY_PATH.read_text())
    assert isinstance(data, dict), "Inventory root must be a mapping"


def test_inventory_covers_all_command_groups() -> None:
    """Every top-level command group from build_parser() must be a key in the inventory."""
    data = _load_inventory()
    listed = set(data.keys())

    expected = set(EXPECTED_GROUPS.keys())
    missing = expected - listed
    assert not missing, f"Inventory missing command groups: {sorted(missing)}"


def _commands_module_handler_names() -> set[str]:
    """Return the set of handler names available via deployment.commands.*."""
    import importlib
    import pkgutil

    handler_names: set[str] = set()
    try:
        import deployment.commands

        for _, name, _ in pkgutil.iter_modules(
            deployment.commands.__path__
        ):
            mod = importlib.import_module(f"deployment.commands.{name}")
            for attr_name in dir(mod):
                if attr_name.startswith("_"):
                    handler_names.add(attr_name)
    except ImportError:
        pass  # commands package may not be populated yet
    return handler_names


def test_inventory_handlers_exist_in_codebase() -> None:
    """Every handler named in the inventory must be defined in the codebase.

    During the cli-router-split, handlers are gradually extracted from
    ``wb_cli.py`` into ``deployment.commands.*`` modules. This test
    checks ALL known locations, not just ``wb_cli.py``.
    """
    data = _load_inventory()
    defined = _defined_handlers() | _commands_module_handler_names()

    # Gather every handler reference from the inventory's groups
    referenced: set[str] = set()
    for group_data in data.values():
        if not isinstance(group_data, dict):
            continue
        for handler in group_data.get("handlers", []):
            if isinstance(handler, str):
                referenced.add(handler)
        for sub in group_data.get("subcommands", []):
            if isinstance(sub, dict):
                h = sub.get("handler")
                if isinstance(h, str):
                    referenced.add(h)
                for hh in sub.get("handlers", []):
                    if isinstance(hh, str):
                        referenced.add(hh)

    missing = referenced - defined
    assert not missing, f"Inventory references handlers not found in codebase: {sorted(missing)}"


def test_wb_cli_baseline_line_count() -> None:
    """Baseline: wb_cli.py is the file being split. Pin its current line count.

    This guard lets e03s02-e03s05 detect a successful split: the line
    count of wb_cli.py must drop below the baseline.
    """
    baseline = 232
    actual = sum(1 for _ in WB_CLI_PATH.open())
    assert actual == baseline, (
        f"wb_cli.py is {actual} lines; expected {baseline} baseline. "
        "If you intentionally changed the file, update the baseline."
    )


def test_wb_cli_still_works_after_inventory() -> None:
    """Sanity: ``import deployment.wb_cli`` still imports cleanly.

    The inventory is a documentation artifact. It must not change
    runtime behaviour.
    """
    mod = importlib.import_module("deployment.wb_cli")
    importlib.reload(mod)
    assert callable(mod.main)
    assert callable(mod.build_parser)
