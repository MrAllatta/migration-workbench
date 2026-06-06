"""Generate, parse, and merge discovery-interview Markdown for view manifests.

The discovery interview is a structured Markdown questionnaire pre-populated
from a view manifest. A consultant runs it with a client to capture role
ownership, status semantics, and weekly actions, then feeds the operator's
answers back into the manifest's ``role_hints``, ``weekly_actions``, and
per-view ``notes`` fields.

The Markdown emitted here is hand-editable. Each answerable question is
preceded by an HTML comment marker (``<!-- q: TYPE key=val -->``) so the
parser can locate answers without matching free-form question prose.

Public functions:

- :func:`render_interview` — manifest dict to interview Markdown.
- :func:`parse_interview` — operator-filled Markdown to a patch dict.
- :func:`apply_discovery_patch` — merges a patch into a fresh manifest copy.
- :func:`render_summary` — annotated manifest to discovery-summary Markdown.
- :func:`build_interaction_contract_from_patch` — patch dict to interaction-contract dict.
"""

from __future__ import annotations

import copy
import datetime as _dt
import re
from typing import Any

INTERVIEW_FORMAT_VERSION = "draft-1"
_FORMAT_HEADER = f"<!-- discovery-interview-format: {INTERVIEW_FORMAT_VERSION} -->"

_PLACEHOLDER = "_Your answer:_"

_QUESTION_MARKER_RE = re.compile(r"<!--\s*q:\s*([^\s>]+)((?:\s+[\w]+=\S+)*)\s*-->")
_KV_RE = re.compile(r"(\w+)=(\S+)")
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_LIST_ITEM_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _format_inferred_fields(fields: list[str], glossary_hints: list[str] | None = None) -> str:
    """Render an inline reminder of inferred editable fields, comma-separated."""
    if not fields and not glossary_hints:
        return "(none inferred)"
    parts = []
    if fields:
        parts.extend(fields)
    if glossary_hints:
        parts.append(f"(glossary: {', '.join(glossary_hints)})")
    return ", ".join(parts)


def _extract_role_name(full_answer: str) -> str:
    """Extract a concise role name from a full interview answer.
    
    Answers are expected to be in the format:
    "Role description — explanation" or "Role description. explanation"
    
    Returns the role description part, stripped of whitespace.
    """
    if not full_answer:
        return ""
    
    # Split on common delimiters: " — " (em dash) or ". " (period + space)
    # Take the first part as the role name
    if " — " in full_answer:
        return full_answer.split(" — ", 1)[0].strip()
    elif ". " in full_answer:
        return full_answer.split(". ", 1)[0].strip()
    else:
        # If no delimiter found, return the whole answer stripped
        return full_answer.strip()


def _question_marker(kind: str, **kwargs: str) -> str:
    """Emit ``<!-- q: kind key=val ... -->`` with stable key ordering."""
    parts = [f"<!-- q: {kind}"]
    for key in sorted(kwargs):
        parts.append(f"{key}={kwargs[key]}")
    return " ".join(parts) + " -->"


def _render_view_block(
    view: dict[str, Any],
    *,
    tab_role_presets: dict[str, list[str]] | None = None,
    tab_glossary_hints: dict[str, list[str]] | None = None,
) -> list[str]:
    """Render the per-view section of the interview for one view entry.

    Args:
        view: A view manifest entry dict.
        tab_role_presets: Optional mapping of tab title to list of role
            names from a vertical template. Pre-fills the role question.
        tab_glossary_hints: Optional mapping of tab title to list of
            glossary terms from a vertical template.
    """
    title = str(view.get("source_tab") or view.get("name") or "")
    hidden = bool(view.get("hidden") or view.get("type") == "hidden")
    # ``hidden`` is not on the manifest view shape directly; we recognise
    # hidden tabs by absence from ``workflow_hints.tab_sequence`` instead.
    lines: list[str] = []
    if hidden:
        # Reserved for future use; current call sites pass hidden flag externally.
        pass
    if view.get("_is_hidden_tab"):
        lines.append(f"### {title} (hidden tab — staging/admin)")
        lines.append("")
        lines.append(_question_marker("access", tab=title))
        lines.append(f"- Who has access to **{title}**? Is this an internal-only tab?")
        lines.append(f"  > {_PLACEHOLDER}")
        lines.append("")
        return lines

    lines.append(f"### {title} (source tab: {title})")
    lines.append("")
    lines.append(_question_marker("role", tab=title))
    lines.append(f"- Is **{title}** used by everyone, or a specific role?")
    role_presets = (tab_role_presets or {}).get(title)
    if role_presets:
        lines.append(f"  > {_PLACEHOLDER} (vertical presets: {', '.join(role_presets)})")
    else:
        lines.append(f"  > {_PLACEHOLDER}")
    lines.append("")
    fields = list(view.get("editable_fields") or [])
    glossary_hints = view.get("_vertical_glossary_hints")
    lines.append("- Which fields does your team edit most frequently?")
    lines.append(f"  > _Editable fields inferred: {_format_inferred_fields(fields, glossary_hints)}_")
    lines.append("")
    status_field = view.get("status_field")
    if status_field:
        lines.append(_question_marker("status", tab=title, field=str(status_field)))
        lines.append(
            f"- What does moving the **{status_field}** field from one value to another mean in your process?"
        )
        lines.append(f"  > {_PLACEHOLDER}")
        lines.append("")
        lines.append(
            _question_marker("status_override", tab=title, field=str(status_field))
        )
        lines.append(
            f"- Should the status field for **{title}** be different from **{status_field}**?"
        )
        lines.append(f"  > {_PLACEHOLDER} (leave blank to keep **{status_field}**)")
        lines.append("")
    return lines


def _annotate_hidden_views(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a copy of views with ``_is_hidden_tab`` set when absent from sequence."""
    sequence = set((manifest.get("workflow_hints") or {}).get("tab_sequence") or [])
    annotated: list[dict[str, Any]] = []
    for view in manifest.get("views") or []:
        v = dict(view)
        title = str(view.get("source_tab") or "")
        v["_is_hidden_tab"] = bool(title and title not in sequence)
        annotated.append(v)
    return annotated


def _build_tab_role_presets(
    vertical_template: dict[str, Any] | None,
) -> dict[str, list[str]]:
    """Build tab-to-roles mapping from a vertical template's interaction defaults.

    Args:
        vertical_template: Optional vertical template dict (e.g. from
            ``VerticalTemplate`` attributes).

    Returns:
        Mapping of tab title to list of role names, or empty dict.
    """
    presets: dict[str, list[str]] = {}
    if not vertical_template:
        return presets
    roles = (vertical_template.get("interaction_defaults") or {}).get("roles") or {}
    for role_name, role_config in roles.items():
        role_tabs = role_config.get("tabs") or []
        for tab_name in role_tabs:
            presets.setdefault(str(tab_name), []).append(str(role_name))
    return presets


def _build_tab_glossary_hints(
    vertical_template: dict[str, Any] | None,
) -> dict[str, list[str]]:
    """Build tab-to-glossary-terms mapping from a vertical template's vocabulary.

    Maps each vocabulary category (operational, reference, etc.) to its
    list of terms.  The caller may use these hints to enrich interview
    questions about tab content.

    Args:
        vertical_template: Optional vertical template dict.

    Returns:
        Mapping of tab title to list of glossary terms, or empty dict.
    """
    hints: dict[str, list[str]] = {}
    if not vertical_template:
        return hints
    vocabulary = (
        (vertical_template.get("domain_context") or {}).get("vocabulary") or {}
    )
    for category, terms in vocabulary.items():
        hints[category] = list(terms) if isinstance(terms, list) else [str(terms)]
    return hints


def render_interview(
    manifest: dict[str, Any],
    *,
    source_id: str | None = None,
    vertical_template: dict[str, Any] | None = None,
) -> str:
    """Render a view manifest into a discovery-interview Markdown document.

    Args:
        manifest: Parsed view-manifest dict (``view-manifest-draft-1``).
        source_id: Optional override; defaults to ``manifest["source"]["source_id"]``.
        vertical_template: Optional vertical template dict with
            ``interaction_defaults.roles`` and/or ``domain_context.vocabulary``
            to pre-seed role presets and glossary hints.

    Returns:
        str: Markdown text terminated with a trailing newline.
    """
    sid = source_id
    if sid is None:
        sid = (manifest.get("source") or {}).get("source_id") or "(unset)"

    tab_role_presets = _build_tab_role_presets(vertical_template)
    tab_glossary_hints = _build_tab_glossary_hints(vertical_template)

    lines: list[str] = [
        _FORMAT_HEADER,
        f"# Discovery Interview \u2014 {sid}",
        "",
        "## Top-level",
        "",
        _question_marker("weekly_workflow"),
        "1. Walk me through what you do with this sheet on a typical Monday.",
        f"   > {_PLACEHOLDER}",
        "",
        "## Per-view questions",
        "",
    ]

    annotated_views = _annotate_hidden_views(manifest)
    for view in annotated_views:
        lines.extend(
            _render_view_block(
                view,
                tab_role_presets=tab_role_presets,
                tab_glossary_hints=tab_glossary_hints,
            )
        )

    lines.extend(
        [
            "## Workflow actions",
            "",
            _question_marker("weekly_actions"),
            "- What are the 3\u20135 things you do in this sheet every week?",
            f"  1. {_PLACEHOLDER}",
            f"  2. {_PLACEHOLDER}",
            f"  3. {_PLACEHOLDER}",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _strip_placeholder(text: str) -> str:
    """Return ``text`` with the answer placeholder removed; empty if unanswered."""
    cleaned = text.strip()
    if not cleaned:
        return ""
    if cleaned == _PLACEHOLDER or _PLACEHOLDER in cleaned:
        return ""
    return cleaned


def _next_blockquote_answer(lines: list[str], start: int) -> str:
    """Find the first non-placeholder blockquote answer at or after ``start``.

    Walks forward looking for a ``> ...`` blockquote. Tolerates both filling
    conventions: operator replaces the placeholder in-place, *or* appends a
    new blockquote line below the placeholder. Stops at blank lines once the
    placeholder has been seen, at headings, at non-list / non-blockquote text
    that looks like a new question (e.g. the editable-fields reminder), and at
    new ``<!-- q: ... -->`` markers.
    """
    saw_placeholder = False
    for offset in range(0, 8):
        idx = start + offset
        if idx >= len(lines):
            break
        line = lines[idx]
        if _HEADING_RE.match(line):
            break
        if offset > 0 and _QUESTION_MARKER_RE.search(line):
            break
        match = _BLOCKQUOTE_RE.match(line)
        if match:
            content = match.group(1).strip()
            if not content or content == _PLACEHOLDER or _PLACEHOLDER in content:
                saw_placeholder = True
                continue
            return content
        if line.strip() == "":
            # Blank lines after the placeholder mean the operator left the
            # answer empty; stop before drifting into the next question.
            if saw_placeholder:
                break
            continue
        if _LIST_ITEM_RE.match(line):
            # Numbered list items belong to a different question type.
            if saw_placeholder:
                break
            continue
        if line.lstrip().startswith("- ") and saw_placeholder:
            # New bullet introduces a different question; the prior answer
            # was left blank.
            break
    return ""


def _collect_list_items(lines: list[str], start: int) -> list[str]:
    """Collect numbered list items immediately under a workflow-actions question.

    Stops at the next heading or question marker, or when a blank line is
    followed by a non-list line.
    """
    items: list[str] = []
    blanks = 0
    for offset in range(0, 30):
        idx = start + offset
        if idx >= len(lines):
            break
        line = lines[idx]
        if _HEADING_RE.match(line):
            break
        if offset > 0 and _QUESTION_MARKER_RE.search(line):
            break
        match = _LIST_ITEM_RE.match(line)
        if match:
            answer = _strip_placeholder(match.group(1))
            if answer:
                items.append(answer)
            blanks = 0
            continue
        if line.strip() == "":
            blanks += 1
            if blanks >= 2:
                break
            continue
    return items


def parse_interview(interview_text: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Parse an operator-filled interview Markdown into a discovery patch dict.

    The parser locates ``<!-- q: TYPE key=val -->`` markers; missing markers
    are tolerated so partially-filled or trimmed Markdown still works.

    Args:
        interview_text: Full Markdown text of the (filled) interview.
        manifest: The manifest the interview was generated from.  Currently
            unused for parsing but accepted for forward compatibility (e.g.
            future heuristics that map answers to specific view entries).

    Returns:
        dict: Patch dict::

            {
                "role_hints": ["Orders: finance team only", ...],
                "weekly_actions": ["Check open orders", ...],
                "view_notes": {"Orders": "...", "Staging": "..."},
                "weekly_workflow": "...",
            }
    """
    # ``manifest`` is reserved for future use; current parsing is purely
    # marker-driven and does not need to consult it.
    del manifest

    lines = interview_text.splitlines()
    role_hints: list[str] = []
    weekly_actions: list[str] = []
    view_notes: dict[str, list[str]] = {}
    weekly_workflow = ""
    status_overrides: dict[str, str] = {}

    for idx, line in enumerate(lines):
        match = _QUESTION_MARKER_RE.search(line)
        if not match:
            continue
        kind = match.group(1)
        attrs = dict(_KV_RE.findall(match.group(2) or ""))

        if kind == "weekly_workflow":
            answer = _next_blockquote_answer(lines, idx + 1)
            if answer:
                weekly_workflow = answer
        elif kind == "weekly_actions":
            weekly_actions.extend(_collect_list_items(lines, idx + 1))
        elif kind == "role":
            tab = attrs.get("tab") or ""
            answer = _next_blockquote_answer(lines, idx + 1)
            if tab and answer:
                role_hints.append(f"{tab}: {answer}")
        elif kind == "status":
            tab = attrs.get("tab") or ""
            field = attrs.get("field") or ""
            answer = _next_blockquote_answer(lines, idx + 1)
            if tab and answer:
                note = f"status[{field}]: {answer}" if field else f"status: {answer}"
                view_notes.setdefault(tab, []).append(note)
        elif kind == "access":
            tab = attrs.get("tab") or ""
            answer = _next_blockquote_answer(lines, idx + 1)
            if tab and answer:
                view_notes.setdefault(tab, []).append(f"access: {answer}")
        elif kind == "status_override":
            tab = attrs.get("tab") or ""
            answer = _next_blockquote_answer(lines, idx + 1)
            if tab and answer:
                status_overrides[tab] = answer

    return {
        "role_hints": role_hints,
        "weekly_actions": weekly_actions,
        "view_notes": {tab: " | ".join(parts) for tab, parts in view_notes.items()},
        "weekly_workflow": weekly_workflow,
        "status_overrides": status_overrides,
    }


def apply_discovery_patch(
    manifest: dict[str, Any], patch: dict[str, Any]
) -> dict[str, Any]:
    """Return a deep-copied manifest with discovery-patch fields merged in.

    - ``workflow_hints.role_hints`` is replaced with the patch list (any
      pre-existing hints remain at the front so re-runs are additive).
    - ``workflow_hints.weekly_actions`` is replaced with the patch list,
      preserving any existing entries first.
    - ``views[].notes`` is set per-tab from ``patch["view_notes"]``; existing
      notes are preserved when the patch does not cover that tab.

    Args:
        manifest: Source manifest dict; not mutated.
        patch: Patch dict produced by :func:`parse_interview`.

    Returns:
        dict: New manifest dict with patch applied.
    """
    out = copy.deepcopy(manifest)
    hints = out.setdefault("workflow_hints", {})

    existing_roles = list(hints.get("role_hints") or [])
    new_roles = list(patch.get("role_hints") or [])
    merged_roles = existing_roles + [r for r in new_roles if r not in existing_roles]
    hints["role_hints"] = merged_roles

    existing_actions = list(hints.get("weekly_actions") or [])
    new_actions = list(patch.get("weekly_actions") or [])
    merged_actions = existing_actions + [
        a for a in new_actions if a not in existing_actions
    ]
    hints["weekly_actions"] = merged_actions

    note_map = patch.get("view_notes") or {}
    for view in out.get("views") or []:
        tab = str(view.get("source_tab") or "")
        if tab in note_map:
            existing = view.get("notes")
            new_note = note_map[tab]
            if existing:
                view["notes"] = f"{existing} | {new_note}"
            else:
                view["notes"] = new_note

    status_overrides = patch.get("status_overrides") or {}
    for view in out.get("views") or []:
        tab = str(view.get("source_tab") or "")
        if tab in status_overrides:
            override = status_overrides[tab]
            suppressed = override.lower() in ("", "none", "null", "clear")
            if suppressed:
                view["status_field"] = None
            else:
                view["status_field"] = override

    return out


def render_summary(
    manifest: dict[str, Any],
    *,
    generated_at: str | None = None,
    weekly_workflow: str = "",
) -> str:
    """Render a discovery-summary Markdown recap from an annotated manifest.

    Args:
        manifest: Annotated manifest dict (post :func:`apply_discovery_patch`).
        generated_at: Optional ISO date string; defaults to today.
        weekly_workflow: Optional free-form narrative captured by the
            ``weekly_workflow`` interview question (not stored in the manifest).

    Returns:
        str: Markdown text terminated with a trailing newline.
    """
    sid = (manifest.get("source") or {}).get("source_id") or "(unset)"
    gen_at = generated_at or _dt.date.today().isoformat()
    hints = manifest.get("workflow_hints") or {}
    role_hints = list(hints.get("role_hints") or [])
    weekly_actions = list(hints.get("weekly_actions") or [])

    lines: list[str] = [
        f"# Discovery Summary \u2014 {sid}",
        "",
        f"Generated: {gen_at}",
        "",
    ]
    if weekly_workflow:
        lines.extend(["## Weekly workflow", "", weekly_workflow, ""])

    lines.extend(["## Role hints", ""])
    if role_hints:
        for rh in role_hints:
            lines.append(f"- {rh}")
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.extend(["## Weekly actions", ""])
    if weekly_actions:
        for idx, action in enumerate(weekly_actions, start=1):
            lines.append(f"{idx}. {action}")
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.extend(["## View notes", ""])
    annotated_any = False
    for view in manifest.get("views") or []:
        tab = view.get("source_tab") or view.get("name") or "(unnamed)"
        notes = view.get("notes")
        if notes:
            lines.append(f"- **{tab}**: {notes}")
            annotated_any = True
    if not annotated_any:
        lines.append("_(none)_")
    lines.append("")

    return "\n".join(lines) + "\n"


def build_interaction_contract_from_patch(
    patch: dict[str, Any],
    manifest: dict[str, Any],
    *,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Convert a discovery patch dict into an interaction-contract YAML dict.

    Maps the discovery interview patch fields to the interaction contract schema:

    - ``role_hints`` → ``interviews[].role`` entries, grouped by role.
    - ``view_notes`` with status info → ``interviews[].status_semantics``.
    - ``weekly_actions`` → ``interviews[].weekly_actions``.
    - ``status_overrides`` → ``interviews[].status_semantics`` enrichments.
    - Archetype overrides from manifest ``type`` changes → ``interviews[].archetype_overrides``.

    Args:
        patch: Patch dict produced by :func:`parse_interview` with keys
            ``role_hints``, ``weekly_actions``, ``view_notes``,
            ``weekly_workflow``, ``status_overrides``.
        manifest: Source manifest dict used to extract view types and
            tab titles.
        source_id: Optional source identifier.

    Returns:
        A valid interaction-contract dict conforming to
        ``interaction-contract-1``.
    """
    from workbook.interaction_contract import build_interaction_contract

    # Build roles → tab mapping from role_hints.
    # role_hints format: ["Tab: Role name", "Tab2: Role name2"]
    tab_to_role: dict[str, str] = {}
    for hint in patch.get("role_hints") or []:
        if ":" in hint:
            tab_name, role_name = hint.split(":", 1)
            # Extract concise role name from the full answer
            concise_role_name = _extract_role_name(role_name.strip())
            tab_to_role[tab_name.strip()] = concise_role_name

    # Collect archetype overrides from manifest per-view type annotations.
    # When the discovery interview changes a view's type from 'list' to
    # 'form'/'dashboard'/'reference', that is recorded as an override.
    # For now, we consider manifest type != 'list' as an override signal.
    archetype_overrides: dict[str, str] = {}
    for view in manifest.get("views") or []:
        tab_title = str(view.get("source_tab") or "")
        view_type = str(view.get("type") or "list")
        if tab_title and view_type != "list":
            archetype_overrides[tab_title] = view_type

    # Build status semantics from view_notes. Parse "status[field]: desc" patterns.
    status_semantics: dict[str, str] = {}
    for tab_name, notes in (patch.get("view_notes") or {}).items():
        if isinstance(notes, str) and "status[" in notes:
            # Extract status semantics from notes like "status[status]: open -> pending -> shipped"
            import re as _re

            status_match = _re.search(r"status\[([^\]]+)\]:\s*(.*)", notes)
            if status_match:
                field_name = status_match.group(1)
                desc = status_match.group(2)
                # Convert "open -> pending -> shipped" to individual status mappings
                if "->" in desc:
                    status_parts = [s.strip() for s in desc.split("->")]
                    for status_idx in range(len(status_parts) - 1):
                        status_semantics[status_parts[status_idx]] = status_parts[status_idx + 1]
                else:
                    status_semantics[field_name] = desc

    # Collect unique roles from role_hints.
    unique_roles = sorted({role for role in tab_to_role.values()})

    # Build interview entries.
    interviews: list[dict[str, Any]] = []
    for role_name in unique_roles:
        # Find tabs owned by this role.
        role_tabs = [t for t, r in tab_to_role.items() if r == role_name]

        # Build per-role archetype_overrides from tabs owned by this role.
        role_overrides: dict[str, str] = {}
        for tab_name in role_tabs:
            if tab_name in archetype_overrides:
                role_overrides[tab_name] = archetype_overrides[tab_name]

        entry: dict[str, Any] = {"role": role_name}

        if role_overrides:
            entry["archetype_overrides"] = role_overrides

        if status_semantics:
            entry["status_semantics"] = dict(status_semantics)

        workflow_notes = patch.get("weekly_workflow") or ""
        if workflow_notes:
            entry["workflow_notes"] = workflow_notes

        weekly_actions = patch.get("weekly_actions") or []
        if weekly_actions:
            entry["weekly_actions"] = list(weekly_actions)

        # Access hints from view_notes with "access:" prefix.
        access_notes = []
        for tab_name in role_tabs:
            notes = (patch.get("view_notes") or {}).get(tab_name, "")
            if isinstance(notes, str) and "access:" in notes:
                access_notes.append(f"{tab_name}: {notes}")
        if access_notes:
            entry["access_hints"] = {"notes": access_notes}

        interviews.append(entry)

        # If no roles were extracted from role_hints but there are weekly_actions
        # or status_semantics, create a default "operator" interview entry.
        all_weekly_actions = patch.get("weekly_actions") or []
        if not interviews and (all_weekly_actions or status_semantics):
            entry: dict[str, Any] = {"role": "operator"}
            if status_semantics:
                entry["status_semantics"] = dict(status_semantics)
            if all_weekly_actions:
                entry["weekly_actions"] = list(all_weekly_actions)
            interviews.append(entry)

    sid = source_id
    if sid is None:
        sid = (manifest.get("source") or {}).get("source_id") or ""

    return build_interaction_contract(source_id=sid, interviews=interviews)
