"""Merge an operator-filled discovery interview back into a view-manifest YAML."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from workbook.discovery import (
    apply_discovery_patch,
    build_interaction_contract_from_patch,
    parse_interview,
    render_summary,
)


class Command(BaseCommand):
    help = (
        "Parse a filled-in discovery-interview Markdown and write the "
        "operator's role hints, weekly actions, and per-view notes back "
        "into the view-manifest YAML. Optionally emits a discovery-summary "
        "Markdown recap."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--manifest",
            required=True,
            help="Path to the source view-manifest YAML (read; not modified unless --out is the same path)",
        )
        parser.add_argument(
            "--interview",
            required=True,
            help="Path to the operator-filled discovery-interview Markdown",
        )
        parser.add_argument(
            "--out",
            required=True,
            help="Path to write the patched view-manifest YAML (may be the same as --manifest)",
        )
        parser.add_argument(
            "--summary-out",
            default=None,
            help="Optional path for a discovery-summary Markdown recap",
        )
        parser.add_argument(
            "--output-interaction-contract",
            default=None,
            help="Optional path to write the interaction-contract YAML derived from interview answers",
        )

    def handle(self, *args, **options):
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CommandError(
                "PyYAML is required to read/write manifest YAML."
            ) from exc

        manifest_path = Path(options["manifest"]).resolve()
        if not manifest_path.is_file():
            raise CommandError(f"manifest not found: {manifest_path}")
        interview_path = Path(options["interview"]).resolve()
        if not interview_path.is_file():
            raise CommandError(f"interview not found: {interview_path}")

        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise CommandError(f"manifest is not a YAML mapping: {manifest_path}")
        interview_text = interview_path.read_text(encoding="utf-8")

        patch = parse_interview(interview_text, manifest)
        updated = apply_discovery_patch(manifest, patch)

        out_path = Path(options["out"]).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            yaml.safe_dump(
                updated,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(f"wrote {out_path}"))

        summary_arg = options.get("summary_out")
        if summary_arg:
            summary_path = Path(summary_arg).resolve()
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                render_summary(
                    updated,
                    weekly_workflow=patch.get("weekly_workflow") or "",
                ),
                encoding="utf-8",
            )
            self.stdout.write(self.style.SUCCESS(f"wrote {summary_path}"))

        contract_out = options.get("output_interaction_contract")
        if contract_out:
            interaction_contract = build_interaction_contract_from_patch(
                patch,
                updated,
                source_id=((updated.get("source") or {}).get("source_id") or ""),
            )
            contract_path = Path(contract_out).resolve()
            contract_path.parent.mkdir(parents=True, exist_ok=True)
            contract_path.write_text(
                yaml.safe_dump(
                    interaction_contract,
                    sort_keys=False,
                    allow_unicode=True,
                    default_flow_style=False,
                ),
                encoding="utf-8",
            )
            self.stdout.write(self.style.SUCCESS(f"wrote {contract_path}"))
