"""Merge profiler signals, interaction contract, and view manifest into a codegen manifest.

Usage::

    python manage.py merge_interaction_contract \\
        --profiler-signals build/profiler-signals.yaml \\
        --interaction-contract build/interaction-contract.yaml \\
        --view-manifest build/view-manifest.yaml \\
        --output build/codegen-manifest.yaml
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    """Merge profiler signals, interaction contract, and view manifest."""

    help = (
        "Merge profiler signals (Layer 1), interaction contract (Layer 2), "
        "and view manifest into a codegen manifest (Layer 3) consumed by "
        "generate_admin and future frontend generators."
    )

    def add_arguments(self, parser):
        """Add CLI arguments for the ``merge_interaction_contract`` command."""
        parser.add_argument(
            "--profiler-signals",
            default=None,
            help="Path to profiler-signals YAML (Layer 1, optional)",
        )
        parser.add_argument(
            "--interaction-contract",
            default=None,
            help="Path to interaction-contract YAML (Layer 2, optional)",
        )
        parser.add_argument(
            "--view-manifest",
            default=None,
            help="Path to view-manifest YAML (Layer 3 input, optional)",
        )
        parser.add_argument(
            "--output",
            required=True,
            help="Path to write the codegen-manifest YAML",
        )

    def handle(self, *args, **options):
        """Read inputs, merge, and write the codegen manifest."""
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CommandError(
                "PyYAML is required to read/write YAML files."
            ) from exc

        from workbook.tools.manifest_merger import merge_manifests

        # Load optional inputs.
        profiler_signals = None
        if options.get("profiler_signals"):
            signals_path = Path(options["profiler_signals"]).resolve()
            if not signals_path.is_file():
                raise CommandError(
                    f"profiler-signals not found: {signals_path}"
                )
            profiler_signals = yaml.safe_load(
                signals_path.read_text(encoding="utf-8")
            )
            if not isinstance(profiler_signals, dict):
                raise CommandError(
                    f"profiler-signals is not a YAML mapping: {signals_path}"
                )

        interaction_contract = None
        if options.get("interaction_contract"):
            contract_path = Path(options["interaction_contract"]).resolve()
            if not contract_path.is_file():
                raise CommandError(
                    f"interaction-contract not found: {contract_path}"
                )
            interaction_contract = yaml.safe_load(
                contract_path.read_text(encoding="utf-8")
            )
            if not isinstance(interaction_contract, dict):
                raise CommandError(
                    f"interaction-contract is not a YAML mapping: {contract_path}"
                )

        view_manifest = None
        if options.get("view_manifest"):
            manifest_path = Path(options["view_manifest"]).resolve()
            if not manifest_path.is_file():
                raise CommandError(
                    f"view-manifest not found: {manifest_path}"
                )
            view_manifest = yaml.safe_load(
                manifest_path.read_text(encoding="utf-8")
            )
            if not isinstance(view_manifest, dict):
                raise CommandError(
                    f"view-manifest is not a YAML mapping: {manifest_path}"
                )

        codegen_manifest = merge_manifests(
            profiler_signals=profiler_signals,
            interaction_contract=interaction_contract,
            view_manifest=view_manifest,
        )

        out_path = Path(options["output"]).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            yaml.safe_dump(
                codegen_manifest,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        table_count = len(codegen_manifest.get("tables") or [])
        self.stdout.write(
            self.style.SUCCESS(f"wrote {out_path}  ({table_count} table(s))")
        )
