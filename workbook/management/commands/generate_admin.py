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
from workbook.codegen.contract import load_contract, validate_contract_tables
from workbook.codegen.manifest import load_manifest


class Command(BaseCommand):
    help = "Generate a Django admin.py from schema-contract YAML + optional view manifest."

    def add_arguments(self, parser):
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
            required=True,
            help="Output path for admin.py (use /dev/null for smoke-only)",
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
        parser.add_argument(
            "--diff",
            action="store_true",
            help="Show diff against current output instead of overwriting",
        )

    def handle(self, *args, **options):
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
        if manifest:
            views = len(manifest.get("views") or [])
            self.stdout.write(
                self.style.SUCCESS(f"loaded manifest ({views} view(s))")
            )

        source = render_admin_py(contract, manifest=manifest, app_label=app_label)

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
            if str(out_path) != "/dev/null":
                out_path.rename(str(out_path) + ".bak")
        out_path.write_text(source, encoding="utf-8")

        line_count = source.count("\n")
        self.stdout.write(
            self.style.SUCCESS(
                f"wrote {out_path}  ({line_count} lines)"
            )
        )
