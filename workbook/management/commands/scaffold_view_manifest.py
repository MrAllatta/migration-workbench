"""Emit a view-manifest YAML from a profiler ``structure.json`` (and optional schema contract).
When ``--signals-only`` is set, emit a profiler-signals YAML instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from workbook.schema_contract import load_json
from workbook.tools.signal_extraction import extract_signals
from workbook.view_manifest import VIEW_MANIFEST_VERSION, build_view_manifest


def _load_yaml(path: Path) -> Any:
    """Read and parse a UTF-8 YAML file via PyYAML."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise CommandError("PyYAML is required to read schema-contract YAML.") from exc
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_json(path: Path) -> Any:
    """Read and parse a UTF-8 JSON file."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CommandError(f"Invalid JSON in {path}: {exc}") from exc


class Command(BaseCommand):
    help = (
        "Build a first-draft view-manifest YAML from a structure.json "
        "(produced by `pull_bundle --include-structure`) and an optional "
        "schema-contract YAML for entity binding.  Use --signals-only to "
        "emit profiler signals YAML instead."
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
            default=None,
            help="Output view-manifest path (.yaml or .yml). "
            "Required unless --signals-only is set.",
        )
        parser.add_argument(
            "--summary-json",
            default=None,
            help="Optional companion JSON with manifest counts for gate assertions",
        )
        parser.add_argument(
            "--signals-only",
            action="store_true",
            default=False,
            help="Emit profiler-signals YAML instead of a view manifest. "
            "Use with --bundle-config and --output.",
        )
        parser.add_argument(
            "--bundle-config",
            default=None,
            help="Path to bundle-config JSON. "
            "Used in --signals-only mode to resolve workbook codes.",
        )
        parser.add_argument(
            "--output",
            default="build/profiler-signals.yaml",
            help="Output path for --signals-only YAML "
            "(default: build/profiler-signals.yaml).",
        )

    def handle(self, *args, **options):
        structure_path = Path(options["structure"]).resolve()
        if not structure_path.is_file():
            raise CommandError(f"structure not found: {structure_path}")
        structure = load_json(structure_path)

        if options.get("signals_only"):
            self._handle_signals_only(structure, options)
            return

        out_path_arg = options.get("out")
        if not out_path_arg:
            raise CommandError(
                "--out is required when --signals-only is not set."
            )

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

        out_path = Path(out_path_arg).resolve()
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
                "status_fields_inferred": sum(
                    1 for v in views if v.get("status_field")
                ),
                "tabs_hidden_skipped": sum(1 for t in tabs if t.get("hidden")),
            }
            summary_path.write_text(
                json.dumps(summary, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            self.stdout.write(self.style.SUCCESS(f"wrote {summary_path}"))

    def _handle_signals_only(
        self,
        structure: dict[str, Any],
        options: dict[str, Any],
    ) -> None:
        """Handle the ``--signals-only`` code path: extract and write signals YAML."""
        bundle_config: dict[str, Any] | None = None
        bundle_config_arg = options.get("bundle_config")
        if bundle_config_arg:
            bundle_config_path = Path(bundle_config_arg).resolve()
            if not bundle_config_path.is_file():
                raise CommandError(
                    f"bundle-config not found: {bundle_config_path}"
                )
            bundle_config = _load_json(bundle_config_path)

        signals = extract_signals(structure, bundle_config=bundle_config)

        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CommandError(
                "PyYAML is required for YAML output."
            ) from exc

        out_path = Path(options["output"]).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(
            signals,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        out_path.write_text(text, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"wrote profiler signals {out_path}"))
