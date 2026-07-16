"""Contract loading: YAML parsing, ``!include`` support, and normalisation.

Extracted from ``workbook/codegen/contract.py`` as part of e04
(contract-layer-split).

Owns:
- ``_make_contract_loader`` — YAML SafeLoader subclass with ``!include``
- ``load_contract_unvalidated`` — load and normalise without validation
- ``load_contract`` — load and strictly validate
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _make_contract_loader(base_path: str | Path) -> type:
    """Return a ``SafeLoader`` subclass supporting ``!include`` and ``!include_list``.

    Both tags load YAML from another file and inline it at the point of use.
    Include paths are resolved relative to the directory of the including
    file, not the root contract file.

    Cyclic includes are detected and rejected.
    """
    import yaml

    contract_path = Path(base_path).resolve()

    class ContractLoader(yaml.SafeLoader):
        """YAML loader that supports ``!include`` for contract composition."""

        _include_stack: list[Path] = []
        _contract_path: Path = contract_path

    def _resolve_include_target(loader: ContractLoader, path_str: str) -> Path:
        """Resolve an ``!include`` path relative to the including file."""
        including_file = (
            loader._include_stack[-1]
            if loader._include_stack
            else loader._contract_path
        )
        return (including_file.parent / path_str).resolve()

    def _load_included_yaml(loader: ContractLoader, target: Path) -> Any:
        """Load a YAML file referenced by ``!include`` with cycle detection."""
        if target == loader._contract_path or target in loader._include_stack:
            cycle = " -> ".join(str(p) for p in loader._include_stack + [target])
            from workbench.exceptions import UserFacingError

            raise UserFacingError(
                f"cyclic include detected: {cycle}",
                action="Remove the circular !include reference in the contract YAML.",
                check_id="WORKBOOK-CONTRACT-001",
            )
        if not target.is_file():
            from workbench.exceptions import UserFacingError

            raise UserFacingError(
                f"include file not found: {target}",
                action="Create the missing file or correct the !include path in the contract YAML.",
                check_id="WORKBOOK-CONTRACT-002",
            )
        loader._include_stack.append(target)
        try:
            text = target.read_text(encoding="utf-8")
            return yaml.load(text, Loader=type(loader))
        finally:
            loader._include_stack.pop()

    def _include_constructor(loader: ContractLoader, node: yaml.ScalarNode) -> Any:
        """PyYAML constructor for ``!include`` scalar tags."""
        path_str: str = str(loader.construct_scalar(node))
        target = _resolve_include_target(loader, path_str)
        return _load_included_yaml(loader, target)

    def _include_list_constructor(loader: ContractLoader, node: yaml.ScalarNode) -> Any:
        """PyYAML constructor for ``!include`` tags expected to resolve to a list."""
        path_str: str = str(loader.construct_scalar(node))
        target = _resolve_include_target(loader, path_str)
        included = _load_included_yaml(loader, target)
        if not isinstance(included, list):
            from workbench.exceptions import UserFacingError

            included_type_name = type(included).__name__
            raise UserFacingError(
                f"!include_list target must be a YAML list (got {included_type_name}) in {target}",
                action="Ensure the included file contains a YAML list (a sequence starting with '-').",
                check_id="WORKBOOK-CONTRACT-003",
            )
        return included

    ContractLoader.add_constructor("!include", _include_constructor)
    ContractLoader.add_constructor("!include_list", _include_list_constructor)
    return ContractLoader


def load_contract_unvalidated(path: str | Path) -> dict[str, Any]:
    """Load a schema-contract YAML and return a normalised dict without validation.

    Handles YAML loading with ``!include``/``!include_list`` support,
    default key injection, table-list validation, and recursive flattening
    of nested table entries.

    Args:
        path: Filesystem path to a ``.yaml`` / ``.yml`` file.

    Returns:
        Normalised contract dict with ``"version"``, ``"source"``, and
        ``"tables"`` keys guaranteed present.
    """
    import yaml

    src = Path(path).read_text(encoding="utf-8")
    loader_cls = _make_contract_loader(path)
    raw: dict[str, Any] = yaml.load(src, Loader=loader_cls)
    if not isinstance(raw, dict):
        from workbench.exceptions import UserFacingError

        raise UserFacingError(
            "Schema contract must be a YAML mapping",
            action="Check that the contract file is valid YAML with a top-level mapping (not a list).",
            check_id="WORKBOOK-CONTRACT-004",
        )

    raw.setdefault("version", "")
    raw.setdefault("source", {})
    raw.setdefault("tables", [])

    tables = raw.get("tables")
    if not isinstance(tables, list):
        from workbench.exceptions import UserFacingError

        raise UserFacingError(
            "Schema contract 'tables' must be a YAML list",
            action="Ensure the 'tables' key in your contract contains a list of table mappings.",
            check_id="WORKBOOK-CONTRACT-005",
        )

    def _walk_table_entries(table_entries: list[Any]) -> list[dict[str, Any]]:
        """Flatten nested table-entry lists from ``!include`` expansion."""
        flattened: list[dict[str, Any]] = []
        for entry in table_entries:
            if isinstance(entry, list):
                flattened.extend(_walk_table_entries(entry))
                continue
            if not isinstance(entry, dict):
                from workbench.exceptions import UserFacingError

                entry_type_name = type(entry).__name__
                raise UserFacingError(
                    f"Schema contract table entries must be mappings (got {entry_type_name})",
                    action="Each entry in the 'tables' list must be a mapping (key-value pairs). Check for stray scalar or list entries.",
                    check_id="WORKBOOK-CONTRACT-006",
                )
            flattened.append(entry)
        return flattened

    raw["tables"] = _walk_table_entries(tables)

    return raw


def load_contract(path: str | Path) -> dict[str, Any]:
    """Load and strictly validate a contract YAML.

    Loads the contract via :func:`load_contract_unvalidated` and then runs
    :func:`strict_validate_contract`.  Raises ``UserFacingError`` if
    validation fails.

    Args:
        path: Filesystem path to a ``.yaml`` / ``.yml`` file.

    Returns:
        Normalised contract dict with ``"version"``, ``"source"``, and
        ``"tables"`` keys guaranteed present.
    """
    contract = load_contract_unvalidated(path)
    # Lazy import to avoid circular dep: workbook.codegen.contract →
    # workbook.contract.loading → workbook.codegen.contract
    from workbook.codegen.contract import strict_validate_contract  # noqa: PLC0415
    from workbench.exceptions import UserFacingError  # noqa: PLC0415

    results = strict_validate_contract(contract)
    if results:
        lines = [f"  {r.check_id}: {r.message}" for r in results]
        if any(r.action for r in results):
            lines.append("Suggested actions:")
            for r in results:
                if r.action:
                    lines.append(f"  - {r.action}")
        raise UserFacingError(
            "Contract validation failed:\n" + "\n".join(lines),
            action="Fix the reported issues in the contract and re-run.",
            check_id="WORKBOOK-CONTRACT-007",
        )
    return contract
