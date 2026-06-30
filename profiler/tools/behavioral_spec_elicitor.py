"""MWBS Behavioral Spec Elicitor — derive BehavioralSpec from profiler artifacts.

This module evolves the old BPRS Stage 4 operational model deriver into the
MWBS behavioral spec elicitor.  It copies all existing helper functions from
``operational_model_deriver.py`` (unchanged) and adds:

* ``InferenceRule`` dataclass and ``INFERENCE_RULES`` catalog (INF-01..INF-12)
* ``InferenceConfidenceLog`` dataclass
* ``generate_placeholders()`` — Section 5.3 placeholder generation
* ``generate_elicitation_worksheet()`` — Markdown elicitation worksheet
* ``derive_behavioral_spec()`` — produce a ``BehavioralSpec`` from profiler
  artifacts with provenance records and placeholder scaffolding

Backward compat: ``derive_operational_model()`` remains unchanged and
continues to produce ``OperationalModel`` instances.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Union

from profiler.tools.behavioral_spec import (
    MWBS_SPEC_VERSION,
    Actor,
    BehavioralEvent,
    BehavioralSpec,
    BehavioralWorkflow,
    BusinessRule,
    BusinessSection,
    Decision,
    JobStory,
    MwbsProject,
    PayloadField,
    Placeholder,
    Provenance,
    WorkflowDataEntry,
    WorkflowException,
    WorkflowInput,
    WorkflowOperational,
    WorkflowStep,
)
from profiler.tools.operational_model import (
    OperationalModel,
    Capability,
    Command as OpCommand,
    Event as OpEvent,
    Invariant,
    Workflow as OpWorkflow,
)

# Import shared helpers from operational_model_deriver (de-dup)
from profiler.tools.operational_model_deriver import (
    _cluster_tabs_into_entities,
    _infer_candidate_events,
    _infer_workflows_from_graph,
    _infer_workflows_from_clusters,
    _infer_commands_from_tabs,
    _derive_invariants_from_events,
)

# ---------------------------------------------------------------------------
# InferenceRule catalog
# ---------------------------------------------------------------------------


@dataclass
class InferenceRule:
    """Catalog entry mapping spreadsheet signals to MWBS elements.

    Attributes:
        id: Unique rule identifier (e.g. ``INF-01``).
        name: Short human-readable rule name.
        signal: Description of the spreadsheet signal being detected.
        infers: Description of the MWBS element being inferred.
        confidence_weight: Confidence weight between 0.0 and 1.0.
    """

    id: str = ""
    name: str = ""
    signal: str = ""
    infers: str = ""
    confidence_weight: float = 0.5


INFERENCE_RULES: list[InferenceRule] = [
    InferenceRule(
        id="INF-01",
        name="tab_title_entity",
        signal="Tab title contains domain entity name (e.g. 'Crop', 'Field')",
        infers="Entity / Model candidate",
        confidence_weight=0.8,
    ),
    InferenceRule(
        id="INF-02",
        name="column_header_field",
        signal="Column header matches domain vocabulary",
        infers="Field candidate",
        confidence_weight=0.7,
    ),
    InferenceRule(
        id="INF-03",
        name="date_column_event",
        signal="Column is date/time type with temporal header",
        infers="Temporal event",
        confidence_weight=0.6,
    ),
    InferenceRule(
        id="INF-04",
        name="print_range_report",
        signal="Print range defined on sheet",
        infers="Report candidate",
        confidence_weight=0.7,
    ),
    InferenceRule(
        id="INF-05",
        name="cross_sheet_formula",
        signal="Formula references another sheet",
        infers="Workflow dependency edge",
        confidence_weight=0.8,
    ),
    InferenceRule(
        id="INF-06",
        name="fk_candidate",
        signal="Column values match another sheet's key column",
        infers="FK relationship",
        confidence_weight=0.6,
    ),
    InferenceRule(
        id="INF-07",
        name="data_validation_dropdown",
        signal="Column has dropdown validation",
        infers="Choice/Enum field",
        confidence_weight=0.7,
    ),
    InferenceRule(
        id="INF-08",
        name="tab_cluster_entity",
        signal="Multiple tabs share >50% column overlap",
        infers="Entity cluster",
        confidence_weight=0.5,
    ),
    InferenceRule(
        id="INF-09",
        name="action_verb_title",
        signal="Tab title starts with action verb (Plan, Harvest, etc.)",
        infers="Workflow candidate",
        confidence_weight=0.6,
    ),
    InferenceRule(
        id="INF-10",
        name="quantity_field",
        signal="Column header contains quantity keyword (qty, amount, count)",
        infers="Measurement event",
        confidence_weight=0.5,
    ),
    InferenceRule(
        id="INF-11",
        name="boolean_column",
        signal="Column has exactly 2 distinct values, low null rate",
        infers="Status/Flag field",
        confidence_weight=0.7,
    ),
    InferenceRule(
        id="INF-12",
        name="named_range",
        signal="Named range defined in spreadsheet",
        infers="Report field / constant",
        confidence_weight=0.4,
    ),
]


# ---------------------------------------------------------------------------
# InferenceConfidenceLog
# ---------------------------------------------------------------------------


@dataclass
class InferenceConfidenceLog:
    """Per-element inference confidence record.

    Attributes:
        element_id: Identifier of the inferred element.
        element_type: Type of element (e.g. ``event``, ``workflow``).
        inference_rule_id: The INF-XX rule that produced this inference.
        confidence_weight: Confidence weight from the rule.
        signals_found: List of specific signal values that triggered the rule.
        verified: Whether this inference has been human-verified.
    """

    element_id: str = ""
    element_type: str = ""
    inference_rule_id: str = ""
    confidence_weight: float = 0.0
    signals_found: list[str] = field(default_factory=list)
    verified: bool = False


# ---------------------------------------------------------------------------
# Helper: lookup inference rule by id
# ---------------------------------------------------------------------------


def _lookup_rule(rule_id: str) -> InferenceRule | None:
    """Look up an InferenceRule by its id.

    Args:
        rule_id: Rule identifier (e.g. ``INF-01``).

    Returns:
        The matching InferenceRule or None if not found.
    """
    for rule in INFERENCE_RULES:
        if rule.id == rule_id:
            return rule
    return None


# ---------------------------------------------------------------------------
# Helper: build provenance from rule id
# ---------------------------------------------------------------------------


def _provenance_from_rule(
    rule_id: str,
    signals: list[dict[str, str]] | None = None,
) -> Provenance:
    """Build a Provenance record from an inference rule id.

    Args:
        rule_id: The INF-XX rule identifier.
        signals: Optional additional inference signals beyond the rule.

    Returns:
        A Provenance instance set to ``source="inferred"`` with the rule
        captured in ``inference_signals``.
    """
    inference_signals: list[dict[str, str]] = []
    if rule_id:
        rule = _lookup_rule(rule_id)
        signal_desc = rule.signal if rule else ""
        inference_signals.append(
            {
                "rule_id": rule_id,
                "signal": rule.name if rule else "",
                "description": signal_desc,
            }
        )
    if signals:
        inference_signals.extend(signals)
    return Provenance(
        source="inferred",
        inference_signals=inference_signals,
        verification_required=True,
    )


# ---------------------------------------------------------------------------
# Placeholder generation (Section 5.3)
# ---------------------------------------------------------------------------


def generate_placeholders(spec: Union[BehavioralSpec, dict]) -> list[Placeholder]:
    """Generate ``[REQUIRES_ELICITATION]`` placeholders for un-inferrable elements.

    Matches Section 5.3 of the MWBS design spec.  For each type of element
    that the elicitor cannot fully infer, a ``Placeholder`` is created with
    the correct field path targeting the spec structure.

    Args:
        spec: A ``BehavioralSpec`` instance or a plain dict with the same
            structure.

    Returns:
        List of ``Placeholder`` records for elements requiring elicitation.
    """
    placeholders: list[Placeholder] = []

    # Convert dict to BehavioralSpec if needed for uniform traversal
    if isinstance(spec, dict):
        spec = BehavioralSpec.from_dict(spec)

    # --- Workflow-level placeholders ---
    for workflow in spec.workflows:
        wf_id = workflow.id

        # operational.max_duration_minutes
        if (
            workflow.operational is None
            or workflow.operational.max_duration_minutes == 0
        ):
            placeholders.append(
                Placeholder(
                    field_path=f"workflows[{wf_id}].operational.max_duration_minutes",
                    description="Maximum duration per workflow session",
                    section="workflows",
                    workflow_id=wf_id,
                    reason="Cannot be inferred from spreadsheet structure alone",
                )
            )

        # job_story.when
        if workflow.job_story is None or not workflow.job_story.when:
            placeholders.append(
                Placeholder(
                    field_path=f"workflows[{wf_id}].job_story.when",
                    description="Situational context \u2014 what triggers this workflow?",
                    section="workflows",
                    workflow_id=wf_id,
                    reason="Situational trigger context requires human elicitation",
                )
            )

        # data_entry.preferred_input
        if workflow.data_entry is None or not workflow.data_entry.preferred_input:
            placeholders.append(
                Placeholder(
                    field_path=f"workflows[{wf_id}].data_entry.preferred_input",
                    description="Preferred data entry method",
                    section="workflows",
                    workflow_id=wf_id,
                    reason="Input method preference requires operator interview",
                )
            )

        # priority
        if workflow.priority == 0:
            placeholders.append(
                Placeholder(
                    field_path=f"workflows[{wf_id}].priority",
                    description="Priority stack rank relative to other workflows",
                    section="workflows",
                    workflow_id=wf_id,
                    reason="Relative priority requires stakeholder input",
                )
            )

        # decisions within workflow — criteria_actor_applies
        for decision_index, decision_dict in enumerate(workflow.decisions):
            if not decision_dict.get("criteria_actor_applies"):
                placeholders.append(
                    Placeholder(
                        field_path=f"workflows[{wf_id}].decisions[{decision_index}].criteria_actor_applies",
                        description="Decision criteria the actor applies",
                        section="decisions",
                        workflow_id=wf_id,
                        reason="Decision criteria require subject-matter expert input",
                    )
                )

        # exceptions within workflow — current_handling
        for exception_index, exception_dict in enumerate(workflow.exceptions):
            if not exception_dict.get("current_handling"):
                placeholders.append(
                    Placeholder(
                        field_path=f"workflows[{wf_id}].exceptions[{exception_index}].current_handling",
                        description="Current manual handling of this exception",
                        section="exceptions",
                        workflow_id=wf_id,
                        reason="Exception handling procedures require operator interview",
                    )
                )

    # --- Actor-level placeholders ---
    for actor in spec.actors:
        if not actor.time_pressures:
            placeholders.append(
                Placeholder(
                    field_path=f"actors.{actor.id}.time_pressures",
                    description="Time pressure context for this actor",
                    section="actors",
                    workflow_id=actor.id,
                    reason="Time pressure context requires role-specific elicitation",
                )
            )

    # --- Top-level decision criteria (for Decision objects on spec.decisions) ---
    for decision in spec.decisions:
        if not decision.criteria_actor_applies:
            placeholders.append(
                Placeholder(
                    field_path=f"decisions[{decision.id}].criteria_actor_applies",
                    description="Decision criteria the actor applies",
                    section="decisions",
                    workflow_id=decision.within_workflow,
                    reason="Decision criteria require subject-matter expert input",
                )
            )

    # --- Top-level exception current_handling ---
    for exception in spec.exceptions:
        if not exception.current_handling:
            placeholders.append(
                Placeholder(
                    field_path=f"exceptions[{exception.id}].current_handling",
                    description="Current manual handling of this exception",
                    section="exceptions",
                    workflow_id=exception.workflow,
                    reason="Exception handling procedures require operator interview",
                )
            )

    return placeholders


# ---------------------------------------------------------------------------
# Elicitation worksheet generator
# ---------------------------------------------------------------------------


def generate_elicitation_worksheet(spec: BehavioralSpec) -> str:
    """Generate a human-readable Markdown elicitation worksheet.

    Produces a structured Markdown document with six sections, each
    listing the relevant workflows and placeholder descriptions for
    elements requiring human elicitation.

    Args:
        spec: The behavioral specification to generate the worksheet for.

    Returns:
        Markdown string with the full elicitation worksheet.
    """
    placeholders = generate_placeholders(spec)

    # Group placeholders by section
    sections: dict[str, list[Placeholder]] = {}
    for placeholder in placeholders:
        section_key = placeholder.section or "other"
        if section_key not in sections:
            sections[section_key] = []
        sections[section_key].append(placeholder)

    lines: list[str] = []
    lines.append("# Elicitation Worksheet")
    lines.append("")

    # Helper to write a section
    def _write_section(
        title: str,
        section_key: str,
        placeholder_filter: str | None = None,
    ) -> None:
        """Write a section of the worksheet."""
        items = sections.get(section_key, [])

        lines.append(f"## {title}")
        lines.append("")

        # Sub-filter for workflow-related placeholders
        wf_groups: dict[str, list[Placeholder]] = {}
        non_wf_items: list[Placeholder] = []

        for item in items:
            if placeholder_filter and placeholder_filter not in item.description:
                continue
            if item.workflow_id:
                if item.workflow_id not in wf_groups:
                    wf_groups[item.workflow_id] = []
                wf_groups[item.workflow_id].append(item)
            else:
                non_wf_items.append(item)

        if not wf_groups and not non_wf_items:
            lines.append("*No items to elicit in this section.*")
            lines.append("")
            return

        for wf_id in sorted(wf_groups):
            wf_items = wf_groups[wf_id]
            if not wf_items:
                continue
            lines.append(f"### Workflow: {wf_id}")
            lines.append("")
            for wf_item in wf_items:
                lines.append(f"- **{wf_item.field_path}**: {wf_item.description}")
                if wf_item.reason:
                    lines.append(f"  - *Reason*: {wf_item.reason}")
                lines.append("")
            lines.append("")
            lines.append("---")
            lines.append("")

        for item in non_wf_items:
            lines.append(f"- **{item.field_path}**: {item.description}")
            if item.reason:
                lines.append(f"  - *Reason*: {item.reason}")
            lines.append("")
            lines.append("---")
            lines.append("")

    # Section 1: Workflow Walk-Through
    _write_section(
        "Workflow Walk-Through",
        "workflows",
        None,
    )

    # Section 2: Speed Calibration
    _write_section(
        "Speed Calibration",
        "workflows",
        "duration",
    )

    # Section 3: Paper Process Inventory
    _write_section(
        "Paper Process Inventory",
        "workflows",
        "data entry",
    )

    # Section 4: Exception Review
    _write_section(
        "Exception Review",
        "exceptions",
        None,
    )

    # Section 5: Decision Inventory
    _write_section(
        "Decision Inventory",
        "decisions",
        None,
    )

    # Section 6: Priority Stack Rank
    _write_section(
        "Priority Stack Rank",
        "workflows",
        "priority",
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared helpers extracted from derive_behavioral_spec / derive_operational_model
# ---------------------------------------------------------------------------


def _build_tabs_from_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build normalized tab list from deep profile entries.

    Args:
        entries: List of deep profile entry dicts, each with ``tab_title``
            and ``columns``.

    Returns:
        List of dicts with ``tab_title`` and ``columns`` (header_label list).
    """
    tabs: list[dict[str, Any]] = []
    for entry in entries:
        tab_title = str(entry.get("tab_title") or "")
        if not tab_title:
            continue
        entry_columns = entry.get("columns") or []
        tabs.append(
            {
                "tab_title": tab_title,
                "columns": [column.get("header_label") for column in entry_columns],
            }
        )
    return tabs


def _extract_cross_sheet_edges(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect FK and formula cross-sheet edges with dedup.

    Args:
        entries: List of deep profile entry dicts, each with optional
            ``fk_candidates`` and ``_dependency_artifact.sheet_graph``.

    Returns:
        List of edge dicts with ``from``, ``to``, ``ref_type`` and
        optional ``weight``.
    """
    cross_sheet_edges: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for entry in entries:
        tab_title = str(entry.get("tab_title") or "")

        fk_candidates = entry.get("fk_candidates") or []
        for fk_candidate in fk_candidates:
            target = fk_candidate.get("target")
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

        dep_artifact = entry.get("dependency_artifact")
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

    return cross_sheet_edges


def _supplement_workflows_with_clusters_and_events(
    graph_workflows: list[dict[str, Any]],
    entity_clusters: list[dict[str, Any]],
    event_tabs: set[str],
) -> list[dict[str, Any]]:
    """Merge cluster workflows and event-only tab workflows.

    Args:
        graph_workflows: Initial workflow candidates from graph inference.
            Mutated and returned.
        entity_clusters: Entity cluster dicts from
            ``_cluster_tabs_into_entities``.
        event_tabs: Set of tab titles that produce events (caller
            extracts per-function since event types differ).

    Returns:
        The same list with cluster and singleton-event workflows appended.
    """
    cluster_workflows = _infer_workflows_from_clusters(entity_clusters)
    all_workflow_ids = {workflow["id"] for workflow in graph_workflows}
    for cluster_wf in cluster_workflows:
        if cluster_wf["id"] not in all_workflow_ids:
            graph_workflows.append(cluster_wf)
            all_workflow_ids.add(cluster_wf["id"])

    # Supplement with event-only tabs that lack workflow coverage
    evidence_tabs: set[str] = set()
    for graph_wf in graph_workflows:
        evidence_tabs.update(graph_wf.get("evidence", []))
    for tab_title in sorted(event_tabs - evidence_tabs):
        tab_slug = tab_title.lower().replace(" ", "_")[:30]
        wf_id = f"{tab_slug}_workflow"
        if wf_id not in all_workflow_ids:
            graph_workflows.append(
                {
                    "id": wf_id,
                    "commands": [f"manage_{tab_slug}"],
                    "evidence": [tab_title],
                    "ref_type": "singleton_event_tab",
                }
            )
            all_workflow_ids.add(wf_id)

    return graph_workflows


# ---------------------------------------------------------------------------
# Helper: derive actors from interaction contract roles or vocabulary
# ---------------------------------------------------------------------------


def _derive_actors(
    interaction_contract: dict[str, Any] | None,
    domain_knowledge: dict[str, Any] | None,
) -> list[Actor]:
    """Derive Actor objects preferring interaction contract roles over vocabulary.

    When ``interaction_contract`` contains ``views[].workflow_hints.role_hints``,
    one Actor is created per role entry with name, description, and access hints
    from the role data.  The fallback path uses domain vocabulary operational
    terms (existing behavior) and tags those actors with provenance
    ``source="vocabulary_stub"``.

    Args:
        interaction_contract: Optional interaction contract dict with
            ``views`` containing ``workflow_hints.role_hints``.
        domain_knowledge: Domain knowledge dict with ``vocabulary``.

    Returns:
        List of Actor dataclass instances.
    """
    # -- Try interaction contract roles first --
    roles = _extract_role_hints(interaction_contract)
    if roles:
        seen_role_ids: set[str] = set()
        actors_from_roles: list[Actor] = []
        for role in roles:
            role_name: str = role.get("name") or role.get("role", "")
            if not role_name:
                continue
            role_slug: str = role_name.lower().replace(" ", "_")
            if role_slug in seen_role_ids:
                continue
            seen_role_ids.add(role_slug)
            responsibilities: list[str] = []
            hints: str = role.get("hints") or role.get("description", "")
            if hints:
                responsibilities.append(hints)
            access_hints = role.get("access_hints")
            access_level: str = "not_yet_elicited"
            if access_hints and isinstance(access_hints, str):
                access_level = access_hints
            elif access_hints and isinstance(access_hints, list):
                access_level = ", ".join(str(a) for a in access_hints)
            actors_from_roles.append(
                Actor(
                    id=role_slug,
                    name=role_name,
                    responsibilities=responsibilities,
                    time_pressures=[],
                    access_level=access_level,
                )
            )
        if actors_from_roles:
            return actors_from_roles

    # -- Fall back to vocabulary-based derivation with provenance tag --
    vocabulary = (domain_knowledge.get("vocabulary") or {}) if domain_knowledge else {}
    operational_terms = vocabulary.get("operational") or []
    actors_from_vocab: list[Actor] = []
    for term in operational_terms:
        actors_from_vocab.append(
            Actor(
                id=term.replace(" ", "_"),
                name=term.title(),
                responsibilities=[f"Manage {term}"],
                time_pressures=[],
                access_level="not_yet_elicited",
                provenance=Provenance(
                    source="vocabulary_stub",
                    inference_signals=[],
                    verification_required=True,
                ),
            )
        )
    if not actors_from_vocab:
        actors_from_vocab = [
            Actor(
                id="primary_operator",
                name="Primary Operator",
                responsibilities=["Operate discovered workflows"],
                time_pressures=[],
                provenance=Provenance(
                    source="vocabulary_stub",
                    inference_signals=[],
                    verification_required=True,
                ),
            )
        ]
    return actors_from_vocab


def _extract_role_hints(
    interaction_contract: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Extract role hint entries from an interaction contract dict.

    Walks ``views[].workflow_hints.role_hints`` and collects all unique
    role entries across all views.

    Args:
        interaction_contract: Interaction contract dict or ``None``.

    Returns:
        List of role hint dicts (may be empty).
    """
    if not interaction_contract:
        return []
    views: list[dict[str, Any]] = interaction_contract.get("views") or []
    seen: set[str] = set()
    roles: list[dict[str, Any]] = []
    for view in views:
        workflow_hints: dict[str, Any] = view.get("workflow_hints") or {}
        role_hints: list[dict[str, Any]] = workflow_hints.get("role_hints") or []
        for role in role_hints:
            role_name: str = role.get("name") or role.get("role", "")
            if role_name and role_name not in seen:
                seen.add(role_name)
                roles.append(role)
    return roles


# ---------------------------------------------------------------------------
# derive_behavioral_spec() — the new primary entry point
# ---------------------------------------------------------------------------


def derive_behavioral_spec(
    discovery: dict[str, Any],
    deep_profile_index: dict[str, Any],
    domain_knowledge: dict[str, Any],
    interaction_contract: dict[str, Any] | None = None,
) -> BehavioralSpec:
    """Derive a BehavioralSpec from profiler artifacts.

    Uses the same internal helpers as ``derive_operational_model`` but
    produces a ``BehavioralSpec`` with provenance records and placeholders.

    Prefers role data from ``interaction_contract`` (if available) for actor
    derivation, falling back to vocabulary-based stubs when no role hints
    are present.

    Args:
        discovery: Discovery state dict with ``workbook_index`` and
            ``broad_inventory``.
        deep_profile_index: Deep profile index dict with ``entries`` list.
        domain_knowledge: Domain knowledge dict with ``domain`` and
            ``vocabulary``.
        interaction_contract: Optional interaction contract dict with
            ``views`` containing ``workflow_hints.role_hints``. When
            provided, actors are derived from role data instead of
            vocabulary terms.

    Returns:
        A populated BehavioralSpec instance with ``spec_version`` set to
        ``MWBS_SPEC_VERSION`` and ``project.status`` set to ``"draft"``.
    """
    source_id = str(domain_knowledge.get("domain", "")) if domain_knowledge else ""

    entries = deep_profile_index.get("entries") or []

    # -- Build tab list from entries --
    tabs = _build_tabs_from_entries(entries)

    # -- Entity clustering --
    entity_clusters = _cluster_tabs_into_entities(tabs)

    # -- Actors: prefer interaction contract roles over vocabulary stubs --
    actors: list[Actor] = _derive_actors(interaction_contract, domain_knowledge)

    # -- Events from column profiles --
    events: list[BehavioralEvent] = []
    for entry in entries:
        tab_title = str(entry.get("tab_title") or "")
        entry_columns = entry.get("columns") or []
        candidate_events = _infer_candidate_events(entry_columns)

        for candidate_event in candidate_events:
            event_type = candidate_event.get("event_type", "generic")
            # Map event type to inference rule
            if event_type == "temporal":
                rule_id = "INF-03"
            elif event_type == "action":
                rule_id = "INF-02"
            elif event_type == "boolean":
                rule_id = "INF-11"
            elif event_type == "measurement":
                rule_id = "INF-10"
            elif event_type == "categorical":
                rule_id = "INF-07"
            else:
                rule_id = "INF-02"

            events.append(
                BehavioralEvent(
                    id=candidate_event["suggested_event_id"],
                    name=candidate_event["suggested_event_id"]
                    .replace("_", " ")
                    .title(),
                    description=f"Inferred from column '{candidate_event['source_column']}' "
                    f"on tab '{tab_title}'",
                    producer=tab_title,
                    payload=[
                        PayloadField(
                            field=candidate_event["source_column"], type="string"
                        ),
                    ],
                    consumed_by=[],
                    provenance=_provenance_from_rule(
                        rule_id,
                        signals=[{"source_column": candidate_event["source_column"]}],
                    ),
                )
            )

    # -- Cross-sheet edges (FK + formula) --
    cross_sheet_edges = _extract_cross_sheet_edges(entries)

    # -- Workflow inference --
    formula_graph = {"edges": cross_sheet_edges} if cross_sheet_edges else None
    graph_workflows = _infer_workflows_from_graph(formula_graph)

    # Collect event tabs (BehavioralEvent.producer)
    event_tabs: set[str] = set()
    for event in events:
        event_tabs.add(event.producer)

    graph_workflows = _supplement_workflows_with_clusters_and_events(
        graph_workflows,
        entity_clusters,
        event_tabs,
    )

    # Build BehavioralWorkflow objects
    workflows: list[BehavioralWorkflow] = []
    for wf_candidate in graph_workflows:
        wf_id = wf_candidate["id"]
        wf_evidence = wf_candidate.get("evidence", [])
        ref_type = wf_candidate.get("ref_type", "unknown")

        # Determine inference rule
        if ref_type == "entity_cluster":
            rule_id = "INF-08"
        elif ref_type == "FK":
            rule_id = "INF-06"
        elif ref_type == "singleton_event_tab":
            rule_id = "INF-01"
        else:
            rule_id = "INF-05"

        title = wf_id.replace("_", " ").title()

        # Extract decisions and exceptions from evidence
        wf_decisions: list[dict[str, str]] = []
        wf_exceptions: list[dict[str, str]] = []

        workflows.append(
            BehavioralWorkflow(
                id=wf_id,
                title=title,
                job_story=JobStory(
                    when="",
                    i_need_to=f"Manage the {title.lower()} process",
                    so_i_can=f"Track and complete {title.lower()} activities",
                ),
                actor=actors[0].id if actors else "",
                frequency="",
                peak_pressure="",
                trigger={"type": "scheduled", "source": ", ".join(wf_evidence)},
                inputs=[
                    WorkflowInput(
                        id=f"{wf_id}_input",
                        source_event=None,
                        description=f"Data from {evidence}" if evidence else "",
                    )
                    for evidence in wf_evidence[:3]
                ],
                steps=[
                    WorkflowStep(
                        id=f"{wf_id}_step_1",
                        title="Review input data",
                        actor_action="Review inputs and check completeness",
                    ),
                    WorkflowStep(
                        id=f"{wf_id}_step_2",
                        title="Execute operation",
                        actor_action="Perform the primary operation",
                        emits=f"{wf_id}_completed",
                    ),
                ],
                emits=[f"{wf_id}_completed"],
                decisions=wf_decisions,
                exceptions=wf_exceptions,
                acceptance_tests=[],
                operational=WorkflowOperational(max_duration_minutes=0),
                data_entry=WorkflowDataEntry(
                    frequency="",
                    volume="",
                    preferred_input="",
                    batch_capable=False,
                ),
                priority=0,
                provenance=_provenance_from_rule(
                    rule_id,
                    signals=[{"evidence": ", ".join(wf_evidence[:3])}],
                ),
            )
        )

    # -- Decisions built from workflow triggers --
    all_decisions: list[Decision] = []
    decision_seen: set[str] = set()
    for workflow in workflows:
        if workflow.trigger:
            decision_id = f"dec_{workflow.id}_start"
            if decision_id not in decision_seen:
                decision_seen.add(decision_id)
                all_decisions.append(
                    Decision(
                        id=decision_id,
                        title=f"When to start {workflow.title}",
                        within_workflow=workflow.id,
                        within_step=f"{workflow.id}_step_1",
                        description=f"Decision about initiating {workflow.title}",
                        information_system_must_provide=["relevant data availability"],
                        criteria_actor_applies=[],
                        outcome="",
                        outcome_recorded_as="",
                        automation_level="human_only",
                        rationale="",
                        provenance=_provenance_from_rule("INF-01"),
                    )
                )

    # -- Exceptions built from workflow edge cases --
    all_exceptions: list[WorkflowException] = []
    exception_seen: set[str] = set()
    for workflow in workflows:
        exc_id = f"exc_{workflow.id}_data_issue"
        if exc_id not in exception_seen:
            exception_seen.add(exc_id)
            all_exceptions.append(
                WorkflowException(
                    id=exc_id,
                    title=f"Data issue in {workflow.title}",
                    workflow=workflow.id,
                    condition="Required data is missing or invalid",
                    severity="warning",
                    current_handling="",
                    migration_improvement="",
                    provenance=_provenance_from_rule("INF-01"),
                )
            )

    # -- Business rules from invariants --
    event_payloads = [
        {"id": event.id, "payload": [pf.field for pf in event.payload]}
        for event in events
    ]
    invariant_candidates = _derive_invariants_from_events(event_payloads)
    rules: list[BusinessRule] = [
        BusinessRule(
            id=inv["id"],
            title=inv["id"].replace("_", " ").title(),
            expression=inv["expression"],
            severity=(
                inv["violations_are"]
                if inv["violations_are"] == "warning"
                else "warning"
            ),
            applies_to="",
            violation_response=inv.get("enforcement", "application_logic"),
            provenance=_provenance_from_rule("INF-10"),
        )
        for inv in invariant_candidates
    ]

    # -- Build project --
    project = MwbsProject(
        name=source_id.title() if source_id else "Migration Project",
        source_files=[],
        profiler_run_date=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        elicitor_run_date=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        version=1,
        status="draft",
    )

    # -- Build business section --
    business = BusinessSection(
        name=source_id.title() if source_id else "",
        domain=source_id,
        description=(
            f"MWBS behavioral specification for {source_id}" if source_id else ""
        ),
    )

    # -- Assemble BehavioralSpec --
    spec = BehavioralSpec(
        spec_version=MWBS_SPEC_VERSION,
        project=project,
        business=business,
        actors=actors,
        events=events,
        workflows=workflows,
        decisions=all_decisions,
        exceptions=all_exceptions,
        rules=rules,
    )

    return spec


# ---------------------------------------------------------------------------
# Backward-compat: derive_operational_model stays working (unchanged)
# ---------------------------------------------------------------------------


def derive_operational_model(
    discovery: dict[str, Any],
    deep_profile_index: dict[str, Any],
    domain_knowledge: dict[str, Any],
) -> OperationalModel:
    """Derive an OperationalModel from profiler artifacts.

    This function is unchanged from the original ``operational_model_deriver``
    module and is maintained for backward compatibility.

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

    tabs = _build_tabs_from_entries(entries)

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

    events: list[OpEvent] = []
    for entry in entries:
        tab_title = str(entry.get("tab_title") or "")
        entry_columns = entry.get("columns") or []
        candidate_events = _infer_candidate_events(entry_columns)
        for candidate_event in candidate_events:
            events.append(
                OpEvent(
                    id=candidate_event["suggested_event_id"],
                    payload=[candidate_event["source_column"]],
                    sourced_from=[
                        {"tab": tab_title, "column": candidate_event["source_column"]}
                    ],
                )
            )

    cross_sheet_edges = _extract_cross_sheet_edges(entries)

    formula_graph = {"edges": cross_sheet_edges} if cross_sheet_edges else None
    workflow_candidates = _infer_workflows_from_graph(formula_graph)

    # Collect event tabs (OpEvent.sourced_from[].tab)
    event_tabs: set[str] = set()
    for event in events:
        for source in event.sourced_from:
            tab = source.get("tab", "")
            if tab:
                event_tabs.add(tab)

    workflow_candidates = _supplement_workflows_with_clusters_and_events(
        workflow_candidates,
        entity_clusters,
        event_tabs,
    )

    workflows = [
        OpWorkflow(
            id=wf_candidate["id"],
            commands=wf_candidate.get("commands", []),
            evidence=wf_candidate["evidence"],
        )
        for wf_candidate in workflow_candidates
    ]

    # Commands from workflows
    command_seen: set[str] = set()
    commands = []
    for workflow in workflows:
        for command_id in workflow.commands:
            if command_id not in command_seen:
                command_seen.add(command_id)
                commands.append(OpCommand(id=command_id))

    # Supplement commands from tab title action verbs
    tab_commands = _infer_commands_from_tabs(tabs)
    for cmd in tab_commands:
        if cmd["id"] not in command_seen:
            command_seen.add(cmd["id"])
            commands.append(OpCommand(id=cmd["id"]))

    # Supplement commands from capabilities
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
                commands.append(OpCommand(id=command_id))

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
