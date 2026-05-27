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
    assert "discover complete" in out.getvalue()


@patch("profiler.tools.cohort_corpus.run_cohort_corpus")
def test_run_pipeline_state_all_phase(
    mock_run_cohort_corpus, tmp_path: Path
):
    """--phase all runs deep_profile and derive_contracts on a partial
    checkpoint, skipping already-completed phases."""
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"domain": "test_domain"}), encoding="utf-8")

    checkpoint = tmp_path / "state.yaml"

    # Create a deep coverage file so deep_profile populates entries,
    # allowing derive_contracts to proceed.
    deep_file = tmp_path / "deep_coverage.json"
    deep_file.write_text(
        json.dumps([
            {
                "tab": "Crop Planner",
                "columns": [
                    {"header": "name", "data_type": "string"},
                ],
            },
        ]),
        encoding="utf-8",
    )
    mock_run_cohort_corpus.return_value = {"deep_coverage": str(deep_file)}

    # Seed a checkpoint with discover and score_and_select already
    # complete, so only deep_profile and derive_contracts run.
    from profiler.tools.pipeline_state import (
        DiscoveryState,
        DomainKnowledge,
        PipelineState,
    )

    state = PipelineState(
        domain_knowledge=DomainKnowledge(domain="test_domain"),
        discovery=DiscoveryState(
            source_tree={"provider": "google_sheets"},
            workbook_index=[{"workbook_code": "101", "year": 2023}],
            broad_inventory=[
                {
                    "tab_title": "Crop Planner",
                    "row_count": 100,
                    "column_count": 20,
                },
            ],
            shortlist=[{"tab_title": "Crop Planner", "score": 85}],
            approved_tabs={"101": ["Crop Planner"]},
        ),
    )
    state.save_checkpoint(checkpoint)

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
    assert raw["domain_knowledge"]["domain"] == "test_domain"

    output = out.getvalue()
    assert "[skip] discover already complete" in output
    assert "deep_profile complete" in output
    assert "derive_contracts complete" in output
    # Verify the checkpoint contains derived contracts
    assert "schema_contract" in raw
    assert "interaction_contract" in raw


@patch("profiler.tools.cohort_corpus.run_cohort_corpus")
def test_run_pipeline_state_resume(
    mock_run_cohort_corpus, tmp_path: Path
):
    """Loading a partial checkpoint skips completed phases."""
    mock_run_cohort_corpus.return_value = {}

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"domain": "resume_test"}), encoding="utf-8")

    checkpoint = tmp_path / "state.yaml"

    # Seed a checkpoint with discover, score_and_select, and
    # deep_profile already complete (entries populated, approved_tabs set,
    # schema_contract still None so derive_contracts runs).
    from profiler.tools.pipeline_state import PipelineState

    state = PipelineState()
    state.discover()
    state.score_and_select()
    state.discovery.approved_tabs = {"101": ["Sheet1"]}
    state.deep_profile_index.entries = [
        {
            "tab": "Crop Planner",
            "columns": [
                {"header": "crop_name", "data_type": "string"},
            ],
        },
    ]
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
    assert "[skip] deep_profile already complete" in output
    assert "derive_contracts complete" in output

    # Verify final checkpoint preserves data from completed phases
    # and includes derived contracts.
    raw = yaml.safe_load(checkpoint.read_text(encoding="utf-8"))
    assert "discovery" in raw
    assert "domain_knowledge" in raw
    assert "schema_contract" in raw
    assert "interaction_contract" in raw


class TestDomainContextArgument:
    """Verify --domain-context is accepted and routed."""

    def test_domain_context_flag_in_help(self, capsys):
        """--help shows --domain-context."""
        with pytest.raises(SystemExit):
            call_command("run_pipeline_state", "--help")
        captured = capsys.readouterr()
        assert "--domain-context" in captured.out

    @patch("profiler.tools.cohort_corpus.run_cohort_corpus")
    def test_domain_context_seeds_domain_knowledge(
        self, mock_run_cohort_corpus, tmp_path
    ):
        """Passing --domain-context seeds DomainKnowledge on fresh state."""
        mock_run_cohort_corpus.return_value = {}
        config_path = tmp_path / "config.json"
        config_path.write_text('{"domain": "test"}', encoding="utf-8")

        dc_path = tmp_path / "domain_context.yaml"
        dc_path.write_text(
            'domain: "test_domain"\n'
            "vocabulary:\n"
            "  operational: [test_token]\n"
            "  reference: []\n"
            "  support: []\n"
            "  derived: []\n"
            "year_scope:\n"
            "  active: [2026]\n"
            "  archived: []\n"
            "  forward: []\n",
            encoding="utf-8",
        )

        checkpoint = tmp_path / "state.yaml"
        out = StringIO()
        call_command(
            "run_pipeline_state",
            f"--config={config_path}",
            f"--checkpoint={checkpoint}",
            "--phase=discover",
            f"--domain-context={dc_path}",
            stdout=out,
        )

        raw = yaml.safe_load(checkpoint.read_text(encoding="utf-8"))
        assert raw["domain_knowledge"]["domain"] == "test_domain"
        assert "test_token" in raw["domain_knowledge"]["vocabulary"].get("operational", [])


class TestValidatePhase:
    """Verify --phase validate works end-to-end."""

    def test_validate_empty_checkpoint(self, tmp_path):
        """validate on a fresh/empty checkpoint succeeds."""
        config_path = tmp_path / "config.json"
        config_path.write_text('{"domain": "test"}', encoding="utf-8")

        out = StringIO()
        call_command(
            "run_pipeline_state",
            f"--config={config_path}",
            "--phase=validate",
            f"--checkpoint={tmp_path / 'pipeline-state.yaml'}",
            stdout=out,
        )
        output = out.getvalue()
        assert "Checkpoint valid" in output
