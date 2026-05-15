"""Emit a Django ``models.py`` from a schema-contract YAML (v1.0–1.3).

Reads a schema-contract YAML produced by ``scaffold_workbook_schema``
(possibly hardened by hand with v1.1–1.3 extensions) and writes a complete
``models.py`` with resolved foreign keys, ``class Meta``, ``__str__``
methods, computed properties, and hand-authored extra fields.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from workbook.codegen.contract import load_contract, validate_contract_tables
from workbook.codegen.model_generator import render_models_py


class Command(BaseCommand):
    help = "Generate a Django models.py from a schema-contract YAML (v1.0–1.3)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--contract",
            required=True,
            help="Path to schema-contract YAML (e.g. build/schema-contract.yaml)",
        )
        parser.add_argument(
            "--out",
            required=True,
            help="Output path for models.py (use /dev/null for smoke-only)",
        )
        parser.add_argument(
            "--app-label",
            default="core",
            help="Django app label for Meta.db_table and import messages (default: core)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite output file without prompting",
        )
        parser.add_argument(
            "--diff",
            action="store_true",
            help="Show diff against current output instead of overwriting",
        )

    def handle(self, *args, **options):
        contract_path = Path(options["contract"]).resolve()
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")

        out_path = Path(options["out"]).resolve()
        app_label = options["app_label"]
        force = options["force"]
        show_diff = options["diff"]

        try:
            contract = load_contract(str(contract_path))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        warnings = validate_contract_tables(contract)
        for w in warnings:
            self.stdout.write(self.style.WARNING(f"validation: {w}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"loaded contract v{contract['version']} "
                f"({len(contract.get('tables') or [])} table(s))"
            )
        )

        source = render_models_py(contract, app_label=app_label)

        if show_diff:
            if out_path.exists():
                current = out_path.read_text(encoding="utf-8")
                diff = difflib.unified_diff(
                    current.splitlines(keepends=True),
                    source.splitlines(keepends=True),
                    fromfile=str(out_path),
                    tofile="<generated>",
                )
                diff_text = "".join(diff)
                if diff_text:
                    self.stdout.write(diff_text)
                else:
                    self.stdout.write(self.style.SUCCESS("no changes"))
            else:
                self.stdout.write(self.style.WARNING(f"no existing file: {out_path}"))
            return

        if out_path.exists() and not force:
            self.stdout.write(self.style.WARNING(f"output exists: {out_path}"))
            self.stdout.write("use --force to overwrite")
            sys.exit(1)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(source, encoding="utf-8")

        model_count = len(contract.get("tables") or [])
        line_count = source.count("\n")
        self.stdout.write(
            self.style.SUCCESS(
                f"wrote {out_path}  ({model_count} model(s), {line_count} lines)"
            )
        )
