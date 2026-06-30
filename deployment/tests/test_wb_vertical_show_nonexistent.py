"""Tests for ``wb vertical show nonexistent`` command."""

import json
import subprocess
import sys


def _run_wb(extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run ``wb vertical show nonexistent`` with optional extra flags."""
    cmd = [
        sys.executable,
        "-m",
        "deployment.wb_cli",
        "vertical",
        "show",
        "nonexistent",
        *(extra_args or []),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_wb_vertical_show_nonexistent_clear_error():
    """wb vertical show nonexistent gives clear error message."""
    result = _run_wb()
    assert result.returncode == 1, (
        f"Expected exit code 1, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout
    # Should contain clear error message, not traceback
    assert (
        "WB-VERTICAL-4001" in output
    ), f"Expected error code WB-VERTICAL-4001, got: {output}"
    assert (
        "Vertical template 'nonexistent' not found." in output
    ), f"Expected clear error message, got: {output}"
    # Should not contain traceback-like content
    assert "Traceback" not in output, f"Should not contain traceback, got: {output}"
    assert (
        "FileNotFoundError" not in output
    ), f"Should not contain FileNotFoundError, got: {output}"


def test_wb_vertical_show_nonexistent_json_returns_error():
    """--json flag returns valid JSON with error for nonexistent vertical."""
    result = _run_wb(["--json"])
    assert result.returncode == 1, (
        f"Expected exit code 1, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is False, f"Expected ok=False, got: {payload}"
    assert (
        payload.get("error_code") == "WB-VERTICAL-4001"
    ), f"Expected error_code WB-VERTICAL-4001, got: {payload.get('error_code')}"
    assert (
        "Vertical template 'nonexistent' not found." in payload["message"]
    ), f"Expected clear error message in JSON, got: {payload['message']}"
