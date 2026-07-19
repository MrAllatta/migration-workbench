"""PipelineState behavioral spec phase methods.

Extracted from ``profiler.pipeline.phases.bprs``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from profiler.pipeline.phases.deep_profile import _parse_raw_deep_profile

logger = logging.getLogger(__name__)


def derive_behavioral_spec(
    self, base_dir: str | os.PathLike[str] | None = None
) -> Any:
    """Phase: Derive the behavioral specification from profiler artifacts.

    Consumes ``discovery``, ``deep_profile_index``, and ``domain_knowledge``
    to produce the MWBS BehavioralSpec artifact.

    Args:
        base_dir: Base directory for resolving ``out_json`` relative paths
            in deep profile index entries.

    Returns:
        PipelineState: Self for chaining.

    Raises:
        RuntimeError: If ``domain_knowledge.domain`` is empty.
    """
    if not self.domain_knowledge.domain:
        raise RuntimeError(
            "derive_behavioral_spec: domain_knowledge.domain is required"
        )

    from profiler.tools.behavioral_spec_elicitor import derive_behavioral_spec

    # Resolve out_json references to inline column data
    entries: list[dict[str, Any]] = []
    for entry in self.deep_profile_index.entries or []:
        entry_dict = (
            dict(entry) if hasattr(entry, "__dataclass_fields__") else dict(entry)
        )
        out_json = entry_dict.get("out_json")
        if out_json and not entry_dict.get("columns"):
            candidate_bases: list[Path] = []
            if base_dir:
                base_path = Path(base_dir)
                candidate_bases.append(base_path)
                candidate_bases.append(base_path.parent)
                candidate_bases.append(base_path.parent / "data")

            resolved = False
            for candidate_base in candidate_bases:
                candidate_path = candidate_base / out_json
                if candidate_path.exists():
                    try:
                        with open(candidate_path, "r", encoding="utf-8") as f:
                            deep_data = json.load(f)
                        columns = deep_data.get("columns") or deep_data.get(
                            "summary", {}
                        ).get("columns", [])
                        if not columns:
                            columns = _parse_raw_deep_profile(deep_data)
                        entry_dict["columns"] = columns
                        resolved = True
                        break
                    except (OSError, json.JSONDecodeError):
                        continue

            if not resolved and base_dir:
                logger.warning(
                    "Could not resolve out_json %s from base_dir %s",
                    out_json,
                    base_dir,
                )

        # Resolve dependency_json artifact paths
        dep_json = entry_dict.get("dependency_json")
        if dep_json and base_dir:
            dep_candidate_bases: list[Path] = [
                Path(base_dir),
                Path(base_dir).parent,
                Path(base_dir).parent / "data",
            ]
            dep_resolved = False
            for dep_base in dep_candidate_bases:
                dep_path = dep_base / dep_json
                if dep_path.exists():
                    try:
                        with open(dep_path, "r", encoding="utf-8") as f:
                            entry_dict["dependency_artifact"] = json.load(f)
                        dep_resolved = True
                        break
                    except (OSError, json.JSONDecodeError):
                        continue
            if not dep_resolved:
                logger.debug(
                    "Could not resolve dependency_json %s from base_dir %s",
                    dep_json,
                    base_dir,
                )

        entries.append(entry_dict)

    self.behavioral_spec = derive_behavioral_spec(
        discovery={
            "workbook_index": self.discovery.workbook_index,
            "broad_inventory": self.discovery.broad_inventory,
        },
        deep_profile_index={"entries": entries},
        domain_knowledge={
            "domain": self.domain_knowledge.domain,
            "vocabulary": self.domain_knowledge.vocabulary,
        },
        interaction_contract=self.interaction_contract,
    )

    # Populate operator_priority from behavioral spec project metadata
    if self.behavioral_spec and self.behavioral_spec.project:
        project = self.behavioral_spec.project
        if project.operator:
            self.operator_priority[project.operator] = 1
        if project.developer:
            self.operator_priority[project.developer] = 2

    return self


def derive_state_projections(
    self, projection: str = "schema_contract"
) -> Any:
    """Phase: Derive state projections from the operational model.

    Currently supports ``schema_contract``, ``test_scaffold``, and
    ``doc_scaffold`` projections.

    Args:
        projection: Which projection to derive. Defaults to
            ``schema_contract``.

    Returns:
        PipelineState: Self for chaining.

    Raises:
        RuntimeError: If ``operational_model`` is not populated.
        ValueError: If *projection* is not supported.
    """
    if self.operational_model is None:
        raise RuntimeError(
            "derive_state_projections: operational_model must be derived first"
        )

    if projection == "schema_contract":
        from profiler.pipeline.phases.operational_model import (
            _derive_schema_contract_from_operational_model,
        )

        self.schema_contract = _derive_schema_contract_from_operational_model(self)
    elif projection == "test_scaffold":
        from profiler.pipeline.phases.operational_model import (
            _derive_test_scaffold_from_operational_model,
        )

        self.test_scaffold = _derive_test_scaffold_from_operational_model(self)
    elif projection == "doc_scaffold":
        from profiler.pipeline.phases.operational_model import (
            _derive_doc_scaffold_from_operational_model,
        )

        self.doc_scaffold = _derive_doc_scaffold_from_operational_model(self)
    else:
        raise ValueError(f"Unsupported projection: {projection}")

    return self


def validate_behavioral_spec(
    self, base_dir: str | os.PathLike[str] | None = None
) -> Any:
    """Phase: Validate the behavioral spec, computing coverage.

    Uses the new MWBS :func:`compute_coverage_metrics` which takes a
    single ``BehavioralSpec`` argument (not ``OperationalModel`` + dict).

    Returns:
        PipelineState: Self for chaining.

    Raises:
        RuntimeError: If ``behavioral_spec`` is not populated.
    """
    if self.behavioral_spec is None:
        raise RuntimeError(
            "validate_behavioral_spec: behavioral_spec must be derived first"
        )

    from profiler.tools.behavioral_spec_validation import compute_coverage_metrics

    self.coverage_report = compute_coverage_metrics(self.behavioral_spec)
    return self
