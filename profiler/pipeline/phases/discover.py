"""PipelineState discover phase method.

Extracted from ``profiler.tools.pipeline_state``.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from profiler.pipeline.phases._base import _build_google_services, _load_json_artifact
from profiler.pipeline.state import _extract_approved_tabs

logger = logging.getLogger(__name__)


def discover(
    self,
    drive_service=None,
    sheets_service=None,
) -> Any:
    """Phase 0/1: Discover source tree, enumerate workbooks, and score tabs.

    Delegates to ``run_cohort_corpus()`` for profiling, then maps results
    onto discovery fields and records tab-scoring decisions.

    Parameters
    ----------
    drive_service : optional
        Google Drive service handle.
    sheets_service : optional
        Google Sheets service handle.

    Returns
    -------
    PipelineState
        Self for chaining.

    Raises
    ------
    RuntimeError
        If ``source_tree`` is already populated.
    """
    if self.discovery.source_tree is not None:
        raise RuntimeError("discover: source_tree already populated")
    from profiler.tools.cohort_corpus import run_cohort_corpus

    if drive_service is None and sheets_service is None:
        drive_service, sheets_service = _build_google_services()

    out_dir = self._out_dir or Path("data/profile_snapshots")
    date_stamp = self._date_stamp or date.today().isoformat()

    folder_id = self._config.get("folder_id") or os.environ.get("DRIVE_FOLDER_ID")

    artifact_paths = run_cohort_corpus(
        drive_service=drive_service,
        sheets_service=sheets_service,
        config=self._config or {},
        out_dir=out_dir,
        date_stamp=date_stamp,
        stop_before_deep=True,
        folder_id=folder_id,
    )

    self.discovery.source_tree = _load_json_artifact(
        artifact_paths.get("discovery"), {}
    )
    # workbook_index JSON may be a dict with "records" key or a plain list.
    raw_index = _load_json_artifact(artifact_paths.get("index"), [])
    if isinstance(raw_index, dict) and "records" in raw_index:
        self.discovery.workbook_index = raw_index["records"]
    elif isinstance(raw_index, list):
        self.discovery.workbook_index = raw_index
    else:
        self.discovery.workbook_index = []
    broad_coverage = _load_json_artifact(
        artifact_paths.get("broad_coverage"), {}
    )
    if isinstance(broad_coverage, dict):
        self.discovery.broad_inventory = broad_coverage.get("results", [])
    elif isinstance(broad_coverage, list):
        self.discovery.broad_inventory = broad_coverage
    else:
        self.discovery.broad_inventory = []
    self.discovery.shortlist = _load_json_artifact(
        artifact_paths.get("tab_shortlist"), []
    )
    tab_selection_raw = _load_json_artifact(
        artifact_paths.get("tab_selection"), {}
    )
    if isinstance(tab_selection_raw, dict):
        self.discovery.approved_tabs = _extract_approved_tabs(tab_selection_raw)
    else:
        self.discovery.approved_tabs = tab_selection_raw

    shortlist_entries = self.discovery.shortlist
    if isinstance(shortlist_entries, dict):
        shortlist_entries = shortlist_entries.get("selected") or []
    for tab in shortlist_entries or []:
        score = tab.get("final_score", 0)
        confidence = min(abs(score) / 10.0, 1.0) if score else 0.5
        rationale = tab.get("breakdown_summary") or "heuristics"
        self.record_decision(
            decision_id=f"discover_tab_{tab.get('tab_title', 'unknown')}",
            phase="discover",
            description=(
                f"Scored tab '{tab.get('tab_title', 'unknown')}' ({rationale})"
            ),
            outcome="approved" if confidence >= 0.5 else "deferred",
            confidence=confidence,
            metadata={
                "score": score,
                "tab_title": tab.get("tab_title", ""),
                "workbook_code": tab.get("workbook_code", ""),
            },
        )

    self.completed_phases.append("discover")
    return self
