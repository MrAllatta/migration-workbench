#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/inject_project_local_config.sh \
    --project-dir /path/to/project \
    --drive-folder-id "..." \
    --drive-folder-name "..." \
    --workbench-path /path/to/migration-workbench \
    --google-impersonate-service-account "service-account@project.iam.gserviceaccount.com"

Updates:
  - config/cohort_corpus.json: folder_name (non-secret heuristics)
  - .env: WORKBENCH, GOOGLE_IMPERSONATE_SERVICE_ACCOUNT, DRIVE_FOLDER_ID

Notes:
  - Existing values are replaced in place.
  - If .env does not exist, the script copies .env.example first.
  - If WORKBENCH, GOOGLE_IMPERSONATE_SERVICE_ACCOUNT, or DRIVE_FOLDER_ID are missing in .env, they are appended.
EOF
}

project_dir=""
drive_folder_id=""
drive_folder_name=""
workbench_path=""
google_impersonate_service_account=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      project_dir="${2:-}"
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
    --workbench-path)
      workbench_path="${2:-}"
      shift 2
      ;;
    --google-impersonate-service-account)
      google_impersonate_service_account="${2:-}"
      shift 2
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

if [[ -z "$project_dir" || -z "$drive_folder_id" || -z "$drive_folder_name" || -z "$workbench_path" || -z "$google_impersonate_service_account" ]]; then
  echo "Error: all required arguments must be provided." >&2
  usage
  exit 1
fi

project_dir="${project_dir%/}"
config_path="$project_dir/config/cohort_corpus.json"
env_path="$project_dir/.env"
env_example_path="$project_dir/.env.example"

if [[ ! -f "$config_path" ]]; then
  echo "Error: config file not found: $config_path" >&2
  exit 1
fi

if [[ ! -f "$env_path" ]]; then
  if [[ ! -f "$env_example_path" ]]; then
    echo "Error: env file not found: $env_path" >&2
    echo "Error: cannot bootstrap .env because .env.example is missing: $env_example_path" >&2
    exit 1
  fi

  cp "$env_example_path" "$env_path"
  echo "Created $env_path from $env_example_path"
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

python3 - "$env_path" "$workbench_path" "$google_impersonate_service_account" "$drive_folder_id" <<'PYTHON'
import pathlib
import re
import sys

env_path = pathlib.Path(sys.argv[1])
workbench_path = sys.argv[2]
google_impersonate_service_account = sys.argv[3]
drive_folder_id = sys.argv[4]

env_text = env_path.read_text()
final_text = env_text

def replace_or_append(existing_text: str, env_key: str, env_value: str) -> str:
    env_line = f"{env_key}={env_value}"
    env_pattern = re.compile(rf"^{re.escape(env_key)}=.*$", re.MULTILINE)

    if env_pattern.search(existing_text):
        return env_pattern.sub(env_line, existing_text)

    if existing_text and not existing_text.endswith("\n"):
        return existing_text + "\n" + env_line + "\n"

    return existing_text + env_line + "\n"

final_text = replace_or_append(final_text, "WORKBENCH", workbench_path)
final_text = replace_or_append(
    final_text,
    "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT",
    google_impersonate_service_account,
)
final_text = replace_or_append(final_text, "DRIVE_FOLDER_ID", drive_folder_id)

env_path.write_text(final_text)
PYTHON

echo "Updated:"
echo "  - $config_path (folder_name)"
echo "  - $env_path (WORKBENCH, GOOGLE_IMPERSONATE_SERVICE_ACCOUNT, DRIVE_FOLDER_ID)"
echo ""
echo "── Handoff ──────────────────────────────────────────────────────"
echo "Environment configured. Next for the downstream agent:"
echo "  make check-env                    # verify env is ready"
echo "  make bash                         # interactive shell with env"
echo "  make install && make install-dev-workbench  # setup venv"
echo "  Read AGENTS.md — start at Gate 0"
echo "──────────────────────────────────────────────────────────────────"
