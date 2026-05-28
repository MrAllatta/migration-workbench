"""Render a discovery-interview Markdown questionnaire from a view-manifest YAML."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from workbook.discovery import render_interview


class Command(BaseCommand):
    """Render a discovery-interview Markdown questionnaire from a view-manifest YAML."""

    help = (
        "Render a pre-populated discovery-interview Markdown questionnaire "
        "from a view-manifest YAML. The operator fills in the answer "
        "placeholders, then runs `merge_discovery_notes` to patch the "
        "manifest."
    )

    def add_arguments(self, parser):
        """Add CLI arguments for the ``generate_discovery_interview`` command."""
        parser.add_argument(
            "--manifest",
            required=True,
            help="Path to a view-manifest YAML (e.g. produced by scaffold_view_manifest)",
        )
        parser.add_argument(
            "--out",
            required=True,
            help="Output Markdown path",
        )

    def handle(self, *args, **options):
        """Read the view-manifest YAML and render the interview Markdown to disk."""
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CommandError("PyYAML is required to read the manifest YAML.") from exc

        manifest_path = Path(options["manifest"]).resolve()
        if not manifest_path.is_file():
            raise CommandError(f"manifest not found: {manifest_path}")

        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise CommandError(f"manifest is not a YAML mapping: {manifest_path}")

        out_path = Path(options["out"]).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_interview(manifest), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"wrote {out_path}"))
