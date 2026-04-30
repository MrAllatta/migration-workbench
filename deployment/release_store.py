from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import json

from deployment.models import ReleaseRecord


@dataclass(frozen=True)
class ReleaseEvent:
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
    return (
        ReleaseRecord.objects.filter(space=space, environment=environment, is_healthy=True)
        .order_by("-created_at")
        .first()
    )
