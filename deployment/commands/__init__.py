"""Command groups for the ``wb`` CLI.

Each submodule here owns one top-level command group from the
``wb`` CLI. ``deployment.wb_cli`` imports each module's parser
builder and dispatches subcommands to the module's handler
functions.

See ``specs/inventory/cli-router.yaml`` for the full inventory
and ``specs/epics/e03-cli-router-split/`` for the split roadmap.
"""
