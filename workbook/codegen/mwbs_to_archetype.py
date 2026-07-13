"""MWBS-to-archetype adapter — convert behavioral spec elements into
archetype configs that the existing view generator can consume.

The adapter translates MWBS (Migration Workbench Behavioral Specification)
data classes into :class:`LandingArchetype`, :class:`ChecklistArchetype`,
and list view config dicts, bridging the gap between ``profiler/tools/behavioral_spec.py``
and ``workbook/codegen/view_generator.py``.

Usage::

    from profiler.tools.behavioral_spec import Actor, Report
    from workbook.codegen.mwbs_to_archetype import landing_from_actor

    archetype = landing_from_actor(actor, reports)
    view_source = render_landing_view_py(archetype)
"""

from __future__ import annotations

import re
from typing import Any

from profiler.tools.behavioral_spec import Actor, Report, WorkflowStep
from workbook.codegen.view_generator import LandingArchetype, SummaryCard


def _sluggify(name: str) -> str:
    """Convert a human-readable name to a snake_case identifier."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _responsibility_to_model_name(responsibility: str) -> str:
    """Heuristic: first noun-like token in a responsibility string becomes
    the Django model name hint.
    
    Examples:
        "Open tasks this week" → "Task"
        "Current plantings" → "Planting"
        "Nursery items to seed" → "NurserySeeding"
        "Low inventory alerts" → "Inventory"
    """
    parts = responsibility.split()
    if not parts:
        return "Record"
    
    # Skip generic leading adjectives and remove possessive apostrophes
    skip = {"open", "current", "low", "pending", "active", "closed", "past",
            "upcoming", "recent", "overdue", "new", "all"}
    model_part = None
    for p in parts:
        cleaned = p.strip("'s").lower()
        if cleaned not in skip:
            # Strip any possessive or punctuation for safe Python identifiers
            model_part = p.replace("'", "").replace("`", "")
            break
    if not model_part:
        model_part = parts[-1].replace("'", "").replace("`", "")
    
    # Capitalize first letter
    model_name = model_part[0].upper() + model_part[1:] if model_part else "Record"
    
    # Remove trailing punctuation
    model_name = model_name.rstrip(".")
    
    return model_name


def _responsibility_to_count_expression(
    responsibility: str,
    model_name_overrides: dict[str, str] | None = None,
) -> str:
    """Turn a human-readable responsibility into a draft Django ORM count expression.

    The generated expression is a best-effort heuristic. It is designed to be
    human-editable after code generation, matching the existing pattern where
    archetype configs are YAML inputs that a human reviews.

    Examples:
        "Open tasks this week" → ``Task.objects.filter(status='open').count()``
        "Assigned tasks today" → ``Task.objects.filter(assigned=True).count()``
    """
    model_name = _responsibility_to_model_name(responsibility)

    # Apply overrides: match lowercased responsibility words to override keys
    if model_name_overrides:
        for word in responsibility.lower().split():
            word = word.strip("'s")
            if word in model_name_overrides:
                model_name = model_name_overrides[word]
                break
    low = responsibility.lower()
    
    # Detect year/week filtering pattern
    week_filters = []
    if "this week" in low or "current week" in low:
        week_filters.append("planned_year=current_year")
        week_filters.append("planned_week=current_week")
    if "today" in low or "current day" in low:
        week_filters.append("planned_date=current_date")
    
    # Detect status filtering
    status_filter = ""
    for token in ("open", "pending", "active", "overdue", "closed", "completed"):
        if token in low:
            status_filter = f"status='{token}'"
            break
    
    parts = []
    if status_filter:
        parts.append(status_filter)
    parts.extend(week_filters)
    
    if parts:
        filter_args = ", ".join(parts)
        return f"{model_name}.objects.filter({filter_args}).count()"
    else:
        return f"{model_name}.objects.count()"


def _report_to_summary_card(
    report: Report,
    model_name_overrides: dict[str, str] | None = None,
) -> SummaryCard:
    """Map an MWBS Report to a SummaryCard displaying a recent-items list."""
    label = report.title if report.title else report.id.replace("-", " ").title()
    # The card shows "recent N items" — the template iterates the list
    model_name = _responsibility_to_model_name(label)
    if model_name_overrides:
        for word in label.lower().split():
            word = word.strip("'s")
            if word in model_name_overrides:
                model_name = model_name_overrides[word]
                break
    count_expr = f"{model_name}.objects.order_by('-id')[:10]"
    return SummaryCard(
        label=label,
        count_expression=f"len({count_expr})",
    )


def landing_from_actor(
    actor: Actor,
    reports: list[Report],
    model_name_overrides: dict[str, str] | None = None,
) -> LandingArchetype:
    """Convert an MWBS ``Actor`` and associated ``Report`` list into a
    ``LandingArchetype`` config suitable for ``render_landing_view_py()``.

    Each of the actor's ``responsibilities`` becomes a
    :class:`SummaryCard` with a heuristic ORM count expression.  Each
    MWBS ``Report`` becomes a card showing recent items.

    Args:
        actor: The MWBS Actor whose landing to generate.
        reports: MWBS Reports this actor subscribes to.
        model_name_overrides: Optional dict mapping responsibility keywords
            to explicit Django model names.  Keys are lowercase tokens
            found in the responsibility string; values are model names.
            Example: ``{"task": "TaskPlan", "planting": "PlantingPlan"}``

    Returns:
        LandingArchetype config ready for the view generator.
    """
    role = actor.id if actor.id else _sluggify(actor.name)
    title = f"{actor.name} — Dashboard"

    cards: list[SummaryCard] = []
    for responsibility in actor.responsibilities:
        card = SummaryCard(
            label=responsibility,
            count_expression=_responsibility_to_count_expression(
                responsibility, model_name_overrides
            ),
        )
        cards.append(card)

    for report in reports:
        cards.append(_report_to_summary_card(report, model_name_overrides))

    return LandingArchetype(
        role=role,
        title=title,
        cards=cards,
    )


def _parse_filter_hints(system_provides: list[str]) -> list[str]:
    """Extract filter field names from ``system_provides`` hints.

    Heuristic: if a string starts with "Filter by " the remainder is a
    comma-or-" and "-separated list of field names.
    """
    filters: list[str] = []
    for hint in system_provides:
        low = hint.lower()
        if low.startswith("filter by "):
            remainder = low[len("filter by "):]
            for token in re.split(r"[,/]|\band\b|\bor\b", remainder):
                token = token.strip()
                if token:
                    filters.append(_sluggify(token))
    return filters


def list_from_workflow_step(
    step: WorkflowStep,
    model_name: str,
) -> dict[str, Any]:
    """Convert an MWBS ``WorkflowStep`` into a list view config dict.

    The config dict is shaped to match :class:`workbook.codegen.list_generator.ListArchetype`
    and can be passed directly to ``ListArchetype(**config)``.

    Args:
        step: The MWBS workflow step with list semantics.
        model_name: Name of the Django model this list displays.

    Returns:
        Config dict with keys: ``model``, ``title``, ``description``,
        ``columns``, ``filters``, ``ordering``, ``paginate_by``,
        ``context_object_name``, ``filter_options``, ``template_path``,
        ``app_label``.
    """
    title = step.title if step.title else step.id.replace("-", " ").title()

    columns: list[str] = []
    for hint in step.system_provides:
        if "list" in hint.lower() or "browse" in hint.lower():
            # Extract field-like tokens
            tokens = re.findall(r"[A-Z][a-z]+|[a-z]+", hint)
            columns.extend(t.lower() for t in tokens if t.lower() not in {
                "with", "and", "by", "list", "browse", "filter", "the",
                "status",
            })

    if not columns:
        columns = ["name"]

    filters = _parse_filter_hints(step.system_provides)

    # Detect ordering hints ("Ordered by name" → ordering=["name"])
    ordering: list[str] = []
    for hint in step.system_provides:
        low = hint.lower()
        if low.startswith("ordered by "):
            field_part = low[len("ordered by "):].strip()
            for token in re.split(r"[,/]|\band\b|\bor\b", field_part):
                token = token.strip()
                if token:
                    ordering.append(_sluggify(token))
        elif low.startswith("sort by "):
            field_part = low[len("sort by "):].strip()
            for token in re.split(r"[,/]|\band\b|\bor\b", field_part):
                token = token.strip()
                if token:
                    ordering.append(_sluggify(token))

    if not ordering:
        ordering = ["name"]

    # Detect pagination hints ("Pagination" or "50 per page" → paginate_by=50)
    paginate_by = 50
    for hint in step.system_provides:
        low = hint.lower()
        match = re.search(r"(\d+)\s+per\s+page", low)
        if match:
            paginate_by = int(match.group(1))
            break
        if "paginate" in low or "pagination" in low:
            # Default to 50 if pagination is hinted
            paginate_by = 50
            break

    # Default context_object_name: model name snake_case + 's'
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", model_name).lower()
    if snake.endswith("y"):
        context_object_name = f"{snake[:-1]}ies"
    elif snake.endswith("s"):
        context_object_name = snake
    else:
        context_object_name = f"{snake}s"

    return {
        "model": model_name,
        "title": title,
        "columns": columns,
        "filters": filters,
        "ordering": ordering,
        "paginate_by": paginate_by,
        "context_object_name": context_object_name,
        "filter_options": {},
        "template_path": f"generated/list_{snake}.html",
        "app_label": "core",
    }
