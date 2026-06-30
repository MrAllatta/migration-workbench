"""Tests for ``wb vertical show example`` command."""

import json
import subprocess
import sys


def _run_wb(extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run ``wb vertical show example`` with optional extra flags."""
    cmd = [
        sys.executable,
        "-m",
        "deployment.wb_cli",
        "vertical",
        "show",
        "example",
        *(extra_args or []),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_wb_vertical_show_example_shows_details():
    """wb vertical show example shows details of example vertical."""
    result = _run_wb()
    assert result.returncode == 0, (
        f"Expected exit code 0, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout
    # Should contain example vertical details
    assert "example" in output, f"Expected 'example' in output, got: {output}"
    assert (
        "Example vertical template for testing" in output
    ), f"Expected description in output, got: {output}"
    assert "Widget" in output, f"Expected Widget entity in output, got: {output}"
    assert "Category" in output, f"Expected Category entity in output, got: {output}"


def test_wb_vertical_show_example_json_returns_valid_json():
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
        vertical.get("name") == "example"
    ), f"Expected name 'example', got: {vertical.get('name')}"
    assert (
        vertical.get("version") == "0.1.0"
    ), f"Expected version '0.1.0', got: {vertical.get('version')}"
    assert (
        "example" in vertical.get("description", "").lower()
    ), f"Expected description to contain 'example', got: {vertical.get('description')}"
    assert (
        vertical.get("confidence") == "exploratory"
    ), f"Expected confidence 'exploratory', got: {vertical.get('confidence')}"
    # Check entity templates
    entity_templates = vertical.get("entity_templates", {})
    assert (
        "Widget" in entity_templates
    ), f"Expected Widget in entity_templates, got: {list(entity_templates.keys())}"
    assert (
        "Category" in entity_templates
    ), f"Expected Category in entity_templates, got: {list(entity_templates.keys())}"
