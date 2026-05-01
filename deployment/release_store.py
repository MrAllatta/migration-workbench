"""Durable release-event store backed by the Django ORM.

Every deploy attempt (including dry runs) is recorded as a
:class:`ReleaseEvent` in the ``deployment_releaserecord`` table.  A companion
JSONL file at *durable_log_path* provides an append-only audit trail that
survives database resets — useful during disaster-recovery scenarios where
you need to know which release was last healthy before a rollback.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import json

from deployment.models import ReleaseRecord


@dataclass(frozen=True)
class ReleaseEvent:
    """Immutable snapshot of a recorded release event.

    Returned by :func:`record_release_event` so callers always work with a
    plain Python object rather than a live ORM instance.

    Attributes:
        space: Space name from the manifest (e.g. ``"farm"``).
        environment: Target environment (``"preview"`` or ``"production"``).
        release_id: Unique string identifying this specific release attempt.
        git_sha: Short git SHA of the deployed commit.
        actor: OS username or CI actor who triggered the release.
        outcome: Free-form outcome label (e.g. ``"dry_run"``, ``"success"``,
            ``"rollback"``).
        is_healthy: ``True`` when the deploy passed the health gate.
        is_rollback: ``True`` when this event records a rollback.
        metadata: Arbitrary JSON-serialisable dict for provider-specific data.
        created_at: UTC timestamp from the database record.
    """

    space: str
    environment: str
    release_id: str
    git_sha: str
    actor: str
    outcome: str
    is_healthy: bool
    is_rollback: bool
    metadata: dict
    created_at: datetime


def record_release_event(
    *,
    space: str,
    environment: str,
    release_id: str,
    git_sha: str,
    actor: str,
    outcome: str,
    is_healthy: bool,
    is_rollback: bool = False,
    metadata: dict | None = None,
    durable_log_path: Path | None = None,
) -> ReleaseEvent:
    """Persist a release event to the database and optionally to a JSONL log.

    The database record provides queryable history; the optional *durable_log_path*
    file provides an append-only audit trail independent of the database.

    Args:
        space: Space name from the manifest.
        environment: Target environment (``"preview"`` or ``"production"``).
        release_id: Unique identifier for this deploy attempt.
        git_sha: Short git SHA of the deployed commit.
        actor: OS username or CI identity that triggered the release.
        outcome: Outcome label (e.g. ``"dry_run"``, ``"success"``).
        is_healthy: Whether the deploy passed its health gate.
        is_rollback: Whether this event records a rollback.  Defaults to
            ``False``.
        metadata: Optional dict of provider-specific or pipeline metadata.
        durable_log_path: If provided, the event is appended as a JSON line to
            this file.  Parent directories are created automatically.

    Returns:
        ReleaseEvent: Frozen dataclass reflecting the persisted database record.
    """
    item = ReleaseRecord.objects.create(
        space=space,
        environment=environment,
        release_id=release_id,
        git_sha=git_sha,
        actor=actor,
        outcome=outcome,
        is_healthy=is_healthy,
        is_rollback=is_rollback,
        metadata=metadata or {},
    )
    event = ReleaseEvent(
        space=item.space,
        environment=item.environment,
        release_id=item.release_id,
        git_sha=item.git_sha,
        actor=item.actor,
        outcome=item.outcome,
        is_healthy=item.is_healthy,
        is_rollback=item.is_rollback,
        metadata=item.metadata,
        created_at=item.created_at,
    )
    if durable_log_path:
        durable_log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(event)
        payload["created_at"] = event.created_at.isoformat()
        with durable_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True))
            handle.write("\n")
    return event


def get_last_healthy_release(space: str, environment: str) -> ReleaseRecord | None:
    """Return the most recent healthy release record for *space* and *environment*.

    Useful for rollback tooling and health dashboards that need to know the
    last known-good state.

    Args:
        space: Space name (matches ``ReleaseRecord.space``).
        environment: Environment name (``"preview"`` or ``"production"``).

    Returns:
        ReleaseRecord or None: The most recent healthy record, or ``None`` if
        no healthy release exists for this space/environment pair.
    """
    return (
        ReleaseRecord.objects.filter(space=space, environment=environment, is_healthy=True)
        .order_by("-created_at")
        .first()
    )
