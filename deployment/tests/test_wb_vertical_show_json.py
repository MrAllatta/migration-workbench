"""Tests for ``wb vertical show --json`` command."""

import json
import subprocess
import sys


def _run_wb(extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run ``wb vertical show`` with optional extra flags."""
    cmd = [
        sys.executable,
        "-m",
        "deployment.wb_cli",
        "vertical",
        "show",
        "example",  # Using example vertical for testing
        *(extra_args or []),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_wb_vertical_show_json_returns_valid_json():
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
    # Check that we got the expected structure
    assert isinstance(
        vertical, dict
    ), f"Expected vertical to be dict, got: {type(vertical)}"
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
