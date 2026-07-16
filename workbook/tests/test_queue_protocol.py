"""Tests for the filesystem queue protocol module.

Covers: lifecycle dataclass, queue entry reading/parsing, validation,
acknowledgement (activation/consumption), health check reports, and
module-level constants.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import pytest
import yaml

from workbook.tools.queue_protocol import (
    QUEUE_NAMES,
    QUEUE_LABELS,
    LIFECYCLE_STATUSES,
    DEFAULT_TIMEOUTS,
    QUEUE_REQUIRED_FIELDS,
    Lifecycle,
    QueueEntry,
    QueueHealthReport,
    find_omo_root,
    list_queue_entries,
    read_queue_entry,
    validate_queue_entry,
    acknowledge_activation,
    acknowledge_consumption,
    check_queue_health,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify module-level constants are well-formed."""

    def test_all_queue_names_have_labels(self):
        """Every queue in QUEUE_NAMES has a corresponding label."""
        for name in QUEUE_NAMES:
            assert name in QUEUE_LABELS, f"Missing label for queue '{name}'"

    def test_all_queue_names_have_timeouts(self):
        """Every queue in QUEUE_NAMES has timeout config."""
        for name in QUEUE_NAMES:
            assert name in DEFAULT_TIMEOUTS, f"Missing timeouts for queue '{name}'"
            for status in ("created", "active"):
                assert status in DEFAULT_TIMEOUTS[name], (
                    f"Queue '{name}' missing timeout for status '{status}'"
                )

    def test_lifecycle_statuses_are_valid(self):
        """LIFECYCLE_STATUSES contains exactly the three expected values."""
        assert set(LIFECYCLE_STATUSES) == {"created", "active", "consumed"}

    def test_required_fields_exist_for_all_queues(self):
        """Every queue name has a list of required fields."""
        for name in QUEUE_NAMES:
            assert name in QUEUE_REQUIRED_FIELDS, (
                f"Missing required fields for queue '{name}'"
            )
            assert isinstance(QUEUE_REQUIRED_FIELDS[name], list)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Lifecycle dataclass construction and serialisation."""

    def test_default_status_is_created(self):
        """A default Lifecycle has status 'created'."""
        lc = Lifecycle()
        assert lc.status == "created"

    def test_from_dict_none_returns_active_with_timestamp(self):
        """from_dict(None) returns status='active' and a non-empty created_at."""
        lc = Lifecycle.from_dict(None)
        assert lc.status == "active"
        assert lc.created_at != ""

    def test_from_dict_empty_returns_active(self):
        """from_dict({}) returns status='active'."""
        lc = Lifecycle.from_dict({})
        assert lc.status == "active"

    def test_from_dict_preserves_values(self):
        """from_dict preserves all provided values."""
        lc = Lifecycle.from_dict(
            {
                "status": "consumed",
                "created_at": "2026-01-01T00:00:00",
                "activated_at": "2026-01-02T00:00:00",
                "consumed_at": "2026-01-03T00:00:00",
                "actor": "test-agent",
            }
        )
        assert lc.status == "consumed"
        assert lc.created_at == "2026-01-01T00:00:00"
        assert lc.activated_at == "2026-01-02T00:00:00"
        assert lc.consumed_at == "2026-01-03T00:00:00"
        assert lc.actor == "test-agent"

    def test_to_dict_includes_timestamps(self):
        """to_dict returns a dict with status and created_at."""
        lc = Lifecycle(status="created", created_at="2026-01-01T00:00:00")
        d = lc.to_dict()
        assert d["status"] == "created"
        assert d["created_at"] == "2026-01-01T00:00:00"

    def test_to_dict_with_active_includes_activated_at(self):
        """to_dict includes activated_at when present."""
        lc = Lifecycle(
            status="active",
            created_at="2026-01-01T00:00:00",
            activated_at="2026-01-02T00:00:00",
        )
        d = lc.to_dict()
        assert d["activated_at"] == "2026-01-02T00:00:00"


# ---------------------------------------------------------------------------
# QueueEntry
# ---------------------------------------------------------------------------


class TestQueueEntry:
    """QueueEntry dataclass properties."""

    def test_age_hours_from_created_at(self, tmp_path: Path):
        """age_hours returns a positive number for a recent entry."""
        now = datetime.now(timezone.utc)
        created_str = now.isoformat()
        entry = QueueEntry(
            path=tmp_path / "dummy.yaml",
            queue_name="next",
            filename="dummy.yaml",
            lifecycle=Lifecycle(status="created", created_at=created_str),
            data={},
        )
        assert entry.age_hours >= 0.0

    def test_age_hours_zero_when_no_created_at(self, tmp_path: Path):
        """age_hours returns 0.0 when created_at is empty."""
        entry = QueueEntry(
            path=tmp_path / "dummy.yaml",
            queue_name="next",
            filename="dummy.yaml",
            lifecycle=Lifecycle(status="created", created_at=""),
            data={},
        )
        assert entry.age_hours == 0.0


# ---------------------------------------------------------------------------
# find_omo_root
# ---------------------------------------------------------------------------


class TestFindOmoRoot:
    """Walking up directories to locate .omo/."""

    def test_raises_when_no_omo_dir(self, tmp_path: Path):
        """find_omo_root raises FileNotFoundError when no .omo/ exists."""
        with pytest.raises(FileNotFoundError, match="No .omo/ directory found"):
            find_omo_root(start_path=tmp_path)

    def test_finds_omo_root_from_repo_root(self):
        """find_omo_root locates the .omo/ directory from the repo root."""
        omo = find_omo_root()
        assert omo.name == ".omo"
        assert omo.is_dir()


# ---------------------------------------------------------------------------
# list_queue_entries
# ---------------------------------------------------------------------------


class TestListQueueEntries:
    """Discovering entries in a queue directory."""

    def test_returns_empty_for_missing_queue(self, tmp_path: Path):
        """A non-existent queue directory returns an empty list."""
        entries = list_queue_entries("next", base_path=tmp_path)
        assert entries == []

    def test_returns_yaml_entries_in_order(self, tmp_path: Path):
        """YAML files in the queue directory are returned sorted by name."""
        omo = tmp_path / ".omo"
        qdir = omo / "next"
        qdir.mkdir(parents=True)

        (qdir / "b.yaml").write_text("feature: beta\n", encoding="utf-8")
        (qdir / "a.yaml").write_text("feature: alpha\n", encoding="utf-8")

        entries = list_queue_entries("next", base_path=omo)
        assert len(entries) == 2
        assert entries[0].filename == "a.yaml"
        assert entries[1].filename == "b.yaml"

    def test_handles_malformed_yaml(self, tmp_path: Path):
        """Malformed YAML files are included with _parse_error=True."""
        omo = tmp_path / ".omo"
        qdir = omo / "next"
        qdir.mkdir(parents=True)

        (qdir / "bad.yaml").write_text("{unclosed: [", encoding="utf-8")

        entries = list_queue_entries("next", base_path=omo)
        assert len(entries) == 1
        assert entries[0].data.get("_parse_error") is True

    def test_skips_non_yaml_files_without_front_matter(self, tmp_path: Path):
        """Files without .yaml/.yml/.md suffix are skipped."""
        omo = tmp_path / ".omo"
        qdir = omo / "next"
        qdir.mkdir(parents=True)

        (qdir / "readme.txt").write_text("hello", encoding="utf-8")
        (qdir / "data.json").write_text('{"a": 1}', encoding="utf-8")

        entries = list_queue_entries("next", base_path=omo)
        assert entries == []


# ---------------------------------------------------------------------------
# read_queue_entry
# ---------------------------------------------------------------------------


class TestReadQueueEntry:
    """Parsing individual queue entry files."""

    def test_reads_yaml_with_lifecycle(self, tmp_path: Path):
        """A YAML file with a lifecycle block is parsed correctly."""
        fpath = tmp_path / "entry.yaml"
        fpath.write_text(
            "feature: my-feature\n"
            "lifecycle:\n"
            "  status: created\n"
            "  created_at: '2026-01-01T00:00:00'\n",
            encoding="utf-8",
        )
        entry = read_queue_entry(fpath, "next")
        assert entry.data["feature"] == "my-feature"
        assert entry.lifecycle.status == "created"
        assert entry.lifecycle.created_at == "2026-01-01T00:00:00"

    def test_reads_yaml_without_lifecycle_defaults_active(self, tmp_path: Path):
        """A YAML file without a lifecycle block defaults to status='active'."""
        fpath = tmp_path / "entry.yaml"
        fpath.write_text("feature: my-feature\n", encoding="utf-8")
        entry = read_queue_entry(fpath, "next")
        assert entry.lifecycle.status == "active"
        assert entry.lifecycle.created_at != ""

    def test_reads_markdown_with_front_matter(self, tmp_path: Path):
        """A Markdown file with YAML front matter is parsed."""
        fpath = tmp_path / "entry.md"
        fpath.write_text(
            "---\n"
            "title: Bug Report\n"
            "type: bug\n"
            "severity: high\n"
            "---\n"
            "Body content here\n",
            encoding="utf-8",
        )
        entry = read_queue_entry(fpath, "issues")
        assert entry.data["title"] == "Bug Report"
        assert entry.data["type"] == "bug"

    def test_markdown_without_front_matter_returns_empty_data(self, tmp_path: Path):
        """A Markdown file without front matter returns empty data dict."""
        fpath = tmp_path / "entry.md"
        fpath.write_text("Just body content\n", encoding="utf-8")
        entry = read_queue_entry(fpath, "issues")
        assert entry.data == {}


# ---------------------------------------------------------------------------
# validate_queue_entry
# ---------------------------------------------------------------------------


class TestValidateQueueEntry:
    """Schema validation of queue entry data."""

    def test_valid_entry_returns_no_errors(self):
        """A properly structured entry returns an empty error list."""
        data = {"feature": "my-feature"}
        errors = validate_queue_entry(data, "next")
        assert errors == []

    def test_missing_required_field(self):
        """Missing a required field returns an appropriate error."""
        data = {}
        errors = validate_queue_entry(data, "next")
        assert any("'feature'" in e for e in errors)

    def test_invalid_lifecycle_status(self):
        """An invalid lifecycle status triggers a validation error."""
        data = {
            "feature": "x",
            "lifecycle": {"status": "unknown_status", "created_at": "2026-01-01"},
        }
        errors = validate_queue_entry(data, "next")
        assert any("Invalid lifecycle status" in e for e in errors)

    def test_non_dict_entry(self):
        """A non-dict entry returns an appropriate error."""
        errors = validate_queue_entry("not a dict", "next")
        assert any("dict" in e for e in errors)

    def test_nested_required_field_quality_gate(self, tmp_path: Path):
        """Nested dotted required fields are validated correctly."""
        data = {
            "meta": {
                "name": "gate-1",
                "milestone": "v1.0",
            },
            "tests": ["test_a", "test_b"],
        }
        errors = validate_queue_entry(data, "quality-gates")
        assert errors == []

    def test_nested_field_valid(self):
        """A dotted field resolves correctly."""
        data = {"meta": {"name": "gate-1", "milestone": "v1.0"}, "tests": []}
        errors = validate_queue_entry(data, "quality-gates")
        assert errors == []

    def test_strict_mode_warns_missing_version(self):
        """Strict mode warns about a missing 'version' field."""
        data = {"feature": "x"}
        errors = validate_queue_entry(data, "next", strict=True)
        assert any("'version'" in e for e in errors)

    def test_lifecycle_must_be_dict(self):
        """When lifecycle is present but not a dict, an error is returned."""
        data = {"feature": "x", "lifecycle": "not-a-dict"}
        errors = validate_queue_entry(data, "next")
        assert any("lifecycle' must be a dict" in e for e in errors)

    def test_missing_lifecycle_created_at(self):
        """When lifecycle lacks created_at, an error is returned."""
        data = {"feature": "x", "lifecycle": {"status": "created"}}
        errors = validate_queue_entry(data, "next")
        assert any("lifecycle.created_at" in e for e in errors)


# ---------------------------------------------------------------------------
# acknowledge_activation / acknowledge_consumption
# ---------------------------------------------------------------------------


class TestAcknowledgeActivation:
    """Marking a queue entry as active."""

    def test_updates_yaml_file_in_place(self, tmp_path: Path):
        """Activation updates the YAML file's lifecycle status."""
        fpath = tmp_path / "entry.yaml"
        fpath.write_text(
            "feature: my-feature\n"
            "lifecycle:\n"
            "  status: created\n"
            "  created_at: '2026-01-01T00:00:00'\n",
            encoding="utf-8",
        )
        acknowledge_activation(fpath, actor="test-worker")
        updated = yaml.safe_load(fpath.read_text(encoding="utf-8"))
        assert updated["lifecycle"]["status"] == "active"
        assert updated["lifecycle"]["actor"] == "test-worker"

    def test_updates_markdown_front_matter(self, tmp_path: Path):
        """Activation updates the lifecycle in Markdown front matter."""
        fpath = tmp_path / "entry.md"
        fpath.write_text(
            "---\n"
            "title: Bug Report\n"
            "lifecycle:\n"
            "  status: created\n"
            "  created_at: '2026-01-01T00:00:00'\n"
            "---\n"
            "Body content\n",
            encoding="utf-8",
        )
        acknowledge_activation(fpath, actor="test-worker")

        # Re-read via read_queue_entry to confirm
        entry = read_queue_entry(fpath, "issues")
        assert entry.lifecycle.status == "active"


class TestAcknowledgeConsumption:
    """Marking a queue entry as consumed."""

    def test_sets_consumed_status(self, tmp_path: Path):
        """Consumption updates the YAML file's lifecycle to consumed."""
        fpath = tmp_path / "entry.yaml"
        fpath.write_text(
            "feature: my-feature\n"
            "lifecycle:\n"
            "  status: active\n"
            "  created_at: '2026-01-01T00:00:00'\n",
            encoding="utf-8",
        )
        acknowledge_consumption(fpath, actor="test-worker")
        updated = yaml.safe_load(fpath.read_text(encoding="utf-8"))
        assert updated["lifecycle"]["status"] == "consumed"


# ---------------------------------------------------------------------------
# QueueHealthReport
# ---------------------------------------------------------------------------


class TestQueueHealthReport:
    """QueueHealthReport dataclass and serialisation."""

    def test_to_dict_includes_summary_fields(self):
        """to_dict returns expected top-level keys."""
        report = QueueHealthReport(
            queue_name="next",
            total_entries=2,
            by_status={"created": 1, "active": 1},
            stale_entries=[],
            malformed_entries=[],
        )
        d = report.to_dict()
        assert d["queue_name"] == "next"
        assert d["total_entries"] == 2
        assert d["stale_count"] == 0
        assert d["malformed_count"] == 0


# ---------------------------------------------------------------------------
# check_queue_health
# ---------------------------------------------------------------------------


class TestCheckQueueHealth:
    """Health check over queue directories."""

    def test_reports_empty_queue(self, tmp_path: Path):
        """An empty queue directory reports zero entries."""
        omo = tmp_path / ".omo"
        (omo / "next").mkdir(parents=True)
        reports = check_queue_health(base_path=omo)
        by_name = {r.queue_name: r for r in reports}
        assert by_name["next"].total_entries == 0

    def test_reports_multiple_entries(self, tmp_path: Path):
        """A queue with multiple entries reports the correct count."""
        omo = tmp_path / ".omo"
        qdir = omo / "next"
        qdir.mkdir(parents=True)

        (qdir / "a.yaml").write_text(
            "feature: alpha\n"
            "lifecycle:\n"
            "  status: created\n"
            "  created_at: '2026-01-01T00:00:00'\n",
            encoding="utf-8",
        )
        (qdir / "b.yaml").write_text(
            "feature: beta\n"
            "lifecycle:\n"
            "  status: active\n"
            "  created_at: '2026-01-02T00:00:00'\n",
            encoding="utf-8",
        )

        reports = check_queue_health(base_path=omo)
        by_name = {r.queue_name: r for r in reports}
        assert by_name["next"].total_entries == 2
        assert by_name["next"].by_status.get("created") == 1
        assert by_name["next"].by_status.get("active") == 1

    def test_flags_stale_entries(self, tmp_path: Path):
        """Entries older than their status timeout are flagged as stale."""
        omo = tmp_path / ".omo"
        qdir = omo / "next"
        qdir.mkdir(parents=True)

        # An entry created long ago — should be stale
        (qdir / "old.yaml").write_text(
            "feature: old\n"
            "lifecycle:\n"
            "  status: created\n"
            "  created_at: '2020-01-01T00:00:00'\n",
            encoding="utf-8",
        )

        reports = check_queue_health(base_path=omo)
        by_name = {r.queue_name: r for r in reports}
        assert len(by_name["next"].stale_entries) >= 1
        assert by_name["next"].stale_entries[0]["filename"] == "old.yaml"

    def test_detects_malformed_entries(self, tmp_path: Path):
        """Malformed YAML files are reported as malformed."""
        omo = tmp_path / ".omo"
        qdir = omo / "next"
        qdir.mkdir(parents=True)

        (qdir / "bad.yaml").write_text("{unclosed: [", encoding="utf-8")

        reports = check_queue_health(base_path=omo)
        by_name = {r.queue_name: r for r in reports}
        assert by_name["next"].malformed_entries == ["bad.yaml"]

    def test_checks_single_queue(self, tmp_path: Path):
        """Passing a queue_name checks only that queue."""
        omo = tmp_path / ".omo"
        (omo / "next").mkdir(parents=True)
        (omo / "ready").mkdir(parents=True)

        reports = check_queue_health(queue_name="ready", base_path=omo)
        assert len(reports) == 1
        assert reports[0].queue_name == "ready"


# ---------------------------------------------------------------------------
# Unknown queue name
# ---------------------------------------------------------------------------


class TestUnknownQueue:
    """Behaviour when an unknown queue name is used."""

    def test_list_queue_entries_raises(self):
        """list_queue_entries raises ValueError for unknown queue."""
        with pytest.raises(ValueError, match="Unknown queue"):
            list_queue_entries("nonexistent")

    def test_validate_queue_entry_unknown_queue(self):
        """validate_queue_entry on an unknown queue returns no errors."""
        errors = validate_queue_entry({"feature": "x"}, "unknown_queue")
        # Unknown queue — no required fields configured
        assert errors == []
