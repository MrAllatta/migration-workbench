#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"

if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
fi

RUNNER_MODE="${RUNNER_MODE:-local}"
IMPORT_ACTION="${1:-}"

usage() {
    cat <<'EOF'
Usage:
  scripts/run_import.sh <action>

Actions:
  import_preflight    Run importer in validate-only mode.
  import_apply        Run importer in apply mode.
  pull_bundle         Pull normalized bundle from provider tabs.
  pull_preflight      Pull bundle then run importer validate-only.
  pull_apply          Pull bundle then run importer apply.
  snapshot_bundle     Build bundle from local CSV snapshots.

Key env vars:
  RUNNER_MODE=local|cloud             (default: local)
  IMPORT_DATA_DIR=/abs/or/rel/path    (default: example_data)
  BUNDLE_OUTPUT_DIR=/abs/or/rel/path  (default: bundle_out)
  SOURCE_CONFIG=/path/to/config.json  (required for pull_* and snapshot_bundle)
  IMPORT_SUMMARY_JSON=/path.json      (optional)
  IMPORT_COMMAND=import_reference_example (default demo importer command)

Cloud mode env vars:
  PROJECT_ID=<gcp-project-id>         (required in cloud mode)
  REGION=<gcp-region>                 (default: us-central1)
  CLOUD_RUN_IMPORT_PREFLIGHT_JOB=<name> (default: migration-workbench-preflight)
  CLOUD_RUN_IMPORT_APPLY_JOB=<name>     (default: migration-workbench-apply)
  CLOUD_RUN_PULL_BUNDLE_JOB=<name>      (default: migration-workbench-pull-bundle)
EOF
}

if [[ -z "${IMPORT_ACTION}" ]]; then
    usage
    exit 1
fi

IMPORT_DATA_DIR="${IMPORT_DATA_DIR:-example_data}"
IMPORT_SUMMARY_JSON="${IMPORT_SUMMARY_JSON:-}"
SOURCE_CONFIG="${SOURCE_CONFIG:-}"
BUNDLE_OUTPUT_DIR="${BUNDLE_OUTPUT_DIR:-bundle_out}"
IMPORT_COMMAND="${IMPORT_COMMAND:-import_reference_example}"
DEFAULT_PYTHON="python3"
if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    DEFAULT_PYTHON="${REPO_ROOT}/.venv/bin/python"
fi
MANAGE_PY="${MANAGE_PY:-${DEFAULT_PYTHON} ${REPO_ROOT}/manage.py}"

run_import_command() {
    local data_dir="${1}"
    local validate_flag="${2:-}"
    if [[ -n "${IMPORT_SUMMARY_JSON}" ]]; then
        ${MANAGE_PY} "${IMPORT_COMMAND}" "${data_dir}" ${validate_flag} --summary-json "${IMPORT_SUMMARY_JSON}"
    else
        ${MANAGE_PY} "${IMPORT_COMMAND}" "${data_dir}" ${validate_flag}
    fi
}

run_local() {
    case "${IMPORT_ACTION}" in
        import_preflight)
            run_import_command "${IMPORT_DATA_DIR}" "--validate-only"
            ;;
        import_apply)
            run_import_command "${IMPORT_DATA_DIR}"
            ;;
        pull_bundle)
            if [[ -z "${SOURCE_CONFIG}" ]]; then
                echo "SOURCE_CONFIG is required for pull_bundle in local mode."
                exit 1
            fi
            ${MANAGE_PY} pull_bundle --config "${SOURCE_CONFIG}" --output-dir "${BUNDLE_OUTPUT_DIR}"
            ;;
        snapshot_bundle)
            if [[ -z "${SOURCE_CONFIG}" ]]; then
                echo "SOURCE_CONFIG is required for snapshot_bundle in local mode."
                exit 1
            fi
            ${MANAGE_PY} snapshot_bundle --config "${SOURCE_CONFIG}" --output-dir "${BUNDLE_OUTPUT_DIR}"
            ;;
        pull_preflight)
            if [[ -z "${SOURCE_CONFIG}" ]]; then
                echo "SOURCE_CONFIG is required for pull_preflight in local mode."
                exit 1
            fi
            ${MANAGE_PY} pull_bundle --config "${SOURCE_CONFIG}" --output-dir "${BUNDLE_OUTPUT_DIR}"
            run_import_command "${BUNDLE_OUTPUT_DIR}" "--validate-only"
            ;;
        pull_apply)
            if [[ -z "${SOURCE_CONFIG}" ]]; then
                echo "SOURCE_CONFIG is required for pull_apply in local mode."
                exit 1
            fi
            ${MANAGE_PY} pull_bundle --config "${SOURCE_CONFIG}" --output-dir "${BUNDLE_OUTPUT_DIR}"
            run_import_command "${BUNDLE_OUTPUT_DIR}"
            ;;
        *)
            echo "Unknown action: ${IMPORT_ACTION}"
            usage
            exit 1
            ;;
    esac
}

run_cloud() {
    PROJECT_ID="${PROJECT_ID:-}"
    REGION="${REGION:-us-central1}"

    if [[ -z "${PROJECT_ID}" ]]; then
        echo "PROJECT_ID is required when RUNNER_MODE=cloud."
        exit 1
    fi

    local job_name
    case "${IMPORT_ACTION}" in
        import_preflight)
            job_name="${CLOUD_RUN_IMPORT_PREFLIGHT_JOB:-migration-workbench-preflight}"
            ;;
        import_apply)
            job_name="${CLOUD_RUN_IMPORT_APPLY_JOB:-migration-workbench-apply}"
            ;;
        pull_bundle|pull_preflight|pull_apply)
            job_name="${CLOUD_RUN_PULL_BUNDLE_JOB:-migration-workbench-pull-bundle}"
            ;;
        *)
            echo "Unknown action: ${IMPORT_ACTION}"
            usage
            exit 1
            ;;
    esac

    gcloud run jobs execute "${job_name}" \
        --project "${PROJECT_ID}" \
        --region "${REGION}" \
        --wait
}

if [[ "${RUNNER_MODE}" == "local" ]]; then
    run_local
elif [[ "${RUNNER_MODE}" == "cloud" ]]; then
    run_cloud
else
    echo "Invalid RUNNER_MODE: ${RUNNER_MODE} (expected local|cloud)"
    exit 1
fi
