"""Emit a contract YAML table skeleton for a designed (non-source-tab) model.

Designed models are entities like ``FieldEvent`` or ``InventoryEntry`` that
have no corresponding source worksheet tab.  This command emits a single
table entry with ``source_tab: null`` and ``extra_fields`` pre-populated
from ``--fields`` arguments, ready to paste into a schema-contract YAML.

Usage::

    python manage.py scaffold_designed_model \\
        --name FieldEvent \\
        --fields "event_type:CharField:max_length=30,choices=EventType" \\
        --fields "timestamp:DateTimeField" \\
        --fields "target_crop:ForeignKey:to=Crop"
"""

from __future__ import annotations

import re
from typing import Any

import yaml
from django.core.management.base import BaseCommand


def _parse_kwarg_value(raw: str) -> Any:
    """Parse a single YAML kwarg value from a CLI string.

    Handles booleans, integers, and strings.
    """
    if raw.lower() in ("true", "yes"):
        return True
    if raw.lower() in ("false", "no"):
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    return raw


def _parse_field_spec(spec: str) -> dict[str, Any]:
    """Parse a ``--fields`` value into a field dict.

    Expected format: ``field_name:FieldClass:kwarg=val,kwarg=val``

    Raises:
        ValueError: When the spec is malformed.
    """
    parts = spec.split(":")
    if len(parts) < 2:
        raise ValueError(
            f"Invalid field spec {spec!r}: expected name:FieldClass[:kwargs]"
        )
    name = parts[0]
    field_class = parts[1]
    kwargs: dict[str, Any] = {}
    if len(parts) >= 3:
        raw_kwargs = parts[2]
        if raw_kwargs:
            for pair in raw_kwargs.split(","):
                pair = pair.strip()
                if not pair:
                    continue
                if "=" not in pair:
                    raise ValueError(
                        f"Invalid kwarg {pair!r} in {spec!r}: expected key=value"
                    )
                k, v = pair.split("=", 1)
                kwargs[k.strip()] = _parse_kwarg_value(v.strip())
    return {"name": name, "class": field_class, "kwargs": kwargs}


def _slugify(name: str) -> str:
    """Convert a PascalCase model name to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class Command(BaseCommand):
    help = "Emit a contract YAML table skeleton for a designed (non-source-tab) model."

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            required=True,
            help="PascalCase model name (e.g. FieldEvent)",
        )
        parser.add_argument(
            "--fields",
            action="append",
            default=[],
            help="Field spec: name:FieldClass:kwarg=val,kwarg=val (repeatable)",
        )
        parser.add_argument(
            "--model-base",
            default="models.Model",
            help="Model base class (default: models.Model)",
        )
        parser.add_argument(
            "--is-abstract",
            action="store_true",
            help="Mark model as abstract base",
        )
        parser.add_argument(
            "--str-template",
            default=None,
            help="__str__ f-string body (e.g. '{self.name}')",
        )

    def handle(self, *args, **options):
        model_name = options["name"]
        fields = options["fields"]
        model_base = options["model_base"]
        is_abstract = options["is_abstract"]
        str_template = options["str_template"]

        extra_fields: dict[str, Any] = {}
        for spec in fields:
            parsed = _parse_field_spec(spec)
            extra_fields[parsed["name"]] = {
                "class": parsed["class"],
                "kwargs": parsed["kwargs"],
            }

        table: dict[str, Any] = {
            "suggested_model_name": _slugify(model_name),
            "bundle_worksheet_title": None,
            "source_tab": None,
            "model_name": model_name,
            "model_base": model_base,
            "columns": [],
            "extra_fields": extra_fields,
        }

        if is_abstract:
            table["is_abstract"] = True

        if str_template:
            table["str_template"] = str_template

        output = {
            "version": "1.3",
            "tables": [table],
        }

        self.stdout.write(
            yaml.safe_dump(
                output,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        )
