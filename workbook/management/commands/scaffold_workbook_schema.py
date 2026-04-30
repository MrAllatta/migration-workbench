"""Emit a schema contract YAML (and optional models.py stub) from bundle config + profiler JSON."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from workbook.schema_contract import build_contract, load_json


def _kwargs_python(kwargs: dict[str, Any]) -> str:
    parts: list[str] = []
    for k, v in kwargs.items():
        if k == "on_delete":
            parts.append("on_delete=models.PROTECT")
        elif k == "to":
            parts.append(f"to={v!r}")
        elif isinstance(v, bool):
            parts.append(f"{k}={v}")
        elif isinstance(v, int):
            parts.append(f"{k}={v}")
        elif v is None:
            parts.append(f"{k}=None")
        else:
            parts.append(f"{k}={v!r}")
    return ", ".join(parts)


def _render_models_stub(contract: dict[str, Any], app_label: str) -> str:
    lines = [
        '"""',
        "Generated stub — review FKs, Meta, constraints, and field types before migrating.",
        '"""',
        "",
        "from django.db import models",
        "",
    ]
    for t in contract.get("tables") or []:
        model = t.get("suggested_model_name") or "model"
        class_name = "".join(part.capitalize() for part in model.split("_") if part)
        if not class_name:
            class_name = "Row"
        lines.append(f"class {class_name}(models.Model):")
        lines.append(f'    """Bundle tab: {t.get("bundle_worksheet_title")!s}."""')
        for col in t.get("columns") or []:
            fname = col.get("suggested_field_name") or "field"
            fc = col.get("django_field_class") or "models.TextField"
            kwargs = col.get("django_field_kwargs") or {}
            kw_str = _kwargs_python(kwargs)
            if kw_str:
                lines.append(f"    {fname} = {fc}({kw_str})")
            else:
                lines.append(f"    {fname} = {fc}()")
        lines.append("")
        lines.append("    class Meta:")
        lines.append(f'        db_table = "{app_label}_{model}"')
        lines.append("")
    return "\n".join(lines)


class Command(BaseCommand):
    help = (
        "Build schema-contract YAML from pull_bundle config plus optional "
        "profile_coda_doc / profile_coda_table JSON artifacts."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--bundle-config",
            required=True,
            help="JSON path (e.g. live-config.json with tabs[])",
        )
        parser.add_argument(
            "--doc-profile",
            default=None,
            help="Optional profile_coda_doc output JSON",
        )
        parser.add_argument(
            "--table-profile",
            action="append",
            default=[],
            metavar="PATH",
            help="profile_coda_table JSON (repeat per table)",
        )
        parser.add_argument(
            "--out",
            required=True,
            help="Output schema contract path (.yaml or .yml)",
        )
        parser.add_argument(
            "--models-stub-out",
            default=None,
            help="Optional path to write a review-only models.py fragment",
        )
        parser.add_argument(
            "--models-app-label",
            default="domain",
            help="App label for Meta.db_table prefix on stub (default: domain)",
        )

    def handle(self, *args, **options):
        bundle_path = Path(options["bundle_config"]).resolve()
        if not bundle_path.is_file():
            raise CommandError(f"bundle-config not found: {bundle_path}")
        bundle_config = load_json(bundle_path)

        doc_profile = None
        if options["doc_profile"]:
            dp = Path(options["doc_profile"]).resolve()
            if not dp.is_file():
                raise CommandError(f"doc-profile not found: {dp}")
            doc_profile = load_json(dp)

        table_profiles: dict[str, dict[str, Any]] = {}
        for raw in options["table_profile"] or []:
            p = Path(raw).resolve()
            if not p.is_file():
                raise CommandError(f"table-profile not found: {p}")
            payload = load_json(p)
            summary = payload.get("summary") or {}
            title = str(summary.get("table_name") or "")
            if not title:
                raise CommandError(f"table profile missing summary.table_name: {p}")
            table_profiles[title] = payload

        contract = build_contract(
            bundle_config,
            doc_profile=doc_profile,
            table_profiles=table_profiles or None,
        )

        out_path = Path(options["out"]).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CommandError(
                "PyYAML is required for YAML output. Install migration-workbench with dependencies."
            ) from exc

        text = yaml.safe_dump(
            contract,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        out_path.write_text(text, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"wrote {out_path}"))

        stub_out = options.get("models_stub_out")
        if stub_out:
            stub_path = Path(stub_out).resolve()
            stub_path.parent.mkdir(parents=True, exist_ok=True)
            stub_path.write_text(
                _render_models_stub(contract, options["models_app_label"]),
                encoding="utf-8",
            )
            self.stdout.write(self.style.SUCCESS(f"wrote {stub_path}"))
