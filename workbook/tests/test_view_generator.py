"""Unit tests for the weekly checklist view generator.

Covers:
- ``ChecklistArchetype`` defaults and field initialization
- ``render_checklist_view_py`` produces a syntactically valid Python module
- ``render_checklist_template_html`` produces a Django template
  with the expected structure (table, week nav, status badges, HTMX toggle)
- ``render_checklist_url_pattern`` produces a Django path() line
- ``render_toggle_handler_py`` produces an HTMX handler
- ``render_views_auto_py`` + ``render_urls_auto_py`` combine multiple archetypes
- ``build_archetype_from_contract`` auto-derives columns, select_related,
  and ordering
- The ``generate_views`` management command runs end-to-end with both
  explicit targets and ``auto`` mode
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command

from workbook.codegen.view_generator import (
    AlertCard,
    ChecklistArchetype,
    ChecklistColumn,
    DashboardArchetype,
    DetailColumn,
    DetailSection,
    LandingArchetype,
    SummaryCard,
    build_archetype_from_contract,
    render_checklist_template_html,
    render_checklist_url_pattern,
    render_checklist_view_py,
    render_dashboard_template_html,
    render_dashboard_url_pattern,
    render_dashboard_urls_auto_py,
    render_dashboard_view_py,
    render_dashboard_views_auto_py,
    render_landing_template_html,
    render_landing_url_pattern,
    render_landing_urls_auto_py,
    render_landing_view_py,
    render_landing_views_auto_py,
    render_toggle_handler_py,
    render_urls_auto_py,
    render_views_auto_py,
)


# -- fixtures ---------------------------------------------------------------


@pytest.fixture
def archetype() -> ChecklistArchetype:
    """A representative archetype for a TaskPlan checklist."""
    return ChecklistArchetype(
        model="TaskPlan",
        app_label="core",
        year_field="planned_year",
        week_field="planned_week",
        columns=[
            ChecklistColumn(field="category", label="Category", format="choice_display"),
            ChecklistColumn(field="field_block", label="Block", format="fk_display"),
            ChecklistColumn(field="crop", label="Crop", format="fk_display"),
        ],
        select_related=["field_block", "crop"],
        ordering=["status", "category"],
        status_field="status",
        status_open_value="open",
        status_done_value="done",
        status_values=["open", "done", "skipped"],
        toggle_field="status",
        toggle_url_name="farm_ui_toggle_task_done",
        toggle_button_label="Mark Done",
        toggle_field_label="Status",
        title="Task Checklist",
        context_object_name="tasks",
        url_path="field/tasks/",
        url_name="farm_ui_task_checklist",
        template_path="farm_ui/checklist_tasks.html",
    )


@pytest.fixture
def contract_table() -> dict[str, Any]:
    """A minimal contract table with FK + year/week fields."""
    return {
        "model_name": "PlantingPlan",
        "model_meta": {"app_label": "core", "verbose_name": "Planting Plan"},
        "columns": [
            {"name": "id", "class": "models.BigAutoField"},
            {"name": "season", "class": "models.ForeignKey"},
            {"name": "crop", "class": "models.ForeignKey"},
            {"name": "field_block", "class": "models.ForeignKey"},
            {"name": "bed_start", "class": "models.PositiveSmallIntegerField"},
            {"name": "bed_end", "class": "models.PositiveSmallIntegerField"},
            {"name": "planned_week", "class": "models.PositiveSmallIntegerField"},
            {"name": "planned_year", "class": "models.PositiveSmallIntegerField"},
        ],
    }


# -- archetype defaults -----------------------------------------------------


class TestChecklistArchetype:
    """Defaults and field initialization on the archetype dataclass."""

    def test_toggle_field_defaults_to_status_field(self) -> None:
        """When toggle_field is unset but status_field is set, toggle is the status field."""
        arch = ChecklistArchetype(
            model="TaskPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
            status_field="status",
        )
        assert arch.toggle_field == "status"

    def test_toggle_url_name_default(self) -> None:
        """The toggle URL name defaults to ``<url_name>_toggle``."""
        arch = ChecklistArchetype(
            model="TaskPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
            url_name="farm_ui_task_checklist",
        )
        assert arch.toggle_url_name == "farm_ui_task_checklist_toggle"

    def test_toggle_url_path_default(self) -> None:
        """The toggle URL path defaults to ``<url_path><int:pk>/toggle/``."""
        arch = ChecklistArchetype(
            model="TaskPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
            url_path="field/tasks/",
        )
        assert arch.toggle_url_path == "field/tasks/<int:pk>/toggle/"

    def test_status_badges_default_when_status_field_set(self) -> None:
        """A status field without explicit badges gets ``done`` and ``skipped`` defaults."""
        arch = ChecklistArchetype(
            model="TaskPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
            status_field="status",
            status_done_value="done",
        )
        assert arch.status_badges["done"] == "badge-success"
        assert arch.status_badges["skipped"] == "badge-pending"

    def test_status_badges_preserves_explicit(self) -> None:
        """Explicit status_badges are not overridden by the default."""
        arch = ChecklistArchetype(
            model="TaskPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
            status_field="status",
            status_badges={"open": "custom-open"},
        )
        assert arch.status_badges == {"open": "custom-open"}


# -- view source rendering --------------------------------------------------


class TestRenderChecklistViewPy:
    """The view Python source renders and parses cleanly."""

    def test_renders_valid_python(self, archetype: ChecklistArchetype) -> None:
        """The output must be valid Python (parses with ast.parse)."""
        source = render_checklist_view_py(archetype)
        ast.parse(source)

    def test_includes_model_class_name(self, archetype: ChecklistArchetype) -> None:
        """The ListView class is named ``<Model>ChecklistView``."""
        source = render_checklist_view_py(archetype)
        assert "class TaskPlanChecklistView" in source

    def test_sets_model_attribute(self, archetype: ChecklistArchetype) -> None:
        """The ListView model attribute is the PascalCase model name."""
        source = render_checklist_view_py(archetype)
        assert "model = TaskPlan" in source

    def test_sets_template_name(self, archetype: ChecklistArchetype) -> None:
        """The template_name matches the archetype's template_path."""
        source = render_checklist_view_py(archetype)
        assert 'template_name = "farm_ui/checklist_tasks.html"' in source

    def test_queryset_filters_by_year_and_week(self, archetype: ChecklistArchetype) -> None:
        """``get_queryset`` filters by the configured year_field and week_field."""
        source = render_checklist_view_py(archetype)
        assert "planned_year=year" in source
        assert "planned_week=week" in source

    def test_queryset_applies_select_related(self, archetype: ChecklistArchetype) -> None:
        """``get_queryset`` calls ``select_related`` with the configured FKs."""
        source = render_checklist_view_py(archetype)
        assert ".select_related(" in source
        assert "'field_block'" in source
        assert "'crop'" in source

    def test_queryset_applies_ordering(self, archetype: ChecklistArchetype) -> None:
        """``get_queryset`` calls ``order_by`` with the configured fields."""
        source = render_checklist_view_py(archetype)
        assert ".order_by(" in source
        assert "'status'" in source
        assert "'category'" in source

    def test_context_data_calculates_prev_next(self, archetype: ChecklistArchetype) -> None:
        """``get_context_data`` includes prev_year, prev_week, next_year, next_week."""
        source = render_checklist_view_py(archetype)
        for token in (
            "current_year", "current_week",
            "prev_year", "prev_week",
            "next_year", "next_week",
        ):
            assert token in source

    def test_context_data_handles_year_boundary(self, archetype: ChecklistArchetype) -> None:
        """The week-52 boundary wraps to week 1 of the next year."""
        source = render_checklist_view_py(archetype)
        assert "week >= 52" in source
        assert 'context["next_week"] = 1' in source
        assert "year + 1" in source

    def test_context_data_handles_week_1_boundary(self, archetype: ChecklistArchetype) -> None:
        """The week-1 boundary wraps to week 52 of the previous year."""
        source = render_checklist_view_py(archetype)
        assert "week <= 1" in source
        assert 'context["prev_week"] = 52' in source
        assert "year - 1" in source

    def test_view_source_in_login_required_mixin(self) -> None:
        """The generated view class inherits from LoginRequiredMixin."""
        arch = ChecklistArchetype(
            model="PlantingPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
        )
        source = render_checklist_view_py(arch)
        assert "LoginRequiredMixin" in source
        assert "ListView" in source


# -- toggle handler rendering ----------------------------------------------


class TestRenderToggleHandlerPy:
    """The HTMX toggle handler source renders correctly."""

    def test_renders_valid_python(self, archetype: ChecklistArchetype) -> None:
        """The toggle handler is parseable Python."""
        source = render_toggle_handler_py(archetype)
        ast.parse(source)

    def test_handler_decorated_with_post_and_login_required(self, archetype: ChecklistArchetype) -> None:
        """The handler has ``@require_POST`` and ``@login_required`` decorators."""
        source = render_toggle_handler_py(archetype)
        assert "@require_POST" in source
        assert "@login_required" in source

    def test_handler_toggles_status(self, archetype: ChecklistArchetype) -> None:
        """The handler maps between ``open`` and ``done`` values."""
        source = render_toggle_handler_py(archetype)
        assert 'obj.status = "done" if obj.status == "open" else "open"' in source

    def test_handler_saves_with_update_fields(self, archetype: ChecklistArchetype) -> None:
        """The handler saves only the toggled field."""
        source = render_toggle_handler_py(archetype)
        assert "obj.save(update_fields=['status'])" in source

    def test_handler_returns_htmx_response(self, archetype: ChecklistArchetype) -> None:
        """The handler returns an HttpResponse containing a ``<td>`` snippet."""
        source = render_toggle_handler_py(archetype)
        assert "HttpResponse" in source
        assert "<td" in source

    def test_no_toggle_returns_empty(self) -> None:
        """An archetype without a toggle field produces empty source."""
        arch = ChecklistArchetype(
            model="PlantingPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
        )
        assert render_toggle_handler_py(arch) == ""


# -- URL pattern rendering --------------------------------------------------


class TestRenderChecklistUrlPattern:
    """The URL pattern lines render correctly."""

    def test_renders_listview_path(self, archetype: ChecklistArchetype) -> None:
        """The ListView path() line is present with the correct name and path."""
        lines = render_checklist_url_pattern(archetype)
        joined = "\n".join(lines)
        assert 'path("field/tasks/"' in joined
        assert "name=\"farm_ui_task_checklist\"" in joined

    def test_renders_toggle_path(self, archetype: ChecklistArchetype) -> None:
        """The toggle handler path() line is present."""
        lines = render_checklist_url_pattern(archetype)
        joined = "\n".join(lines)
        assert "toggle" in joined
        assert "<int:pk>" in joined
        assert "farm_ui_toggle_task_done" in joined

    def test_returns_empty_when_no_url(self) -> None:
        """An archetype without a url_path returns no lines."""
        arch = ChecklistArchetype(
            model="PlantingPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
        )
        assert render_checklist_url_pattern(arch) == []


# -- template rendering -----------------------------------------------------


class TestRenderChecklistTemplateHtml:
    """The template HTML renders with the expected structure."""

    def test_includes_title_and_week(self, archetype: ChecklistArchetype) -> None:
        """The template heading shows the title + current week + year."""
        html = render_checklist_template_html(archetype)
        assert "Task Checklist" in html
        assert "{{ current_week }}" in html
        assert "{{ current_year }}" in html

    def test_includes_week_navigation(self, archetype: ChecklistArchetype) -> None:
        """The week-nav block has prev/this-week/next links."""
        html = render_checklist_template_html(archetype)
        assert "week-nav" in html
        assert "Prev Week" in html
        assert "Next Week" in html
        assert "This Week" in html

    def test_includes_data_table(self, archetype: ChecklistArchetype) -> None:
        """A ``<table class="data-table">`` block is rendered."""
        html = render_checklist_template_html(archetype)
        assert '<table class="data-table">' in html

    def test_includes_table_headers(self, archetype: ChecklistArchetype) -> None:
        """All column labels appear as ``<th>`` headers."""
        html = render_checklist_template_html(archetype)
        assert "<th>Category</th>" in html
        assert "<th>Block</th>" in html
        assert "<th>Crop</th>" in html
        assert "<th>Status</th>" in html
        assert "<th>Action</th>" in html

    def test_includes_status_badges(self, archetype: ChecklistArchetype) -> None:
        """The status cell renders a badge for each status value."""
        html = render_checklist_template_html(archetype)
        assert "badge badge-success" in html
        assert ">Done<" in html
        assert ">Open<" in html
        assert ">Skipped<" in html

    def test_includes_htmx_toggle_button(self, archetype: ChecklistArchetype) -> None:
        """The action cell contains an HTMX ``hx-post`` button."""
        html = render_checklist_template_html(archetype)
        assert "hx-post" in html
        assert "farm_ui_toggle_task_done" in html
        assert "Mark Done" in html
        assert "hx-target" in html

    def test_includes_empty_row(self, archetype: ChecklistArchetype) -> None:
        """The empty state shows a colspan message."""
        html = render_checklist_template_html(archetype)
        assert "No records for this week" in html


# -- combined modules -------------------------------------------------------


class TestRenderViewsAutoPy:
    """The combined ``views_auto.py`` module renders cleanly."""

    def test_combines_multiple_archetypes(self) -> None:
        """Two archetypes produce two ListView classes in one module."""
        arch1 = ChecklistArchetype(
            model="TaskPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
            status_field="status",
            toggle_field="status",
            url_path="tasks/",
            url_name="tasks",
        )
        arch2 = ChecklistArchetype(
            model="PlantingPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
            url_path="plantings/",
            url_name="plantings",
        )
        source = render_views_auto_py([arch1, arch2])
        ast.parse(source)
        assert "class TaskPlanChecklistView" in source
        assert "class PlantingPlanChecklistView" in source

    def test_includes_shared_helper(self) -> None:
        """The combined module includes ``_resolve_week_year`` once."""
        arch = ChecklistArchetype(
            model="TaskPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
        )
        source = render_views_auto_py([arch])
        assert "_resolve_week_year" in source

    def test_imports_correct_models(self) -> None:
        """The combined module imports every model from the archetypes."""
        arch1 = ChecklistArchetype(
            model="TaskPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
        )
        arch2 = ChecklistArchetype(
            model="PlantingPlan",
            app_label="core",
            year_field="planned_year",
            week_field="planned_week",
        )
        source = render_views_auto_py([arch1, arch2])
        assert "from core.models import" in source
        assert "TaskPlan" in source
        assert "PlantingPlan" in source


class TestRenderUrlsAutoPy:
    """The combined ``urls_auto.py`` module renders cleanly."""

    def test_renders_urlpatterns_list(self, archetype: ChecklistArchetype) -> None:
        """The output has a ``urlpatterns`` list with the archetype's path."""
        source = render_urls_auto_py([archetype])
        ast.parse(source)
        assert "urlpatterns = [" in source
        assert "field/tasks/" in source


# -- factory from contract --------------------------------------------------


class TestBuildArchetypeFromContract:
    """``build_archetype_from_contract`` derives columns, select_related, ordering."""

    def test_auto_columns_excludes_year_week(self, contract_table: dict[str, Any]) -> None:
        """Year/week fields are not promoted into the table columns."""
        arch = build_archetype_from_contract(
            model="PlantingPlan",
            app_label="core",
            contract_table=contract_table,
        )
        column_fields = {c.field for c in arch.columns}
        assert "planned_year" not in column_fields
        assert "planned_week" not in column_fields

    def test_auto_columns_includes_fk_with_fk_display(self, contract_table: dict[str, Any]) -> None:
        """FK fields get ``format="fk_display"`` for related-object rendering."""
        arch = build_archetype_from_contract(
            model="PlantingPlan",
            app_label="core",
            contract_table=contract_table,
        )
        fk_columns = [c for c in arch.columns if c.format == "fk_display"]
        assert any(c.field == "crop" for c in fk_columns)
        assert any(c.field == "field_block" for c in fk_columns)

    def test_auto_select_related_lists_all_fks(self, contract_table: dict[str, Any]) -> None:
        """All FK fields end up in ``select_related``."""
        arch = build_archetype_from_contract(
            model="PlantingPlan",
            app_label="core",
            contract_table=contract_table,
        )
        assert "season" in arch.select_related
        assert "crop" in arch.select_related
        assert "field_block" in arch.select_related

    def test_auto_ordering_prefers_first_fk(self, contract_table: dict[str, Any]) -> None:
        """Ordering prefers the first FK field."""
        arch = build_archetype_from_contract(
            model="PlantingPlan",
            app_label="core",
            contract_table=contract_table,
        )
        assert arch.ordering and arch.ordering[0] in arch.select_related

    def test_explicit_columns_override_auto(self, contract_table: dict[str, Any]) -> None:
        """Explicit columns replace auto-derived ones."""
        explicit = [ChecklistColumn(field="notes", label="Notes")]
        arch = build_archetype_from_contract(
            model="PlantingPlan",
            app_label="core",
            contract_table=contract_table,
            columns=explicit,
        )
        assert arch.columns == explicit


# -- management command end-to-end -----------------------------------------


class TestGenerateViewsCommand:
    """The ``generate_views`` management command runs end-to-end."""

    def _write_contract(self, tmp_path: Path) -> Path:
        """Write a minimal contract YAML for the management command."""
        import yaml  # type: ignore[import-untyped]

        contract = {
            "version": "1.3",
            "tables": [
                {
                    "model_name": "PlantingPlan",
                    "model_meta": {
                        "app_label": "core",
                        "verbose_name": "Planting Plan",
                    },
                    "columns": [
                        {"name": "id", "class": "models.BigAutoField"},
                        {"name": "crop", "class": "models.ForeignKey"},
                        {"name": "field_block", "class": "models.ForeignKey"},
                        {
                            "name": "planned_week",
                            "class": "models.PositiveSmallIntegerField",
                        },
                        {
                            "name": "planned_year",
                            "class": "models.PositiveSmallIntegerField",
                        },
                    ],
                },
                {
                    "model_name": "TaskPlan",
                    "model_meta": {
                        "app_label": "core",
                        "verbose_name": "Task Plan",
                    },
                    "columns": [
                        {"name": "id", "class": "models.BigAutoField"},
                        {"name": "status", "class": "models.CharField"},
                        {
                            "name": "planned_week",
                            "class": "models.PositiveSmallIntegerField",
                        },
                        {
                            "name": "planned_year",
                            "class": "models.PositiveSmallIntegerField",
                        },
                    ],
                },
            ],
        }
        path = tmp_path / "contract.yaml"
        path.write_text(yaml.safe_dump(contract), encoding="utf-8")
        return path

    def test_explicit_target_generates_files(self, tmp_path: Path) -> None:
        """``--archetype-checklist core.PlantingPlan`` writes views, urls, and template."""
        contract_path = self._write_contract(tmp_path)
        out_dir = tmp_path / "out"
        call_command(
            "generate_views",
            contract=str(contract_path),
            out_dir=str(out_dir),
            archetype_checklist="core.PlantingPlan",
            force=True,
        )
        assert (out_dir / "views_auto.py").exists()
        assert (out_dir / "urls_auto.py").exists()

    def test_auto_mode_finds_eligible_tables(self, tmp_path: Path) -> None:
        """``--archetype-checklist auto`` discovers tables with year/week fields."""
        contract_path = self._write_contract(tmp_path)
        out_dir = tmp_path / "out_auto"
        call_command(
            "generate_views",
            contract=str(contract_path),
            out_dir=str(out_dir),
            archetype_checklist="auto",
            force=True,
        )
        views_source = (out_dir / "views_auto.py").read_text(encoding="utf-8")
        assert "class PlantingPlanChecklistView" in views_source
        assert "class TaskPlanChecklistView" in views_source


# -- landing archetype tests ------------------------------------------------


class TestLandingArchetype:
    """LandingArchetype dataclass defaults."""

    def test_default_url_name_from_role(self) -> None:
        """When url_name is unset, it derives from role."""
        arch = LandingArchetype(role="field_worker", title="Test")
        assert arch.url_name == "landing_field_worker"

    def test_default_url_path_from_role(self) -> None:
        """When url_path is unset, it derives from role with hyphens."""
        arch = LandingArchetype(role="field_worker", title="Test")
        assert arch.url_path == "field-worker/"

    def test_default_template_path(self) -> None:
        """When template_path is unset, it derives from url_name."""
        arch = LandingArchetype(role="field_worker", title="Test")
        assert arch.template_path == "generated/landing_field_worker.html"

    def test_summary_card_has_fields(self) -> None:
        """A SummaryCard stores label, expression, link, and css_class."""
        card = SummaryCard(
            label="Open Tasks",
            count_expression="TaskPlan.objects.filter(status='open').count()",
            link_url_name="farm_ui_tasks",
            css_class="card-warning",
        )
        assert card.label == "Open Tasks"
        assert "filter(status='open')" in card.count_expression
        assert card.link_url_name == "farm_ui_tasks"
        assert card.css_class == "card-warning"


class TestRenderLandingViewPy:
    """Landing view Python source renders and parses cleanly."""

    def test_renders_valid_python(self) -> None:
        """The output must be valid Python (parses with ast.parse)."""
        arch = LandingArchetype(
            role="field_worker",
            title="Field Ops",
            cards=[
                SummaryCard(
                    label="Open Tasks",
                    count_expression="42",
                ),
            ],
        )
        source = render_landing_view_py(arch)
        ast.parse(source)

    def test_includes_class_name(self) -> None:
        """The class is named ``<PascalRole>LandingView``."""
        arch = LandingArchetype(role="field_worker", title="Field Ops")
        source = render_landing_view_py(arch)
        assert "class FieldWorkerLandingView" in source

    def test_class_inherits_from_template_view(self) -> None:
        """The class inherits from LoginRequiredMixin and TemplateView."""
        arch = LandingArchetype(role="field_worker", title="Field Ops")
        source = render_landing_view_py(arch)
        assert "LoginRequiredMixin" in source
        assert "TemplateView" in source

    def test_sets_template_name(self) -> None:
        """The template_name matches the archetype's template_path."""
        arch = LandingArchetype(
            role="field_worker", title="Field Ops",
        )
        source = render_landing_view_py(arch)
        assert 'template_name = "generated/landing_field_worker.html"' in source

    def test_get_context_data_presents_summary_cards(self) -> None:
        """The context has a ``summary_cards`` list of dicts."""
        arch = LandingArchetype(
            role="planner",
            title="Planner Dashboard",
            cards=[
                SummaryCard(
                    label="Open Tasks",
                    count_expression="TaskPlan.objects.filter(status='open').count()",
                    link_url_name="tasks",
                ),
                SummaryCard(
                    label="Low Inventory",
                    count_expression="len(InventoryLedger.objects.filter(...))",
                    css_class="card-warning",
                ),
            ],
        )
        source = render_landing_view_py(arch)
        ast.parse(source)
        assert "summary_cards" in source
        assert "Open Tasks" in source
        assert "Low Inventory" in source
        assert 'reverse("tasks")' in source
        assert "card-warning" in source

    def test_empty_cards_produces_empty_list(self) -> None:
        """A landing with no cards still produces valid Python."""
        arch = LandingArchetype(role="field_worker", title="Empty")
        source = render_landing_view_py(arch)
        ast.parse(source)
        assert "summary_cards" in source

    def test_card_value_is_computed_from_expression(self) -> None:
        """The count_expression is rendered as a Python variable assignment."""
        arch = LandingArchetype(
            role="field_worker",
            title="Field Ops",
            cards=[
                SummaryCard(
                    label="Count",
                    count_expression="sum([1, 2, 3])",
                ),
            ],
        )
        source = render_landing_view_py(arch)
        assert "sum([1, 2, 3])" in source


class TestRenderLandingTemplateHtml:
    """Landing template HTML renders with the expected structure."""

    def test_includes_title(self) -> None:
        """The template shows the title in an <h1>."""
        arch = LandingArchetype(role="field_worker", title="Field Ops")
        html = render_landing_template_html(arch)
        assert "Field Ops" in html
        assert "<h1>" in html

    def test_includes_summary_cards_grid(self) -> None:
        """The template has a ``summary-cards`` container."""
        arch = LandingArchetype(role="field_worker", title="Field Ops")
        html = render_landing_template_html(arch)
        assert 'class="summary-cards"' in html

    def test_renders_card_labels_in_template(self) -> None:
        """Card labels appear in the template (via ``{{ card.label }}``)."""
        arch = LandingArchetype(role="field_worker", title="Field Ops")
        html = render_landing_template_html(arch)
        assert "card.label" in html
        assert "card.value" in html

    def test_renders_card_url_when_present(self) -> None:
        """When a card has a url_name, the template wraps in <a> tag."""
        arch = LandingArchetype(role="field_worker", title="Field Ops")
        html = render_landing_template_html(arch)
        assert "card.url" in html

    def test_empty_state_message(self) -> None:
        """An empty-state message appears when no cards are present."""
        arch = LandingArchetype(role="field_worker", title="Field Ops")
        html = render_landing_template_html(arch)
        assert "No data available" in html or "{% empty %}" in html


class TestRenderLandingUrlPattern:
    """Landing URL pattern lines render correctly."""

    def test_renders_path_with_name(self) -> None:
        """The path() line has the correct URL and name."""
        arch = LandingArchetype(
            role="field_worker",
            title="Field Ops",
            url_path="field-worker/",
            url_name="landing_field_worker",
        )
        lines = render_landing_url_pattern(arch)
        joined = "\n".join(lines)
        assert 'path("field-worker/"' in joined
        assert 'name="landing_field_worker"' in joined

    def test_returns_empty_when_no_url(self) -> None:
        """An archetype without url_path returns no lines."""
        # Unset role so post_init doesn't auto-assign url_path/url_name.
        arch = LandingArchetype(
            role="", title="Field Ops",
            url_path="", url_name="",
        )
        assert render_landing_url_pattern(arch) == []


class TestRenderLandingViewsAutoPy:
    """Combined landing views_auto.py module."""

    def test_combines_multiple_archetypes(self) -> None:
        """Two archetypes produce two landing view classes."""
        arch1 = LandingArchetype(role="field_worker", title="Field")
        arch2 = LandingArchetype(role="planner", title="Planner")
        source = render_landing_views_auto_py([arch1, arch2])
        ast.parse(source)
        assert "class FieldWorkerLandingView" in source
        assert "class PlannerLandingView" in source

    def test_includes_imports(self) -> None:
        """The module imports LoginRequiredMixin and TemplateView."""
        arch = LandingArchetype(role="field_worker", title="Field")
        source = render_landing_views_auto_py([arch])
        assert "LoginRequiredMixin" in source
        assert "TemplateView" in source


class TestRenderLandingUrlsAutoPy:
    """Combined landing urls_auto.py module."""

    def test_renders_urlpatterns_list(self) -> None:
        """The output has a ``urlpatterns`` list with the archetype's path."""
        arch = LandingArchetype(
            role="field_worker", title="Field",
            url_path="field-worker/", url_name="landing_field_worker",
        )
        source = render_landing_urls_auto_py([arch])
        ast.parse(source)
        assert "urlpatterns = [" in source
        assert "field-worker/" in source


class TestGenerateViewsCommandLanding:
    """The ``generate_views`` management command handles ``--archetype-landing``."""

    def test_landing_from_config(self, tmp_path: Path) -> None:
        """``--archetype-landing <config.yaml>`` writes views, urls, and template."""
        import yaml  # type: ignore[import-untyped]

        # Write a minimal landing config.
        config = {
            "landings": [
                {
                    "role": "field_worker",
                    "title": "Field Ops",
                    "cards": [
                        {
                            "label": "Open Tasks",
                            "count_expression": "42",
                            "link_url_name": "tasks",
                        },
                    ],
                },
            ],
        }
        config_path = tmp_path / "landing-config.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

        # Provide a minimal contract (needed by the command even though not used for landing).
        contract = {
            "version": "1.3",
            "tables": [],
        }
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")

        out_dir = tmp_path / "out_landing"
        call_command(
            "generate_views",
            contract=str(contract_path),
            out_dir=str(out_dir),
            archetype_landing=str(config_path),
            force=True,
        )
        assert (out_dir / "views_auto.py").exists()
        assert (out_dir / "urls_auto.py").exists()
        views_source = (out_dir / "views_auto.py").read_text(encoding="utf-8")
        assert "class FieldWorkerLandingView" in views_source
        # Title appears in template, not view source
        template_source = (out_dir / "generated" / "landing_field_worker.html").read_text(encoding="utf-8")
        assert "Field Ops" in template_source


# -- dashboard archetype tests ----------------------------------------------


class TestAlertCard:
    """AlertCard dataclass defaults and initialization."""

    def test_minimal(self) -> None:
        card = AlertCard(label="Zero Stock", count_expression="42")
        assert card.label == "Zero Stock"
        assert card.count_expression == "42"
        assert card.severity == "info"
        assert card.link_url_name is None

    def test_full(self) -> None:
        card = AlertCard(
            label="Low Stock",
            count_expression="Item.objects.filter(qty__lt=5).count()",
            severity="warning",
            link_url_name="inventory",
        )
        assert card.severity == "warning"
        assert card.link_url_name == "inventory"


class TestDetailColumn:
    """DetailColumn dataclass and template cell rendering."""

    def test_default_format(self) -> None:
        col = DetailColumn(field="crop", label="Crop")
        assert col.format == "value"
        assert "default" in col.as_template_cell()

    def test_fk_display_format(self) -> None:
        col = DetailColumn(field="crop", label="Crop", format="fk_display")
        cell = col.as_template_cell()
        assert "row.crop" in cell
        assert "default" not in cell

    def test_choice_display_format(self) -> None:
        col = DetailColumn(field="status", label="Status", format="choice_display")
        cell = col.as_template_cell()
        assert "get_status_display" in cell


class TestDetailSection:
    """DetailSection dataclass defaults."""

    def test_minimal(self) -> None:
        sec = DetailSection(title="Items", queryset_expression="Items.objects.all()")
        assert sec.title == "Items"
        assert sec.columns == []
        assert sec.limit is None
        assert sec.empty_message == "No records found."

    def test_with_columns(self) -> None:
        cols = [DetailColumn(field="name", label="Name")]
        sec = DetailSection(
            title="Items",
            queryset_expression="Items.objects.all()",
            columns=cols,
            limit=50,
            empty_message="No items.",
        )
        assert len(sec.columns) == 1
        assert sec.limit == 50
        assert sec.empty_message == "No items."


class TestDashboardArchetype:
    """DashboardArchetype dataclass and defaults."""

    def test_minimal(self) -> None:
        arch = DashboardArchetype(name="inventory", title="Inventory")
        assert arch.name == "inventory"
        assert arch.alerts == []
        assert arch.sections == []
        assert arch.url_path == "inventory/"
        assert arch.url_name == "dashboard_inventory"
        assert arch.template_path == "generated/dashboard_inventory.html"

    def test_custom_url(self) -> None:
        arch = DashboardArchetype(
            name="inventory",
            title="Inventory Dashboard",
            url_path="stock/",
            url_name="dashboard_stock",
        )
        assert arch.url_path == "stock/"
        assert arch.url_name == "dashboard_stock"


class TestRenderDashboardViewPy:
    """render_dashboard_view_py produces valid Python with alert cards and sections."""

    def _compile_view(self, arch: DashboardArchetype) -> None:
        source = render_dashboard_view_py(arch)
        # Wrap in a minimal import preamble to make it compilable.
        preamble = (
            "from django.contrib.auth.mixins import LoginRequiredMixin\n"
            "from django.views.generic import TemplateView\n"
        )
        compile(preamble + source, "<test>", "exec")

    def test_alerts_only(self) -> None:
        arch = DashboardArchetype(
            name="inventory",
            title="Inventory",
            alerts=[
                AlertCard(label="Zero", count_expression="Item.objects.filter(qty=0).count()"),
            ],
        )
        self._compile_view(arch)
        source = render_dashboard_view_py(arch)
        assert "class InventoryDashboardView" in source
        assert '_alert_0 = Item.objects.filter(qty=0).count()' in source
        assert 'context["alerts"]' in source

    def test_alerts_with_urls(self) -> None:
        arch = DashboardArchetype(
            name="inventory",
            title="Inventory",
            alerts=[
                AlertCard(label="Zero", count_expression="42", link_url_name="items"),
            ],
        )
        self._compile_view(arch)
        source = render_dashboard_view_py(arch)
        assert "from django.urls import reverse" in source
        assert 'reverse("items")' in source

    def test_alerts_with_sections(self) -> None:
        arch = DashboardArchetype(
            name="season",
            title="Season",
            alerts=[
                AlertCard(label="Planned", count_expression="Plan.objects.count()"),
            ],
            sections=[
                DetailSection(
                    title="Events",
                    queryset_expression="Event.objects.all()",
                    columns=[
                        DetailColumn(field="name", label="Name"),
                    ],
                ),
            ],
        )
        self._compile_view(arch)
        source = render_dashboard_view_py(arch)
        assert 'context["section_0_title"]' in source
        assert 'context["section_0_rows"]' in source
        assert 'context["section_0_empty_message"]' in source
        assert 'Event.objects.all()' in source

    def test_multiple_sections(self) -> None:
        arch = DashboardArchetype(
            name="overview",
            title="Overview",
            alerts=[
                AlertCard(label="A", count_expression="1"),
            ],
            sections=[
                DetailSection(title="S1", queryset_expression="A.objects.all()"),
                DetailSection(title="S2", queryset_expression="B.objects.all()"),
            ],
        )
        self._compile_view(arch)
        source = render_dashboard_view_py(arch)
        assert 'section_0_title' in source
        assert 'section_1_title' in source
        assert 'section_1_rows' in source

    def test_no_alerts(self) -> None:
        arch = DashboardArchetype(
            name="empty",
            title="Empty Dashboard",
            alerts=[],
        )
        self._compile_view(arch)
        source = render_dashboard_view_py(arch)
        assert 'context["alerts"] = []' in source


class TestRenderDashboardTemplateHtml:
    """render_dashboard_template_html produces a valid Django template."""

    def test_template_structure(self) -> None:
        arch = DashboardArchetype(
            name="inventory",
            title="Inventory Dashboard",
            alerts=[
                AlertCard(label="Zero", count_expression="0", severity="warning"),
            ],
        )
        html = render_dashboard_template_html(arch)
        assert "Inventory Dashboard" in html
        assert "{% extends" in html
        assert "{% block content" in html
        assert "{% endblock" in html
        assert "summary-cards" in html
        assert "card-{{ alert.severity }}" in html
        assert "card-number" in html
        assert "card-label" in html

    def test_section_table_rendered(self) -> None:
        arch = DashboardArchetype(
            name="inventory",
            title="Inventory",
            alerts=[],
            sections=[
                DetailSection(
                    title="Items",
                    queryset_expression="Item.objects.all()",
                    columns=[
                        DetailColumn(field="name", label="Name"),
                        DetailColumn(field="crop", label="Crop", format="fk_display"),
                    ],
                ),
            ],
        )
        html = render_dashboard_template_html(arch)
        assert 'section_0_title' in html
        assert 'section_0_rows' in html
        assert 'section_0_empty_message' in html
        assert '<th>Name</th>' in html
        assert '<th>Crop</th>' in html
        assert '{{ row.name|default:"—" }}' in html
        assert '{{ row.crop }}' in html
        assert 'data-table' in html

    def test_section_limit_shown(self) -> None:
        arch = DashboardArchetype(
            name="test",
            title="Test",
            alerts=[],
            sections=[
                DetailSection(
                    title="Items",
                    queryset_expression="Item.objects.all()",
                    limit=10,
                ),
            ],
        )
        html = render_dashboard_template_html(arch)
        # The limit appears in the view source ([:10]), not the template.
        assert 'section_0_rows' in html

    def test_back_link(self) -> None:
        arch = DashboardArchetype(
            name="test",
            title="Test",
            back_url_name="home",
            back_url_label="Back to Home",
        )
        html = render_dashboard_template_html(arch)
        assert 'Back to Home' in html
        assert 'reverse' not in html  # URL resolution happens in view, not template

    def test_empty_alerts(self) -> None:
        arch = DashboardArchetype(
            name="test",
            title="Test",
            alerts=[],
        )
        html = render_dashboard_template_html(arch)
        assert "No alerts configured." in html

    def test_multiple_sections(self) -> None:
        arch = DashboardArchetype(
            name="multi",
            title="Multi",
            alerts=[],
            sections=[
                DetailSection(title="S1", queryset_expression="A.objects.all()"),
                DetailSection(title="S2", queryset_expression="B.objects.all()"),
            ],
        )
        html = render_dashboard_template_html(arch)
        assert 'section_0_title' in html
        assert 'section_0_rows' in html
        assert 'section_1_title' in html
        assert 'section_1_rows' in html


class TestRenderDashboardUrlPattern:
    """render_dashboard_url_pattern produces Django path() lines."""

    def test_url_pattern(self) -> None:
        arch = DashboardArchetype(
            name="inventory",
            title="Inventory",
            url_path="inventory/",
            url_name="dashboard_inventory",
        )
        lines = render_dashboard_url_pattern(arch)
        assert len(lines) == 1
        assert 'path("inventory/"' in lines[0]
        assert 'name="dashboard_inventory"' in lines[0]
        assert 'InventoryDashboardView' in lines[0]

    def test_no_url_empty(self) -> None:
        arch = DashboardArchetype(name="inventory", title="Inventory")
        # No explicit url_path means defaults are set via __post_init__.
        lines = render_dashboard_url_pattern(arch)
        assert len(lines) == 1
        assert 'inventory/' in lines[0]


class TestRenderDashboardViewsAuto:
    """render_dashboard_views_auto_py produces a combined module."""

    def test_auto_imports(self) -> None:
        arch = DashboardArchetype(
            name="inventory",
            title="Inventory",
            alerts=[
                AlertCard(label="Zero", count_expression="InventoryLedger.objects.filter(qty=0).count()"),
                AlertCard(label="Low", count_expression="LowStock.objects.count()"),
            ],
        )
        source = render_dashboard_views_auto_py([arch])
        compile(source, "<test>", "exec")
        assert "from django.contrib.auth.mixins import LoginRequiredMixin" in source
        assert "from django.views.generic import TemplateView" in source
        assert "InventoryLedger" in source
        assert "LowStock" in source

    def test_multiple_archetypes(self) -> None:
        a1 = DashboardArchetype(
            name="inv", title="Inv",
            alerts=[AlertCard(label="Z", count_expression="X.objects.count()")],
        )
        a2 = DashboardArchetype(
            name="sea", title="Sea",
            alerts=[AlertCard(label="P", count_expression="Y.objects.count()")],
        )
        source = render_dashboard_views_auto_py([a1, a2])
        compile(source, "<test>", "exec")
        assert "class InvDashboardView" in source
        assert "class SeaDashboardView" in source


class TestRenderDashboardUrlsAuto:
    """render_dashboard_urls_auto_py produces a combined URL module."""

    def test_url_patterns(self) -> None:
        arch = DashboardArchetype(
            name="inventory",
            title="Inventory",
            url_path="inv/",
            url_name="dashboard_inv",
        )
        source = render_dashboard_urls_auto_py([arch])
        compile(source, "<test>", "exec")
        assert "path(\"inv/\"" in source
        assert "InventoryDashboardView" in source

    def test_multiple(self) -> None:
        a1 = DashboardArchetype(
            name="inv", title="Inv",
            alerts=[AlertCard(label="Z", count_expression="1")],
        )
        a2 = DashboardArchetype(
            name="season", title="Season",
            alerts=[AlertCard(label="P", count_expression="1")],
        )
        source = render_dashboard_urls_auto_py([a1, a2])
        compile(source, "<test>", "exec")
        assert "InvDashboardView" in source
        assert "SeasonDashboardView" in source


class TestGenerateViewsCommandDashboard:
    """The ``generate_views`` command handles ``--archetype-dashboard``."""

    def test_dashboard_from_config(self, tmp_path: Path) -> None:
        """``--archetype-dashboard <config.yaml>`` writes views, urls, and template."""
        import yaml  # type: ignore[import-untyped]

        config = {
            "dashboards": [
                {
                    "name": "inventory",
                    "title": "Inventory Dashboard",
                    "alerts": [
                        {
                            "label": "Zero Stock",
                            "count_expression": "Item.objects.filter(qty=0).count()",
                            "severity": "warning",
                        },
                    ],
                    "sections": [
                        {
                            "title": "Items",
                            "queryset_expression": "Item.objects.all()",
                            "columns": [
                                {"field": "name", "label": "Name"},
                            ],
                            "limit": 50,
                        },
                    ],
                },
            ],
        }
        config_path = tmp_path / "dashboard-config.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

        contract = {"version": "1.3", "tables": []}
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")

        out_dir = tmp_path / "out_dashboard"
        call_command(
            "generate_views",
            contract=str(contract_path),
            out_dir=str(out_dir),
            archetype_dashboard=str(config_path),
            force=True,
        )
        assert (out_dir / "views_auto.py").exists()
        assert (out_dir / "urls_auto.py").exists()
        views_source = (out_dir / "views_auto.py").read_text(encoding="utf-8")
        assert "class InventoryDashboardView" in views_source
        template_source = (out_dir / "generated" / "dashboard_inventory.html").read_text(encoding="utf-8")
        assert "Inventory Dashboard" in template_source
