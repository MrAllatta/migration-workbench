"""Emit a schema contract YAML (and optional models.py stub) from bundle config + profiler JSON."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from connectors.spreadsheet import guess_header_row, raw_sheet_to_row_lists
from workbook.codegen.designed_model_detection import (
    find_column_overlap_groups,
    suggest_designed_model,
)
from workbook.field_mapping import map_profiler_column_to_django_field, suggested_field_name
from workbook.schema_contract import build_contract, load_json


def _infer_format_type_from_samples(samples: list[str]) -> str | None:
    """Guess a profiler ``format_type`` from a list of sample string values."""
    non_empty = [s for s in samples if s and s.strip()]
    if not non_empty:
        return None
    numeric_count = 0
    date_count = 0
    for value in non_empty:
        cleaned = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if re.match(r"^-?\d+(\.\d+)?$", cleaned):
            numeric_count += 1
        elif re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$", value.strip()):
            date_count += 1
    if numeric_count == len(non_empty):
        return "number"
    if date_count > len(non_empty) / 2:
        return "date"
    return "text"


def _inject_designed_models(tables: list[dict]) -> list[dict]:
    """Detect overlapping tab column sets and inject designed model entries.

    Args:
        tables: List of schema-contract table entries.

    Returns:
        list[dict]: Tables list with designed model entries appended.
    """
    tab_columns: dict[str, set[str]] = {}
    for table in tables:
        title = table.get("bundle_worksheet_title", "")
        if title:
            tab_columns[title] = {
                col.get("suggested_field_name", col.get("source_column", ""))
                for col in table.get("columns", [])
            }

    overlap_groups = find_column_overlap_groups(tab_columns, min_overlap_ratio=0.5)
    if overlap_groups:
        for cluster_entry in overlap_groups:
            tab_names = cluster_entry["tab_names"]
            parts = sorted(tab_names)
            merged_name = suggested_field_name(" ".join(parts))
            suggested = suggest_designed_model(
                cluster_entry,
                suggested_name=merged_name,
            )
            suggested["_meta"] = {"generated_by": "designed_model_detection"}
            tables.append(suggested)

    return tables


def _build_cohort_contract(
    deep_dir: Path,
    coverage_payload: dict,
    *,
    version: str = "1.0",
    hardened: bool = False,
) -> dict[str, Any]:
    """Build a schema contract from a cohort corpus ``deep_profile_coverage`` payload.

    Args:
        deep_dir: Directory containing per-tab deep JSON artifacts.
        coverage_payload: Parsed ``deep_profile_coverage_*.json`` content.
        version: Schema contract version.  Defaults to ``"1.0"``.
        hardened: When ``True``, emit ``import_config``, ``fk_resolutions``,
            ``field_overrides``, and ``admin`` blocks.  Defaults to ``False``.

    Returns:
        dict: Schema contract dict ready for YAML serialisation.
    """
    tables: list[dict[str, Any]] = []
    for result in coverage_payload.get("results", []):
        if result.get("exit_code", 0) != 0:
            continue
        out_json = result.get("out_json")
        if not out_json:
            continue
        # out_json stores paths relative to the snapshots root
        # (e.g. "cohort_corpus/deep/202_2023_...json"), but deep_dir
        # points at the deep/ subdirectory already.  Use the filename
        # portion only, since deep/ contains flat filename listings.
        deep_path = (deep_dir / Path(out_json).name).resolve() if not Path(out_json).is_absolute() else Path(out_json)
        if not deep_path.exists():
            continue
        try:
            payload = json.loads(deep_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        raw = payload.get("raw", {})
        summary = payload.get("summary", {})
        tab_title = result.get("tab_title", "")
        workbook_code = result.get("workbook_code", "")

        row_lists = _raw_to_row_lists(raw)
        header_index = guess_header_row(row_lists)
        if header_index is None:
            continue
        headers_raw = row_lists[header_index]
        data_rows = row_lists[header_index + 1:]

        columns: list[dict[str, Any]] = []
        for col_index, header in enumerate(headers_raw):
            if not header.strip():
                continue
            sample_values = [
                str(data_row[col_index]) if col_index < len(data_row) else ""
                for data_row in data_rows[:20]
            ]
            fmt = _infer_format_type_from_samples(sample_values)
            col_meta = {"name": header, "format_type": fmt}
            hint = map_profiler_column_to_django_field(col_meta)
            columns.append(
                {
                    "source_column": header.strip(),
                    "suggested_field_name": suggested_field_name(header),
                    "profiler_format_type": fmt,
                    "has_formula": None,
                    "formula_pattern": None,
                    "django_field_class": hint["django_field_class"],
                    "django_field_kwargs": hint["django_field_kwargs"],
                    "notes": hint.get("notes") or [],
                }
            )

        model_slug = suggested_field_name(tab_title) or workbook_code.lower()
        table_entry: dict[str, Any] = {
            "bundle_worksheet_title": tab_title,
            "suggested_model_name": model_slug,
            "columns": columns,
        }
        tables.append(table_entry)

    _inject_designed_models(tables)

    contract = {
        "version": version,
        "source": {
            "provider": "google_sheets",
            "doc_url": None,
            "doc_id": None,
            "source_id": "cohort_corpus",
        },
        "tables": tables,
    }
    if hardened:
        _harden_contract(contract)
    return contract


def _raw_to_row_lists(raw: dict) -> list[list[str]]:
    """Convert raw Sheets API grid data into list-of-lists for header detection."""
    return raw_sheet_to_row_lists(raw)


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


def _harden_contract(contract: dict[str, Any]) -> None:
    """Augment a schema contract with import_config, FK, and admin blocks."""
    for table in contract.get("tables", []):
        columns = table.get("columns", [])
        if not columns:
            continue
        first_field = columns[0]["suggested_field_name"]
        table["import_config"] = {
            "import_key": first_field,
            "unique_on": [first_field],
        }
        fk_resolutions: dict[str, str] = {}
        for col in columns:
            if col.get("django_field_class") == "models.ForeignKey":
                fk_resolutions[col["suggested_field_name"]] = "TODO_TargetModel"
        if fk_resolutions:
            table["fk_resolutions"] = fk_resolutions
        field_overrides: dict[str, dict[str, Any]] = {}
        for col in columns:
            notes = col.get("notes", [])
            if "low_cardinality_sample" in notes:
                field_overrides[col["suggested_field_name"]] = {
                    "choices": [],
                    "notes": ["TODO: populate choices from domain data"],
                }
        if field_overrides:
            table["field_overrides"] = field_overrides
        editable = [
            col["suggested_field_name"]
            for col in columns
            if col["django_field_class"] != "models.ForeignKey"
        ]
        table["admin"] = {
            "list_display": editable[:6],
        }


class Command(BaseCommand):
    help = (
        "Build schema-contract YAML from pull_bundle config plus optional "
        "profile_coda_doc / profile_coda_table JSON artifacts, or from a "
        "cohort corpus deep-profile output directory."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--bundle-config",
            default=None,
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
            "--cohort-corpus-out-dir",
            default=None,
            help="Directory containing cohort corpus deep-profile artifacts "
            "(deep_profile_coverage_*.json + deep/ subdirectory)",
        )
        parser.add_argument(
            "--hardened",
            action="store_true",
            default=False,
            help="Emit import_config, fk_resolutions, field_overrides, and "
            "admin blocks in the contract",
        )
        parser.add_argument(
            "--contract-version",
            default="1.0",
            help="Schema contract version string (default: 1.0)",
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
        out_path = Path(options["out"]).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        cohort_dir = options.get("cohort_corpus_out_dir")
        bundle_config_path = options.get("bundle_config")

        if cohort_dir:
            contract = self._handle_cohort_corpus(
                Path(cohort_dir).resolve(),
                hardened=bool(options.get("hardened")),
                version=options.get("contract_version", "1.0"),
            )
        elif bundle_config_path:
            contract = self._handle_bundle_config(options)
        else:
            raise CommandError(
                "Either --bundle-config or --cohort-corpus-out-dir is required."
            )

        app_label = options["models_app_label"]
        for table in contract.get("tables", []):
            meta = table.setdefault("model_meta", {})
            meta.setdefault("app_label", app_label)

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

    def _handle_bundle_config(self, options: dict[str, Any]) -> dict[str, Any]:
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

        hardened = bool(options.get("hardened"))
        version = options.get("contract_version", "1.0")
        contract = build_contract(
            bundle_config,
            doc_profile=doc_profile,
            table_profiles=table_profiles or None,
        )
        contract["version"] = version
        if hardened:
            _harden_contract(contract)
        tables = contract.get("tables", [])
        _inject_designed_models(tables)
        return contract

    def _handle_cohort_corpus(
        self, cohort_dir: Path, *, hardened: bool, version: str
    ) -> dict[str, Any]:
        coverage_files = sorted(cohort_dir.glob("deep_profile_coverage_*.json"))
        if not coverage_files:
            raise CommandError(
                f"No deep_profile_coverage_*.json found in {cohort_dir}"
            )
        coverage_path = coverage_files[-1]
        coverage_payload = load_json(coverage_path)
        deep_dir = cohort_dir / "deep"
        if not deep_dir.is_dir():
            raise CommandError(
                f"Expected a deep/ subdirectory inside {cohort_dir}; none found"
            )
        contract = _build_cohort_contract(
            deep_dir,
            coverage_payload,
            version=version,
            hardened=hardened,
        )
        return contract
