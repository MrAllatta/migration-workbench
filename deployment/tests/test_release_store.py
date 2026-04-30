from pathlib import Path

import pytest

from deployment.release_store import get_last_healthy_release, record_release_event


@pytest.mark.django_db
def test_record_release_event_persists_and_appends_log(tmp_path: Path):
    log_path = tmp_path / "events.jsonl"
    event = record_release_event(
        space="farm",
        environment="preview",
        release_id="dryrun-abc123",
        git_sha="deadbeef",
        actor="tester",
        outcome="dry_run",
        is_healthy=True,
        durable_log_path=log_path,
    )

    assert event.release_id == "dryrun-abc123"
    assert log_path.exists()
    assert "dryrun-abc123" in log_path.read_text(encoding="utf-8")


@pytest.mark.django_db
def test_get_last_healthy_release_returns_latest():
    record_release_event(
        space="farm",
        environment="production",
        release_id="r1",
        git_sha="aaaaaaa",
        actor="tester",
        outcome="failed",
        is_healthy=False,
    )
    record_release_event(
        space="farm",
        environment="production",
        release_id="r2",
        git_sha="bbbbbbb",
        actor="tester",
        outcome="success",
        is_healthy=True,
    )

    latest = get_last_healthy_release("farm", "production")
    assert latest is not None
    assert latest.release_id == "r2"
