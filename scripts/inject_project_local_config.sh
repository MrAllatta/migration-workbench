#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  # Google Sheets
  scripts/inject_project_local_config.sh \
    --provider google_sheets \
    --project-dir /path/to/project \
    --workbench-path /path/to/migration-workbench \
    --drive-folder-id "..." \
    --drive-folder-name "..." \
    --google-impersonate-service-account "service-account@project.iam.gserviceaccount.com"

  # Coda
  scripts/inject_project_local_config.sh \
    --provider coda \
    --project-dir /path/to/project \
    --workbench-path /path/to/migration-workbench \
    --coda-api-token "bearer-token" \
    --coda-doc-ids "docId1,docId2"

Updates:
  - For google_sheets:
      config/cohort_corpus.json: folder_name (non-secret heuristics)
      .env: WORKBENCH, GOOGLE_IMPERSONATE_SERVICE_ACCOUNT, DRIVE_FOLDER_ID
  - For coda:
      .env: WORKBENCH, CODA_API_TOKEN, CODA_DOC_IDS

Optional:
  --force                  Overwrite existing values even if they differ.
  --coda-corpus-out-dir    Set CODA_CORPUS_OUT_DIR (default: build/coda_corpus)

Notes:
  - Existing values are replaced in place.
  - If .env does not exist, the script copies .env.example first.
  - If any required env key is missing in .env, it is appended.
EOF
}

provider=""
project_dir=""
workbench_path=""
force=false

# Google Sheets specific
drive_folder_id=""
drive_folder_name=""
google_impersonate_service_account=""

# Coda specific
coda_api_token=""
coda_doc_ids=""
coda_corpus_out_dir=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider)
      provider="${2:-}"
      shift 2
      ;;
    --project-dir)
      project_dir="${2:-}"
      shift 2
      ;;
    --workbench-path)
      workbench_path="${2:-}"
      shift 2
      ;;
    --drive-folder-id)
      drive_folder_id="${2:-}"
      shift 2
      ;;
    --drive-folder-name)
      drive_folder_name="${2:-}"
      shift 2
      ;;
    --google-impersonate-service-account)
      google_impersonate_service_account="${2:-}"
      shift 2
      ;;
    --coda-api-token)
      coda_api_token="${2:-}"
      shift 2
      ;;
    --coda-doc-ids)
      coda_doc_ids="${2:-}"
      shift 2
      ;;
    --coda-corpus-out-dir)
      coda_corpus_out_dir="${2:-}"
      shift 2
      ;;
    --force)
      force=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

# Validate provider
if [[ "$provider" != "google_sheets" && "$provider" != "coda" ]]; then
  echo "Error: --provider must be 'google_sheets' or 'coda'." >&2
  usage
  exit 1
fi

# Validate common required args
if [[ -z "$project_dir" || -z "$workbench_path" ]]; then
  echo "Error: --project-dir and --workbench-path are required." >&2
  usage
  exit 1
fi

# Validate provider-specific required args
if [[ "$provider" == "google_sheets" ]]; then
  if [[ -z "$drive_folder_id" || -z "$drive_folder_name" || -z "$google_impersonate_service_account" ]]; then
    echo "Error: google_sheets provider requires --drive-folder-id, --drive-folder-name, and --google-impersonate-service-account." >&2
    usage
    exit 1
  fi
elif [[ "$provider" == "coda" ]]; then
  if [[ -z "$coda_api_token" || -z "$coda_doc_ids" ]]; then
    echo "Error: coda provider requires --coda-api-token and --coda-doc-ids." >&2
    usage
    exit 1
  fi
fi

project_dir="${project_dir%/}"
env_path="$project_dir/.env"
env_example_path="$project_dir/.env.example"

if [[ ! -f "$env_path" ]]; then
  if [[ ! -f "$env_example_path" ]]; then
    echo "Error: env file not found: $env_path" >&2
    echo "Error: cannot bootstrap .env because .env.example is missing: $env_example_path" >&2
    exit 1
  fi

  cp "$env_example_path" "$env_path"
  echo "Created $env_path from $env_example_path"
fi

# --- Provider-specific config file updates ---
if [[ "$provider" == "google_sheets" ]]; then
  config_path="$project_dir/config/cohort_corpus.json"
  if [[ ! -f "$config_path" ]]; then
    echo "Error: config file not found: $config_path" >&2
    exit 1
  fi

  python3 - "$config_path" "$drive_folder_name" <<'PYTHON'
import json
import pathlib
import sys

config_path = pathlib.Path(sys.argv[1])
drive_folder_name = sys.argv[2]

config_payload = json.loads(config_path.read_text())
config_payload["folder_name"] = drive_folder_name

config_path.write_text(json.dumps(config_payload, indent=2) + "\n")
PYTHON

  echo "Updated $config_path (folder_name)"
fi

# --- .env updates ---
python3 - "$env_path" "$workbench_path" "$force" "$provider" \
  "$google_impersonate_service_account" "$drive_folder_id" \
  "$coda_api_token" "$coda_doc_ids" "$coda_corpus_out_dir" <<'PYTHON'
import pathlib
import re
import sys

env_path = pathlib.Path(sys.argv[1])
workbench_path = sys.argv[2]
force = sys.argv[3] == "true"
provider = sys.argv[4]
google_impersonate_service_account = sys.argv[5]
drive_folder_id = sys.argv[6]
coda_api_token = sys.argv[7]
coda_doc_ids = sys.argv[8]
coda_corpus_out_dir = sys.argv[9]

env_text = env_path.read_text()
final_text = env_text

def replace_or_append(existing_text: str, env_key: str, env_value: str) -> str:
    if not env_value:
        return existing_text
    env_line = f"{env_key}={env_value}"
    env_pattern = re.compile(rf"^{re.escape(env_key)}=.*$", re.MULTILINE)

    if env_pattern.search(existing_text):
        return env_pattern.sub(env_line, existing_text)

    if existing_text and not existing_text.endswith("\n"):
        return existing_text + "\n" + env_line + "\n"

    return existing_text + env_line + "\n"

final_text = replace_or_append(final_text, "WORKBENCH", workbench_path)

if provider == "google_sheets":
    final_text = replace_or_append(
        final_text,
        "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT",
        google_impersonate_service_account,
    )
    final_text = replace_or_append(final_text, "DRIVE_FOLDER_ID", drive_folder_id)
elif provider == "coda":
    final_text = replace_or_append(final_text, "CODA_API_TOKEN", coda_api_token)
    final_text = replace_or_append(final_text, "CODA_DOC_IDS", coda_doc_ids)
    if coda_corpus_out_dir:
        final_text = replace_or_append(final_text, "CODA_CORPUS_OUT_DIR", coda_corpus_out_dir)

env_path.write_text(final_text)
PYTHON

# --- Summary ---
echo ""
echo "Updated $env_path:"
if [[ "$provider" == "google_sheets" ]]; then
  echo "  - WORKBENCH"
  echo "  - GOOGLE_IMPERSONATE_SERVICE_ACCOUNT"
  echo "  - DRIVE_FOLDER_ID"
elif [[ "$provider" == "coda" ]]; then
  echo "  - WORKBENCH"
  echo "  - CODA_API_TOKEN"
  echo "  - CODA_DOC_IDS"
  if [[ -n "$coda_corpus_out_dir" ]]; then
    echo "  - CODA_CORPUS_OUT_DIR"
  fi
fi

echo ""
echo "── Handoff ──────────────────────────────────────────────────────"
echo "Environment configured. Next for the downstream agent:"
echo "  make check-env                    # verify env is ready"
echo "  make bash                         # interactive shell with env"
echo "  make install && make install-dev-workbench  # setup venv"
echo "  Read AGENTS.md — start at Gate 0"
echo "──────────────────────────────────────────────────────────────────"
