"""Emit a schema contract YAML (and optional models.py stub) from bundle config + profiler JSON."""

from __future__ import annotations

import json
import keyword
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from collections.abc import Callable
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from connectors.spreadsheet import guess_header_row, raw_sheet_to_row_lists
from workbook.partial_output import PartialOutputCollector
from workbook.codegen.designed_model_detection import (
    find_column_overlap_groups,
    suggest_designed_model,
)
from workbook.field_mapping import (
    is_valid_python_identifier,
    map_profiler_column_to_django_field,
    suggested_field_name,
)
from workbook.schema_contract import (
    build_contract,
    _compute_fk_resolutions,
    _suggest_import_keys,
    _compute_bundle_paths,
    load_json,
)
from profiler.tools.enrichment_utils import _ENTITY_KEYWORDS, _to_pascal_case


def _flag_fk_columns(columns: list[dict]) -> None:
    """Flag columns that look like FK references with suggested_fk_target.

    Detects: columns ending in '_id', or columns named after entity keywords.
    Skips columns that already have suggested_fk_target set by profiler enrichment.
    Mutates columns in-place.
    """
    for col in columns:
        if col.get("suggested_fk_target"):
            continue
        name = col.get("suggested_field_name", "")
        if name.endswith("_id"):
            target = _to_pascal_case(name[:-3])
            col["suggested_fk_target"] = target
            col["review_note"] = f"Auto-detected FK: {target}"
        elif name.lower() in _ENTITY_KEYWORDS:
            target = _to_pascal_case(name)
            col["suggested_fk_target"] = target
            col["review_note"] = f"Auto-detected FK: {target}"


def _flag_computed_fields(table: dict) -> None:
    """Move formula-derived columns from columns[] to computed_fields{}.

    Columns with formula_pattern 'row_formula' or 'expansion_formula' are
    removed from the stored columns list and added as computed field stubs.
    Columns with is_computed=True are also moved.
    """
    columns = table.get("columns", [])
    kept = []
    computed = {}
    for col in columns:
        pattern = col.get("formula_pattern")
        is_computed = col.get("is_computed", False)
        if pattern in ("row_formula", "expansion_formula") or is_computed:
            name = col["suggested_field_name"]
            computed[name] = {
                "return_type": col.get("django_field_class", "models.FloatField"),
                "expression": f"# TODO: {col.get('source_column', name)} is formula-derived",
            }
        else:
            kept.append(col)
    table["columns"] = kept
    if computed:
        table.setdefault("computed_fields", {}).update(computed)


def _suggest_tab_merges(tabs: dict[str, dict]) -> list[dict]:
    """Suggest which tabs from the same workbook should be merged into one entity.

    Tabs sharing 2+ column header names are merge candidates.
    Returns a list of {tabs: set[str], shared_headers: list[str]} dicts.
    """
    tab_names = list(tabs.keys())
    candidates = []
    for i in range(len(tab_names)):
        for j in range(i + 1, len(tab_names)):
            a_headers = set(tabs[tab_names[i]].get("columns", []))
            b_headers = set(tabs[tab_names[j]].get("columns", []))
            shared = a_headers & b_headers
            if len(shared) >= 2:
                candidates.append(
                    {
                        "tabs": {tab_names[i], tab_names[j]},
                        "shared_headers": sorted(shared),
                    }
                )
    return candidates


def _derive_bundle_path(label: str) -> str:
    """Derive a default CSV bundle_path from a suggested model name.

    Sales Channel  -> reference/sales_channels.csv
    Farm           -> reference/farms.csv
    Address        -> reference/addresses.csv
    Business Unit  -> reference/business_units.csv
    """
    stem = label.strip().lower().replace(" ", "_")
    plural = stem + "es" if stem.endswith("s") else stem + "s"
    return f"reference/{plural}.csv"


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
            if "model_name" not in suggested:
                suggested["model_name"] = _to_pascal_case(suggested.get("suggested_model_name", merged_name))
            tables.append(suggested)

    return tables


def _validate_tables_for_scaffold(
    tables: list[dict[str, Any]], continue_on_error: bool = False, pivot_detection_threshold: float = 0.5
) -> tuple[list[dict[str, Any]], PartialOutputCollector]:
    collector = PartialOutputCollector()
    valid_tables: list[dict[str, Any]] = []

    for table in tables:
        if table.get("source_tab") is None and not table.get("bundle_worksheet_title"):
            valid_tables.append(table)
            continue

        model_name = str(table.get("model_name", "")).strip()
        if not model_name:
            if continue_on_error:
                collector.add(
                    table,
                    check_id="SCAFFOLD_NULL_MODEL_NAME",
                    message=f"Tab {table.get('bundle_worksheet_title', '?')!r} produced empty model_name",
                    action="Deduplicate the tab across year workbooks or set a unique suggested_model_name",
                )
                continue
            else:
                tab_title = table.get("bundle_worksheet_title") or table.get(
                    "suggested_model_name", "?"
                )
                raise CommandError(
                    f'FAIL[SCAFFOLD_NULL_MODEL_NAME]: Tab "{tab_title}" produced empty model_name'
                )

        pivot_errors = _check_pivot_tables(table, pivot_detection_threshold=pivot_detection_threshold)
        if pivot_errors:
            if continue_on_error:
                collector.add(
                    table,
                    check_id="SCAFFOLD_PIVOT_TABLE",
                    message=pivot_errors[0].split(":", 1)[1].strip(),
                    action="Add to vocabulary.derived or exclude from corpus config",
                )
                continue
            else:
                raise CommandError(pivot_errors[0])

        id_errors = _check_invalid_identifiers(table)
        if id_errors:
            if continue_on_error:
                collector.add(
                    table,
                    check_id="SCAFFOLD_INVALID_IDENTIFIER",
                    message=id_errors[0].split(":", 1)[1].strip(),
                    action="Rename the source column header or add a column alias in the bundle config",
                )
                continue
            else:
                raise CommandError(id_errors[0])

        valid_tables.append(table)

    return valid_tables, collector


def _check_null_model_names(tables: list[dict]) -> list[str]:
    """Return error messages for tables with empty model_name."""
    errors: list[str] = []
    for table in tables:
        model_name = str(table.get("model_name", "")).strip()
        if not model_name:
            tab_title = table.get("bundle_worksheet_title") or table.get("suggested_model_name", "?")
            errors.append(
                f'FAIL[SCAFFOLD_NULL_MODEL_NAME]: Tab "{tab_title}" produced empty model_name\n'
                "  → Action: Deduplicate the tab across year workbooks or set a unique suggested_model_name\n"
                f"  (Table: {tab_title}, Field: model_name)"
            )
    return errors


def _check_pivot_tables(table: dict, *, pivot_detection_threshold: float = 0.5) -> list[str]:
    """Return error messages if the table looks like a pivot table."""
    errors: list[str] = []
    columns = table.get("columns", [])
    if not columns:
        return errors
    headers = [col.get("source_column", "").strip() for col in columns]
    numeric_headers = [h for h in headers if h.isdigit()]
    if len(numeric_headers) / len(headers) > pivot_detection_threshold:
        tab_title = table.get("bundle_worksheet_title", "?")
        numeric_list = ", ".join(numeric_headers[:10])
        errors.append(
            f'FAIL[SCAFFOLD_PIVOT_TABLE]: Tab "{tab_title}" appears to be a pivot table '
            f"(numeric headers: {numeric_list})\n"
            "  → Action: Add it to vocabulary.derived or exclude it from the corpus config.\n"
            f"  (Table: {tab_title})"
        )
    return errors


def _check_invalid_identifiers(table: dict) -> list[str]:
    """Return error messages for invalid field or model names."""
    errors: list[str] = []
    model_name = str(table.get("model_name", "")).strip()
    tab_title = table.get("bundle_worksheet_title", "?")
    if model_name and not is_valid_python_identifier(model_name):
        errors.append(
            f'FAIL[SCAFFOLD_INVALID_IDENTIFIER]: model_name "{model_name}" is not a valid Python identifier\n'
            "  → Action: Rename the source tab or set an explicit suggested_model_name.\n"
            f"  (Table: {tab_title}, Field: model_name)"
        )
    for col in table.get("columns", []):
        field_name = col.get("suggested_field_name", "")
        if field_name and not is_valid_python_identifier(field_name):
            errors.append(
                f'FAIL[SCAFFOLD_INVALID_IDENTIFIER]: Field name "{field_name}" is not a valid Python identifier\n'
                "  → Action: Rename the source column header or add a column alias in the bundle config.\n"
                f"  (Table: {tab_title}, Field: {field_name})"
            )
    return errors


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$")
_BOOL_VALUES = {"TRUE", "FALSE", "Yes", "No", "yes", "no", "1", "0"}


def _infer_format_type_from_samples(sample_values: list[str]) -> str:
    """Infer a profiler format_type from raw cell string values.

    Conservative heuristic: defaults to ``"text"`` when ambiguous so that no
    column is mis-typed.  Returns one of ``"text"``, ``"number"``,
    ``"date"``, or ``"checkbox"``.
    """
    non_empty = [v for v in sample_values if v.strip()]
    if not non_empty:
        return "text"

    if all(v.strip() in _BOOL_VALUES for v in non_empty):
        return "checkbox"

    date_matches = sum(1 for v in non_empty if _DATE_RE.match(v.strip()))
    if date_matches / len(non_empty) >= 0.8:
        return "date"

    def _is_number(value: str) -> bool:
        cleaned = value.strip().lstrip("$").rstrip("%").replace(",", "")
        try:
            Decimal(cleaned)
            return True
        except InvalidOperation:
            return False

    number_matches = sum(1 for v in non_empty if _is_number(v))
    if number_matches / len(non_empty) >= 0.8:
        return "number"

    return "text"


def _build_cohort_contract(
    deep_dir: Path,
    coverage_payload: dict,
    *,
    hardened: bool = False,
    continue_on_error: bool = False,
    pivot_detection_threshold: float = 0.5,
) -> tuple[dict[str, Any], PartialOutputCollector]:
    """Build a schema contract from a cohort corpus ``deep_profile_coverage`` payload.

    Args:
        deep_dir: Directory containing per-tab deep JSON artifacts.
        coverage_payload: Parsed ``deep_profile_coverage_*.json`` content.
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
        deep_path = (
            (deep_dir / Path(out_json).name).resolve()
            if not Path(out_json).is_absolute()
            else Path(out_json)
        )
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
        data_rows = row_lists[header_index + 1 :]

        summary_col_meta: dict[str, dict[str, Any]] = {}
        for sc in summary.get("columns") or []:
            sn = str(sc.get("name") or "")
            if sn:
                summary_col_meta[sn] = sc

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
            enrichment = summary_col_meta.get(header.strip(), {})
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
                    "suggested_entity": enrichment.get("suggested_entity"),
                    "suggested_fk_target": enrichment.get("suggested_fk_target"),
                    "is_computed": enrichment.get("is_computed", False),
                    "is_import_key_candidate": enrichment.get(
                        "is_import_key_candidate", False
                    ),
                    "cross_tab_group": enrichment.get("cross_tab_group"),
                }
            )

        model_slug = suggested_field_name(tab_title) or workbook_code.lower()
        table_entry: dict[str, Any] = {
            "bundle_worksheet_title": tab_title,
            "suggested_model_name": model_slug,
            "columns": columns,
        }
        table_entry["model_name"] = _to_pascal_case(
            table_entry.get("suggested_model_name", "")
        )
        import_config = table_entry.setdefault("import_config", {})
        if "bundle_path" not in import_config:
            import_config["bundle_path"] = _derive_bundle_path(
                table_entry.get("suggested_model_name", "")
            )
        tables.append(table_entry)

    _inject_designed_models(tables)
    for table in tables:
        _flag_fk_columns(table.get("columns", []))
        _flag_computed_fields(table)

    tables, collector = _validate_tables_for_scaffold(tables, continue_on_error=continue_on_error)

    tab_headers = {}
    for table in tables:
        title = table.get("bundle_worksheet_title", "")
        cols = [c.get("source_column", "") for c in table.get("columns", [])]
        if title:
            tab_headers[title] = {"columns": cols}
    merge_candidates = _suggest_tab_merges(tab_headers)

    contract = {
        "source": {
            "provider": "google_sheets",
            "doc_url": None,
            "doc_id": None,
            "source_id": "cohort_corpus",
        },
        "tables": tables,
    }
    if merge_candidates:
        contract["_merge_candidates"] = merge_candidates
    if hardened:
        _harden_contract(contract)
    return contract, collector


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
        import_key_candidates = [
            c["suggested_field_name"]
            for c in columns
            if c.get("is_import_key_candidate")
        ]
        unique_on = import_key_candidates if import_key_candidates else [first_field]
        existing_bundle_path = table.get("import_config", {}).get("bundle_path")
        table["import_config"] = {
            "import_key": unique_on[0] if unique_on else first_field,
            "unique_on": unique_on,
        }
        model_name = table.get("model_name") or table.get("suggested_model_name", "")
        table["import_config"]["bundle_path"] = (
            existing_bundle_path or _derive_bundle_path(model_name)
        )
        ik = _suggest_import_keys(table.get("columns", []))
        if ik:
            table.setdefault("import_key", {})
            table["import_key"].setdefault("fields", ik["fields"])
            table["import_key"].setdefault("confidence", ik["confidence"])
            table["import_key"].setdefault("note", ik["note"])
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

    fk_resolutions = _compute_fk_resolutions(contract.get("tables", []))
    if fk_resolutions:
        contract.setdefault("fk_resolutions", []).extend(fk_resolutions)

    _compute_bundle_paths(contract.get("tables", []))


def _merge_domain_knowledge(
    tables: list[dict],
    domain_knowledge: dict,
    warn: Callable[..., None] | None = None,
) -> None:
    """Merge domain-knowledge entity definitions into scaffolded tables.

    Domain-knowledge field types override profiler-inferred types for matching
    fields. Profiler columns not mentioned in the domain entity get a
    review_note. Domain entities not matched to any profiler tab produce a
    warning.
    """
    if warn is None:
        warn = lambda _: None

    entities = domain_knowledge.get("entities", {})
    tab_to_entity: dict[str, tuple[str, dict]] = {}
    for entity_name, entity_def in entities.items():
        for tab in entity_def.get("source_tabs", []):
            tab_to_entity[tab] = (entity_name, entity_def)

    for table in tables:
        tab_title = table.get("bundle_worksheet_title", "")
        match = tab_to_entity.get(tab_title)
        if not match:
            continue
        entity_name, entity_def = match
        domain_fields = entity_def.get("fields", {})
        for col in table.get("columns", []):
            field_name = col.get("suggested_field_name", "")
            if field_name in domain_fields:
                df = domain_fields[field_name]
                col["django_field_class"] = df.get(
                    "type", col.get("django_field_class")
                )
                for key, value in df.items():
                    if key != "type":
                        col[key] = value
            else:
                col["review_note"] = f"Not mapped in domain knowledge for {entity_name}"

    matched_tabs = {t.get("bundle_worksheet_title", "") for t in tables}
    for entity_name, entity_def in entities.items():
        for tab in entity_def.get("source_tabs", []):
            if tab not in matched_tabs:
                warn(
                    f"Entity '{entity_name}' references tab '{tab}' not found in profiler output"
                )


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
        parser.add_argument(
            "--domain-knowledge",
            default=None,
            help="Path to a domain-knowledge YAML file with entity definitions",
        )
        parser.add_argument(
            "--continue-on-error",
            action="store_true",
            default=False,
            help="Collect validation errors and write partial contract YAML",
        )

    def handle(self, *args, **options):
        out_path = Path(options["out"]).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CommandError(
                "PyYAML is required for YAML output. Install migration-workbench with dependencies."
            ) from exc

        cohort_dir = options.get("cohort_corpus_out_dir")
        bundle_config_path = options.get("bundle_config")
        continue_on_error = bool(options.get("continue_on_error", False))

        if cohort_dir:
            contract, collector = self._handle_cohort_corpus(
                Path(cohort_dir).resolve(),
                hardened=bool(options.get("hardened")),
                continue_on_error=continue_on_error,
            )
        elif bundle_config_path:
            contract, collector = self._handle_bundle_config(options)
        else:
            raise CommandError(
                "Either --bundle-config or --cohort-corpus-out-dir is required."
            )

        app_label = options["models_app_label"]
        for table in contract.get("tables", []):
            meta = table.setdefault("model_meta", {})
            meta.setdefault("app_label", app_label)

        domain_knowledge_path = options.get("domain_knowledge")
        if domain_knowledge_path:
            dk_path = Path(domain_knowledge_path)
            if not dk_path.exists():
                raise CommandError(
                    f"Domain knowledge file not found: {domain_knowledge_path}"
                )
            with dk_path.open() as f:
                domain_knowledge = yaml.safe_load(f) or {}
            _merge_domain_knowledge(
                contract.get("tables", []), domain_knowledge, self.stdout.write
            )

        text = yaml.safe_dump(
            contract,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        out_path.write_text(text, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"wrote {out_path}"))

        if not collector.is_empty():
            rejection_path = out_path.parent / "schema-contract-rejected.yaml"
            collector.write_rejection_file(rejection_path)
            self.stdout.write(self.style.WARNING(collector.summary()))
            self.stdout.write(self.style.WARNING(f"Rejections written to: {rejection_path}"))

        stub_out = options.get("models_stub_out")
        if stub_out:
            stub_path = Path(stub_out).resolve()
            stub_path.parent.mkdir(parents=True, exist_ok=True)
            stub_path.write_text(
                _render_models_stub(contract, options["models_app_label"]),
                encoding="utf-8",
            )
            self.stdout.write(self.style.SUCCESS(f"wrote {stub_path}"))

    def _handle_bundle_config(self, options: dict[str, Any]) -> tuple[dict[str, Any], PartialOutputCollector]:
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
        contract = build_contract(
            bundle_config,
            doc_profile=doc_profile,
            table_profiles=table_profiles or None,
        )
        if hardened:
            _harden_contract(contract)
        tables = contract.get("tables", [])
        _inject_designed_models(tables)
        for table in tables:
            _flag_fk_columns(table.get("columns", []))
            _flag_computed_fields(table)

        continue_on_error = bool(options.get("continue_on_error", False))
        tables, collector = _validate_tables_for_scaffold(tables, continue_on_error=continue_on_error, pivot_detection_threshold=0.5)
        contract["tables"] = tables

        tab_headers = {}
        for tab in bundle_config.get("tabs", []):
            title = tab.get("worksheet_title", "")
            cols = tab.get("required_headers", [])
            if title:
                tab_headers[title] = {"columns": cols}
        merge_candidates = _suggest_tab_merges(tab_headers)
        if merge_candidates:
            contract["_merge_candidates"] = merge_candidates
        return contract, collector

    def _handle_cohort_corpus(
        self, cohort_dir: Path, *, hardened: bool, continue_on_error: bool = False
    ) -> tuple[dict[str, Any], PartialOutputCollector]:
        coverage_files = sorted(cohort_dir.glob("deep_profile_coverage_*.json"))
        if not coverage_files:
            raise CommandError(f"No deep_profile_coverage_*.json found in {cohort_dir}")
        coverage_path = coverage_files[-1]
        coverage_payload = load_json(coverage_path)
        deep_dir = cohort_dir / "deep"
        if not deep_dir.is_dir():
            raise CommandError(
                f"Expected a deep/ subdirectory inside {cohort_dir}; none found"
            )
        pivot_threshold = float(coverage_payload.get("pivot_detection_threshold", 0.5))
        contract, collector = _build_cohort_contract(
            deep_dir,
            coverage_payload,
            hardened=hardened,
            continue_on_error=continue_on_error,
            pivot_detection_threshold=pivot_threshold,
        )
        return contract, collector
