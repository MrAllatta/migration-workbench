"""Generate a pipeline manifest YAML from contract + corpus config.

The pipeline manifest is a machine-generated, disposable artifact that bridges
profile artifacts and the schema contract to pull/import commands. It should
never be hand-edited; regenerate it after any contract or corpus config change.
"""

from __future__ import annotations

import difflib
import json
import sys
import yaml
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from workbook.codegen.contract import load_contract
from workbook.pipeline_manifest import build_pipeline_manifest


class Command(BaseCommand):
    help = "Generate a pipeline manifest YAML from contract + corpus config."

    def add_arguments(self, parser):
        parser.add_argument(
            "--contract",
            required=True,
            help="Path to schema-contract YAML",
        )
        parser.add_argument(
            "--corpus-config",
            required=True,
            help="Path to cohort_corpus JSON config",
        )
        parser.add_argument(
            "--corpus-dir",
            default=None,
            help="Path to directory with in_scope_workbook_index_*.json files",
        )
        parser.add_argument(
            "--out",
            required=True,
            help="Output path for pipeline_manifest.yaml",
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

        corpus_config_path = Path(options["corpus_config"]).resolve()
        if not corpus_config_path.is_file():
            raise CommandError(f"corpus_config not found: {corpus_config_path}")

        contract = load_contract(str(contract_path))
        try:
            corpus_config = json.loads(corpus_config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"invalid JSON in {corpus_config_path}: {exc}") from exc
        corpus_dir = options.get("corpus_dir")

        manifest = build_pipeline_manifest(
            contract, corpus_config, corpus_dir=corpus_dir
        )

        out_path = Path(options["out"]).resolve()
        force = options["force"]
        show_diff = options["diff"]

        text = yaml.safe_dump(
            manifest,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

        if show_diff:
            if out_path.exists():
                current = out_path.read_text(encoding="utf-8")
                diff = difflib.unified_diff(
                    current.splitlines(keepends=True),
                    text.splitlines(keepends=True),
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
            if current != text:
                diff = difflib.unified_diff(
                    current.splitlines(keepends=True),
                    text.splitlines(keepends=True),
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
        out_path.write_text(text, encoding="utf-8")

        table_count = len(manifest.get("tables") or [])
        self.stdout.write(
            self.style.SUCCESS(f"wrote {out_path}  ({table_count} table(s))")
        )
