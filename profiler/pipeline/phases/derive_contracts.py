"""PipelineState derive_contracts phase method and helpers.

Extracted from ``profiler.tools.pipeline_state``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from profiler.pipeline.phases.deep_profile import _extract_columns_from_entry

logger = logging.getLogger(__name__)


def derive_contracts(self) -> Any:
    """Derive schema and interaction contracts from deep profile data.

    Builds a schema contract from ``deep_profile_index.entries`` by
    creating model names and field definitions for each profiled tab.

    Returns
    -------
    PipelineState
        Self for chaining.

    Raises
    ------
    RuntimeError
        If ``deep_profile_index.entries`` is empty (the list is
        never ``None`` \u2014 it defaults to ``[]``).
    """
    if not self.deep_profile_index.entries:
        raise RuntimeError("derive_contracts: deep_profile must run first")
    tables: list[dict] = []
    for entry in self.deep_profile_index.entries:
        tab_name = entry.get("tab_title") or entry.get("tab", "unknown")
        columns = _extract_columns_from_entry(self, entry)
        fields = []
        for col in columns:
            col_name = col.get("header", "unknown")
            col_type = col.get("data_type", "string")
            fields.append(
                {
                    "name": col_name,
                    "source_column": col_name,
                    "data_type": col_type,
                }
            )

        # Convert tab name to PascalCase model name
        model_name = "".join(
            word.capitalize()
            for word in tab_name.replace("-", "_").replace(" ", "_").split("_")
        )
        table = {
            "model_name": model_name,
            "source_tab": tab_name,
            "fields": fields,
        }
        tables.append(table)

        self.record_decision(
            decision_id=f"model_{tab_name}",
            phase="derive_contracts",
            description=(
                f"Derived model name '{model_name}' from tab title '{tab_name}'"
            ),
            outcome="approved",
            confidence=0.7,
            metadata={"tab_name": tab_name, "model_name": model_name},
        )

    self.schema_contract = {"tables": tables}

    # Record provenance for the derived schema contract
    if self.schema_contract:
        self.record_artifact_provenance(
            artifact_key="schema_contract",
            source="inferred",
            signals=[
                {
                    "phase": "derive_contracts",
                    "tables_count": len(self.schema_contract.get("tables", [])),
                }
            ],
        )

    self.interaction_contract = {"views": []}

    # --- Tab Classification ---
    _classify_deep_profiled_tabs(self)

    # --- Filter out UI-config tabs ---
    _filter_ui_config_tabs(self)

    # Emit profiler signals alongside contracts
    _emit_profiler_signals(self)

    self.completed_phases.append("derive_contracts")
    return self


def _classify_deep_profiled_tabs(self) -> None:
    """Classify deep-profiled tabs and store results in the interaction contract.

    Uses ``classify_tabs_batch`` from the tab classifier module. Collects
    classification signals, records a decision with the summary, and stores
    per-tab classification in the interaction contract.
    """
    try:
        from profiler.tools.tab_classifier import (
            classify_tabs_batch,
            classification_summary,
        )
    except ImportError:
        logger.warning("tab_classifier not available \u2014 skipping classification")
        return

    tab_entries: list[dict] = []
    for entry in self.deep_profile_index.entries:
        tab_title = entry.get("tab_title") or entry.get("tab", "unknown")
        tab_entries.append(
            {
                "tab_title": tab_title,
                "rows": entry.get("total_rows", 0),
                "cols": entry.get("total_cols", 0),
                "score": entry.get("score", 0),
                "reasons": entry.get("scoring_reasons", []),
                "breakdown": entry.get("breakdown", {}),
            }
        )

    if not tab_entries:
        return

    classifications = classify_tabs_batch(tab_entries)
    summary = classification_summary(classifications)

    self.record_decision(
        decision_id="tab_classification",
        phase="derive_contracts",
        description=(
            f"Classified {summary['total']} tabs: "
            f"{summary['classified']} classified, "
            f"{summary['coverage_pct']}% coverage"
        ),
        outcome="approved",
        confidence=summary["coverage_pct"] / 100.0 if summary["total"] > 0 else 0.0,
        metadata={
            "total": summary["total"],
            "classified": summary["classified"],
            "coverage_pct": summary["coverage_pct"],
            "counts": summary["counts"],
        },
    )

    # Store per-tab classification in interaction contract
    if self.interaction_contract is None:
        self.interaction_contract = {"views": []}
    self.interaction_contract["tab_classifications"] = {
        c.tab_title: {
            "category": c.category,
            "confidence": c.confidence,
            "rationale": c.rationale,
        }
        for c in classifications
    }


def _filter_ui_config_tabs(self) -> None:
    """Filter out UI-config tabs from the schema contract.

    Reads ``tab_classifications`` from ``interaction_contract`` and
    removes any table from ``schema_contract["tables"]`` whose
    ``source_tab`` is classified as ``ui_config``. Records a decision
    for each excluded tab.

    Only excludes tabs whose deep profile entry has explicit
    ``total_rows`` or ``total_cols`` keys (meaning the entry was
    produced by a real deep-profile run, not a test stub).

    Gracefully skips if ``interaction_contract`` is ``None`` or
    ``tab_classifications`` is missing (backward compatibility).
    """
    if self.interaction_contract is None or self.schema_contract is None:
        return
    tab_classifications = self.interaction_contract.get("tab_classifications")
    if not tab_classifications:
        return

    ui_config_tabs: set[str] = {
        tab_title
        for tab_title, classification in tab_classifications.items()
        if classification.get("category") == "ui_config"
    }
    if not ui_config_tabs:
        return

    # Determine which tabs have real profile dimensionality data.
    # Entries that lack total_rows/total_cols are test stubs and
    # should not be filtered (the classifier falls back to defaults
    # that may not reflect real classification).
    profiled_tabs: set[str] = set()
    for entry in self.deep_profile_index.entries:
        tab_title = entry.get("tab_title") or entry.get("tab", "unknown")
        if "total_rows" in entry or "total_cols" in entry:
            profiled_tabs.add(tab_title)

    original_tables = self.schema_contract.get("tables", [])
    filtered_tables: list[dict] = []
    for table in original_tables:
        source_tab = table.get("source_tab", "")
        if source_tab in ui_config_tabs and source_tab in profiled_tabs:
            classification = tab_classifications.get(source_tab, {})
            confidence = classification.get("confidence", 0.0)
            sanitized = source_tab.replace(" ", "_").replace("-", "_")
            self.record_decision(
                decision_id=f"exclude_ui_config_{sanitized}",
                phase="derive_contracts",
                description=(
                    f"Excluded tab '{source_tab}' from schema contract"
                    " \u2014 classified as ui_config"
                ),
                outcome="excluded",
                confidence=confidence,
                metadata={
                    "tab_name": source_tab,
                    "category": "ui_config",
                    "confidence": confidence,
                },
            )
        else:
            filtered_tables.append(table)

    self.schema_contract["tables"] = filtered_tables


def _emit_profiler_signals(self) -> None:
    """Build and write profiler-signals YAML from deep profile index.

    Constructs a structure-like dict from ``deep_profile_index.entries``,
    then extracts signals via ``extract_signals`` and writes the result
    as a YAML artifact.  Sets ``profiler_signals_path`` to the absolute
    path of the written file.
    """
    if not self.deep_profile_index.entries:
        return

    from workbook.tools.signal_extraction import extract_signals

    from profiler.pipeline.phases.deep_profile import _extract_columns_from_entry

    # Build a minimal structure dict from deep-profile index entries
    fake_tabs: list[dict] = []
    for entry in self.deep_profile_index.entries:
        tab_title = entry.get("tab_title") or entry.get("tab", "unknown")
        columns = _extract_columns_from_entry(self, entry)
        cols_out: list[dict] = []
        for col in columns:
            cols_out.append(
                {
                    "header_label": col.get("header", "unknown"),
                    "is_formula": col.get("is_formula", False),
                }
            )
        fake_tabs.append(
            {
                "worksheet_title": tab_title,
                "columns": cols_out,
                "total_rows": entry.get("total_rows", 0),
                "total_cols": len(cols_out),
                "named_ranges": [],
                "filter_views": [],
            }
        )

    fake_structure: dict[str, Any] = {
        "schema_version": "structure-draft-1",
        "source_id": self._config.get("source_id", ""),
        "provider": self._config.get("provider", "google_sheets"),
        "tabs": fake_tabs,
    }

    # Pass tab classifications into signal extraction if available
    tab_classifications = None
    if (
        self.interaction_contract
        and "tab_classifications" in self.interaction_contract
    ):
        tab_classifications = self.interaction_contract["tab_classifications"]

    signals = extract_signals(
        fake_structure,
        tab_classifications=tab_classifications,
    )

    # Determine output path: prefer runtime override, then alongside checkpoint
    signals_path = self._signals_output_path or (
        (self._out_dir or Path("build")).parent / "profiler-signals.yaml"
    )
    signals_path = Path(signals_path)
    signals_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("PyYAML not available \u2014 skipping signals artifact")
        return

    try:
        signals_path.write_text(
            yaml.safe_dump(
                signals,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        self.profiler_signals_path = str(signals_path.resolve())
        logger.info("wrote profiler signals to %s", self.profiler_signals_path)
    except Exception as exc:
        logger.warning(
            "failed to write profiler signals to %s: %s",
            signals_path,
            exc,
        )
