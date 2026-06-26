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
    jaccard_threshold: float = 0.30,
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

    A column is a candidate event source when it is well-populated
    (null rate <= 0.40) AND one of:
    - Header contains temporal keywords (date, time, when, log, timestamp, at)
    - Header contains action/decision keywords (status, stage, decision, ...)
    - Header contains quantity/measurement keywords (qty, amount, total, ...)
    - Values are categorical (2-50 distinct)
    - Values appear numeric (measurement or count)
    - Values are boolean-ish (exactly 2 distinct values, low null rate)

    Args:
        columns: List of column profile dicts from deep profiling.

    Returns:
        List of candidate event dicts with ``suggested_event_id`` and
        ``source_column`` keys.
    """
    temporal_keywords = {"date", "time", "when", "log", "timestamp", "at"}
    action_keywords = {
        "status",
        "stage",
        "decision",
        "action",
        "task",
        "result",
        "outcome",
        "state",
        "phase",
        "step",
        "type",
        "category",
        "choice",
        "option",
        "method",
        "reason",
        "flag",
        "code",
        "group",
        "class",
        "rank",
        "priority",
        "level",
        "grade",
        "mode",
        "source",
        "format",
        "tag",
        "label",
        "event",
    }
    quantity_keywords = {
        "qty",
        "quantity",
        "amount",
        "total",
        "count",
        "weight",
        "volume",
        "price",
        "cost",
        "rate",
        "size",
        "length",
        "width",
        "height",
        "depth",
        "area",
        "percent",
        "pct",
        "sum",
        "avg",
        "average",
        "min",
        "max",
    }
    candidates: list[dict[str, Any]] = []
    _numeric_patterns: set[str] = set()

    def _has_numeric_values(distinct_vals: list) -> bool:
        """Check if sample values are predominantly numeric."""
        if not distinct_vals:
            return False
        sample = [str(v).strip() for v in distinct_vals[:20]]
        numeric_count = sum(1 for v in sample if v and _is_numeric_string(v))
        return numeric_count >= len(sample) * 0.7 if sample else False

    def _is_numeric_string(s: str) -> bool:
        try:
            float(s.replace(",", "").replace("$", "").replace("%", ""))
            return True
        except (ValueError, TypeError):
            return False

    for column in columns:
        header = str(column.get("header_label") or "").lower()
        null_rate = column.get("null_rate", 1.0)
        distinct_values = column.get("distinct_values") or []

        has_temporal_keyword = any(keyword in header for keyword in temporal_keywords)
        has_action_keyword = any(keyword in header for keyword in action_keywords)
        has_quantity_keyword = any(keyword in header for keyword in quantity_keywords)
        is_well_populated = null_rate <= 0.55
        is_categorical = 1 < len(distinct_values) <= 50
        is_boolean = 1 < len(distinct_values) <= 2 and null_rate <= 0.10
        is_timestamp_like = bool(distinct_values) and any(
            "-" in str(val) for val in distinct_values[:5]
        )
        is_numeric = _has_numeric_values(distinct_values)
        is_numeric_with_quantity_header = is_numeric and has_quantity_keyword

        if not is_well_populated:
            continue

        if has_temporal_keyword and (is_categorical or is_timestamp_like):
            event_id = header.replace(" ", "_") + "_logged"
            candidates.append(
                {
                    "suggested_event_id": event_id,
                    "source_column": header,
                    "null_rate": null_rate,
                    "distinct_count": len(distinct_values),
                    "event_type": "temporal",
                }
            )
        elif has_action_keyword and is_categorical:
            event_id = header.replace(" ", "_") + "_recorded"
            candidates.append(
                {
                    "suggested_event_id": event_id,
                    "source_column": header,
                    "null_rate": null_rate,
                    "distinct_count": len(distinct_values),
                    "event_type": "action",
                }
            )
        elif is_boolean:
            event_id = header.replace(" ", "_") + "_flagged"
            candidates.append(
                {
                    "suggested_event_id": event_id,
                    "source_column": header,
                    "null_rate": null_rate,
                    "distinct_count": len(distinct_values),
                    "event_type": "boolean",
                }
            )
        elif is_timestamp_like and is_categorical:
            event_id = header.replace(" ", "_") + "_logged"
            candidates.append(
                {
                    "suggested_event_id": event_id,
                    "source_column": header,
                    "null_rate": null_rate,
                    "distinct_count": len(distinct_values),
                    "event_type": "temporal",
                }
            )
        elif is_numeric_with_quantity_header:
            event_id = header.replace(" ", "_") + "_measured"
            candidates.append(
                {
                    "suggested_event_id": event_id,
                    "source_column": header,
                    "null_rate": null_rate,
                    "distinct_count": len(distinct_values),
                    "event_type": "measurement",
                }
            )
        elif is_categorical and null_rate <= 0.40:
            event_id = header.replace(" ", "_") + "_set"
            candidates.append(
                {
                    "suggested_event_id": event_id,
                    "source_column": header,
                    "null_rate": null_rate,
                    "distinct_count": len(distinct_values),
                    "event_type": "categorical",
                }
            )
        elif null_rate <= 0.50:
            event_id = header.replace(" ", "_") + "_recorded"
            candidates.append(
                {
                    "suggested_event_id": event_id,
                    "source_column": header,
                    "null_rate": null_rate,
                    "distinct_count": len(distinct_values),
                    "event_type": "generic",
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


def _infer_workflows_from_clusters(
    entity_clusters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Infer candidate workflows from entity clusters.

    Tabs that belong to the same entity cluster represent related
    business activities that form a natural workflow
    (e.g. Crop Planning -> Crop by Season -> Crop Info).

    Args:
        entity_clusters: List of entity cluster dicts, each with
            ``entity_name`` and ``tabs`` keys.

    Returns:
        List of workflow candidate dicts with ``id``, ``commands``,
        and ``evidence`` keys.
    """
    workflows: list[dict[str, Any]] = []
    for cluster in entity_clusters:
        cluster_tabs = cluster.get("tabs") or []
        if len(cluster_tabs) < 2:
            continue
        entity_name = cluster.get("entity_name", "entity").lower()
        workflow_id = f"{entity_name}_workflow"
        tab_slugs = [tab.lower().replace(" ", "_")[:20] for tab in cluster_tabs]
        workflows.append(
            {
                "id": workflow_id,
                "commands": [f"manage_{slug}" for slug in tab_slugs],
                "evidence": cluster_tabs,
                "ref_type": "entity_cluster",
            }
        )
    return workflows


def _infer_commands_from_tabs(
    tabs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Infer candidate commands from tab titles with action verbs.

    Args:
        tabs: List of tab dicts with ``tab_title`` key.

    Returns:
        List of command candidate dicts with ``id``, ``verbs``,
        and ``source_tab`` keys.
    """
    action_verbs = {
        "plan",
        "plant",
        "harvest",
        "pack",
        "ship",
        "order",
        "record",
        "schedule",
        "allocate",
        "transfer",
        "adjust",
        "review",
        "approve",
        "setup",
        "configure",
        "update",
        "create",
        "manage",
        "track",
        "monitor",
        "report",
    }
    commands: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for tab in tabs:
        title = str(tab.get("tab_title") or "").lower()
        words = title.split()
        matched_verbs = [w for w in words if w in action_verbs]
        if not matched_verbs:
            continue
        verb = matched_verbs[-1]
        noun = words[-1] if words else verb
        command_id = f"{verb}_{noun}"
        if command_id not in seen_ids:
            seen_ids.add(command_id)
            commands.append(
                {
                    "id": command_id,
                    "verbs": matched_verbs,
                    "source_tab": title,
                }
            )

    return commands


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

    entries = deep_profile_index.get("entries") or []

    tabs: list[dict[str, Any]] = []
    for entry in entries:
        tab_title = str(entry.get("tab_title") or "")
        if not tab_title:
            continue
        entry_columns = entry.get("columns") or []
        tabs.append(
            {
                "tab_title": tab_title,
                "columns": [col.get("header_label") for col in entry_columns],
            }
        )

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

    # Supplement with entity-cluster-based workflows
    cluster_workflows = _infer_workflows_from_clusters(entity_clusters)
    all_workflow_ids = {w["id"] for w in workflow_candidates}
    for cluster_wf in cluster_workflows:
        if cluster_wf["id"] not in all_workflow_ids:
            workflow_candidates.append(cluster_wf)
            all_workflow_ids.add(cluster_wf["id"])

    evidence_tabs: set[str] = set()
    for wf in workflow_candidates:
        evidence_tabs.update(wf.get("evidence", []))
    event_tabs: set[str] = set()
    for event in events:
        for source in event.sourced_from:
            tab = source.get("tab", "")
            if tab:
                event_tabs.add(tab)
    for tab_title in sorted(event_tabs - evidence_tabs):
        tab_slug = tab_title.lower().replace(" ", "_")[:30]
        wf_id = f"{tab_slug}_workflow"
        if wf_id not in all_workflow_ids:
            workflow_candidates.append(
                {
                    "id": wf_id,
                    "commands": [f"manage_{tab_slug}"],
                    "evidence": [tab_title],
                    "ref_type": "singleton_event_tab",
                }
            )
            all_workflow_ids.add(wf_id)

    workflows = [
        Workflow(
            id=workflow["id"],
            commands=workflow.get("commands", []),
            evidence=workflow["evidence"],
        )
        for workflow in workflow_candidates
    ]

    # Commands from workflows
    command_seen: set[str] = set()
    commands = []
    for workflow in workflows:
        for command_id in workflow.commands:
            if command_id not in command_seen:
                command_seen.add(command_id)
                commands.append(Command(id=command_id))

    # Supplement commands from tab title action verbs
    tab_commands = _infer_commands_from_tabs(tabs)
    for cmd in tab_commands:
        if cmd["id"] not in command_seen:
            command_seen.add(cmd["id"])
            commands.append(Command(id=cmd["id"]))

    # Supplement commands from capabilities — each capability implies
    # record/schedule/manage operations
    capability_command_map = {
        "harvest": "record_harvest",
        "pack": "record_pack",
        "plant": "record_planting",
        "order": "record_order",
        "seed": "manage_seed_order",
        "nursery": "manage_nursery",
        "market": "manage_market",
        "csa": "manage_csa",
        "inventory": "manage_inventory",
        "field": "record_field_event",
        "crop": "manage_crop",
        "planner": "manage_plan",
        "forecast": "generate_forecast",
        "sales": "manage_sales",
        "staging": "manage_staging",
        "tray": "manage_tray",
    }
    for cap in capabilities:
        cap_id = cap.id.lower()
        for keyword, command_id in capability_command_map.items():
            if keyword in cap_id and command_id not in command_seen:
                command_seen.add(command_id)
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
