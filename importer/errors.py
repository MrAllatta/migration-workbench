FAILURE_SIGNATURE_OWNERSHIP = {
    "missing_required": {
        "owner_area": "data-contracts",
        "owner_team": "import-pipeline",
        "severity": "medium",
        "escalation_path": "ops-oncall -> data-contracts",
        "recovery": "populate required source fields and rerun --validate-only",
    },
    "namespace_mismatch": {
        "owner_area": "data-contracts",
        "owner_team": "import-pipeline",
        "severity": "medium",
        "escalation_path": "ops-oncall -> data-contracts",
        "recovery": "correct source value namespaces and rerun --validate-only",
    },
    "stale_fk": {
        "owner_area": "reference-data",
        "owner_team": "import-pipeline",
        "severity": "high",
        "escalation_path": "ops-oncall -> reference-data",
        "recovery": "seed missing reference rows and rerun --validate-only",
    },
    "fatal_import_exception": {
        "owner_area": "import-runtime",
        "owner_team": "platform",
        "severity": "high",
        "escalation_path": "ops-oncall -> platform",
        "recovery": "review fatal_error and importer logs before retry",
    },
    "unknown": {
        "owner_area": "triage",
        "owner_team": "platform",
        "severity": "high",
        "escalation_path": "ops-oncall -> platform",
        "recovery": "classify signature and add ownership mapping",
    },
}
