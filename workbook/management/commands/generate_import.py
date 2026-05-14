"""Emit a Django import management command from a schema-contract YAML (v1.1).

Reads a schema-contract YAML (v1.0 or v1.1) and writes a complete
``BaseImportCommand`` subclass that imports data from normalized bundle
CSVs.  Only tables with an ``import_config`` block in the contract are
emitted; the command reads the bundle via ``read_bundle_tab``, resolves
foreign keys, and tracks statistics.
"""

from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from workbook.codegen.contract import load_contract, validate_contract_tables
from workbook.codegen.import_generator import render_import_py


class Command(BaseCommand):
    help = (
        "Generate a Django import management command from a schema-contract "
        "YAML (v1.1 with import_config blocks)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--contract",
            required=True,
            help="Path to schema-contract YAML (e.g. build/schema-contract.yaml)",
        )
        parser.add_argument(
            "--out",
            required=True,
            help="Output path for the import command (e.g. backend/apps/core/management/commands/import_data.py)",
        )
        parser.add_argument(
            "--app-label",
            default="core",
            help="Django app label for model imports (default: core)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite output file without prompting",
        )

    def handle(self, *args, **options):
        contract_path = Path(options["contract"]).resolve()
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")

        out_path = Path(options["out"]).resolve()
        app_label = options["app_label"]
        force = options["force"]

        try:
            contract = load_contract(str(contract_path))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        warnings = validate_contract_tables(contract)
        for w in warnings:
            self.stdout.write(self.style.WARNING(f"validation: {w}"))

        tables_with_import = [
            t for t in (contract.get("tables") or [])
            if t.get("import_config")
        ]
        self.stdout.write(
            self.style.SUCCESS(
                f"loaded contract v{contract['version']} "
                f"({len(tables_with_import)} table(s) with import_config)"
            )
        )

        source = render_import_py(contract, app_label=app_label)

        if out_path.exists() and not force:
            self.stdout.write(self.style.WARNING(f"output exists: {out_path}"))
            self.stdout.write("use --force to overwrite")
            sys.exit(1)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(source, encoding="utf-8")

        line_count = source.count("\n")
        self.stdout.write(
            self.style.SUCCESS(
                f"wrote {out_path}  ({line_count} lines)"
            )
        )
