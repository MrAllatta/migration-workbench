"""Filesystem queue protocol for the three-agent ecosystem.

Lifecycle states:
    created  — entry written to queue, not yet read
    active   — entry has been read, processing in progress
    consumed — entry fully processed, resolved

Each queue entry is a YAML file with a ``lifecycle`` block tracking its state.
Entries without a ``lifecycle`` block are assumed ``active`` (backward compatibility).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml

# All recognised queue directory names under .omo/
QUEUE_NAMES: list[str] = [
    "next",
    "ready",
    "exercise",
    "results",
    "issues",
    "quality-gates",
    "proposals",
]

# Human-readable labels for each queue.
QUEUE_LABELS: dict[str, str] = {
    "next": "Meta → Workbench: build or repair",
    "ready": "Workbench → Meta: feature built, gate passed",
    "exercise": "Meta → Product: integrate and validate",
    "results": "Product → Meta: smoke test results",
    "issues": "Product → Meta: structured failure reports",
    "quality-gates": "Product → Human: milestone certification",
    "proposals": "Meta → Human: squash proposals",
}

LIFECYCLE_STATUSES: list[str] = ["created", "active", "consumed"]

# Default timeouts (hours) for each lifecycle status per queue.
# Entries past timeout are flagged as stale.
DEFAULT_TIMEOUTS: dict[str, dict[str, int]] = {
    "next": {"created": 72, "active": 168},
    "ready": {"created": 72, "active": 168},
    "exercise": {"created": 72, "active": 168},
    "results": {"created": 168, "active": 336},
    "issues": {"created": 336, "active": 672},
    "quality-gates": {"created": 336, "active": 672},
    "proposals": {"created": 72, "active": 168},
}

# Required fields per queue (in addition to lifecycle).
QUEUE_REQUIRED_FIELDS: dict[str, list[str]] = {
    "next": ["feature"],
    "ready": ["feature"],
    "exercise": ["feature"],
    "results": ["feature", "result"],
    "issues": ["title", "type", "severity"],
    "quality-gates": ["meta.name", "meta.milestone", "tests"],
    "proposals": ["milestone"],
}

# Maximum directory depth to search for .omo/ root.
_MAX_OMO_DEPTH: int = 10


@dataclass
class Lifecycle:
    """Lifecycle state of a queue entry."""

    status: str = "created"
    created_at: str = ""
    activated_at: str | None = None
    consumed_at: str | None = None
    actor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize lifecycle to a dict (omitting ``None`` optional fields)."""
        result: dict[str, Any] = {
            "status": self.status,
            "created_at": self.created_at or _now_iso(),
        }
        if self.activated_at:
            result["activated_at"] = self.activated_at
        if self.consumed_at:
            result["consumed_at"] = self.consumed_at
        if self.actor:
            result["actor"] = self.actor
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Lifecycle:
        """Deserialize a lifecycle dict, falling back to active default."""
        if not data:
            return cls(status="active", created_at=_now_iso())
        return cls(
            status=data.get("status", "active"),
            created_at=data.get("created_at", ""),
            activated_at=data.get("activated_at"),
            consumed_at=data.get("consumed_at"),
            actor=data.get("actor"),
        )


@dataclass
class QueueEntry:
    """A single queue entry with its lifecycle and content."""

    path: Path
    queue_name: str
    filename: str
    lifecycle: Lifecycle
    data: dict[str, Any]

    @property
    def age_hours(self) -> float:
        """Return hours since this entry was created (0 for missing timestamps)."""
        if not self.lifecycle.created_at:
            return 0.0
        try:
            created = datetime.fromisoformat(self.lifecycle.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return (now - created).total_seconds() / 3600
        except (ValueError, TypeError):
            return 0.0


def _now_iso() -> str:
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def find_omo_root(start_path: Path | None = None) -> Path:
    """Walk up from *start_path* (default: cwd) to find the .omo/ directory."""
    candidate = start_path or Path.cwd()
    for _ in range(_MAX_OMO_DEPTH):
        omo = candidate / ".omo"
        if omo.is_dir():
            return omo
        candidate = candidate.parent
    raise FileNotFoundError(
        "No .omo/ directory found. Run from a workbench or product repo root."
    )


def list_queue_entries(
    queue_name: str,
    base_path: Path | None = None,
) -> list[QueueEntry]:
    """Return all entries in *queue_name*, ordered by filename."""
    if queue_name not in QUEUE_NAMES:
        raise ValueError(
            f"Unknown queue '{queue_name}'. Choose from: {', '.join(QUEUE_NAMES)}"
        )
    if base_path is None:
        base_path = find_omo_root()
    queue_dir = base_path / queue_name
    if not queue_dir.is_dir():
        return []

    entries: list[QueueEntry] = []
    for fpath in sorted(queue_dir.iterdir()):
        if not fpath.is_file() or fpath.suffix not in (".yaml", ".yml", ".md"):
            continue
        try:
            entry = read_queue_entry(fpath, queue_name)
            entries.append(entry)
        except (yaml.YAMLError, ValueError, OSError):
            entries.append(
                QueueEntry(
                    path=fpath,
                    queue_name=queue_name,
                    filename=fpath.name,
                    lifecycle=Lifecycle(status="unknown", created_at=_now_iso()),
                    data={"_parse_error": True},
                )
            )
    return entries


def read_queue_entry(fpath: Path, queue_name: str) -> QueueEntry:
    """Read and parse a single queue entry file."""
    raw = fpath.read_text(encoding="utf-8")

    if fpath.suffix == ".md":
        data = _parse_markdown_front_matter(raw)
    else:
        data = yaml.safe_load(raw) or {}

    if not isinstance(data, dict):
        data = {}

    lifecycle_data = data.pop("lifecycle", None) if isinstance(data, dict) else None
    lifecycle = Lifecycle.from_dict(lifecycle_data)

    return QueueEntry(
        path=fpath,
        queue_name=queue_name,
        filename=fpath.name,
        lifecycle=lifecycle,
        data=data,
    )


def _parse_markdown_front_matter(raw: str) -> dict[str, Any]:
    """Extract YAML front matter from a Markdown file."""
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end_idx = None
    for line_index in range(1, len(lines)):
        if lines[line_index].strip() == "---":
            end_idx = line_index
    if end_idx is None:
        return {}
    front = "\n".join(lines[1:end_idx])
    return yaml.safe_load(front) or {}


def _get_nested_value(data: dict[str, Any], dotted_key: str) -> Any:
    """Access a nested dict value using dot-separated keys (e.g. 'meta.name')."""
    parts = dotted_key.split(".")
    current: Any = data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def validate_queue_entry(
    data: dict[str, Any],
    queue_name: str,
    strict: bool = False,
) -> list[str]:
    """Validate a queue entry against the schema for *queue_name*.

    Returns a list of validation error messages. Empty list means valid.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return [f"Entry must be a dict, got {type(data).__name__}"]

    required = QUEUE_REQUIRED_FIELDS.get(queue_name, [])
    for entry_field in required:
        value = _get_nested_value(data, entry_field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"Missing required field: '{entry_field}'")

    lifecycle = data.get("lifecycle")
    if lifecycle is not None:
        if not isinstance(lifecycle, dict):
            errors.append("'lifecycle' must be a dict")
        else:
            lc_status = lifecycle.get("status", "created")
            if lc_status not in LIFECYCLE_STATUSES:
                errors.append(
                    f"Invalid lifecycle status '{lc_status}'. "
                    f"Must be one of: {', '.join(LIFECYCLE_STATUSES)}"
                )
            if "created_at" not in lifecycle:
                errors.append("Missing 'lifecycle.created_at'")

    if strict and "version" not in data:
        errors.append("Missing recommended field: 'version'")

    return errors


def acknowledge_activation(path: Path, actor: str = "agent") -> None:
    """Mark a queue entry as active (being processed)."""
    _update_lifecycle_in_file(path, "active", actor)


def acknowledge_consumption(path: Path, actor: str = "agent") -> None:
    """Mark a queue entry as consumed (fully processed)."""
    _update_lifecycle_in_file(path, "consumed", actor)


def _update_lifecycle_in_file(path: Path, new_status: str, actor: str) -> None:
    """Read a queue entry file, update its lifecycle block, and write back."""
    now = _now_iso()
    raw = path.read_text(encoding="utf-8")

    # Step 1: Parse — branch on format
    if path.suffix == ".md":
        data = _parse_markdown_front_matter(raw)
    else:
        data = yaml.safe_load(raw) or {}

    if not isinstance(data, dict):
        import logging

        logging.getLogger(__name__).warning(
            f"Cannot update lifecycle in {path}: content is not a dict"
        )
        return

    # Step 2: Update lifecycle in memory (shared logic)
    lifecycle = Lifecycle.from_dict(data.get("lifecycle"))
    lifecycle.status = new_status
    lifecycle.actor = actor
    if new_status == "active":
        lifecycle.activated_at = now
    elif new_status == "consumed":
        lifecycle.consumed_at = now
    data["lifecycle"] = lifecycle.to_dict()

    # Step 3: Serialize — branch on format
    if path.suffix == ".md":
        _write_markdown_front_matter(path, raw, data)
    else:
        path.write_text(
            yaml.dump(
                data, default_flow_style=False, sort_keys=False, allow_unicode=True
            ),
            encoding="utf-8",
        )


def _write_markdown_front_matter(
    path: Path, original_raw: str, front_matter: dict[str, Any]
) -> None:
    """Replace YAML front matter in a Markdown file while preserving body content."""
    import logging

    logger = logging.getLogger(__name__)

    lines = original_raw.splitlines()
    if not lines or lines[0].strip() != "---":
        logger.warning(f"Cannot write front matter to {path}: no front matter found")
        return
    end_idx = None
    for line_index in range(1, len(lines)):
        if lines[line_index].strip() == "---":
            end_idx = line_index
            break
    if end_idx is None:
        logger.warning(f"Cannot write front matter to {path}: no closing --- found")
        return
    body = "\n".join(lines[end_idx + 1 :])
    new_front = yaml.dump(
        front_matter, default_flow_style=False, sort_keys=False, allow_unicode=True
    ).strip()
    path.write_text(f"---\n{new_front}\n---\n{body}", encoding="utf-8")


@dataclass
class QueueHealthReport:
    """Health report for a single queue."""

    queue_name: str
    total_entries: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    oldest_unconsumed_hours: float | None = None
    oldest_unconsumed_name: str | None = None
    stale_entries: list[dict[str, Any]] = field(default_factory=list)
    malformed_entries: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the health report to a dict for JSON output."""
        return {
            "queue_name": self.queue_name,
            "total_entries": self.total_entries,
            "by_status": self.by_status,
            "oldest_unconsumed_hours": (
                round(self.oldest_unconsumed_hours, 1)
                if self.oldest_unconsumed_hours is not None
                else None
            ),
            "oldest_unconsumed_name": self.oldest_unconsumed_name,
            "stale_count": len(self.stale_entries),
            "stale_entries": [
                {k: v for k, v in e.items() if k != "entry"} for e in self.stale_entries
            ],
            "malformed_count": len(self.malformed_entries),
            "malformed_entries": self.malformed_entries,
        }


def check_queue_health(
    queue_name: str | None = None,
    base_path: Path | None = None,
) -> list[QueueHealthReport]:
    """Check health of one or all queues."""
    if base_path is None:
        base_path = find_omo_root()

    queues_to_check = [queue_name] if queue_name else QUEUE_NAMES
    reports: list[QueueHealthReport] = []

    for qname in queues_to_check:
        report = QueueHealthReport(queue_name=qname)
        entries = list_queue_entries(qname, base_path)

        status_counts: dict[str, int] = {}
        oldest_age = -1.0
        oldest_name = None
        malformed: list[str] = []
        stale: list[dict[str, Any]] = []

        for entry in entries:
            if entry.data.get("_parse_error"):
                malformed.append(entry.filename)
                continue

            status = entry.lifecycle.status
            status_counts[status] = status_counts.get(status, 0) + 1

            if status in ("created", "active"):
                age = entry.age_hours
                if age > oldest_age:
                    oldest_age = age
                    oldest_name = entry.filename

                timeouts = DEFAULT_TIMEOUTS.get(qname, {})
                timeout_hours = timeouts.get(status, 168)
                if age > timeout_hours:
                    stale.append(
                        {
                            "filename": entry.filename,
                            "status": status,
                            "age_hours": round(age, 1),
                            "timeout_hours": timeout_hours,
                        }
                    )

        report.total_entries = len(entries)
        report.by_status = status_counts
        if oldest_age > 0:
            report.oldest_unconsumed_hours = oldest_age
            report.oldest_unconsumed_name = oldest_name
        report.stale_entries = stale
        report.malformed_entries = malformed

        if qname == "results":
            report.validation_errors = _check_results_consistency(entries, base_path)

        reports.append(report)

    return reports


def _check_results_consistency(
    results_entries: list[QueueEntry],
    base_path: Path,
) -> list[str]:
    """Check that every results entry has a matching exercise signal."""
    errors: list[str] = []
    exercise_dir = base_path / "exercise"
    if not exercise_dir.is_dir():
        return errors

    exercise_names: set[str] = set()
    for exercise_file in exercise_dir.iterdir():
        if exercise_file.suffix in (".yaml", ".yml"):
            try:
                data = yaml.safe_load(exercise_file.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict) and data.get("feature"):
                    exercise_names.add(str(data["feature"]))
            except (yaml.YAMLError, OSError):
                pass

    for entry in results_entries:
        feature = entry.data.get("feature")
        if feature and str(feature) not in exercise_names:
            errors.append(
                f"Results entry '{entry.filename}' references feature '{feature}' "
                f"but no matching exercise signal found"
            )

    return errors
