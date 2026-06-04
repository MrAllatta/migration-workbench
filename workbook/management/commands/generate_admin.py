"""Emit a Django ``admin.py`` from a schema-contract YAML + optional view manifest.

Reads a schema-contract YAML (v1.0–1.3) and an optional view-manifest
YAML and writes a complete ``admin.py`` with ``ModelAdmin`` registrations,
``TabularInline`` classes for reverse FK relationships, and inferred
``list_display``, ``list_filter``, ``search_fields``,
``readonly_fields``, ``list_editable``, and ``autocomplete_fields``
from contract admin config and manifest hints.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError

from workbook.codegen.admin_generator import render_admin_py
from workbook.codegen.contract import (
    load_contract_unvalidated,
    strict_validate_contract,
    validate_contract_tables,
)
from workbook.codegen.manifest import load_manifest
from workbook.codegen.validation_pipeline import (
    GlobalValidationError,
    partition_contract_on_validation,
)


class Command(BaseCommand):
    help = (
        "Generate a Django admin.py from schema-contract YAML + optional view manifest."
    )

    def add_arguments(self, parser):
        """Add --contract, --manifest, --out, --app-label, --force, --diff arguments."""
        parser.add_argument(
            "--contract",
            required=True,
            help="Path to schema-contract YAML (e.g. build/schema-contract.yaml)",
        )
        parser.add_argument(
            "--manifest",
            default=None,
            help="Optional path to view-manifest YAML (e.g. build/view-manifest.yaml)",
        )
        parser.add_argument(
            "--out",
            default=None,
            help="Output path for admin_auto.py (default: <app_dir>/admin_auto.py when --app-label resolves)",
        )
        parser.add_argument(
            "--app-label",
            default=None,
            help="Django app label for model imports (default: auto-detect from contract, fallback 'core')",
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
            "--codegen-manifest",
            default=None,
            help="Optional path to codegen-manifest YAML (Layer 3, enriches admin with archetype-based hints)",
        )

    def handle(self, *args, **options):
        """Load contract and manifest, render admin.py, and write to disk."""
        contract_path = Path(options["contract"]).resolve()
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")

        manifest = None
        if options.get("manifest"):
            manifest_path = Path(options["manifest"]).resolve()
            if not manifest_path.is_file():
                raise CommandError(f"manifest not found: {manifest_path}")
            try:
                manifest = load_manifest(str(manifest_path))
            except ValueError as exc:
                raise CommandError(str(exc)) from exc

        codegen_manifest = None
        if options.get("codegen_manifest"):
            cg_path = Path(options["codegen_manifest"]).resolve()
            if not cg_path.is_file():
                raise CommandError(f"codegen-manifest not found: {cg_path}")
            try:
                import yaml  # type: ignore[import-untyped]
                codegen_manifest = yaml.safe_load(
                    cg_path.read_text(encoding="utf-8")
                )
                if not isinstance(codegen_manifest, dict):
                    raise CommandError(
                        f"codegen-manifest is not a YAML mapping: {cg_path}"
                    )
            except yaml.YAMLError as exc:
                raise CommandError(f"codegen-manifest YAML error: {exc}") from exc

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
            out_path = app_dir / "admin_auto.py"
            stub_path = app_dir / "admin.py"
        force = options["force"]
        show_diff = options["diff"]

        results = strict_validate_contract(contract)
        try:
            clean_contract, rejection_collector = partition_contract_on_validation(
                contract,
                results,
                out_path=out_path,
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
        if manifest:
            views = len(manifest.get("views") or [])
            self.stdout.write(self.style.SUCCESS(f"loaded manifest ({views} view(s))"))

        source = render_admin_py(
            clean_contract,
            manifest=manifest,
            app_label=app_label,
            codegen_manifest=codegen_manifest,
        )

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
        if force and out_path.exists():
            current = out_path.read_text(encoding="utf-8")
            if current != source:
                diff = difflib.unified_diff(
                    current.splitlines(keepends=True),
                    source.splitlines(keepends=True),
                    fromfile=str(out_path),
                    tofile="<generated>",
                )
                diff_text = "".join(diff)
                if diff_text:
                    self.stdout.write(
                        self.style.WARNING(
                            f"regenerating {out_path} — changes detected:"
                        )
                    )
                    self.stdout.write(diff_text)
        out_path.write_text(source, encoding="utf-8")

        if stub_path:
            from workbook.codegen.stub_writer import ensure_stub

            ensure_stub(stub_path, "admin_auto")

        line_count = source.count("\n")
        self.stdout.write(self.style.SUCCESS(f"wrote {out_path}  ({line_count} lines)"))
