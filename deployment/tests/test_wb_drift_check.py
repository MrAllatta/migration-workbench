"""Tests for ``wb drift check`` CLI subcommand."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


def _contract_with_model(model_name: str = "crop") -> dict:
    pname = "".join(p.capitalize() for p in model_name.replace("-", "_").split("_"))
    return {
        "source": {"provider": "google_sheets"},
        "tables": [
            {
                "suggested_model_name": model_name,
                "model_name": pname,
                "columns": [
                    {
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 200},
                    },
                ],
            },
        ],
    }


def _run_drift_check(baseline: Path, new: Path, json_output: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "deployment.wb_cli"]
    if json_output:
        cmd.append("--json")
    cmd.extend(["drift", "check", "--baseline", str(baseline), "--new", str(new)])
    return subprocess.run(cmd, capture_output=True, text=True)


def test_drift_check_identical_contracts(tmp_path):
    contract = _contract_with_model("crop")
    baseline = tmp_path / "baseline.yaml"
    new = tmp_path / "new.yaml"
    baseline.write_text(yaml.dump(contract, sort_keys=False), encoding="utf-8")
    new.write_text(yaml.dump(contract, sort_keys=False), encoding="utf-8")

    result = _run_drift_check(baseline, new, json_output=True)
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert "identical" in payload["message"].lower() or "no drift" in payload["message"].lower()


def test_drift_check_detects_added_model(tmp_path):
    old = _contract_with_model("crop")
    new_data = _contract_with_model("crop")
    new_data["tables"].append({
        "suggested_model_name": "variety",
        "model_name": "Variety",
        "columns": [
            {
                "suggested_field_name": "name",
                "django_field_class": "models.CharField",
                "django_field_kwargs": {"max_length": 200},
            },
        ],
    })
    baseline = tmp_path / "baseline.yaml"
    new = tmp_path / "new.yaml"
    baseline.write_text(yaml.dump(old, sort_keys=False), encoding="utf-8")
    new.write_text(yaml.dump(new_data, sort_keys=False), encoding="utf-8")

    result = _run_drift_check(baseline, new, json_output=True)
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "Variety" in payload["diffs"].get("models_added", [])


def test_drift_check_human_readable_output(tmp_path):
    old = _contract_with_model("crop")
    new_data = _contract_with_model("crop")
    new_data["tables"][0]["columns"].append({
        "suggested_field_name": "variety",
        "django_field_class": "models.CharField",
        "django_field_kwargs": {"max_length": 100},
    })
    baseline = tmp_path / "baseline.yaml"
    new = tmp_path / "new.yaml"
    baseline.write_text(yaml.dump(old, sort_keys=False), encoding="utf-8")
    new.write_text(yaml.dump(new_data, sort_keys=False), encoding="utf-8")

    result = _run_drift_check(baseline, new, json_output=False)
    assert result.returncode == 1  # drift detected
    assert "variety" in result.stdout or "added" in result.stdout.lower()


def test_drift_check_missing_baseline_file(tmp_path):
    missing = tmp_path / "nonexistent.yaml"
    new = tmp_path / "new.yaml"
    new.write_text(yaml.dump(_contract_with_model(), sort_keys=False), encoding="utf-8")

    result = _run_drift_check(missing, new, json_output=True)
    assert result.returncode != 0