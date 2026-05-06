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


def _format_inferred_fields(fields: list[str]) -> str:
    """Render an inline reminder of inferred editable fields, comma-separated."""
    if not fields:
        return "(none inferred)"
    return ", ".join(fields)


def _question_marker(kind: str, **kwargs: str) -> str:
    """Emit ``<!-- q: kind key=val ... -->`` with stable key ordering."""
    parts = [f"<!-- q: {kind}"]
    for key in sorted(kwargs):
        parts.append(f"{key}={kwargs[key]}")
    return " ".join(parts) + " -->"


def _render_view_block(view: dict[str, Any]) -> list[str]:
    """Render the per-view section of the interview for one view entry."""
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
    lines.append(f"  > {_PLACEHOLDER}")
    lines.append("")
    fields = list(view.get("editable_fields") or [])
    lines.append("- Which fields does your team edit most frequently?")
    lines.append(f"  > _Editable fields inferred: {_format_inferred_fields(fields)}_")
    lines.append("")
    status_field = view.get("status_field")
    if status_field:
        lines.append(_question_marker("status", tab=title, field=str(status_field)))
        lines.append(
            f"- What does moving the **{status_field}** field from one value to another mean in your process?"
        )
        lines.append(f"  > {_PLACEHOLDER}")
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


def render_interview(manifest: dict[str, Any], *, source_id: str | None = None) -> str:
    """Render a view manifest into a discovery-interview Markdown document.

    Args:
        manifest: Parsed view-manifest dict (``view-manifest-draft-1``).
        source_id: Optional override; defaults to ``manifest["source"]["source_id"]``.

    Returns:
        str: Markdown text terminated with a trailing newline.
    """
    sid = source_id
    if sid is None:
        sid = (manifest.get("source") or {}).get("source_id") or "(unset)"

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
        lines.extend(_render_view_block(view))

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

    return {
        "role_hints": role_hints,
        "weekly_actions": weekly_actions,
        "view_notes": {tab: " | ".join(parts) for tab, parts in view_notes.items()},
        "weekly_workflow": weekly_workflow,
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
