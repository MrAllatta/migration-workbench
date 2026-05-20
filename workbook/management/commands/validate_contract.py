"""Validate a schema-contract YAML without generating code.

Usage:
    python manage.py validate_contract --contract build/schema-contract.yaml

Exits 0 when clean, 1 when warnings exist.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from workbook.codegen.contract import load_contract, validate_contract_tables


class Command(BaseCommand):
    help = "Validate a schema-contract YAML without generating code."

    def add_arguments(self, parser):
        """Add --contract argument."""
        parser.add_argument(
            "--contract",
            required=True,
            help="Path to schema-contract YAML (e.g. build/schema-contract.yaml)",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Enable strict mode: enforce valid Python identifiers and no duplicate model names",
        )

    def handle(self, *args, **options):
        """Load and validate a schema contract, writing warnings to stdout."""
        contract_path = Path(options["contract"])
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")

        try:
            contract = load_contract(str(contract_path))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        warnings = validate_contract_tables(contract)

        if options["strict"]:
            from workbook.codegen.contract import strict_validate_contract
            strict_errors = strict_validate_contract(contract)
            for err in strict_errors:
                self.stdout.write(self.style.ERROR(err))
            if strict_errors:
                raise CommandError(f"Strict validation failed with {len(strict_errors)} error(s).")

        if not warnings:
            count = len(contract.get("tables", []))
            self.stdout.write(
                self.style.SUCCESS(f"Contract is valid: {count} table(s)")
            )
            return

        for w in warnings:
            self.stdout.write(self.style.WARNING(f"  {w}"))

        raise CommandError(f"{len(warnings)} validation warning(s) found")
