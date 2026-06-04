"""Merge profiler signals, interaction contract, and view manifest into a codegen manifest.

The codegen manifest (Layer 3 of the interaction contract) is the single input that
``generate_admin`` and future frontend generators consume. It is fully derived:
regenerated whenever signals or the human contract changes.

Merge priority (highest wins)
-----------------------------
1. **Interaction contract override** (Layer 2, human-authored)
2. **Profiler signal** (Layer 1, machine-generated)
3. **View manifest fallback** (existing draft)
"""

from __future__ import annotations

import datetime
from typing import Any

CODGEN_MANIFEST_VERSION = 1

# Archetypes valid in all layers.
_VALID_ARCHETYPES = {"form", "list", "dashboard", "reference"}


def _to_pascal_case(snake: str | None) -> str | None:
    """Convert snake_case to PascalCase.

    Args:
        snake: snake_case string, or ``None``.

    Returns:
        PascalCase string, or ``None`` if input is ``None`` or empty.
    """
    if not snake:
        return snake
    return "".join(word.capitalize() for word in snake.split("_"))


def _resolve_archetype(
    tab_title: str,
    profiler_signals_dict: dict[str, dict[str, Any]],
    interaction_contract_dict: dict[str, dict[str, Any]],
    view_manifest_view: dict[str, Any] | None,
) -> tuple[str, float]:
    """Resolve UI archetype for a tab using the merge priority.

    Args:
        tab_title: Source tab title.
        profiler_signals_dict: Signals dict keyed by tab title.
        interaction_contract_dict: Contract dict keyed by tab title
            (archetype_overrides from all roles merged together).
        view_manifest_view: View entry from the view manifest, or None.

    Returns:
        Tuple of (archetype_str, confidence_float).
    """
    # Priority 1: Interaction contract override
    ic_entry = interaction_contract_dict.get(tab_title)
    if ic_entry and "archetype" in ic_entry:
        return ic_entry["archetype"], 1.0

    # Priority 2: Profiler signal
    signal = profiler_signals_dict.get(tab_title)
    if signal:
        archetype = signal.get("ui_archetype", "list")
        confidence = signal.get("confidence_score", 0.5)
        return str(archetype), float(confidence)

    # Priority 3: View manifest fallback
    if view_manifest_view:
        return str(view_manifest_view.get("type", "list")), 0.0

    return "list", 0.0


def _resolve_status_transitions(
    tab_title: str,
    interaction_contract_dict: dict[str, dict[str, Any]],
    view_manifest_view: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve status field and transitions for a tab.

    Args:
        tab_title: Source tab title.
        interaction_contract_dict: Contract dict keyed by tab title.
        view_manifest_view: View entry from the view manifest, or None.

    Returns:
        Dict with ``field`` and ``transitions`` keys, or None.
    """
    # Priority 1: Interaction contract has status_semantics.
    ic_entry = interaction_contract_dict.get(tab_title)
    if ic_entry and "status_semantics" in ic_entry:
        semantics = ic_entry["status_semantics"]
        if isinstance(semantics, dict) and semantics:
            # Find the status field - check for a "field" key or use first entry
            return {
                "field": next(iter(semantics.keys()), ""),
                "transitions": dict(semantics),
            }

    # Priority 2: View manifest has status_field + status_values.
    if view_manifest_view:
        status_field = view_manifest_view.get("status_field")
        status_values = view_manifest_view.get("status_values")
        if status_field:
            result: dict[str, Any] = {"field": status_field}
            if status_values:
                # Build simple transitions from ordered status_values.
                transitions: dict[str, str] = {}
                sv_list = list(status_values)
                for sv_index in range(len(sv_list) - 1):
                    transitions[str(sv_list[sv_index])] = str(sv_list[sv_index + 1])
                if transitions:
                    result["transitions"] = transitions
            return result

    return None


def _resolve_role_hints(
    tab_title: str,
    interaction_contract_dict: dict[str, dict[str, Any]],
    view_manifest: dict[str, Any] | None,
) -> list[str]:
    """Resolve role hints for a tab.

    Args:
        tab_title: Source tab title.
        interaction_contract_dict: Contract dict keyed by tab title.
        view_manifest: View manifest, or None.

    Returns:
        List of role names.
    """
    # Priority 1: Interaction contract role owner.
    ic_entry = interaction_contract_dict.get(tab_title)
    if ic_entry and "role_owner" in ic_entry:
        roles = [ic_entry["role_owner"]]
        reviewers = ic_entry.get("role_reviewers") or []
        roles.extend(r for r in reviewers if r not in roles)
        return roles

    # Priority 2: View manifest role_hints.
    if view_manifest:
        hints = (view_manifest.get("workflow_hints") or {}).get("role_hints") or []
        tab_hints = [h for h in hints if h.startswith(f"{tab_title}:")]
        if tab_hints:
            # Strip the "Tab: " prefix to return clean role names.
            return [h.split(":", 1)[1].strip() for h in tab_hints]

    return []


def _index_interaction_contract(
    interaction_contract: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Index the interaction contract by tab title across all interview entries.

    Merges archetype_overrides and status_semantics from all roles into
    a flat dict keyed by tab title.  Also returns a per-role supplement
    so that status_semantics, workflow_notes, weekly_actions, and
    access_hints carried by a role apply to all tabs that role owns,
    not just tabs with archetype_overrides.

    Args:
        interaction_contract: Parsed interaction-contract dict.

    Returns:
        Tuple of ``(index, role_supplement)``::

            index = {
                "Crop Planner": {
                    "archetype": "form",
                    "role_owner": "field_manager",
                    "status_semantics": {...},
                    "workflow_notes": "...",
                    "weekly_actions": [...],
                },
            }

            role_supplement = {
                "field_manager": {
                    "status_semantics": {...},
                    "workflow_notes": "...",
                    "weekly_actions": [...],
                },
            }
    """
    index: dict[str, dict[str, Any]] = {}
    role_supplement: dict[str, dict[str, Any]] = {}
    for entry in interaction_contract.get("interviews") or []:
        role = entry.get("role", "")
        overrides = entry.get("archetype_overrides") or {}
        semantics = entry.get("status_semantics") or {}

        # Per-role supplemental data (applies to all tabs the role owns).
        role_data: dict[str, Any] = {}
        if semantics:
            role_data["status_semantics"] = dict(semantics)
        if entry.get("workflow_notes"):
            role_data["workflow_notes"] = str(entry["workflow_notes"])
        if entry.get("weekly_actions"):
            role_data["weekly_actions"] = list(entry["weekly_actions"])
        if entry.get("access_hints"):
            role_data["access_hints"] = dict(entry["access_hints"])
        if role_data and role:
            role_supplement[role] = role_data

        # Archetype overrides: keyed by tab title.
        for tab_name, archetype in overrides.items():
            tab_entry = index.setdefault(str(tab_name), {})
            tab_entry["archetype"] = str(archetype)
            tab_entry["role_owner"] = role
            tab_entry["role_reviewers"] = list(entry.get("role_reviewers") or [])
            # Status semantics (per-role, applied to each override tab).
            if semantics:
                tab_entry["status_semantics"] = dict(semantics)
                tab_entry["workflow_notes"] = str(entry.get("workflow_notes") or "")
                tab_entry["weekly_actions"] = list(
                    entry.get("weekly_actions") or []
                )
            # Access hints: flowed from interview entry.
            access = entry.get("access_hints") or {}
            if access:
                tab_entry["access_hints"] = dict(access)

    return index, role_supplement


def _index_profiler_signals(
    profiler_signals: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Index profiler signals by tab title.

    Args:
        profiler_signals: Parsed profiler-signals dict.

    Returns:
        Dict mapping tab title to signal dict.
    """
    index: dict[str, dict[str, Any]] = {}
    for signal in profiler_signals.get("signals") or []:
        tab_title = str(signal.get("tab_title") or "")
        if tab_title:
            index[tab_title] = signal
    return index


def merge_manifests(
    *,
    profiler_signals: dict[str, Any] | None = None,
    interaction_contract: dict[str, Any] | None = None,
    view_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge profiler signals, interaction contract, and view manifest.

    Merge priority (highest wins):
    1. Interaction contract override (Layer 2)
    2. Profiler signal (Layer 1)
    3. View manifest fallback

    Args:
        profiler_signals: Parsed profiler-signals dict with ``signals`` list.
        interaction_contract: Parsed interaction-contract dict with
            ``interviews`` list.
        view_manifest: Parsed view-manifest dict with ``views`` list.

    Returns:
        Codegen manifest dict::

            {
                "version": 1,
                "generated_at": "2026-06-01T...",
                "source_id": "...",
                "tables": [
                    {
                        "model_name": "CropPlanner",
                        "ui_archetype": "form",
                        "confidence": 0.85,
                        "workflow_hints": {
                            "editable": true,
                            "status_field": "status",
                            "status_transitions": {"planted": "harvested"},
                            "roles": ["field_manager", "operations"],
                        },
                    },
                ],
            }
    """
    # Index inputs.
    signal_index = _index_profiler_signals(profiler_signals or {})
    contract_index, role_supplement = _index_interaction_contract(
        interaction_contract or {}
    )

    # Collect all unique tab titles from all sources.
    all_tab_titles: list[str] = []
    seen: set[str] = set()
    for title in signal_index:
        if title not in seen:
            all_tab_titles.append(title)
            seen.add(title)
    for title in contract_index:
        if title not in seen:
            all_tab_titles.append(title)
            seen.add(title)
    if view_manifest:
        for view in view_manifest.get("views") or []:
            title = str(view.get("source_tab") or "")
            if title and title not in seen:
                all_tab_titles.append(title)
                seen.add(title)

    # Build view lookup from manifest.
    view_lookup: dict[str, dict[str, Any]] = {}
    if view_manifest:
        for view in view_manifest.get("views") or []:
            title = str(view.get("source_tab") or "")
            if title:
                view_lookup[title] = view

    # Enrich contract_index with per-role supplement data for tabs that
    # have role_hints in the view manifest but no archetype_overrides.
    if view_manifest and role_supplement:
        role_hints = (
            view_manifest.get("workflow_hints") or {}
        ).get("role_hints") or []
        for hint in role_hints:
            if ":" not in hint:
                continue
            tab_name, role_name_str = hint.split(":", 1)
            tab_name = tab_name.strip()
            role_name = role_name_str.strip()
            if tab_name in contract_index:
                continue  # Already has data from archetype_overrides.
            if role_name in role_supplement:
                role_data = role_supplement[role_name]
                enriched_entry = contract_index.setdefault(tab_name, {})
                if "status_semantics" not in enriched_entry and "status_semantics" in role_data:
                    enriched_entry["status_semantics"] = role_data["status_semantics"]
                if "workflow_notes" not in enriched_entry and "workflow_notes" in role_data:
                    enriched_entry["workflow_notes"] = role_data["workflow_notes"]
                if "weekly_actions" not in enriched_entry and "weekly_actions" in role_data:
                    enriched_entry["weekly_actions"] = role_data["weekly_actions"]
                if "access_hints" not in enriched_entry and "access_hints" in role_data:
                    enriched_entry["access_hints"] = role_data["access_hints"]

    tables: list[dict[str, Any]] = []
    for tab_title in all_tab_titles:
        view = view_lookup.get(tab_title)

        # Resolve archetype and confidence.
        archetype, confidence = _resolve_archetype(
            tab_title, signal_index, contract_index, view
        )

        # Resolve status transitions.
        status_info = _resolve_status_transitions(
            tab_title, contract_index, view
        )

        # Resolve role hints.
        roles = _resolve_role_hints(tab_title, contract_index, view_manifest)

        raw_entity = (view or {}).get("entity")
        model_name = _to_pascal_case(raw_entity) or tab_title

        # Workflow hints.
        workflow_hints: dict[str, Any] = {}
        if archetype in ("form",):
            workflow_hints["editable"] = True
        else:
            workflow_hints["editable"] = False

        if status_info:
            workflow_hints["status_field"] = status_info.get("field", "")
            if status_info.get("transitions"):
                workflow_hints["status_transitions"] = status_info["transitions"]

        if roles:
            workflow_hints["roles"] = roles

        # Add workflow notes from interaction contract.
        ic_entry = contract_index.get(tab_title)
        if ic_entry and ic_entry.get("workflow_notes"):
            workflow_hints["workflow_notes"] = ic_entry["workflow_notes"]
        if ic_entry and ic_entry.get("weekly_actions"):
            workflow_hints["weekly_actions"] = ic_entry["weekly_actions"]

        table_entry: dict[str, Any] = {
            "model_name": model_name,
            "ui_archetype": archetype,
            "confidence": round(confidence, 2),
        }

        if workflow_hints:
            table_entry["workflow_hints"] = workflow_hints

        # Add access_hints from interaction contract.
        if ic_entry and ic_entry.get("access_hints"):
            table_entry["access_hints"] = ic_entry["access_hints"]

        tables.append(table_entry)

    source_id = ""
    if view_manifest:
        source_id = str(
            (view_manifest.get("source") or {}).get("source_id") or ""
        )

    return {
        "version": CODGEN_MANIFEST_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_id": source_id,
        "tables": tables,
    }
