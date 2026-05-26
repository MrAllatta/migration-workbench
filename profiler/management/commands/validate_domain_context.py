#!/usr/bin/env python3
"""Validate domain_context.yaml structure."""

from __future__ import annotations

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Validate domain_context.yaml structure."

    def add_arguments(self, parser):
        parser.add_argument(
            "--config", required=True, help="Path to domain_context.yaml"
        )
        parser.add_argument(
            "--strict", action="store_true", help="Treat warnings as errors (exit 2)"
        )

    def handle(self, *args, **options):
        config_path = Path(options["config"]).resolve()
        if not config_path.exists():
            raise CommandError(f"Config not found: {config_path}")

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise CommandError("Domain context must be a YAML mapping (dict)")

        errors: list[str] = []
        warnings: list[str] = []

        year_scope = raw.get("year_scope") or {}
        for key in ("active", "archived", "forward"):
            val = year_scope.get(key)
            if val is not None and not (
                isinstance(val, list) and all(isinstance(v, int) for v in val)
            ):
                errors.append(f"year_scope.{key} must be a list of integers")

        if not year_scope.get("active"):
            warnings.append("year_scope.active is empty")

        vocab = raw.get("vocabulary") or {}
        for key in ("operational", "reference", "support", "derived"):
            val = vocab.get(key)
            if val is not None and not (
                isinstance(val, list) and all(isinstance(v, str) for v in val)
            ):
                errors.append(f"vocabulary.{key} must be a list of strings")

        if not any(
            vocab.get(k) for k in ("operational", "reference", "support", "derived")
        ):
            warnings.append("vocabulary has no tokens")

        dedup = raw.get("deduplication") or {}
        strategy = dedup.get("strategy", "latest_year")
        if strategy not in ("latest_year", "none"):
            errors.append(
                f"deduplication.strategy must be 'latest_year' or 'none', got {strategy!r}"
            )

        glossary = raw.get("glossary") or {}
        if not isinstance(glossary, dict):
            errors.append("glossary must be a mapping")
        elif glossary and not all(
            isinstance(k, str) and isinstance(v, str) for k, v in glossary.items()
        ):
            errors.append("glossary keys and values must be strings")

        for err in errors:
            self.stdout.write(self.style.ERROR(f"ERROR: {err}"))
        for warn in warnings:
            self.stdout.write(self.style.WARNING(f"WARNING: {warn}"))

        if errors:
            raise CommandError(f"Validation failed with {len(errors)} error(s)")

        self.stdout.write(self.style.SUCCESS("Domain context is valid"))

        if warnings and options["strict"]:
            raise CommandError(
                f"Validation failed with {len(warnings)} warning(s) (strict mode)"
            )
