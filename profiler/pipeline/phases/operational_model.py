"""PipelineState operational model phase methods.

Extracted from ``profiler.pipeline.phases.bprs``.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from profiler.pipeline.phases.deep_profile import _parse_raw_deep_profile

logger = logging.getLogger(__name__)


def derive_operational_model(
    self, base_dir: str | os.PathLike[str] | None = None
) -> Any:
    """Phase: Derive the operational model from profiler artifacts.

    Consumes ``discovery``, ``deep_profile_index``, and ``domain_knowledge``
    to produce the primary BPRS artifact.

    Args:
        base_dir: Base directory for resolving ``out_json`` relative paths
            in deep profile index entries.  If ``None``, entries with
            ``out_json`` but no inline ``columns`` are passed through
            unresolved.

    Returns:
        PipelineState: Self for chaining.

    Raises:
        RuntimeError: If ``domain_knowledge.domain`` is empty.
    """
    if not self.domain_knowledge.domain:
        raise RuntimeError(
            "derive_operational_model: domain_knowledge.domain is required"
        )

    from profiler.tools.operational_model_deriver import derive_operational_model

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

        # Resolve dependency_json artifact paths (formula dependency graph)
        # so the deriver can consume them without file I/O.
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

    self.operational_model = derive_operational_model(
        discovery={
            "workbook_index": self.discovery.workbook_index,
            "broad_inventory": self.discovery.broad_inventory,
        },
        deep_profile_index={"entries": entries},
        domain_knowledge={
            "domain": self.domain_knowledge.domain,
            "vocabulary": self.domain_knowledge.vocabulary,
        },
    )
    return self


def _derive_schema_contract_from_operational_model(self) -> dict[str, Any]:
    """Derive a schema contract dict from the operational model.

    Maps events to contract tables, payloads to columns, and invariants
    to constraints.

    Returns:
        dict: Schema contract compatible with existing codegen.
    """
    # Guard is enforced by the caller, but type checker needs this.
    assert self.operational_model is not None

    tables: list[dict[str, Any]] = []
    for event in self.operational_model.events or []:
        columns: list[dict[str, Any]] = []
        for field_name in event.payload or []:
            columns.append(
                {
                    "source_column": field_name,
                    "suggested_field_name": field_name.lower().replace(" ", "_"),
                    "django_field_class": "models.CharField",
                    "django_field_kwargs": {"max_length": 255, "blank": True},
                }
            )

        tables.append(
            {
                "suggested_model_name": event.id.lower().replace(" ", "_"),
                "bundle_worksheet_title": (
                    event.sourced_from[0]["tab"] if event.sourced_from else ""
                ),
                "columns": columns,
            }
        )

    return {"version": "1.1", "tables": tables}


def _derive_test_scaffold_from_operational_model(self) -> str:
    """Derive a pytest test file string from the operational model.

    Generates test classes for invariants, workflows, and events
    based on the operational model data.

    Returns:
        str: Python source code for a pytest test module.
    """
    assert self.operational_model is not None

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_id = self.operational_model.source_id or "unknown"

    # --- Invariant tests ---
    invariant_tests_lines: list[str] = []
    for invariant in self.operational_model.invariants or []:
        if invariant.enforcement == "database_check":
            safe_name = invariant.id.lower().replace(" ", "_").replace("-", "_")
            expression = invariant.expression or ""
            invariant_tests_lines.append(f"""    def test_{safe_name}(self):
        \"\"\"{expression}\"\"\"
        # TODO: implement with real model instances
        pass
""")
    if not invariant_tests_lines:
        invariant_tests_lines.append(
            "    # No database_check invariants defined.\n"
        )
    invariant_tests = "\n".join(invariant_tests_lines).rstrip()

    # --- Workflow tests ---
    workflow_tests_lines: list[str] = []
    for workflow in self.operational_model.workflows or []:
        safe_name = workflow.id.lower().replace(" ", "_").replace("-", "_")
        commands_ids = workflow.commands or []
        commands_list_repr = str(commands_ids)
        workflow_tests_lines.append(f"""    def test_{safe_name}_has_commands(self):
        \"\"\"Workflow {workflow.id} must have at least one command.\"\"\"
        commands_list = {commands_list_repr}
        assert len(commands_list) >= 1
""")
    if not workflow_tests_lines:
        workflow_tests_lines.append("    # No workflows defined.\n")
    workflow_tests = "\n".join(workflow_tests_lines).rstrip()

    # --- Event tests ---
    event_tests_lines: list[str] = []
    for event in self.operational_model.events or []:
        safe_name = event.id.lower().replace(" ", "_").replace("-", "_")
        payload_list = event.payload or []
        payload_list_repr = str(payload_list)
        event_tests_lines.append(f"""    def test_{safe_name}_has_payload(self):
        \"\"\"Event {event.id} must have payload fields.\"\"\"
        payload_list = {payload_list_repr}
        assert len(payload_list) >= 1
""")
    if not event_tests_lines:
        event_tests_lines.append("    # No events defined.\n")
    event_tests = "\n".join(event_tests_lines).rstrip()

    return f'''"""Auto-generated operational model tests.

Generated from operational model: {source_id}
Generated at: {timestamp}
"""

import pytest


class TestOperationalInvariants:
    """Tests derived from operational model invariants."""

{invariant_tests}


class TestOperationalWorkflows:
    """Tests derived from operational model workflows."""

{workflow_tests}


class TestOperationalEvents:
    """Tests derived from operational model events."""

{event_tests}
'''


def _derive_doc_scaffold_from_operational_model(self) -> str:
    """Derive a Markdown documentation string from the operational model.

    Generates a living documentation file describing the business operating
    system: capabilities, events, workflows, commands, and invariants.

    Returns:
        str: Markdown document as a string.
    """
    assert self.operational_model is not None

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_id = self.operational_model.source_id or "unknown"

    lines: list[str] = []
    lines.append(f"# Operational Model: {source_id}")
    lines.append("")
    lines.append(f"_Generated at: {timestamp}_")
    lines.append("")
    lines.append(
        "This document describes the operational model derived from "
        "profiler evidence. It captures the business operating system's "
        "capabilities, events, workflows, commands, and invariants."
    )
    lines.append("")

    # --- Capabilities ---
    lines.append("## Capabilities")
    lines.append("")
    capabilities = self.operational_model.capabilities or []
    if capabilities:
        for capability in capabilities:
            owners_str = capability.owner or "unknown"
            lines.append(f"- **{capability.id}** \u2014 Owner: {owners_str}")
    else:
        lines.append("*No capabilities defined.*")
    lines.append("")

    # --- Events ---
    lines.append("## Events")
    lines.append("")
    events = self.operational_model.events or []
    if events:
        lines.append("| Event ID | Payload Fields | Source Tab/Column |")
        lines.append("|----------|----------------|--------------------|")
        for event in events:
            payload_str = ", ".join(event.payload or []) or "*empty*"
            source_parts = []
            for src in event.sourced_from or []:
                tab = src.get("tab", "")
                column = src.get("column", "")
                if tab and column:
                    source_parts.append(f"{tab}.{column}")
                elif tab:
                    source_parts.append(tab)
                elif column:
                    source_parts.append(column)
            source_str = "; ".join(source_parts) if source_parts else "*unknown*"
            lines.append(f"| `{event.id}` | {payload_str} | {source_str} |")
    else:
        lines.append("*No events defined.*")
    lines.append("")

    # --- Workflows ---
    lines.append("## Workflows")
    lines.append("")
    workflows = self.operational_model.workflows or []
    if workflows:
        for workflow in workflows:
            lines.append(f"### {workflow.id}")
            lines.append("")
            if workflow.frequency:
                lines.append(f"- **Frequency:** {workflow.frequency}")
            if workflow.actor:
                lines.append(f"- **Actor:** {workflow.actor}")
            if workflow.outcome:
                lines.append(f"- **Outcome:** {workflow.outcome}")
            if workflow.commands:
                commands_list = ", ".join(f"`{cmd}`" for cmd in workflow.commands)
                lines.append(f"- **Commands:** {commands_list}")
            if workflow.evidence:
                evidence_list = ", ".join(workflow.evidence)
                lines.append(f"- **Evidence:** {evidence_list}")
            lines.append("")
    else:
        lines.append("*No workflows defined.*")
    lines.append("")

    # --- Commands ---
    lines.append("## Commands")
    lines.append("")
    commands = self.operational_model.commands or []
    if commands:
        for command in commands:
            lines.append(f"- `{command.id}`")
    else:
        # Collect unique command IDs from workflows as fallback
        command_ids: set[str] = set()
        for workflow in workflows:
            for cmd_id in workflow.commands or []:
                command_ids.add(cmd_id)
        if command_ids:
            for cmd_id in sorted(command_ids):
                lines.append(f"- `{cmd_id}`")
        else:
            lines.append("*No commands defined.*")
    lines.append("")

    # --- Invariants ---
    lines.append("## Invariants")
    lines.append("")
    invariants = self.operational_model.invariants or []
    if invariants:
        lines.append(
            "| Invariant ID | Expression | Enforcement | Violations Handling |"
        )
        lines.append(
            "|--------------|------------|-------------|---------------------|"
        )
        for invariant in invariants:
            expression_str = invariant.expression or "*none*"
            enforcement_str = invariant.enforcement or "application_logic"
            violations_str = invariant.violations_are or "warning"
            lines.append(
                f"| `{invariant.id}` | `{expression_str}` "
                f"| {enforcement_str} | {violations_str} |"
            )
    else:
        lines.append("*No invariants defined.*")
    lines.append("")

    # --- Event-to-Workflow Mapping ---
    lines.append("## Event-to-Workflow Mapping")
    lines.append("")
    # Build mapping by finding workflow/event pairs that share terms
    mapping_found = False
    workflow_event_terms: dict[str, set[str]] = {}
    for workflow in workflows:
        terms: set[str] = set()
        terms.add(workflow.id.lower())
        for cmd in workflow.commands or []:
            terms.add(cmd.lower())
        workflow_event_terms[workflow.id] = terms

    for event in events:
        event_terms: set[str] = set()
        event_terms.add(event.id.lower())
        for payload_field in event.payload or []:
            event_terms.add(payload_field.lower())

        matched = False
        for workflow_id, wf_terms in workflow_event_terms.items():
            shared = event_terms & wf_terms
            if shared:
                lines.append(
                    f"- Event `{event.id}` may trigger workflow "
                    f"`{workflow_id}` (shared terms: "
                    f"{', '.join(sorted(shared))})"
                )
                matched = True
                mapping_found = True

        if not matched:
            lines.append(f"- Event `{event.id}` \u2014 no workflow mapping identified")

    if not mapping_found and not events and not workflows:
        lines.append("*No event-to-workflow mappings available.*")
    lines.append("")

    return "\n".join(lines)


def validate_operational_model(self) -> Any:
    """Phase: Validate the operational model and compute coverage.

    This is a human review gate. The method computes coverage metrics
    and records a validation record.

    Returns:
        PipelineState: Self for chaining.

    Raises:
        RuntimeError: If ``operational_model`` is not populated.
    """
    if self.operational_model is None:
        raise RuntimeError(
            "validate_operational_model: operational_model must be derived first"
        )

    from profiler.tools.validation_framework import (
        CoverageReport,
        compute_coverage_metrics,
    )

    # Backward compat: derive behavioral_spec if not already set, so we
    # can use the new MWBS compute_coverage_metrics (single-arg).
    if self.behavioral_spec is None and self.domain_knowledge.domain:
        self.derive_behavioral_spec()

    if self.behavioral_spec is not None:
        self.coverage_report = compute_coverage_metrics(self.behavioral_spec)
    else:
        self.coverage_report = CoverageReport()
    return self
