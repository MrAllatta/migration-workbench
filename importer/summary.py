import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from importer.errors import FAILURE_SIGNATURE_OWNERSHIP


def normalized_outcomes(model_stats, write_disabled=False):
    created = model_stats.get("created", 0)
    skipped = model_stats.get("skipped", 0)
    error = model_stats.get("error", 0) + model_stats.get("errors", 0)
    updated = model_stats.get("updated", 0) + model_stats.get("processed", 0)
    if write_disabled:
        skipped += created + updated
        created = 0
        updated = 0
    return {"created": created, "updated": updated, "skipped": skipped, "error": error}


def build_failure_signatures(row_errors, status, fatal_error):
    signature_counts = defaultdict(int)
    signature_examples = {}
    for item in row_errors:
        signature = item.get("code") or "unknown"
        signature_counts[signature] += 1
        signature_examples.setdefault(
            signature,
            {
                "model": item.get("model"),
                "field_path": item.get("field_path"),
                "message": item.get("message"),
            },
        )

    if status == "failed" and fatal_error:
        signature_counts["fatal_import_exception"] += 1
        signature_examples.setdefault(
            "fatal_import_exception",
            {"model": "ImportRun", "field_path": "run", "message": str(fatal_error)},
        )

    signatures = []
    for signature in sorted(signature_counts.keys()):
        ownership = FAILURE_SIGNATURE_OWNERSHIP.get(signature, FAILURE_SIGNATURE_OWNERSHIP["unknown"])
        signatures.append(
            {
                "signature": signature,
                "count": signature_counts[signature],
                "owner_area": ownership["owner_area"],
                "owner_team": ownership["owner_team"],
                "severity": ownership["severity"],
                "escalation_path": ownership["escalation_path"],
                "recovery": ownership["recovery"],
                "example": signature_examples[signature],
            }
        )
    return signatures


def build_escalation_summary(failure_signatures):
    grouped = {}
    for item in failure_signatures:
        key = (
            item["owner_area"],
            item["owner_team"],
            item["severity"],
            item["escalation_path"],
        )
        if key not in grouped:
            grouped[key] = {
                "owner_area": item["owner_area"],
                "owner_team": item["owner_team"],
                "severity": item["severity"],
                "escalation_path": item["escalation_path"],
                "count": 0,
                "signatures": [],
                "recovery_steps": [],
            }
        grouped[key]["count"] += item["count"]
        grouped[key]["signatures"].append(item["signature"])
        grouped[key]["recovery_steps"].append(item["recovery"])
    rows = sorted(grouped.values(), key=lambda row: (row["severity"], row["owner_area"]))
    for row in rows:
        row["signatures"].sort()
        row["recovery_steps"] = sorted(set(row["recovery_steps"]))
    return rows


def build_summary_payload(command, status="ok", fatal_error=None):
    per_model = {}
    totals = {"created": 0, "updated": 0, "skipped": 0, "error": 0}
    for model_name in sorted(command.stats.keys()):
        normalized = normalized_outcomes(
            command.stats[model_name], write_disabled=(command.validate_only or command.dry_run)
        )
        per_model[model_name] = normalized
        for key in totals:
            totals[key] += normalized[key]

    failure_signatures = build_failure_signatures(command.row_errors, status, fatal_error)
    return {
        "schema_version": "1.0",
        "status": status,
        "fatal_error": fatal_error,
        "run": {
            "started_at": command.run_started_at.isoformat() + "Z",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "run_id": command.run_id,
            "data_dir": command.data_dir,
            "validate_only": command.validate_only,
            "dry_run": command.dry_run,
            "atomic_apply": command.atomic_apply,
            "verbose": command.verbose,
        },
        "results": {
            "models": per_model,
            "totals": totals,
            "row_errors": command.row_errors,
            "failure_signatures": failure_signatures,
            "escalation_summary": build_escalation_summary(failure_signatures),
        },
    }


def write_summary_json(command, status="ok", fatal_error=None):
    payload = build_summary_payload(command, status=status, fatal_error=fatal_error)
    output_dir = os.path.dirname(os.path.abspath(command.summary_json_path))
    try:
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(command.summary_json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
    except OSError:
        fallback_path = (
            Path(command.data_dir) / "_import_artifacts" / f"import-summary-{command.run_id}.json"
        )
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        with open(fallback_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        command.summary_json_path = str(fallback_path)
