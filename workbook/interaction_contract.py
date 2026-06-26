"""Interaction contract YAML schema model (Layer 2 of the three-layer contract).

The interaction contract captures human-authored or discovery-interview-derived
decisions about how each spreadsheet tab is **used**: role ownership, status
semantics, archetype overrides, workflow notes, weekly actions, and access
control hints.

Schema format (``interaction-contract-1``)::

    version: interaction-contract-1
    generated_at: "2026-06-01T..."
    source_id: "farm_corpus"
    interviews:
      - role: "field_manager"
        archetype_overrides:
          "Crop Planner": "form"
        status_semantics:
          planted: "active"
          harvested: "complete"
        workflow_notes: "Field managers update crop status weekly"
        weekly_actions:
          - "Mark crops as harvested"
          - "Add weekly bed count"
        access_hints:
          internal_only: false
          restricted_to: []

Merge strategy
--------------
Profiler signal (Layer 1) is the default. Interaction contract (Layer 2)
overrides per-tab when present. The merge tool (``manifest_merger``) resolves
both into the codegen manifest (Layer 3).
"""

from __future__ import annotations

import datetime
from typing import Any

INTERACTION_CONTRACT_VERSION = "interaction-contract-1"

# Required top-level keys for a valid interaction contract.
_REQUIRED_KEYS = {"version", "interviews"}

# Valid archetype values for overrides.
_VALID_ARCHETYPES = {"form", "list", "dashboard", "reference"}

# Per-interview-entry required keys.
_INTERVIEW_REQUIRED = {"role"}


def _validate_interview_entry(entry: dict[str, Any], index: int) -> list[str]:
    """Validate a single interview entry, returning a list of error messages.

    Args:
        entry: A single interview dict.
        index: 0-based index of this entry in the interviews list.

    Returns:
        List of validation error strings (empty if valid).
    """
    errors: list[str] = []

    missing = _INTERVIEW_REQUIRED - set(entry.keys())
    if missing:
        errors.append(
            f"interviews[{index}]: missing required keys: {', '.join(sorted(missing))}"
        )

    role = entry.get("role")
    if role and not isinstance(role, str):
        errors.append(
            f"interviews[{index}]: 'role' must be a string, got {type(role).__name__}"
        )

    # Validate archetype_overrides if present.
    overrides = entry.get("archetype_overrides")
    if overrides is not None:
        if not isinstance(overrides, dict):
            errors.append(
                f"interviews[{index}]: 'archetype_overrides' must be a mapping, "
                f"got {type(overrides).__name__}"
            )
        else:
            for tab_name, archetype in overrides.items():
                if not isinstance(archetype, str):
                    errors.append(
                        f"interviews[{index}]: archetype for {tab_name!r} must be a string, "
                        f"got {type(archetype).__name__}"
                    )
                elif archetype not in _VALID_ARCHETYPES:
                    errors.append(
                        f"interviews[{index}]: archetype for {tab_name!r} must be one of "
                        f"{sorted(_VALID_ARCHETYPES)}, got {archetype!r}"
                    )

    # Validate status_semantics if present.
    semantics = entry.get("status_semantics")
    if semantics is not None:
        if not isinstance(semantics, dict):
            errors.append(
                f"interviews[{index}]: 'status_semantics' must be a mapping, "
                f"got {type(semantics).__name__}"
            )
        else:
            for key, value in semantics.items():
                if not isinstance(value, str):
                    errors.append(
                        f"interviews[{index}]: status_semantics value for {key!r} must be a string, "
                        f"got {type(value).__name__}"
                    )

    # Validate workflow_notes if present.
    notes = entry.get("workflow_notes")
    if notes is not None and not isinstance(notes, str):
        errors.append(
            f"interviews[{index}]: 'workflow_notes' must be a string, "
            f"got {type(notes).__name__}"
        )

    # Validate weekly_actions if present.
    actions = entry.get("weekly_actions")
    if actions is not None:
        if not isinstance(actions, list):
            errors.append(
                f"interviews[{index}]: 'weekly_actions' must be a list, "
                f"got {type(actions).__name__}"
            )
        else:
            for action_index, action in enumerate(actions):
                if not isinstance(action, str):
                    errors.append(
                        f"interviews[{index}]: weekly_actions[{action_index}] must be a string, "
                        f"got {type(action).__name__}"
                    )

    # Validate access_hints if present.
    access = entry.get("access_hints")
    if access is not None:
        if not isinstance(access, dict):
            errors.append(
                f"interviews[{index}]: 'access_hints' must be a mapping, "
                f"got {type(access).__name__}"
            )

    return errors


def validate_interaction_contract(raw: dict[str, Any]) -> list[str]:
    """Validate an interaction contract dict, returning a list of error messages.

    Args:
        raw: Parsed interaction-contract YAML dict.

    Returns:
        List of validation error strings. An empty list means the contract is valid.
    """
    errors: list[str] = []

    if not isinstance(raw, dict):
        return ["interaction contract must be a YAML mapping"]

    missing = _REQUIRED_KEYS - set(raw.keys())
    if missing:
        errors.append(f"missing required top-level keys: {', '.join(sorted(missing))}")

    version = raw.get("version")
    if version != INTERACTION_CONTRACT_VERSION:
        errors.append(
            f"unsupported version: {version!r}; expected {INTERACTION_CONTRACT_VERSION!r}"
        )

    interviews = raw.get("interviews")
    if interviews is None:
        errors.append("missing required key: 'interviews'")
    elif not isinstance(interviews, list):
        errors.append(f"'interviews' must be a list, got {type(interviews).__name__}")
    else:
        for entry_index, entry in enumerate(interviews):
            errors.extend(_validate_interview_entry(entry, entry_index))

    return errors


def build_interaction_contract(
    *,
    source_id: str = "",
    interviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a valid interaction-contract dict.

    Args:
        source_id: Optional identifier for the source workbook.
        interviews: List of interview entry dicts.  Each entry must have at
            least a ``role`` key; other keys are optional.

    Returns:
        A valid interaction-contract dict conforming to ``interaction-contract-1``.
    """
    return {
        "version": INTERACTION_CONTRACT_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_id": source_id,
        "interviews": list(interviews or []),
    }


def merge_strategy() -> str:
    """Return a description of the merge strategy for documentation purposes.

    The merge strategy is: profiler signal is the default, interaction contract
    overrides per-tab when present.
    """
    return (
        "Profiler signal (Layer 1) is the default. "
        "Interaction contract (Layer 2) overrides per-tab when present. "
        "The merge tool resolves both into the codegen manifest (Layer 3)."
    )
