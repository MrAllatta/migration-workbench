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

from workbook.codegen.contract import (
    load_contract_unvalidated,
    strict_validate_contract,
    validate_contract_tables,
)
from workbook.codegen.model_generator import render_models_py
from workbook.codegen.validation_pipeline import (
    GlobalValidationError,
    partition_contract_on_validation,
)


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
            default=None,
            help="Output path for models_auto.py (default: <app_dir>/models_auto.py when --app-label resolves)",
        )
        parser.add_argument(
            "--app-label",
            default=None,
            help="Django app label for Meta.db_table and import messages (default: read from contract, fallback 'core')",
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
        parser.add_argument(
            "--continue-on-error",
            action="store_true",
            default=False,
            help="Skip invalid tables and generate models for valid ones",
        )

    def handle(self, *args, **options):
        contract_path = Path(options["contract"]).resolve()
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")

        force = options["force"]
        show_diff = options["diff"]

        contract = load_contract_unvalidated(str(contract_path))

        app_label = options["app_label"]
        if app_label is None:
            for table in contract.get("tables", []):
                meta = table.get("model_meta") or {}
                if meta.get("app_label"):
                    app_label = meta["app_label"]
                    break
        if app_label is None:
            app_label = "core"

        out_path = options.get("out")
        if out_path is not None:
            out_path = Path(out_path).resolve()
            stub_path = None
        else:
            app_dir = Path.cwd() / "backend" / "apps" / app_label
            out_path = app_dir / "models_auto.py"
            stub_path = app_dir / "models.py"

        results = strict_validate_contract(contract)
        try:
            clean_contract, rejection_collector = partition_contract_on_validation(
                contract, results, out_path=out_path,
            )
        except GlobalValidationError as exc:
            raise CommandError(str(exc)) from exc

        if options["app_label"] is not None:
            for table in clean_contract.get("tables", []):
                if "model_meta" not in table:
                    table["model_meta"] = {}
                table["model_meta"]["app_label"] = app_label

        warnings = validate_contract_tables(clean_contract)
        for w in warnings:
            self.stdout.write(self.style.WARNING(f"validation: {w}"))

        version = clean_contract.get("version", "1.0") if clean_contract else "1.0"
        self.stdout.write(
            self.style.SUCCESS(
                f"loaded contract v{version} "
                f"({len(clean_contract.get('tables') or [])} table(s))"
            )
        )

        source, warnings = render_models_py(clean_contract, app_label=app_label)
        for w in warnings:
            self.stdout.write(self.style.WARNING(w))

        if not rejection_collector.is_empty():
            self.stderr.write(self.style.WARNING(rejection_collector.summary()))

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

        if stub_path:
            from workbook.codegen.stub_writer import ensure_stub

            ensure_stub(stub_path, "models_auto")

        model_count = len(clean_contract.get("tables") or [])
        line_count = source.count("\n")
        self.stdout.write(
            self.style.SUCCESS(
                f"wrote {out_path}  ({model_count} model(s), {line_count} lines)"
            )
        )