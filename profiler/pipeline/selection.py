"""Shared corpus pipeline selection logic.

Provider-agnostic auto-selection and override merging for tab/table
shortlists.  Used by both Sheets and Coda adapters.
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import CommandError

TAB_SELECTION_OVERRIDE_KEYS = frozenset({"add", "remove", "replace", "tabs"})


def auto_select_tabs(
    tab_shortlist: list[dict],
    *,
    per_workbook: int = 3,
    per_code_overrides: dict[str, int] | None = None,
    score_cutoff: float | None = None,
    group_key: str = "workbook_code",
    name_key: str = "tab_title",
) -> tuple[dict[str, list[str]], dict[str, list[dict]]]:
    """Group shortlisted items by *group_key*, sort by score, and pick the top N per group.

    Args:
        tab_shortlist: Shortlisted records with ``final_score`` and
            ``occurrences``.
        per_workbook: Default maximum items per group.
        per_code_overrides: Per-group overrides for ``per_workbook``.
        score_cutoff: When set, items below this threshold are excluded.
        group_key: Field name for grouping (default ``"workbook_code"``).
        name_key: Field name for the item name (default ``"tab_title"``).

    Returns:
        tuple:
            - ``approved``: ``{group_key: [name, ...]}``
            - ``details``: ``{group_key: [{name_key, final_score, ...}]}``
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in tab_shortlist:
        grouped[row[group_key]].append(row)
    approved: dict[str, list[str]] = {}
    details: dict[str, list[dict]] = {}
    for group, rows in grouped.items():
        limit = (per_code_overrides or {}).get(group, per_workbook)
        rows.sort(
            key=lambda row: (-row["final_score"], -row["occurrences"], row[name_key])
        )
        if score_cutoff is not None:
            rows = [row for row in rows if row["final_score"] >= score_cutoff]
        selected = rows[:limit]
        approved[group] = [row[name_key] for row in selected]
        details[group] = [
            {
                name_key: row[name_key],
                "final_score": row["final_score"],
                "avg_score": row.get("avg_score"),
                "confidence": row.get("confidence"),
                "coverage_bonus": row.get("coverage_bonus"),
                "reasons": row.get("reasons"),
            }
            for row in selected
        ]
    return approved, details


def apply_tab_selection_overrides(
    approved_tabs: dict[str, list[str]],
    overrides: dict | None,
) -> dict[str, list[str]]:
    """Merge user-supplied tab selection overrides into heuristic *approved_tabs*.

    Each override entry supports three mutually exclusive operations:

    * ``replace: true`` + ``tabs: [...]`` — replace the group's entire
      selection with the provided list.
    * ``add: [...]`` — append tab titles not already present.
    * ``remove: [...]`` — remove tab titles from the current selection.

    Args:
        approved_tabs: Heuristic selection mapping
            ``{group_key: [tab_title, ...]}``.
        overrides: Optional ``{group_key: override_entry}`` dict from the
            corpus config.  ``None`` or empty returns a copy of *approved_tabs*
            unchanged.

    Returns:
        dict[str, list[str]]: Merged tab selection.

    Raises:
        CommandError: On type violations or unknown override keys.
    """
    merged: dict[str, list[str]] = {
        code: list(tabs) for code, tabs in approved_tabs.items()
    }
    if not overrides:
        return merged

    if not isinstance(overrides, dict):
        raise CommandError(
            "tab_selection_overrides must be a mapping of group_key to override entry"
        )

    for group_key, entry in overrides.items():
        if not isinstance(entry, dict):
            raise CommandError(
                f"tab_selection_overrides[{group_key!r}] must be a mapping; got {type(entry).__name__}"
            )
        unknown = set(entry.keys()) - TAB_SELECTION_OVERRIDE_KEYS
        if unknown:
            from workbench.exceptions import command_error

            raise command_error(
                f"tab_selection_overrides[{group_key!r}] has unknown keys: {sorted(unknown)}.",
                valid_values=sorted(TAB_SELECTION_OVERRIDE_KEYS),
                action=f"Replace the key(s) {sorted(unknown)} with valid keys.",
                check_id="PROFILER-OVERRIDE-001",
            )

        if entry.get("replace"):
            tabs = entry.get("tabs")
            if not isinstance(tabs, list) or not all(
                isinstance(item, str) for item in tabs
            ):
                raise CommandError(
                    f"tab_selection_overrides[{group_key!r}] requires 'tabs' as list[str] when 'replace' is true"
                )
            merged[group_key] = list(tabs)
            continue

        if "tabs" in entry:
            raise CommandError(
                f"tab_selection_overrides[{group_key!r}] uses 'tabs' without 'replace: true'"
            )

        add = entry.get("add", []) or []
        remove = entry.get("remove", []) or []
        if not isinstance(add, list) or not all(isinstance(item, str) for item in add):
            raise CommandError(
                f"tab_selection_overrides[{group_key!r}].add must be a list of strings"
            )
        if not isinstance(remove, list) or not all(
            isinstance(item, str) for item in remove
        ):
            raise CommandError(
                f"tab_selection_overrides[{group_key!r}].remove must be a list of strings"
            )

        current = merged.get(group_key, [])
        remove_set = set(remove)
        kept = [tab for tab in current if tab not in remove_set]
        for tab in add:
            if tab not in kept:
                kept.append(tab)
        merged[group_key] = kept

    return merged
