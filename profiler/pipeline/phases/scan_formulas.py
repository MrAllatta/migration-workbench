"""PipelineState scan_formulas phase method.

Extracted from ``profiler.tools.pipeline_state``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def scan_formulas(self, sheets_service=None) -> Any:
    """Scan approved workbooks for formula patterns.

    Reads ``formula_patterns`` from the pipeline config (populated from
    ``cohort_corpus.json``) and delegates to ``scan_workbook_patterns()``
    from the formula scanner module. Stores results in
    ``formula_scan_results`` as a dict mapping spreadsheet ID to list of
    cell-level match records.

    Parameters
    ----------
    sheets_service : optional
        Google Sheets service handle.

    Returns
    -------
    PipelineState
        Self for chaining.
    """
    if "scan_formulas" in self.completed_phases:
        logger.warning("scan_formulas already completed, skipping")
        return self

    formula_config = self._config.get("formula_patterns", {})
    if not formula_config or not formula_config.get("workbooks"):
        logger.warning("No formula_patterns config found \u2014 skipping formula scan")
        return self

    from profiler.tools.formula_scanner import scan_workbook_patterns

    workbook_list = formula_config["workbooks"]
    scan_results: dict[str, list[dict]] = {}
    for workbook_entry in workbook_list:
        spreadsheet_id = workbook_entry.get("spreadsheet_id")
        patterns_raw = workbook_entry.get("patterns", [])
        if not spreadsheet_id or not patterns_raw:
            logger.info(
                "Skipping workbook entry with missing spreadsheet_id or patterns"
            )
            continue

        # Convert pattern definitions to (name, compiled_regex) tuples
        compiled_patterns = []
        for pattern_entry in patterns_raw:
            if isinstance(pattern_entry, dict):
                name = pattern_entry.get("name", "unnamed")
                regex = pattern_entry.get("regex", "")
            else:
                name = f"pattern_{len(compiled_patterns)}"
                regex = str(pattern_entry)
            if regex:
                compiled_patterns.append((name, re.compile(regex)))

        if not compiled_patterns:
            continue

        try:
            matches = scan_workbook_patterns(
                sheets_service, spreadsheet_id, compiled_patterns
            )
            if matches:
                scan_results[spreadsheet_id] = matches
                logger.info(
                    "Formula scan for %s: %d matches across %d patterns",
                    spreadsheet_id,
                    len(matches),
                    len(compiled_patterns),
                )
            else:
                logger.info(
                    "Formula scan for %s: no matches found",
                    spreadsheet_id,
                )
        except Exception:
            logger.exception(
                "Formula scan failed for spreadsheet %s",
                spreadsheet_id,
            )

    self.formula_scan_results = scan_results

    self.record_artifact_provenance(
        artifact_key="formula_scan_results",
        source="inferred",
        signals=[
            {
                "phase": "scan_formulas",
                "workbooks_scanned": len(workbook_list),
                "workbooks_with_matches": len(scan_results),
            }
        ],
    )

    self.completed_phases.append("scan_formulas")
    return self
