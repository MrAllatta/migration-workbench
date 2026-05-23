"""Validate a schema-contract YAML without generating code.

Usage:
    python manage.py validate_contract --contract build/schema-contract.yaml

Exits 0 when clean, 1 when warnings exist.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from workbook.codegen.contract import (
    load_contract_unvalidated,
    strict_validate_contract,
    validate_contract_tables,
)
from workbook.codegen.validation_pipeline import ValidationResult


class Command(BaseCommand):
    help = "Validate a schema-contract YAML without generating code."

    def add_arguments(self, parser):
        """Add --contract and --dump-json arguments."""
        parser.add_argument(
            "--contract",
            required=True,
            help="Path to schema-contract YAML (e.g. build/schema-contract.yaml)",
        )
        parser.add_argument(
            "--dump-json",
            action="store_true",
            help="Output structured JSON with check_id and action fields",
        )

    @staticmethod
    def _result_to_dict(r: ValidationResult) -> dict:
        return {
            "model_name": r.model_name,
            "check_id": r.check_id,
            "severity": r.severity,
            "message": r.message,
            "action": r.action,
        }

    def handle(self, *args, **options):
        """Load and validate a schema contract, writing warnings to stdout."""
        contract_path = Path(options["contract"])
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")

        try:
            contract = load_contract_unvalidated(str(contract_path))
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        results = strict_validate_contract(contract)

        global_errors = [
            r for r in results if r.model_name is None and r.severity == "error"
        ]
        if global_errors:
            from workbench.exceptions import UserFacingError

            lines = [f"  {r.check_id}: {r.message}" for r in global_errors]
            raise CommandError(
                "Contract has structural errors that cannot be skipped:\n"
                + "\n".join(lines)
            ) from UserFacingError(
                "Contract has structural errors",
                action="Fix the contract structure and re-run",
                check_id="WORKBOOK-CONTRACT-GLOBAL",
            )

        table_warnings = validate_contract_tables(contract)

        errors = [r for r in results if r.severity == "error"]

        if options["dump_json"]:
            payload = {
                "ok": len(errors) == 0,
                "errors": [self._result_to_dict(r) for r in results],
            }
            self.stdout.write(json.dumps(payload, indent=2))
            if errors:
                raise CommandError(
                    f"{len(errors)} validation error(s) found"
                )
            return

        for r in results:
            if r.severity == "error":
                self.stdout.write(
                    self.style.ERROR(f"  {r.check_id}: {r.message}")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"  {r.check_id}: {r.message}")
                )

        for w in table_warnings:
            self.stdout.write(self.style.WARNING(f"  {w}"))

        if errors:
            raise CommandError(
                f"{len(errors)} validation error(s) found"
            )

        if table_warnings:
            raise CommandError(
                f"{len(table_warnings)} validation warning(s) found"
            )

        count = len(contract.get("tables", []))
        self.stdout.write(
            self.style.SUCCESS(f"Contract is valid: {count} table(s)")
        )