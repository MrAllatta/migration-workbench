"""Derive an OperationalModel from existing profiler artifacts.

This module implements the BPRS Stage 4 logic: consume discovery state,
deep profile index, and domain knowledge to produce the primary operational
model artifact.
"""

from __future__ import annotations

import datetime
from typing import Any

from profiler.tools.operational_model import (
    Capability,
    Command,
    Event,
    Invariant,
    OperationalModel,
    Workflow,
)


def _cluster_tabs_into_entities(
    tabs: list[dict[str, Any]],
    jaccard_threshold: float = 0.50,
) -> list[dict[str, Any]]:
    """Cluster tabs by overlapping column sets using Jaccard similarity.

    Args:
        tabs: List of tab dicts, each with ``tab_title`` and ``columns`` list.
        jaccard_threshold: Minimum Jaccard similarity to cluster two tabs
            into the same entity.

    Returns:
        List of entity cluster dicts with ``entity_name`` and ``tabs`` keys.
    """
    clusters: list[dict[str, Any]] = []
    assigned: set[int] = set()

    for tab_index, tab in enumerate(tabs):
        if tab_index in assigned:
            continue
        title = str(tab.get("tab_title") or "")
        columns = set(tab.get("columns") or [])
        cluster_tabs = [title]
        assigned.add(tab_index)

        for other_index, other_tab in enumerate(tabs):
            if other_index in assigned:
                continue
            other_columns = set(other_tab.get("columns") or [])
            if not columns or not other_columns:
                continue
            intersection = columns & other_columns
            union = columns | other_columns
            jaccard = len(intersection) / len(union) if union else 0.0
            if jaccard >= jaccard_threshold:
                cluster_tabs.append(str(other_tab.get("tab_title") or ""))
                assigned.add(other_index)

        entity_name = title.split()[0] if title else "entity"
        clusters.append({"entity_name": entity_name, "tabs": cluster_tabs})

    return clusters


def _infer_candidate_events(
    columns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Infer candidate events from column profiles.

    A column is a candidate event source when:
    - Null rate is <= 0.20 (most rows have a value)
    - Values are categorical or timestamp-like
    - Header contains temporal keywords: "date", "time", "when", "log"

    Args:
        columns: List of column profile dicts from deep profiling.

    Returns:
        List of candidate event dicts with ``suggested_event_id`` and
        ``source_column`` keys.
    """
    temporal_keywords = {"date", "time", "when", "log", "timestamp", "at"}
    candidates: list[dict[str, Any]] = []

    for column in columns:
        header = str(column.get("header_label") or "").lower()
        null_rate = column.get("null_rate", 1.0)
        distinct_values = column.get("distinct_values") or []

        has_temporal_keyword = any(keyword in header for keyword in temporal_keywords)
        is_well_populated = null_rate <= 0.20
        is_categorical = 1 < len(distinct_values) <= 50
        is_timestamp_like = bool(distinct_values) and any(
            "-" in str(val) for val in distinct_values[:5]
        )

        if (
            has_temporal_keyword
            and is_well_populated
            and (is_categorical or is_timestamp_like)
        ):
            event_id = header.replace(" ", "_") + "_logged"
            candidates.append(
                {
                    "suggested_event_id": event_id,
                    "source_column": header,
                    "null_rate": null_rate,
                    "distinct_count": len(distinct_values),
                }
            )

    return candidates


def _infer_workflows_from_graph(
    formula_graph: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Infer candidate workflows from formula dependency graph edges.

    Args:
        formula_graph: Dependency graph dict with ``edges`` list.

    Returns:
        List of workflow candidate dicts with ``id``, ``commands``, and
        ``evidence`` keys.
    """
    if not formula_graph:
        return []

    edges = formula_graph.get("edges") or []
    if not edges:
        return []

    workflows: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for edge in edges:
        from_tab = str(edge.get("from") or "")
        to_tab = str(edge.get("to") or "")
        ref_type = str(edge.get("ref_type") or "")
        if not from_tab or not to_tab:
            continue

        pair = (from_tab, to_tab)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        workflow_id = f"{from_tab.lower().replace(' ', '_')}_to_{to_tab.lower().replace(' ', '_')}"
        workflows.append(
            {
                "id": workflow_id,
                "commands": [f"process_{from_tab.lower().replace(' ', '_')}"],
                "evidence": [from_tab, to_tab],
                "ref_type": ref_type,
            }
        )

    return workflows


def _derive_invariants_from_events(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive candidate invariants from event payloads.

    Args:
        events: List of event dicts with ``id`` and ``payload`` keys.

    Returns:
        List of invariant candidate dicts.
    """
    invariants: list[dict[str, Any]] = []
    quantity_fields = {"quantity", "amount", "balance", "count", "total"}

    for event in events:
        payload = event.get("payload") or []
        for field_name in payload:
            field_lower = str(field_name).lower()
            if any(qf in field_lower for qf in quantity_fields):
                inv_id = f"{field_lower}_never_negative"
                expression = f"{field_lower} >= 0"
                invariants.append(
                    {
                        "id": inv_id,
                        "expression": expression,
                        "enforcement": "database_check",
                        "violations_are": "blocking",
                    }
                )

    seen_ids: set[str] = set()
    unique_invariants: list[dict[str, Any]] = []
    for inv in invariants:
        if inv["id"] not in seen_ids:
            seen_ids.add(inv["id"])
            unique_invariants.append(inv)

    return unique_invariants


def derive_operational_model(
    discovery: dict[str, Any],
    deep_profile_index: dict[str, Any],
    domain_knowledge: dict[str, Any],
) -> OperationalModel:
    """Derive an OperationalModel from profiler artifacts.

    Args:
        discovery: Discovery state dict with ``workbook_index`` and
            ``broad_inventory``.
        deep_profile_index: Deep profile index dict with ``entries`` list.
        domain_knowledge: Domain knowledge dict with ``domain`` and
            ``vocabulary``.

    Returns:
        A populated OperationalModel instance.
    """
    source_id = str(domain_knowledge.get("domain", "")) if domain_knowledge else ""

    workbook_index = discovery.get("workbook_index") or []
    tabs = [
        {"tab_title": str(entry.get("tab_title") or ""), "columns": []}
        for entry in workbook_index
    ]

    entries = deep_profile_index.get("entries") or []
    tab_columns: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        tab_title = str(entry.get("tab_title") or "")
        columns = entry.get("columns") or []
        tab_columns[tab_title] = columns

    for tab in tabs:
        tab_title = tab["tab_title"]
        if tab_title in tab_columns:
            tab["columns"] = [col.get("header_label") for col in tab_columns[tab_title]]

    entity_clusters = _cluster_tabs_into_entities(tabs)

    vocabulary = (domain_knowledge.get("vocabulary") or {}) if domain_knowledge else {}
    operational_terms = vocabulary.get("operational") or []
    capabilities = [
        Capability(id=term.replace(" ", "_"), owner=source_id)
        for term in operational_terms
    ]
    if not capabilities:
        discovered_ids: list[str] = []
        for cluster in entity_clusters:
            cluster_tabs = cluster.get("tabs") or []
            has_year_suffix = any(
                any(part.isdigit() and len(part) == 4 for part in tab_name.split())
                for tab_name in cluster_tabs
            )
            if has_year_suffix:
                discovered_ids.append(cluster["entity_name"].lower())
        if discovered_ids:
            capabilities = [
                Capability(id=entity_id, owner=source_id or "unknown")
                for entity_id in dict.fromkeys(discovered_ids)
            ]
        else:
            capabilities = [
                Capability(id="discovered_operations", owner=source_id or "unknown")
            ]

    events: list[Event] = []
    for entry in entries:
        tab_title = str(entry.get("tab_title") or "")
        entry_columns = entry.get("columns") or []
        candidate_events = _infer_candidate_events(entry_columns)
        for event in candidate_events:
            events.append(
                Event(
                    id=event["suggested_event_id"],
                    payload=[event["source_column"]],
                    sourced_from=[{"tab": tab_title, "column": event["source_column"]}],
                )
            )

    cross_sheet_edges: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for entry in entries:
        tab_title = str(entry.get("tab_title") or "")

        fk_candidates = entry.get("fk_candidates") or []
        for fk in fk_candidates:
            target = fk.get("target")
            if target:
                pair = (tab_title, target)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    cross_sheet_edges.append(
                        {
                            "from": tab_title,
                            "to": target,
                            "ref_type": "FK",
                        }
                    )

        dep_artifact = entry.get("_dependency_artifact")
        if dep_artifact:
            sheet_graph = dep_artifact.get("sheet_graph", {})
            for sheet_edge in sheet_graph.get("edges", []):
                from_sheet = str(sheet_edge.get("from_sheet") or "")
                to_sheet = str(sheet_edge.get("to_sheet") or "")
                if not from_sheet or not to_sheet:
                    continue
                pair = (from_sheet, to_sheet)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    cross_sheet_edges.append(
                        {
                            "from": from_sheet,
                            "to": to_sheet,
                            "ref_type": str(sheet_edge.get("ref_type", "formula")),
                            "weight": sheet_edge.get("weight", 1.0),
                        }
                    )

    formula_graph = {"edges": cross_sheet_edges} if cross_sheet_edges else None
    workflow_candidates = _infer_workflows_from_graph(formula_graph)
    workflows = [
        Workflow(
            id=workflow["id"],
            commands=workflow.get("commands", []),
            evidence=workflow["evidence"],
        )
        for workflow in workflow_candidates
    ]

    commands = []
    for workflow in workflows:
        for command_id in workflow.commands:
            commands.append(Command(id=command_id))

    invariant_candidates = _derive_invariants_from_events(
        [{"id": event.id, "payload": event.payload} for event in events]
    )
    invariants = [
        Invariant(
            id=inv["id"],
            expression=inv["expression"],
            enforcement=inv["enforcement"],
            violations_are=inv["violations_are"],
        )
        for inv in invariant_candidates
    ]

    return OperationalModel(
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_id=source_id,
        capabilities=capabilities,
        workflows=workflows,
        commands=commands,
        events=events,
        invariants=invariants,
    )
