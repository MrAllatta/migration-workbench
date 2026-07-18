"""Contract validation: table exception, structural, and strict checks.

Extracted from ``workbook/codegen/contract.py`` as part of e04
(contract-layer-split).

Owns:
- ``_validate_table_exceptions`` — per-table exception block checks
- ``validate_contract_tables`` — cross-table FK and config validation
- ``strict_validate_contract`` — field name, model name, and
  duplicate-detection checks
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from workbook.contract.accessors import get_fields, get_import_config, get_model_name

if TYPE_CHECKING:
    from workbook.codegen.validation_pipeline import ValidationResult



def _validate_table_exceptions(table: dict[str, Any]) -> list[str]:
    """Validate exception blocks on a single contract table.

    Checks that each exception has an ``id``, a ``condition``, a valid
    ``severity`` (one of ``warning``, ``error``, ``blocking``), and that
    every response entry has an ``action``.

    Returns:
        List of human-readable warning strings (empty when no issues).
    """
    warnings: list[str] = []
    name = table.get("model_name") or table.get("source_tab", "?")
    valid_severities = {"warning", "error", "blocking"}

    for exception in table.get("exceptions") or []:
        exc_id = exception.get("id", "")
        if not exc_id:
            warnings.append(f"{name}: exception missing id")
            continue
        if not exception.get("condition"):
            warnings.append(f"{name}: exception {exc_id} missing condition")
        severity = exception.get("severity", "")
        if severity and severity not in valid_severities:
            warnings.append(
                f"{name}: exception {exc_id} has invalid severity '{severity}'"
            )
        for response in exception.get("responses") or []:
            if not response.get("action"):
                warnings.append(f"{name}: exception {exc_id} response missing action")
    return warnings


def validate_contract_tables(
    contract: dict[str, Any],
) -> list[str]:
    """Run validation checks on a schema contract and return warning messages.

    Checks:
    - ``model_name`` is present on every table
    - FK target models exist in the contract table list
    - ``import_config.fk_lookup`` field references resolve to actual fields
    - ``import_config.unique_on`` fields have no duplicates

    Returns:
        List of human-readable warning strings (empty when no issues).
    """
    warnings: list[str] = []
    tables = list(contract.get("tables") or [])

    for table in tables:
        if "model_name" not in table:
            warnings.append(
                f"Table '{table.get('suggested_model_name', '?')}' "
                f"missing required 'model_name'"
            )
            continue

    table_names = {get_model_name(t) for t in tables if "model_name" in t}

    for table in tables:
        if "model_name" not in table:
            continue
        name = get_model_name(table)
        fields = get_fields(table)
        field_names = {f["name"] for f in fields}

        for field in fields:
            if field["class"] != "models.ForeignKey":
                continue
            fk_to = field["kwargs"].get("to")
            if fk_to and fk_to not in table_names and fk_to != "self":
                warnings.append(
                    f'{name}.{field["name"]}: FK target "{fk_to}" '
                    f"is not a table in the contract"
                )

        import_cfg = get_import_config(table)
        if import_cfg:
            fk_lookup = import_cfg.get("fk_lookup") or {}
            for fk_field, fk_cfg in fk_lookup.items():
                if fk_field not in field_names:
                    warnings.append(
                        f"{name}.import_config.fk_lookup.{fk_field}: "
                        f"references a field not in the model"
                    )
                target = fk_cfg.get("model")
                if target and target not in table_names:
                    warnings.append(
                        f"{name}.import_config.fk_lookup.{fk_field}: "
                        f'FK target "{target}" is not a table in the contract'
                    )

            unique_on = import_cfg.get("unique_on") or []
            seen: set[str] = set()
            for f in unique_on:
                if f in seen:
                    warnings.append(
                        f'{name}.import_config.unique_on: "{f}" appears more than once'
                    )
                seen.add(f)

        # Validate exception blocks
        exception_warnings = _validate_table_exceptions(table)
        warnings.extend(exception_warnings)

    return warnings


def strict_validate_contract(contract: dict[str, Any]) -> list[ValidationResult]:
    """Run strict validation checks and return structured results.

    Checks:
    - No model_name is null or empty.
    - Every suggested_field_name is a valid Python identifier and not a keyword.
    - No duplicate model_name values exist across tables.
    - No suggested_field_name starts with a digit.
    """
    import keyword
    from workbook.codegen.validation_pipeline import ValidationResult  # noqa: PLC0415

    results: list[ValidationResult] = []
    tables = list(contract.get("tables") or [])
    model_names: list[str] = []

    for table in tables:
        model_name = str(table.get("model_name", "")).strip()
        if not model_name:
            label = table.get("suggested_model_name") or table.get(
                "bundle_worksheet_title", "?"
            )
            results.append(
                ValidationResult(
                    model_name=model_name or "_UNNAMED",
                    check_id="WORKBOOK-CONTRACT-NULL-MODEL",
                    message=f"Table '{label}' has empty model_name",
                    action="Set a unique model_name or add suggested_model_name to the contract",
                )
            )
            continue
        model_names.append(model_name)

    seen_model_names: set[str] = set()
    for mn in model_names:
        if mn in seen_model_names:
            results.append(
                ValidationResult(
                    model_name=mn,
                    check_id="WORKBOOK-CONTRACT-DUPLICATE-MODEL",
                    message=f'Duplicate model_name "{mn}" (2+ tables)',
                    action="Rename one of the duplicate tables or merge them",
                )
            )
        seen_model_names.add(mn)

    for table in tables:
        model_name = str(table.get("model_name", "")).strip()
        for col in table.get("columns", []):
            field_name = col.get("suggested_field_name", "")
            if not field_name:
                continue
            if not str(field_name).isidentifier() or keyword.iskeyword(str(field_name)):
                results.append(
                    ValidationResult(
                        model_name=model_name or None,
                        check_id="WORKBOOK-CONTRACT-INVALID-FIELD-NAME",
                        message=f'Field "{field_name}" in model "{model_name}" is not a valid Python identifier',
                        action="Rename the source column in the contract",
                    )
                )
            elif str(field_name)[0].isdigit():
                results.append(
                    ValidationResult(
                        model_name=model_name or None,
                        check_id="WORKBOOK-CONTRACT-INVALID-FIELD-NAME",
                        message=f'Field "{field_name}" in model "{model_name}" starts with a digit',
                        action="Rename the source column in the contract",
                    )
                )

    return results
