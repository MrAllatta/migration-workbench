"""Emit a view-manifest YAML from a Slice A ``structure.json`` (and optional schema contract)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from workbook.schema_contract import load_json
from workbook.view_manifest import VIEW_MANIFEST_VERSION, build_view_manifest


def _load_yaml(path: Path) -> Any:
    """Read and parse a UTF-8 YAML file via PyYAML."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise CommandError(
            "PyYAML is required to read schema-contract YAML."
        ) from exc
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class Command(BaseCommand):
    help = (
        "Build a first-draft view-manifest YAML from a structure.json "
        "(produced by `pull_bundle --include-structure`) and an optional "
        "schema-contract YAML for entity binding."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--structure",
            required=True,
            help="Path to structure.json from pull_bundle --include-structure",
        )
        parser.add_argument(
            "--schema-contract",
            default=None,
            help="Optional schema-contract YAML for entity binding",
        )
        parser.add_argument(
            "--out",
            required=True,
            help="Output view-manifest path (.yaml or .yml)",
        )
        parser.add_argument(
            "--summary-json",
            default=None,
            help="Optional companion JSON with manifest counts for gate assertions",
        )

    def handle(self, *args, **options):
        structure_path = Path(options["structure"]).resolve()
        if not structure_path.is_file():
            raise CommandError(f"structure not found: {structure_path}")
        structure = load_json(structure_path)

        schema_contract: dict[str, Any] | None = None
        contract_arg = options.get("schema_contract")
        if contract_arg:
            contract_path = Path(contract_arg).resolve()
            if not contract_path.is_file():
                raise CommandError(f"schema-contract not found: {contract_path}")
            schema_contract = _load_yaml(contract_path)

        manifest = build_view_manifest(
            structure,
            schema_contract=schema_contract,
        )

        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CommandError(
                "PyYAML is required for YAML output. Install migration-workbench with dependencies."
            ) from exc

        out_path = Path(options["out"]).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(
            manifest,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        out_path.write_text(text, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"wrote {out_path}"))

        summary_arg = options.get("summary_json")
        if summary_arg:
            summary_path = Path(summary_arg).resolve()
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            views = manifest.get("views") or []
            tabs = list((structure.get("tabs") or []))
            summary = {
                "version": VIEW_MANIFEST_VERSION,
                "view_count": len(views),
                "entities_bound": sum(1 for v in views if v.get("entity")),
                "status_fields_inferred": sum(1 for v in views if v.get("status_field")),
                "tabs_hidden_skipped": sum(1 for t in tabs if t.get("hidden")),
            }
            summary_path.write_text(
                json.dumps(summary, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            self.stdout.write(self.style.SUCCESS(f"wrote {summary_path}"))
