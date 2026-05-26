from __future__ import annotations

import copy

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from workbench.exceptions import UserFacingError
from workbook.partial_output import PartialOutputCollector


_VALID_SEVERITIES = frozenset({"error", "warning"})


@dataclass(frozen=True)
class ValidationResult:
    """A single validation finding against a contract table.

    Attributes:
        model_name: The contract table model_name that triggered the finding,
            or None for global-level errors that are not table-specific.
        check_id: Stable machine-readable identifier, e.g. ``WORKBOOK-CONTRACT-001``.
        message: Human-readable description of the problem.
        action: Concrete instruction the operator can follow to fix it.
        severity: ``error`` or ``warning``. Only ``error`` severity causes a table
            to be dropped during partition. Global errors (model_name=None)
            always cause hard failure regardless of ``--continue-on-error``.
    """

    model_name: str | None
    check_id: str
    message: str
    action: str | None = None
    severity: Literal["error", "warning"] = "error"

    def __post_init__(self) -> None:
        if self.severity not in _VALID_SEVERITIES:
            raise TypeError(
                f"severity must be one of {_VALID_SEVERITIES}, got {self.severity!r}"
            )


class GlobalValidationError(UserFacingError):
    """Raised when a ValidationResult has model_name=None (global scope).

    These errors are not table-specific and always cause hard failure,
    even with ``--continue-on-error``.
    """


def partition_contract_on_validation(
    contract: dict[str, Any],
    results: list[ValidationResult],
    *,
    out_path: Path,
) -> tuple[dict[str, Any], PartialOutputCollector]:
    """Drop tables with error-level results and write rejections.

    Args:
        contract: The loaded (unvalidated) contract dict.
        results: Validation results (list of ``ValidationResult``, from
            ``strict_validate_contract`` after its return-type refactor).
        out_path: Path the *successful* output will be written to. Used to derive
            the rejection file name so parallel/sequential commands do not collide.

    Returns:
        A tuple of (clean_contract, collector). The clean_contract is a deep
        copy with only valid tables retained. The collector contains rejections
        for every dropped table.

    Raises:
        GlobalValidationError: If any result has ``model_name=None`` and
            ``severity="error"``. These are structural problems (e.g. missing
            ``tables`` key) that cannot be recovered from by dropping a single table.
    """
    global_errors = [
        r for r in results if r.model_name is None and r.severity == "error"
    ]
    if global_errors:
        lines = [f"  {r.check_id}: {r.message}" for r in global_errors]
        raise GlobalValidationError(
            "Contract has structural errors that cannot be skipped:\n"
            + "\n".join(lines),
            check_id="WORKBOOK-CONTRACT-GLOBAL",
            action="Fix the contract structure and re-run",
        )

    error_model_names: set[str] = set()
    for r in results:
        if r.model_name is not None and r.severity == "error":
            error_model_names.add(r.model_name)

    original_tables = list(contract.get("tables") or [])
    clean_tables = [
        t for t in original_tables if t.get("model_name") not in error_model_names
    ]

    clean_contract = copy.deepcopy(contract)
    clean_contract["tables"] = clean_tables

    table_by_model_name: dict[str, dict[str, Any]] = {}
    for t in original_tables:
        mn = t.get("model_name")
        if mn:
            table_by_model_name[mn] = t

    collector = PartialOutputCollector()
    for model_name in sorted(error_model_names):
        table = table_by_model_name.get(model_name, {"model_name": model_name})
        first_result = next(
            r for r in results if r.model_name == model_name and r.severity == "error"
        )
        collector.add(
            table,
            check_id=first_result.check_id,
            message=first_result.message,
            action=first_result.action,
        )

    if not collector.is_empty():
        rejection_path = out_path.parent / (out_path.stem + "-rejected.yaml")
        collector.write_rejection_file(rejection_path)

    return clean_contract, collector
