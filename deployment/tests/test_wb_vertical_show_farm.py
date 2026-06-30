"""Tests for ``wb vertical show farm`` command."""

import json
import subprocess
import sys


def _run_wb(extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run ``wb vertical show farm`` with optional extra flags."""
    cmd = [
        sys.executable,
        "-m",
        "deployment.wb_cli",
        "vertical",
        "show",
        "farm",
        *(extra_args or []),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_wb_vertical_show_farm_shows_entity_templates():
    """wb vertical show farm shows 4 entity templates."""
    result = _run_wb()
    assert result.returncode == 0, (
        f"Expected exit code 0, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout
    # Should contain farm vertical details
    assert "farm" in output, f"Expected 'farm' in output, got: {output}"
    assert (
        "Farm vertical template" in output
    ), f"Expected description in output, got: {output}"
    # Should show the 4 entity templates
    assert "Crop" in output, f"Expected Crop entity in output, got: {output}"
    assert (
        "FieldBlock" in output
    ), f"Expected FieldBlock entity in output, got: {output}"
    assert "Season" in output, f"Expected Season entity in output, got: {output}"
    assert (
        "PlantingPlan" in output
    ), f"Expected PlantingPlan entity in output, got: {output}"


def test_wb_vertical_show_farm_json_returns_valid_json():
    """--json flag returns valid JSON with vertical details."""
    result = _run_wb(["--json"])
    assert result.returncode == 0, (
        f"Expected exit code 0, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, f"Expected ok=True, got: {payload}"
    assert "vertical" in payload, f"Expected 'vertical' key in payload, got: {payload}"
    vertical = payload["vertical"]
    assert (
        vertical.get("name") == "farm"
    ), f"Expected name 'farm', got: {vertical.get('name')}"
    assert (
        vertical.get("version") == "0.1.0"
    ), f"Expected version '0.1.0', got: {vertical.get('version')}"
    assert "Farm vertical template" in vertical.get(
        "description", ""
    ), f"Expected description to contain 'Farm vertical template', got: {vertical.get('description')}"
    assert (
        vertical.get("confidence") == "exploratory"
    ), f"Expected confidence 'exploratory', got: {vertical.get('confidence')}"
    # Check entity templates - should have 4
    entity_templates = vertical.get("entity_templates", {})
    assert (
        len(entity_templates) == 4
    ), f"Expected 4 entity templates, got: {len(entity_templates)}"
    assert (
        "Crop" in entity_templates
    ), f"Expected Crop in entity_templates, got: {list(entity_templates.keys())}"
    assert (
        "FieldBlock" in entity_templates
    ), f"Expected FieldBlock in entity_templates, got: {list(entity_templates.keys())}"
    assert (
        "Season" in entity_templates
    ), f"Expected Season in entity_templates, got: {list(entity_templates.keys())}"
    assert (
        "PlantingPlan" in entity_templates
    ), f"Expected PlantingPlan in entity_templates, got: {list(entity_templates.keys())}"
