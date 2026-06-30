"""Emit a view-manifest YAML from a profiler ``structure.json`` (and optional schema contract).
When ``--signals-only`` is set, emit a profiler-signals YAML instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from profiler.tools.pipeline_state import PipelineState
from workbook.schema_contract import load_json
from workbook.tools.signal_extraction import extract_signals
from workbook.view_manifest import (
    VIEW_MANIFEST_VERSION,
    build_view_manifest,
    validate_view_manifest,
)


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
        parser.add_argument(
            "--explain",
            action="store_true",
            default=False,
            help="Print human-readable archetype explanation for each tab "
            "(only in --signals-only mode).",
        )
        parser.add_argument(
            "--min-confidence",
            type=float,
            default=0.0,
            help="Only show explanations for tabs with confidence below this "
            "threshold (default: 0.0 = show all). Requires --explain.",
        )
        parser.add_argument(
            "--checkpoint",
            default=None,
            help="Path to a PipelineState checkpoint YAML. When provided, "
            "artifact provenance is recorded on the state and saved.",
        )

    def handle(self, *args, **options):
        # Validate argument combinations
        if options.get("min_confidence", 0.0) > 0.0 and not options.get("explain"):
            raise CommandError("--min-confidence requires --explain.")
        if options.get("explain") and not options.get("signals_only"):
            raise CommandError("--explain requires --signals-only.")

        structure_path = Path(options["structure"]).resolve()
        if not structure_path.is_file():
            raise CommandError(f"structure not found: {structure_path}")
        structure = load_json(structure_path)

        if options.get("signals_only"):
            self._handle_signals_only(structure, options)
            return

        out_path_arg = options.get("out")
        if not out_path_arg:
            raise CommandError("--out is required when --signals-only is not set.")

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

        validation_errors = validate_view_manifest(manifest)
        if validation_errors:
            self.stdout.write(self.style.WARNING("View manifest validation issues:"))
            for error in validation_errors:
                self.stdout.write(self.style.WARNING(f"  {error}"))

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

        # Record artifact provenance on PipelineState if checkpoint path provided
        checkpoint_arg = options.get("checkpoint")
        if checkpoint_arg:
            checkpoint_path = Path(checkpoint_arg).resolve()
            if checkpoint_path.exists():
                state = PipelineState.load(checkpoint_path)
            else:
                state = PipelineState()
            if hasattr(state, "record_artifact_provenance"):
                state.record_artifact_provenance(
                    artifact_key=f"view_manifest:{manifest.get('source', {}).get('source_id', 'unknown')}",
                    source="inferred",
                    signals=[{"views_count": len(manifest.get("views", []))}],
                )
                state.save_checkpoint(checkpoint_path)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"recorded provenance on checkpoint {checkpoint_path}"
                    )
                )

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
                raise CommandError(f"bundle-config not found: {bundle_config_path}")
            bundle_config = _load_json(bundle_config_path)

        signals = extract_signals(structure, bundle_config=bundle_config)

        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CommandError("PyYAML is required for YAML output.") from exc

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

        if options.get("explain"):
            self._print_explain_output(signals, options)

    def _print_explain_output(
        self,
        signals: dict[str, Any],
        options: dict[str, Any],
    ) -> None:
        """Print human-readable archetype explanations for each tab."""
        from workbook.tools.signal_extraction import explain_archetype

        min_confidence = float(options.get("min_confidence", 0.0))
        low_count = 0

        for tab_signal in signals.get("signals", []):
            tab_title = tab_signal.get("tab_title", "")
            confidence = float(tab_signal.get("confidence_score", 0.0))

            if min_confidence > 0 and confidence >= min_confidence:
                continue

            null_rates = tab_signal.get("null_rates", {})
            signal_dict = {
                "column_count": int(tab_signal.get("column_count", 0)),
                "formula_density": float(tab_signal.get("formula_density", 0.0)),
                "cross_sheet_ref_count": int(tab_signal.get("cross_sheet_refs", 0)),
                "avg_null_rate": (
                    sum(null_rates.values()) / max(len(null_rates), 1)
                    if null_rates
                    else float(tab_signal.get("avg_null_rate", 0.0))
                ),
                "has_status_column": float(tab_signal.get("has_status_column", False)),
                "has_time_scope": float(tab_signal.get("has_time_scope", False)),
                "data_validation_density": float(
                    tab_signal.get("data_validation_density", 0.0)
                ),
                "header_formula_count": int(tab_signal.get("header_formula_count", 0)),
                "header_entity_count": int(tab_signal.get("header_entity_count", 0)),
                "merged_cell_ratio": float(tab_signal.get("merged_cell_ratio", 0.0)),
                "row_count": int(tab_signal.get("row_count", 0)),
                "expansion_formula_ratio": float(
                    tab_signal.get("expansion_formula_ratio", 0.0)
                ),
            }

            label = tab_signal.get("ui_archetype", "")
            archetype_scores = tab_signal.get("archetype_scores", {})

            explanation = explain_archetype(
                tab_title,
                signals_dict=signal_dict,
                label=label,
                confidence=confidence,
                archetype_scores=archetype_scores,
            )
            self.stdout.write("")
            self.stdout.write(explanation)
            self.stdout.write("---")

            if min_confidence > 0 and confidence < min_confidence:
                low_count += 1

        if min_confidence > 0:
            total = len(signals.get("signals", []))
            self.stdout.write(
                self.style.WARNING(
                    f"\n{low_count}/{total} tabs below "
                    f"--min-confidence {min_confidence}"
                )
            )
