"""PipelineState deep_profile phase method and helpers.

Extracted from ``profiler.tools.pipeline_state``.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from profiler.pipeline.phases._base import _load_json_artifact
from profiler.pipeline.state import _col_index_to_letter

logger = logging.getLogger(__name__)


def deep_profile(self, sheets_service=None) -> Any:
    """Phase 3: Deep-profile approved tabs.

    Delegates to ``run_cohort_corpus()`` in resume mode, then populates
    ``deep_profile_index.entries`` and records FK candidate decisions.

    Parameters
    ----------
    sheets_service : optional
        Google Sheets service handle.

    Returns
    -------
    PipelineState
        Self for chaining.

    Raises
    ------
    RuntimeError
        If ``approved_tabs`` is ``None``.
    """
    if self.discovery.approved_tabs is None:
        raise RuntimeError("deep_profile: no approved_tabs")
    from profiler.tools.cohort_corpus import run_cohort_corpus

    out_dir = self._out_dir or Path("data/profile_snapshots")
    date_stamp = self._date_stamp or date.today().isoformat()

    artifact_paths = run_cohort_corpus(
        drive_service=None,
        sheets_service=sheets_service,
        config=self._config or {},
        out_dir=out_dir,
        date_stamp=date_stamp,
        resume_from_tab_selection=True,
    )

    deep_coverage = _load_json_artifact(
        artifact_paths.get("deep_coverage"), {}
    )
    if isinstance(deep_coverage, list):
        self.deep_profile_index.entries = deep_coverage
    elif isinstance(deep_coverage, dict):
        self.deep_profile_index.entries = deep_coverage.get(
            "results", list(deep_coverage.values())
        )

    for entry in self.deep_profile_index.entries:
        for fk_candidate in entry.get("fk_candidates") or []:
            col = fk_candidate.get("column", "unknown")
            target = fk_candidate.get("target", "unknown")
            confidence = fk_candidate.get("confidence", 0.5)
            entry_tab = entry.get("tab_title") or entry.get("tab", "unknown")
            self.record_decision(
                decision_id=f"fk_{entry_tab}_{col}",
                phase="deep_profile",
                description=(f"FK candidate: {entry_tab}.{col} -> {target}"),
                outcome="approved" if confidence >= 0.5 else "deferred",
                confidence=confidence,
                metadata={
                    "tab": entry_tab,
                    "column": col,
                    "target": target,
                },
            )

    for entry in self.deep_profile_index.entries:
        try:
            _enrich_entry_with_formula_dependencies(
                self,
                entry,
                out_dir=out_dir,
                date_stamp=date_stamp,
            )
        except ImportError:
            logger.info(
                "formula_dependency module not available \u2014 "
                "skipping dependency analysis"
            )
            break

    self.completed_phases.append("deep_profile")
    return self


def _enrich_entry_with_formula_dependencies(
    self,
    entry: dict[str, Any],
    out_dir: Path,
    date_stamp: str,
) -> None:
    """Run formula dependency analysis on a single deep-profile entry.

    If the entry has raw cell data with formulas, this method:
    1. Parses all formulas into a dependency graph.
    2. Saves the dependency artifact alongside the profile artifact.
    3. Computes dependency signals (cross-sheet edges, high-value nodes).
    4. Enriches column profiles with dependency-derived metadata.
    """
    out_json_path = entry.get("out_json")
    if not out_json_path:
        return

    profile_data = _load_json_artifact(out_dir / out_json_path, None)
    if profile_data is None:
        return

    raw = profile_data.get("raw", {})
    if not raw:
        return

    try:
        from connectors.spreadsheet import (
            raw_sheet_to_row_lists,
            guess_header_row,
        )
    except ImportError:
        logger.warning(
            "connectors.spreadsheet not available \u2014 "
            "skipping dependency analysis for %s",
            out_json_path,
        )
        return

    try:
        row_lists = raw_sheet_to_row_lists(raw)
        header_index = guess_header_row(row_lists)
    except Exception:
        logger.warning(
            "failed to parse raw sheet data from %s",
            out_json_path,
        )
        return

    if header_index is None:
        return

    headers = row_lists[header_index]
    tab_title = entry.get("tab_title") or entry.get("tab", "unknown")

    formula_cells: list[dict[str, str]] = []
    column_cells: dict[str, dict] = {}

    for col_idx in range(len(headers)):
        header = str(headers[col_idx]).strip()
        col_letter = _col_index_to_letter(col_idx + 1)
        col_cells = []
        for row_idx in range(header_index + 1, len(row_lists)):
            cell_value = (
                row_lists[row_idx][col_idx]
                if col_idx < len(row_lists[row_idx])
                else ""
            )
            cell_addr = f"{col_letter}{row_idx + 1}"
            cell_text = str(cell_value) if cell_value is not None else ""

            if isinstance(cell_value, str) and cell_value.startswith("="):
                formula_cells.append(
                    {
                        "sheet": tab_title,
                        "cell": cell_addr,
                        "formula": cell_value,
                    }
                )
                col_cells.append({"kind": "formula", "text": cell_value})
            elif cell_text == "" or cell_text is None:
                col_cells.append({"kind": "empty", "text": ""})
            else:
                col_cells.append({"kind": "string", "text": cell_text})

        if header:
            column_cells[col_letter] = {
                "header": header,
                "column_cells": col_cells,
                "tab_name": tab_title,
            }

    if not formula_cells:
        return

    from profiler.tools.formula_dependency import (
        build_dependency_artifact,
        compute_dependency_signals,
        parse_cells,
    )
    from profiler.tools.enrichment_utils import (
        enrich_fk_from_sheet_graph,
        enrich_from_dependency_graph,
    )

    parsed = parse_cells(formula_cells)
    workbook_key = entry.get("workbook_key") or Path(out_json_path).stem
    artifact = build_dependency_artifact(parsed, workbook_key=workbook_key)
    signals = compute_dependency_signals(artifact)

    artifact.update(signals)

    dep_path = out_dir / f"dependency_{Path(out_json_path).stem}.json"
    dep_path.parent.mkdir(parents=True, exist_ok=True)
    dep_path.write_text(
        __import__("json").dumps(artifact, indent=2),
        encoding="utf-8",
    )
    entry["dependency_json"] = str(dep_path.relative_to(out_dir))

    enrich_from_dependency_graph(column_cells, artifact)
    enrich_fk_from_sheet_graph(column_cells, artifact)

    computed_fields = entry.setdefault("computed_fields", [])
    for col_key, profile in column_cells.items():
        if profile.get("is_computed"):
            computed_fields.append(
                {
                    "column": col_key,
                    "header": profile["header"],
                    "source": profile.get("computed_from", []),
                }
            )
        fk_target = profile.get("suggested_fk_target")
        if fk_target:
            fk_candidates = entry.setdefault("fk_candidates", [])
            if not any(fc.get("column") == col_key for fc in fk_candidates):
                fk_candidates.append(
                    {
                        "column": col_key,
                        "target": fk_target,
                        "confidence": 0.6,
                    }
                )

    logger.info(
        "dependency analysis for %s: %d formulas, %d cross-sheet edges",
        tab_title,
        len(parsed),
        len(signals.get("cross_sheet_edges", [])),
    )


def _extract_columns_from_entry(self, entry: dict[str, Any]) -> list[dict]:
    """Extract column definitions from a deep profile index entry.

    When the entry has inline ``columns`` (the old test-only format),
    return them directly.  When the entry references an ``out_json``
    profile file produced by ``cohort_corpus``, load the profile and
    extract column headers from the raw sheet data.

    Args:
        entry: A single entry from ``deep_profile_index.entries``.

    Returns:
        List of column dicts with ``header`` and ``data_type`` keys,
        or an empty list when no column data is available.
    """
    columns = entry.get("columns")
    if columns:
        return columns
    out_json_path = entry.get("out_json")
    if not out_json_path or self._out_dir is None:
        return []
    profile_data = _load_json_artifact(
        self._out_dir / out_json_path, None
    )
    if profile_data is None:
        return []
    raw = profile_data.get("raw", {})
    if not raw:
        return []
    try:
        from connectors.spreadsheet import (
            guess_header_row,
            raw_sheet_to_row_lists,
        )
    except ImportError:
        logger.warning(
            "connectors.spreadsheet not available \u2014 "
            "cannot extract columns from profile %s",
            out_json_path,
        )
        return []
    try:
        row_lists = raw_sheet_to_row_lists(raw)
        header_index = guess_header_row(row_lists)
    except Exception:
        logger.warning(
            "failed to parse raw sheet data from profile %s",
            out_json_path,
        )
        return []
    if header_index is None:
        return []
    header_texts = [
        cell_text.strip()
        for cell_text in row_lists[header_index]
        if cell_text.strip()
    ]
    return [
        {"header": header_text, "data_type": "string"}
        for header_text in header_texts
    ]


def _parse_raw_deep_profile(deep_data: dict) -> list[dict]:
    """Parse raw Google Sheets API response into enriched column entries.

    Farm's deep profile JSON files contain raw API response data without
    pre-enriched ``columns``.  This function extracts headers from the first
    row, collects non-empty values from subsequent rows, and computes null
    rate and distinct values for each column.

    Args:
        deep_data: Raw deep profile JSON dict with ``raw.sheets[0].data[0].rowData``.

    Returns:
        List of column dicts with ``header_label``, ``null_rate``, and
        ``distinct_values`` keys.
    """
    columns: list[dict] = []
    try:
        sheet = deep_data["raw"]["sheets"][0]
        data = sheet["data"][0]
        row_data = data.get("rowData", [])
        if not row_data:
            return columns

        # First row is headers
        header_row = row_data[0]
        headers: list[str] = []
        for cell in header_row.get("values", []):
            headers.append(
                cell.get("formattedValue")
                or cell.get("effectiveValue", {}).get("stringValue", "")
            )

        # Collect data for each column from subsequent rows
        col_values: list[list[str]] = [[] for _ in headers]
        for row in row_data[1:]:
            for col_index, cell in enumerate(row.get("values", [])):
                if col_index >= len(headers):
                    break
                val = cell.get("formattedValue") or cell.get("effectiveValue", {}).get(
                    "stringValue", ""
                )
                if val:
                    col_values[col_index].append(val)

        total_data_rows = len(row_data) - 1
        for col_index, header in enumerate(headers):
            values = col_values[col_index]
            null_rate = (
                (total_data_rows - len(values)) / total_data_rows
                if total_data_rows > 0
                else 0.0
            )
            columns.append(
                {
                    "header_label": header,
                    "null_rate": null_rate,
                    "distinct_values": values[:50],
                }
            )
    except (KeyError, IndexError):
        pass
    return columns
