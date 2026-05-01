"""Build and persist the import-run summary artifact.

The summary JSON (schema version ``"1.0"``) is written to
``data_dir/_import_artifacts/import-summary-<run_id>.json`` by default, or to
the path supplied via ``--summary-json``.  On ``OSError`` it falls back to the
default artifact dir so a malformed custom path never silently swallows the
summary.

Downstream tooling (CI, dashboards) should key on the top-level ``status``
field (``"ok"`` or ``"failed"``) and ``results.totals``.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from importer.errors import FAILURE_SIGNATURE_OWNERSHIP


def normalized_outcomes(model_stats, write_disabled=False):
    """Collapse raw stat counters into canonical ``{created, updated, skipped, error}`` keys.

    Some import tiers use legacy key names (``"processed"`` instead of
    ``"updated"``, ``"errors"`` instead of ``"error"``); this function merges
    them so the summary is consistent regardless of which keys each tier wrote.

    When *write_disabled* is ``True`` (dry-run or validate-only), any rows that
    *would* have been created or updated are reclassified as skipped to make
    the summary accurately reflect what actually happened to the database.

    Args:
        model_stats: Raw stats dict for a single model from
            :attr:`~importer.chassis.ImporterChassisMixin.stats`.
        write_disabled: ``True`` when the run was dry-run or validate-only.

    Returns:
        dict: Normalised outcome dict with keys
        ``created``, ``updated``, ``skipped``, ``error``.
    """
    created = model_stats.get("created", 0)
    skipped = model_stats.get("skipped", 0)
    error = model_stats.get("error", 0) + model_stats.get("errors", 0)
    updated = model_stats.get("updated", 0) + model_stats.get("processed", 0)
    if write_disabled:
        # Reclassify to make the report honest about DB state.
        skipped += created + updated
        created = 0
        updated = 0
    return {"created": created, "updated": updated, "skipped": skipped, "error": error}


def build_failure_signatures(row_errors, status, fatal_error):
    """Aggregate per-row errors into deduplicated failure-signature buckets.

    Each bucket includes ownership metadata from
    :data:`~importer.errors.FAILURE_SIGNATURE_OWNERSHIP` so that ops teams
    can route failures without reading raw error logs.  A synthetic
    ``"fatal_import_exception"`` signature is injected when *status* is
    ``"failed"`` and *fatal_error* is set.

    Args:
        row_errors: List of error dicts from
            :meth:`~importer.chassis.ImporterChassisMixin.record_row_error`.
        status: Run status string (``"ok"`` or ``"failed"``).
        fatal_error: Fatal error message string, or ``None``.

    Returns:
        list[dict]: Sorted list of signature dicts, each with keys
        ``signature``, ``count``, ``owner_area``, ``owner_team``,
        ``severity``, ``escalation_path``, ``recovery``, ``example``.
    """
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
    """Group failure signatures by (owner_area, owner_team, severity, escalation_path).

    Produces one summary row per unique routing key so ops teams see a single
    count and combined recovery steps rather than one row per error code.

    Args:
        failure_signatures: Output of :func:`build_failure_signatures`.

    Returns:
        list[dict]: Rows sorted by ``(severity, owner_area)``, each with keys
        ``owner_area``, ``owner_team``, ``severity``, ``escalation_path``,
        ``count``, ``signatures``, ``recovery_steps``.
    """
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
    """Construct the full summary dict ready for JSON serialisation.

    Args:
        command: The running :class:`~importer.base.BaseImportCommand` instance
            (provides ``stats``, ``row_errors``, ``run_started_at``, ``run_id``,
            ``data_dir``, ``validate_only``, ``dry_run``, ``atomic_apply``,
            ``verbose``).
        status: Top-level run status; ``"ok"`` or ``"failed"``.
        fatal_error: Fatal exception message string, or ``None``.

    Returns:
        dict: Summary payload conforming to schema version ``"1.0"``.
    """
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
    """Serialise the run summary to ``command.summary_json_path``.

    Creates parent directories as needed.  On ``OSError`` (e.g. a
    non-writable custom path), falls back to the default artifact directory
    inside ``data_dir/_import_artifacts/`` and updates
    ``command.summary_json_path`` to reflect the actual location.

    Args:
        command: The running :class:`~importer.base.BaseImportCommand` instance.
        status: Run outcome; ``"ok"`` or ``"failed"``.
        fatal_error: Fatal exception message string, or ``None``.
    """
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
