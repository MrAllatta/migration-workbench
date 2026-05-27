"""Tests for the run_pipeline_state management command."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import yaml
from django.core.management import call_command
from django.core.management.base import CommandError

import pytest


def test_run_pipeline_state_help(capsys):
    """--help shows expected arguments."""
    with pytest.raises(SystemExit):
        call_command("run_pipeline_state", "--help")
    captured = capsys.readouterr()
    help_text = captured.out
    assert "--config" in help_text
    assert "--phase" in help_text
    assert "--checkpoint" in help_text
    assert "discover" in help_text
    assert "score_and_select" in help_text
    assert "deep_profile" in help_text
    assert "derive_contracts" in help_text
    assert "all" in help_text


def test_run_pipeline_state_missing_config():
    """Errors when --config points to a nonexistent file."""
    with pytest.raises(CommandError, match="Config file not found"):
        out = StringIO()
        call_command(
            "run_pipeline_state",
            "--config=/nonexistent/path.json",
            "--phase=discover",
            stdout=out,
            stderr=out,
        )


def test_run_pipeline_state_invalid_phase():
    """Errors on an invalid --phase value."""
    out = StringIO()
    with pytest.raises(CommandError, match="invalid choice"):
        call_command(
            "run_pipeline_state",
            "--config=pyproject.toml",
            "--phase=bogus",
            stdout=out,
        )


@patch("profiler.tools.cohort_corpus.run_cohort_corpus")
def test_run_pipeline_state_discover_phase(
    mock_run_cohort_corpus, tmp_path: Path
):
    """--phase discover runs the discovery pipeline and writes a checkpoint."""
    mock_run_cohort_corpus.return_value = {}

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"domain": "test_domain"}), encoding="utf-8")

    checkpoint = tmp_path / "state.yaml"

    out = StringIO()
    call_command(
        "run_pipeline_state",
        f"--config={config}",
        "--phase=discover",
        f"--checkpoint={checkpoint}",
        stdout=out,
    )

    assert mock_run_cohort_corpus.called
    assert checkpoint.exists()
    raw = yaml.safe_load(checkpoint.read_text(encoding="utf-8"))
    assert raw is not None
    assert raw["discovery"]["source_tree"] == {}
    assert raw["discovery"]["workbook_index"] == []
    assert raw["domain_knowledge"]["domain"] == "test_domain"
    assert "Phase 0/1 complete" in out.getvalue()


@patch("profiler.tools.cohort_corpus.run_cohort_corpus")
def test_run_pipeline_state_all_phase(
    mock_run_cohort_corpus, tmp_path: Path
):
    """--phase all runs all four phases in sequence."""
    mock_run_cohort_corpus.return_value = {}

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"domain": "test_domain"}), encoding="utf-8")

    checkpoint = tmp_path / "state.yaml"

    out = StringIO()
    call_command(
        "run_pipeline_state",
        f"--config={config}",
        "--phase=all",
        f"--checkpoint={checkpoint}",
        stdout=out,
    )

    assert mock_run_cohort_corpus.called
    assert checkpoint.exists()
    raw = yaml.safe_load(checkpoint.read_text(encoding="utf-8"))
    assert raw is not None
    assert raw["discovery"]["source_tree"] == {}
    assert raw["domain_knowledge"]["domain"] == "test_domain"

    output = out.getvalue()
    assert "Phase 0/1 complete" in output
    assert "derive_contracts" in output


@patch("profiler.tools.cohort_corpus.run_cohort_corpus")
def test_run_pipeline_state_resume(
    mock_run_cohort_corpus, tmp_path: Path
):
    """Loading a partial checkpoint skips completed phases."""
    mock_run_cohort_corpus.return_value = {}

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"domain": "resume_test"}), encoding="utf-8")

    checkpoint = tmp_path / "state.yaml"

    # Start with discover and score_and_select already done.
    # Seed approved_tabs so deep_profile proceeds past its guard.
    from profiler.tools.pipeline_state import PipelineState

    state = PipelineState()
    state.discover()
    state.score_and_select()
    state.discovery.approved_tabs = {"101": ["Sheet1"]}
    state.save_checkpoint(checkpoint)

    out = StringIO()
    call_command(
        "run_pipeline_state",
        f"--config={config}",
        "--phase=all",
        f"--checkpoint={checkpoint}",
        stdout=out,
    )

    output = out.getvalue()
    assert "[skip] discover already complete" in output
    assert "[skip] score_and_select already complete" in output
    assert "derive_contracts" in output

    # Verify final checkpoint preserves data from completed phases.
    raw = yaml.safe_load(checkpoint.read_text(encoding="utf-8"))
    assert "discovery" in raw
    assert "domain_knowledge" in raw
