"""Tests for the MWBS-to-archetype adapter.

Covers:
- ``landing_from_actor`` maps an ``Actor`` + ``Report`` list to a
  ``LandingArchetype`` config.
- ``list_from_workflow_step`` maps a ``WorkflowStep`` to a list view config.
- Full round-trip: MWBS YAML → archetype → generated view code → valid Python.

These tests exercise the adapter logic only (no database, no Django setup).
"""

from __future__ import annotations

import ast

import pytest

from profiler.tools.behavioral_spec import Actor, Report, WorkflowStep
from workbook.codegen.mwbs_to_archetype import landing_from_actor, list_from_workflow_step
from workbook.codegen.view_generator import LandingArchetype, SummaryCard


class TestLandingFromActor:
    """landing_from_actor: Actor + Report list → LandingArchetype."""

    def test_planner_actor_produces_landing_archetype(self):
        """A Planner actor with responsibilities and reports yields a
        LandingArchetype with matching role, title, and summary cards."""
        actor = Actor(
            id="planner_manager",
            name="Planner / Manager",
            responsibilities=[
                "Open tasks this week",
                "Current plantings",
                "Nursery items to seed",
                "Low inventory alerts",
            ],
            access_level="full",
        )
        reports = [
            Report(
                id="recent-events",
                title="Recent Events",
                audience="planner_manager",
                format="list",
                displays=["event_date", "crop", "field_block", "description"],
            ),
        ]

        archetype = landing_from_actor(actor, reports)

        assert isinstance(archetype, LandingArchetype)
        assert archetype.role == "planner_manager"
        assert "Planner" in archetype.title
        assert len(archetype.cards) == len(actor.responsibilities) + 1  # 4 cards + recent events
        # Check each responsibility maps to a SummaryCard with a count expression
        for card in archetype.cards:
            assert isinstance(card, SummaryCard)
            assert card.count_expression  # each card must have an ORM expression

    def test_actor_without_reports_produces_minimal_landing(self):
        """An actor with no reports yields a landing with only responsibility cards."""
        actor = Actor(
            id="field_worker",
            name="Field Worker",
            responsibilities=["Assigned tasks today"],
        )

        archetype = landing_from_actor(actor, [])

        assert archetype.role == "field_worker"
        assert len(archetype.cards) == 1
        assert archetype.cards[0].label == "Assigned tasks today"

    def test_responsibility_parses_to_orm_count_expression(self):
        """A responsibility like 'Open tasks this week' becomes an ORM
        count expression like ``TaskPlan.objects.filter(status='open', ...).count()``."""
        actor = Actor(
            id="planner_manager",
            name="Planner",
            responsibilities=["Open tasks this week"],
        )

        archetype = landing_from_actor(actor, [])

        expr = archetype.cards[0].count_expression
        assert ".objects.filter(" in expr or ".objects." in expr
        assert ".count()" in expr

    def test_report_becomes_summary_card(self):
        """An MWBS Report maps to a SummaryCard that lists recent items."""
        actor = Actor(id="planner_manager", name="Planner")
        reports = [
            Report(
                id="recent-events",
                title="Recent Events",
                format="list",
                displays=["event_date", "crop"],
            ),
        ]

        archetype = landing_from_actor(actor, reports)

        event_card = archetype.cards[-1]  # last card = reports section
        assert "Event" in event_card.label
        assert event_card.count_expression

    def test_generated_archetype_renders_valid_view_code(self):
        """The LandingArchetype produced by the adapter must be
        renderable by the existing view generator."""
        from workbook.codegen.view_generator import render_landing_view_py

        actor = Actor(
            id="field_worker",
            name="Field Worker",
            responsibilities=["Assigned tasks"],
        )
        archetype = landing_from_actor(actor, [])
        view_source = render_landing_view_py(archetype)

        # Must parse as valid Python AST
        ast.parse(view_source)
        # Must contain the role in the class name
        assert "FieldWorker" in view_source
        assert "summary_cards" in view_source

    def test_idempotent_multiple_calls(self):
        """Calling landing_from_actor twice with the same inputs yields
        identical LandingArchetype instances (same card count, same labels)."""
        actor = Actor(
            id="nursery_worker",
            name="Nursery Worker",
            responsibilities=["Seeding schedule", "Tray inventory"],
        )

        first = landing_from_actor(actor, [])
        second = landing_from_actor(actor, [])

        assert len(first.cards) == len(second.cards)
        for c1, c2 in zip(first.cards, second.cards, strict=True):
            assert c1.label == c2.label


class TestListFromWorkflowStep:
    """list_from_workflow_step: WorkflowStep → list view archetype config."""

    def test_list_step_produces_list_view_config(self):
        """A WorkflowStep tagged as a list view generates a list archetype
        with model, columns, and filter configuration."""
        step = WorkflowStep(
            id="view-crops",
            title="View Crops",
            description="Browse crop catalog by family and type",
            actor_action="Filter and browse crops",
            system_provides=["Crop list with filters"],
        )

        config = list_from_workflow_step(step, model_name="Crop")

        assert config["model"] == "Crop"
        assert config["title"] == "View Crops"
        assert "columns" in config
        assert "filters" in config

    def test_list_step_with_context_provides_setting(self):
        """system_provides hints like 'filter by family' appear in the
        generated filter configuration."""
        step = WorkflowStep(
            id="view-field-blocks",
            title="View Field Blocks",
            actor_action="Browse field blocks",
            system_provides=["Filter by status"],
        )

        config = list_from_workflow_step(step, model_name="FieldBlock")

        assert "status" in config.get("filters", [])

    def test_list_step_produces_renderable_view_code(self):
        """The list config can be rendered into valid Python view code."""
        from workbook.codegen.list_generator import (
            ListArchetype,
            render_list_view_py,
        )

        step = WorkflowStep(
            id="view-crops",
            title="View Crops",
            description="Browse crop catalog",
            system_provides=["Filter by family", "Filter by type"],
        )
        config = list_from_workflow_step(step, model_name="Crop")
        archetype = ListArchetype(**config)
        view_source = render_list_view_py(archetype)

        ast.parse(view_source)
        assert "CropListView" in view_source
        assert "paginate_by" in view_source
        assert "get_queryset" in view_source
        # Heuristic extracts "family" and "type" from system_provides
        assert "family" in view_source
        assert "type" in view_source

    def test_list_step_has_pagination(self):
        """The list archetype config includes a paginate_by field."""
        step = WorkflowStep(
            id="view-crops",
            title="View Crops",
            description="Browse crop catalog",
            system_provides=["Pagination"],
        )

        config = list_from_workflow_step(step, model_name="Crop")

        assert "paginate_by" in config
        assert isinstance(config["paginate_by"], int)
        assert config["paginate_by"] > 0

    def test_list_step_includes_ordering(self):
        """The list archetype config includes an ordering field."""
        step = WorkflowStep(
            id="view-crops",
            title="View Crops",
            description="Browse crop catalog",
            system_provides=["Ordered by name"],
        )

        config = list_from_workflow_step(step, model_name="Crop")

        assert "ordering" in config
        assert isinstance(config["ordering"], list)
        assert "name" in config["ordering"]
