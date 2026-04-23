import json
from datetime import datetime, timezone

from importer.summary import build_summary_payload


class DummyCommand:
    validate_only = False
    dry_run = False
    atomic_apply = True
    verbose = False
    run_started_at = datetime.now(timezone.utc)
    run_id = "run-1"
    data_dir = "/tmp/in"
    row_errors = []
    stats = {"Example": {"created": 1, "updated": 2, "skipped": 0, "error": 0}}


def test_summary_payload_schema_version():
    payload = build_summary_payload(DummyCommand(), status="ok", fatal_error=None)
    assert payload["schema_version"] == "1.0"
    json.dumps(payload)
