"""Render a discovery-interview Markdown questionnaire from a view-manifest YAML."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from profiler.tools.pipeline_state import PipelineState
from workbook.discovery import render_interview
from workbook.tools.vertical_registry import load_vertical


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
        parser.add_argument(
            "--vertical",
            help="Load vertical template to seed interview presets",
        )
        parser.add_argument(
            "--checkpoint",
            default=None,
            help="Path to a PipelineState checkpoint YAML. When provided, "
            "artifact provenance is recorded on the state and saved.",
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

        vertical_name = options.get("vertical")
        if vertical_name:
            try:
                vertical = load_vertical(vertical_name)
                manifest = self._enrich_manifest_with_vertical(manifest, vertical)
            except Exception as e:
                raise CommandError(f"Failed to load vertical '{vertical_name}': {e}")

        out_path = Path(options["out"]).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        interview_text = render_interview(manifest)
        out_path.write_text(interview_text, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"wrote {out_path}"))

        # Record artifact provenance on PipelineState if checkpoint path provided
        checkpoint_arg = options.get("checkpoint")
        if checkpoint_arg:
            checkpoint_path = Path(checkpoint_arg).resolve()
            if checkpoint_path.exists():
                state = PipelineState.load(checkpoint_path)
            else:
                state = PipelineState()
            source_id = manifest.get("source", {}).get("source_id", "unknown")
            question_count = len(manifest.get("views", []))
            if hasattr(state, "record_artifact_provenance"):
                state.record_artifact_provenance(
                    artifact_key=f"discovery_interview:{source_id}",
                    source="elicited",
                    signals=[{"questions_count": question_count}],
                )
                state.save_checkpoint(checkpoint_path)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"recorded provenance on checkpoint {checkpoint_path}"
                    )
                )

    def _enrich_manifest_with_vertical(self, manifest: dict, vertical) -> dict:
        """Enrich manifest with vertical data for interview presets."""
        import copy

        enriched = copy.deepcopy(manifest)

        interaction_defaults = vertical.interaction_defaults or {}
        roles = interaction_defaults.get("roles", {})
        if roles:
            workflow_hints = enriched.setdefault("workflow_hints", {})
            existing_role_hints = list(workflow_hints.get("role_hints") or [])

            vertical_role_hints = []
            for role_name, role_data in roles.items():
                tabs = role_data.get("tabs", [])
                for tab in tabs:
                    vertical_role_hints.append(f"{tab}: {role_name}")

            merged_role_hints = existing_role_hints + [
                hint for hint in vertical_role_hints if hint not in existing_role_hints
            ]
            workflow_hints["role_hints"] = merged_role_hints

        domain_context = vertical.domain_context or {}
        vocabulary = domain_context.get("vocabulary", {})
        if vocabulary:
            glossary_terms = []
            for category, terms in vocabulary.items():
                if isinstance(terms, list):
                    glossary_terms.extend(terms)
            enriched["_vertical_glossary_hints"] = glossary_terms

        return enriched
