"""Tests for ``wb vertical list`` command."""

import json
import subprocess
import sys


def _run_wb(extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run ``wb vertical list`` with optional extra flags."""
    cmd = [
        sys.executable,
        "-m",
        "deployment.wb_cli",
        "vertical",
        "list",
        * (extra_args or []),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_wb_vertical_list_shows_example_and_farm():
    """wb vertical list shows at least example and farm verticals."""
    result = _run_wb()
    assert result.returncode == 0, (
        f"Expected exit code 0, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout
    # Should contain both example and farm verticals
    assert "example" in output, f"Expected 'example' in output, got: {output}"
    assert "farm" in output, f"Expected 'farm' in output, got: {output}"


def test_wb_vertical_list_json_returns_valid_json():
    """--json flag returns valid JSON with verticals array."""
    result = _run_wb(["--json"])
    assert result.returncode == 0, (
        f"Expected exit code 0, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, f"Expected ok=True, got: {payload}"
    assert "verticals" in payload, f"Expected 'verticals' key in payload, got: {payload}"
    assert isinstance(payload["verticals"], list), f"Expected verticals to be list, got: {payload['verticals']}"
    # Should have at least example and farm
    names = [v.get("name") for v in payload["verticals"]]
    assert "example" in names, f"Expected 'example' in vertical names, got: {names}"
    assert "farm" in names, f"Expected 'farm' in vertical names, got: {names}"