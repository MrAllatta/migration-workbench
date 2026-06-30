"""Build pipeline manifest dicts from contract + corpus config.

A *pipeline manifest* is a machine-generated, machine-readable execution plan
that bridges profile artifacts and the schema contract to the pull/import
commands. It is generated (never hand-edited) and can be regenerated at any
time from its source artifacts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PIPELINE_MANIFEST_VERSION = "1.0"


def _slugify_model_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "model"


def _load_corpus_index(corpus_dir: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    p = Path(corpus_dir)
    if not p.is_dir():
        return index
    for f in sorted(p.glob("in_scope_workbook_index_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for wb in data.get("workbooks") or []:
            year = wb.get("year")
            if year is not None:
                key = str(year)
                index.setdefault(key, {})
                index[key][wb.get("workbook_code", "")] = wb
    return index


def build_pipeline_manifest(
    contract: dict[str, Any],
    corpus_config: dict[str, Any],
    *,
    corpus_dir: str | None = None,
) -> dict[str, Any]:
    """Build a pipeline manifest dict from contract and corpus config.

    Args:
        contract: Parsed schema-contract dict (v1.0+).
        corpus_config: Parsed cohort_corpus JSON config with years and
            workbook_codes mappings.
        corpus_dir: Optional path to directory containing
            ``in_scope_workbook_index_*.json`` files for per-year
            spreadsheet ID resolution.

    Returns:
        dict: Pipeline manifest with version, source, and tables.
    """
    corpus_years: list[int] = []
    years_config = corpus_config.get("years") or {}
    for year_key, year_info in years_config.items():
        corpus_years.append(int(year_key))
    corpus_years.sort()

    workbook_codes = corpus_config.get("workbook_codes") or {}

    corpus_index = _load_corpus_index(corpus_dir) if corpus_dir else {}

    tables_out: list[dict[str, Any]] = []
    for table in contract.get("tables") or []:
        model_name = str(table.get("suggested_model_name") or "")
        title = str(table.get("bundle_worksheet_title") or "")
        import_cfg = table.get("import_config") or {}
        columns = table.get("columns") or []

        required_headers = [
            str(c["source_column"])
            for c in columns
            if c.get("source_column") and not c.get("formula_pattern") == "empty"
        ]

        default_values: dict[str, Any] = {}
        if import_cfg.get("defaults"):
            default_values = dict(import_cfg["defaults"])
        default_values["source_bundle_year"] = "{year}"

        year_entries: list[dict[str, Any]] = []
        for year in corpus_years:
            year_key = str(year)
            year_info = years_config.get(year_key, {})
            workbook_ids = year_info.get("workbook_ids") or {}

            spreadsheet_id = ""
            worksheet_title = title

            for code in workbook_codes:
                if (
                    corpus_index
                    and year_key in corpus_index
                    and code in corpus_index[year_key]
                ):
                    wid = corpus_index[year_key][code].get("spreadsheet_id", "")
                    if wid and not spreadsheet_id:
                        spreadsheet_id = wid
                elif code in workbook_ids:
                    wid = workbook_ids[code]
                    if not spreadsheet_id:
                        spreadsheet_id = wid

            year_entries.append(
                {
                    "year": year,
                    "spreadsheet_id": spreadsheet_id,
                    "worksheet_title": worksheet_title,
                }
            )

        output_pattern = (
            import_cfg.get("bundle_path")
            or f"{{year}}/{_slugify_model_name(model_name)}.csv"
        )

        tables_out.append(
            {
                "model": model_name,
                "bundle_worksheet_title": title,
                "output_pattern": output_pattern,
                "default_values": default_values,
                "required_headers": required_headers,
                "years": year_entries,
            }
        )

    return {
        "version": PIPELINE_MANIFEST_VERSION,
        "generated_from": {
            "contract": "schema-contract.yaml",
            "corpus_config": "cohort_corpus.json",
        },
        "source": {
            "provider": contract.get("source", {}).get("provider")
            or corpus_config.get("provider", ""),
            "corpus_years": corpus_years,
        },
        "tables": tables_out,
    }
