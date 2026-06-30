"""Tests for ``wb contract review --exit-zero`` flag.

Verify that the ``--exit-zero`` flag changes the exit code from 1 to 0
when issues are found, and that the JSON payload marks ``ok: True``
when both ``--json`` and ``--exit-zero`` are set.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

_CONTRACT_WITH_ISSUES = {
    "source": {"provider": "test"},
    "tables": [
        {
            "suggested_model_name": "Widget",
            "model_name": "Widget",
            "columns": [
                {
                    "suggested_field_name": "label",
                    "django_field_class": "models.CharField",
                    "django_field_kwargs": {},
                },
            ],
        },
    ],
}


def _run_wb(
    contract_yaml: str, extra_args: list[str] | None = None
) -> subprocess.CompletedProcess:
    """Run ``wb contract review`` with the given contract YAML and extra flags.

    ``--json`` is a top-level flag (before the subcommand), so this helper
    places subcommand-specific flags after ``review`` and global flags before
    the subcommand verb.
    """
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yml",
        delete=False,
    )
    try:
        tmp.write(contract_yaml)
        tmp.close()
        global_flags: list[str] = []
        subcommand_flags: list[str] = []
        for flag in extra_args or []:
            if flag == "--json":
                global_flags.append(flag)
            else:
                subcommand_flags.append(flag)
        cmd = [
            sys.executable,
            "-m",
            "deployment.wb_cli",
            *global_flags,
            "contract",
            "review",
            "--contract",
            tmp.name,
            *subcommand_flags,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return result


def test_contract_review_exit_zero_returns_0():
    """When --exit-zero is passed and issues exist, exit code is 0."""
    contract_yaml = yaml.dump(_CONTRACT_WITH_ISSUES)
    result = _run_wb(contract_yaml, ["--exit-zero"])
    assert result.returncode == 0, (
        f"Expected exit code 0 with --exit-zero, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_contract_review_default_returns_1():
    """When --exit-zero is NOT passed and issues exist, exit code is 1."""
    contract_yaml = yaml.dump(_CONTRACT_WITH_ISSUES)
    result = _run_wb(contract_yaml)
    assert result.returncode == 1, (
        f"Expected exit code 1 without --exit-zero, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_contract_review_exit_zero_json_marks_ok_true():
    """When --json and --exit-zero are both set and issues exist, ok is True."""
    contract_yaml = yaml.dump(_CONTRACT_WITH_ISSUES)
    result = _run_wb(contract_yaml, ["--json", "--exit-zero"])
    assert result.returncode == 0, (
        f"Expected exit code 0 with --exit-zero --json, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, (
        f"Expected ok=True with --exit-zero --json, got ok={payload.get('ok')}.\n"
        f"Full payload: {payload}"
    )
    assert payload.get("details"), f"Expected details to contain issues, got: {payload}"
    assert (
        "(exit-zero)" in payload["message"]
    ), f"Expected '(exit-zero)' in message, got: {payload['message']}"
