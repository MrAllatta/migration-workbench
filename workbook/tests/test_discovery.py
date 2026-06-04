"""Tests for the discovery-interview generator, parser, and merge helpers."""

from __future__ import annotations

import yaml
from django.core.management import call_command

from workbook.discovery import (
    apply_discovery_patch,
    build_interaction_contract_from_patch,
    parse_interview,
    render_interview,
    render_summary,
)
from workbook.codegen.admin_generator import render_admin_py


def _orders_manifest() -> dict:
    """Fixture view manifest mirroring scaffold_view_manifest output for Orders + hidden Staging."""
    return {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "demo", "provider": "google_sheets"},
        "views": [
            {
                "name": "orders",
                "entity": "orders",
                "source_tab": "Orders",
                "type": "list",
                "editable_fields": ["order_id", "customer", "status"],
                "computed_fields": ["total"],
                "filterable_by": ["status"],
                "status_field": "status",
                "notes": None,
            },
            {
                "name": "staging",
                "entity": None,
                "source_tab": "Staging",
                "type": "list",
                "editable_fields": ["note", "owner"],
                "computed_fields": [],
                "filterable_by": [],
                "status_field": None,
                "notes": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Orders"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }


def _filled_interview_text() -> str:
    """Match the example_data fixture but compact enough to keep tests readable."""
    return (
        "<!-- discovery-interview-format: draft-1 -->\n"
        "# Discovery Interview — demo\n"
        "\n"
        "## Top-level\n"
        "\n"
        "<!-- q: weekly_workflow -->\n"
        "1. Walk me through what you do with this sheet on a typical Monday.\n"
        "   > Open Orders, chase anything still pending.\n"
        "\n"
        "## Per-view questions\n"
        "\n"
        "### Orders (source tab: Orders)\n"
        "\n"
        "<!-- q: role tab=Orders -->\n"
        "- Is **Orders** used by everyone, or a specific role?\n"
        "  > Finance team only.\n"
        "\n"
        "- Which fields does your team edit most frequently?\n"
        "  > _Editable fields inferred: order_id, customer, status_\n"
        "\n"
        "<!-- q: status tab=Orders field=status -->\n"
        "- What does moving the **status** field mean?\n"
        "  > open -> pending -> shipped -> closed.\n"
        "\n"
        "### Staging (hidden tab — staging/admin)\n"
        "\n"
        "<!-- q: access tab=Staging -->\n"
        "- Who has access to **Staging**?\n"
        "  > Internal QA only.\n"
        "\n"
        "## Workflow actions\n"
        "\n"
        "<!-- q: weekly_actions -->\n"
        "- What are the 3-5 things you do every week?\n"
        "  1. Reconcile orders against CRM.\n"
        "  2. Move pending to shipped Wednesday.\n"
        "  3. Close fully-paid orders Friday.\n"
    )


def test_render_interview_has_all_sections():
    md = render_interview(_orders_manifest())
    assert "<!-- discovery-interview-format: draft-1 -->" in md
    assert "# Discovery Interview" in md
    assert "## Top-level" in md
    assert "## Per-view questions" in md
    assert "## Workflow actions" in md
    assert "### Orders (source tab: Orders)" in md
    assert "### Staging (hidden tab" in md


def test_render_interview_status_question_only_when_status_field():
    manifest = _orders_manifest()
    md = render_interview(manifest)
    assert "<!-- q: status field=status tab=Orders -->" in md
    # Staging has no status_field, so no status question for it.
    assert "<!-- q: status field=" in md  # only Orders should have one
    assert md.count("<!-- q: status ") == 1


def test_render_interview_hidden_tab_gets_access_question():
    md = render_interview(_orders_manifest())
    # Hidden Staging should get an access question, not a role question.
    assert "<!-- q: access tab=Staging -->" in md
    assert "<!-- q: role tab=Staging -->" not in md
    # Visible Orders gets role, not access.
    assert "<!-- q: role tab=Orders -->" in md
    assert "<!-- q: access tab=Orders -->" not in md


def test_parse_interview_extracts_answers():
    manifest = _orders_manifest()
    patch = parse_interview(_filled_interview_text(), manifest)

    assert patch["weekly_workflow"] == "Open Orders, chase anything still pending."
    assert patch["role_hints"] == ["Orders: Finance team only."]
    assert patch["weekly_actions"] == [
        "Reconcile orders against CRM.",
        "Move pending to shipped Wednesday.",
        "Close fully-paid orders Friday.",
    ]
    assert "Orders" in patch["view_notes"]
    assert "status[status]" in patch["view_notes"]["Orders"]
    assert "Staging" in patch["view_notes"]
    assert "access:" in patch["view_notes"]["Staging"]


def test_parse_interview_tolerates_blanks():
    manifest = _orders_manifest()
    blank_interview = render_interview(manifest)
    patch = parse_interview(blank_interview, manifest)
    assert patch["role_hints"] == []
    assert patch["weekly_actions"] == []
    assert patch["view_notes"] == {}
    assert patch["weekly_workflow"] == ""


def test_apply_discovery_patch_merges_into_manifest():
    manifest = _orders_manifest()
    snapshot_before = yaml.safe_dump(manifest, sort_keys=True)

    patch = {
        "role_hints": ["Orders: Finance team only."],
        "weekly_actions": ["Reconcile orders", "Ship pending"],
        "view_notes": {
            "Orders": "status: open -> pending -> shipped",
            "Staging": "access: Internal QA only",
        },
        "weekly_workflow": "",
    }
    updated = apply_discovery_patch(manifest, patch)

    assert updated["workflow_hints"]["role_hints"] == ["Orders: Finance team only."]
    assert updated["workflow_hints"]["weekly_actions"] == [
        "Reconcile orders",
        "Ship pending",
    ]
    orders_view = next(v for v in updated["views"] if v["source_tab"] == "Orders")
    staging_view = next(v for v in updated["views"] if v["source_tab"] == "Staging")
    assert orders_view["notes"] == "status: open -> pending -> shipped"
    assert staging_view["notes"] == "access: Internal QA only"

    # Original manifest was not mutated.
    assert yaml.safe_dump(manifest, sort_keys=True) == snapshot_before


def test_render_summary_includes_role_hints_and_actions():
    manifest = _orders_manifest()
    patch = parse_interview(_filled_interview_text(), manifest)
    updated = apply_discovery_patch(manifest, patch)

    summary = render_summary(
        updated,
        generated_at="2026-05-06",
        weekly_workflow=patch["weekly_workflow"],
    )
    assert "# Discovery Summary" in summary
    assert "Generated: 2026-05-06" in summary
    assert "## Weekly workflow" in summary
    assert "Open Orders, chase anything still pending." in summary
    assert "Orders: Finance team only." in summary
    assert "1. Reconcile orders against CRM." in summary
    assert "**Orders**:" in summary
    assert "**Staging**:" in summary


def test_generate_interview_command_writes_md(tmp_path):
    manifest_path = tmp_path / "view-manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(_orders_manifest()), encoding="utf-8")
    out_path = tmp_path / "interview.md"

    call_command(
        "generate_discovery_interview",
        manifest=str(manifest_path),
        out=str(out_path),
    )

    text = out_path.read_text(encoding="utf-8")
    assert "<!-- discovery-interview-format: draft-1 -->" in text
    assert "### Orders (source tab: Orders)" in text
    assert "### Staging (hidden tab" in text


def test_merge_notes_command_writes_updated_manifest(tmp_path):
    manifest_path = tmp_path / "view-manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(_orders_manifest()), encoding="utf-8")
    interview_path = tmp_path / "interview.md"
    interview_path.write_text(_filled_interview_text(), encoding="utf-8")
    out_path = tmp_path / "view-manifest.merged.yaml"
    summary_path = tmp_path / "discovery-summary.md"

    call_command(
        "merge_discovery_notes",
        manifest=str(manifest_path),
        interview=str(interview_path),
        out=str(out_path),
        summary_out=str(summary_path),
    )

    updated = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert updated["workflow_hints"]["role_hints"] == ["Orders: Finance team only."]
    assert (
        "Reconcile orders against CRM." in updated["workflow_hints"]["weekly_actions"]
    )
    orders_view = next(v for v in updated["views"] if v["source_tab"] == "Orders")
    assert orders_view["notes"] is not None
    assert "status[status]" in orders_view["notes"]

    summary_text = summary_path.read_text(encoding="utf-8")
    assert "## Weekly workflow" in summary_text
    assert "Open Orders, chase anything still pending." in summary_text


# ---------------------------------------------------------------------------
# status_override question in interview
# ---------------------------------------------------------------------------


def test_render_interview_includes_status_override_question():
    manifest = _orders_manifest()
    md = render_interview(manifest)
    assert "<!-- q: status_override field=status tab=Orders -->" in md


def test_parse_interview_extracts_status_override():
    interview = (
        "<!-- discovery-interview-format: draft-1 -->\n"
        "# Discovery Interview — demo\n\n"
        "## Per-view questions\n\n"
        "### Orders (source tab: Orders)\n\n"
        "<!-- q: role tab=Orders -->\n"
        "- Role?\n"
        "  > Finance team.\n\n"
        "<!-- q: status tab=Orders field=status -->\n"
        "- Status meaning?\n"
        "  > Open -> closed.\n\n"
        "<!-- q: status_override tab=Orders field=status -->\n"
        "- Override status field?\n"
        "  > priority\n\n"
        "## Workflow actions\n\n"
        "<!-- q: weekly_actions -->\n"
        "- Actions?\n"
    )
    manifest = _orders_manifest()
    patch = parse_interview(interview, manifest)
    assert "status_overrides" in patch
    assert patch["status_overrides"]["Orders"] == "priority"


def test_apply_discovery_patch_writes_status_field_override():
    manifest = _orders_manifest()
    patch = {
        "role_hints": [],
        "weekly_actions": [],
        "view_notes": {},
        "weekly_workflow": "",
        "status_overrides": {"Orders": "priority"},
    }
    updated = apply_discovery_patch(manifest, patch)
    orders_view = next(v for v in updated["views"] if v["source_tab"] == "Orders")
    assert orders_view["status_field"] == "priority"


def test_apply_discovery_patch_clears_status_field():
    manifest = _orders_manifest()
    patch = {
        "role_hints": [],
        "weekly_actions": [],
        "view_notes": {},
        "weekly_workflow": "",
        "status_overrides": {"Orders": "none"},
    }
    updated = apply_discovery_patch(manifest, patch)
    orders_view = next(v for v in updated["views"] if v["source_tab"] == "Orders")
    assert orders_view["status_field"] is None


def test_parse_interview_skips_blank_status_override():
    interview = (
        "<!-- discovery-interview-format: draft-1 -->\n"
        "# Discovery Interview — demo\n\n"
        "## Per-view questions\n\n"
        "### Orders (source tab: Orders)\n\n"
        "<!-- q: role tab=Orders -->\n"
        "- Role?\n"
        "  > Finance team.\n\n"
        "<!-- q: status tab=Orders field=status -->\n"
        "- Status meaning?\n"
        "  > Open -> closed.\n\n"
        "<!-- q: status_override tab=Orders field=status -->\n"
        "- Override?\n"
        "  > _Your answer:_ (leave blank to keep **status**)\n\n"
        "## Workflow actions\n\n"
        "<!-- q: weekly_actions -->\n"
        "- Actions?\n"
    )
    manifest = _orders_manifest()
    patch = parse_interview(interview, manifest)
    assert "status_overrides" in patch
    # Blank override should not be in the dict
    assert "Orders" not in patch["status_overrides"]


# ---------------------------------------------------------------------------
# Edge cases and round-trip
# ---------------------------------------------------------------------------


def test_parse_interview_with_reordered_sections():
    interview = (
        "<!-- discovery-interview-format: draft-1 -->\n"
        "# Discovery Interview — demo\n\n"
        "## Workflow actions\n\n"
        "<!-- q: weekly_actions -->\n"
        "- Actions?\n"
        "  1. Reconcile orders.\n\n"
        "## Per-view questions\n\n"
        "<!-- q: role tab=Orders -->\n"
        "- Role?\n"
        "  > Finance.\n\n"
    )
    manifest = _orders_manifest()
    patch = parse_interview(interview, manifest)
    assert patch["role_hints"] == ["Orders: Finance."]
    assert "Reconcile orders." in patch["weekly_actions"]


def test_parse_interview_with_extra_blank_lines():
    interview = (
        "<!-- discovery-interview-format: draft-1 -->\n"
        "# Discovery Interview — demo\n\n"
        "## Per-view questions\n\n"
        "<!-- q: role tab=Orders -->\n\n\n"
        "- Role?\n"
        "  > Finance.\n\n"
    )
    manifest = _orders_manifest()
    patch = parse_interview(interview, manifest)
    assert patch["role_hints"] == ["Orders: Finance."]


def test_discovery_round_trip_generates_admin():
    """Full round-trip: manifest -> interview -> fill -> parse -> merge -> admin generation."""
    contract = {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": "crop",
                "model_name": "Crop",
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                    {
                        "suggested_field_name": "crop_type",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 100},
                    },
                ],
            },
        ],
    }
    manifest = {
        "version": "view-manifest-draft-1",
        "source": {"source_id": "roundtrip", "provider": "google_sheets"},
        "views": [
            {
                "name": "crop",
                "entity": "crop",
                "source_tab": "Crops",
                "type": "list",
                "editable_fields": ["name", "crop_type"],
                "computed_fields": [],
                "filterable_by": ["crop_type"],
                "status_field": "crop_type",
                "notes": None,
            },
        ],
        "workflow_hints": {
            "tab_sequence": ["Crops"],
            "role_hints": [],
            "weekly_actions": [],
        },
    }
    interview_md = render_interview(manifest)
    assert "<!-- q: role tab=Crops -->" in interview_md
    assert "<!-- q: status_override field=crop_type tab=Crops -->" in interview_md

    filled = (
        interview_md.replace("> _Your answer:_", "> Weekly workflow check.", 1)
        .replace("> _Your answer:_", "> Farm manager.", 1)
        .replace("> _Your answer:_", "> active -> inactive", 1)
        .replace(
            "> _Your answer:_ (leave blank to keep **crop_type**)", "> priority", 1
        )
    )
    patch = parse_interview(filled, manifest)
    assert "Farm manager" in patch["role_hints"][0]
    assert patch["status_overrides"].get("Crops") == "priority"
    merged = apply_discovery_patch(manifest, patch)
    source = render_admin_py(contract, merged, app_label="core")
    assert "@admin.register(Crop)" in source
    assert "list_filter" in source


# ---------------------------------------------------------------------------
# build_interaction_contract_from_patch
# ---------------------------------------------------------------------------


def test_build_interaction_contract_from_role_hints():
    manifest = _orders_manifest()
    patch = parse_interview(_filled_interview_text(), manifest)
    contract = build_interaction_contract_from_patch(patch, manifest)
    assert contract["version"] == "interaction-contract-1"
    assert len(contract["interviews"]) >= 1
    # role "Finance team only." should be in the interviews
    roles = [i["role"] for i in contract["interviews"]]
    assert any("Finance" in r for r in roles)


def test_build_interaction_contract_empty_patch():
    manifest = _orders_manifest()
    blank_interview = render_interview(manifest)
    patch = parse_interview(blank_interview, manifest)
    contract = build_interaction_contract_from_patch(patch, manifest)
    assert contract["version"] == "interaction-contract-1"
    assert contract["interviews"] == []


def test_build_interaction_contract_preserves_weekly_actions():
    manifest = _orders_manifest()
    patch = parse_interview(_filled_interview_text(), manifest)
    contract = build_interaction_contract_from_patch(patch, manifest)
    all_actions: list[str] = []
    for entry in contract["interviews"]:
        all_actions.extend(entry.get("weekly_actions") or [])
    assert "Reconcile orders against CRM." in all_actions


def test_build_interaction_contract_with_source_id():
    manifest = _orders_manifest()
    patch = parse_interview(_filled_interview_text(), manifest)
    contract = build_interaction_contract_from_patch(patch, manifest, source_id="custom")
    assert contract["source_id"] == "custom"


def test_merge_discovery_notes_with_interaction_contract_output(tmp_path):
    """End-to-end: merge_discovery_notes with --output-interaction-contract writes the contract."""
    from django.core.management import call_command

    import yaml

    manifest_path = tmp_path / "view-manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(_orders_manifest()), encoding="utf-8")
    interview_path = tmp_path / "interview.md"
    interview_path.write_text(_filled_interview_text(), encoding="utf-8")
    out_path = tmp_path / "manifest-out.yaml"
    contract_path = tmp_path / "interaction-contract.yaml"

    call_command(
        "merge_discovery_notes",
        manifest=str(manifest_path),
        interview=str(interview_path),
        out=str(out_path),
        output_interaction_contract=str(contract_path),
    )

    assert contract_path.exists()
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    assert contract["version"] == "interaction-contract-1"
    assert len(contract["interviews"]) >= 1
