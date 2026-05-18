"""Emit a Django import management command from a schema-contract YAML (v1.1).

Reads a schema-contract YAML (v1.0 or v1.1) and writes a complete
``BaseImportCommand`` subclass that imports data from normalized bundle
CSVs.  Only tables with an ``import_config`` block in the contract are
emitted; the command reads the bundle via ``read_bundle_tab``, resolves
foreign keys, and tracks statistics.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from workbook.codegen.contract import load_contract, validate_contract_tables
from workbook.codegen.import_generator import render_import_py


def _render_diff(source: str, current_path: Path) -> tuple[str, bool]:
    """Compute a unified diff between *source* and the file at *current_path*.

    Returns:
        Tuple of ``(diff_text, has_changes)``. ``diff_text`` is the unified
        diff string (empty string when files are identical or *current_path*
        does not exist). ``has_changes`` is ``True`` when the diff is non-empty.
    """
    if not current_path.exists():
        return ("", False)
    current = current_path.read_text(encoding="utf-8")
    diff = difflib.unified_diff(
        current.splitlines(keepends=True),
        source.splitlines(keepends=True),
        fromfile=str(current_path),
        tofile="<generated>",
    )
    diff_text = "".join(diff)
    return (diff_text, bool(diff_text))


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
            default=None,
            help="Output path for the import command. When omitted, auto-derived from --app-label into <app>/management/commands/import_<label>.py",
        )
        parser.add_argument(
            "--app-label",
            default=None,
            help="Django app label for model imports (default: read from contract, fallback 'core')",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite output file without prompting",
        )
        parser.add_argument(
            "--diff",
            action="store_true",
            help="Show diff against current output instead of overwriting (ignores --force)",
        )

    def handle(self, *args, **options):
        contract_path = Path(options["contract"]).resolve()
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")

        try:
            contract = load_contract(str(contract_path))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

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
        if out_path is None:
            from pathlib import Path as _Path
            app_dir = _Path.cwd() / "backend" / "apps" / app_label
            mgmt_dir = app_dir / "management" / "commands"
            mgmt_dir.mkdir(parents=True, exist_ok=True)
            (app_dir / "management" / "__init__.py").touch()
            (mgmt_dir / "__init__.py").touch()
            out_path = str(mgmt_dir / f"import_{app_label}.py")
        out_path = Path(out_path).resolve()
        force = options["force"]
        show_diff = options["diff"]

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

        try:
            source = render_import_py(contract, app_label=app_label)
        except ValueError as exc:
            if "bundle_path" in str(exc):
                raise CommandError(
                    "Import generation failed — bundle_path is missing.\n\n"
                    "Each table with import_config needs a bundle_path:\n"
                    "  import_config:\n"
                    "    bundle_path: reference/<table_name>.csv\n\n"
                    "Re-generate the contract from the scaffold, which now\n"
                    "auto-generates bundle_path from the model name."
                )
            raise

        if show_diff:
            diff_text, has_changes = _render_diff(source, out_path)
            if has_changes:
                self.stdout.write(diff_text)
            elif out_path.exists():
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
            diff_text, has_changes = _render_diff(source, out_path)
            if has_changes:
                self.stdout.write(
                    self.style.WARNING(
                        f"regenerating {out_path} — changes detected:"
                    )
                )
                self.stdout.write(diff_text)
        out_path.write_text(source, encoding="utf-8")

        line_count = source.count("\n")
        self.stdout.write(
            self.style.SUCCESS(
                f"wrote {out_path}  ({line_count} lines)"
            )
        )
