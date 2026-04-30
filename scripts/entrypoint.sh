#!/usr/bin/env sh
# Production entrypoint: optional Litestream restore, Django migrate, then Gunicorn (optionally
# supervised by `litestream replicate`). App root /app, non-root user `app`, bind 0.0.0.0:8080.
#
# Required for normal operation: SQLITE_PATH (see migration_workbench.sqlite_path; defaults to
# /app/db.sqlite3 when unset — match Django). Production Fly secrets per deploy/spaces.yml.
#
# Litestream (when LITESTREAM_BUCKET is set):
#   LITESTREAM_ACCESS_KEY_ID, LITESTREAM_SECRET_ACCESS_KEY — required.
#   LITESTREAM_ENDPOINT — optional (S3-compatible URL for Spaces/MinIO/R2).
#   LITESTREAM_REPLICA_PREFIX — object key prefix inside the bucket, e.g. migration-workbench/preview.
#     If unset, derived as migration-workbench/${SPACES_ENV} or migration-workbench/${FLY_ENV}; if
#     those are unset too, the script exits with an error (avoids writing to the bucket root).
#
# Local / Docker smoke without object storage:
#   Omit LITESTREAM_BUCKET — Gunicorn runs without Litestream. If the DB file is missing and
#   SQLITE_PATH resolves under /data (production volume contract), set ALLOW_EMPTY_SQLITE=1 to
#   allow creating a new empty database; otherwise the script fails fast (avoids silent empty prod).
#
# Static/admin assets: full static serving may depend on WI4 (WhiteNoise); /healthz works without it.

set -eu

DB_PATH="${SQLITE_PATH:-}"
if [ -z "$DB_PATH" ]; then
  DB_PATH="/app/db.sqlite3"
else
  case "$DB_PATH" in
    /*) ;;
    *) DB_PATH="/app/${DB_PATH}" ;;
  esac
fi

export SQLITE_PATH="$DB_PATH"

LITESTREAM_CONFIG="${LITESTREAM_CONFIG:-/tmp/litestream.yml}"
GUNICORN_BIN="${GUNICORN_BIN:-/opt/venv/bin/gunicorn}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-1}"
GUNICORN_THREADS="${GUNICORN_THREADS:-4}"

write_litestream_config() {
  _url="$1"
  _endpoint="${2:-}"
  {
    printf '%s\n' "dbs:"
    printf '%s\n' "  - path: ${DB_PATH}"
    printf '%s\n' "    replicas:"
    printf '%s\n' "      - url: ${_url}"
    if [ -n "$_endpoint" ]; then
      printf '%s\n' "        endpoint: ${_endpoint}"
    fi
  } >"$LITESTREAM_CONFIG"
}

replica_s3_url() {
  _prefix="$1"
  _base="$(basename "$DB_PATH")"
  printf 's3://%s/%s/%s' "${LITESTREAM_BUCKET}" "$_prefix" "$_base"
}

resolve_replica_prefix() {
  if [ -n "${LITESTREAM_REPLICA_PREFIX:-}" ]; then
    printf '%s' "$LITESTREAM_REPLICA_PREFIX"
    return
  fi
  _env="${SPACES_ENV:-}"
  if [ -z "$_env" ]; then
    _env="${FLY_ENV:-}"
  fi
  if [ -z "$_env" ]; then
    echo "entrypoint: set LITESTREAM_REPLICA_PREFIX or SPACES_ENV or FLY_ENV when LITESTREAM_BUCKET is set" >&2
    exit 1
  fi
  printf 'migration-workbench/%s' "$_env"
}

require_litestream_secrets() {
  if [ -z "${LITESTREAM_ACCESS_KEY_ID:-}" ] || [ -z "${LITESTREAM_SECRET_ACCESS_KEY:-}" ]; then
    echo "entrypoint: LITESTREAM_ACCESS_KEY_ID and LITESTREAM_SECRET_ACCESS_KEY are required when LITESTREAM_BUCKET is set" >&2
    exit 1
  fi
}

under_data_volume_path() {
  case "$1" in
    /data|/data/*) return 0 ;;
    *) return 1 ;;
  esac
}

mkdir -p "$(dirname "$DB_PATH")"

if [ -f "$DB_PATH" ]; then
  :
else
  if [ -n "${LITESTREAM_BUCKET:-}" ]; then
    require_litestream_secrets
    _prefix="$(resolve_replica_prefix)"
    _url="$(replica_s3_url "$_prefix")"
    _endpoint="${LITESTREAM_ENDPOINT:-}"
    write_litestream_config "$_url" "$_endpoint"
    litestream restore -config "$LITESTREAM_CONFIG" -if-replica-exists "$DB_PATH"
  else
    if under_data_volume_path "$DB_PATH" && [ "${ALLOW_EMPTY_SQLITE:-0}" != "1" ]; then
      echo "entrypoint: database missing at ${DB_PATH}, LITESTREAM_BUCKET unset, and path is under /data — refusing to create an empty database (set ALLOW_EMPTY_SQLITE=1 for explicit local/smoke only)" >&2
      exit 1
    fi
  fi
fi

/opt/venv/bin/python manage.py migrate --noinput

GUNICORN_EXEC="$(printf '%s migration_workbench.wsgi:application --bind 0.0.0.0:8080 --workers %s --threads %s --worker-class gthread' \
  "$GUNICORN_BIN" "$GUNICORN_WORKERS" "$GUNICORN_THREADS")"

if [ -n "${LITESTREAM_BUCKET:-}" ]; then
  require_litestream_secrets
  _prefix="$(resolve_replica_prefix)"
  _url="$(replica_s3_url "$_prefix")"
  _endpoint="${LITESTREAM_ENDPOINT:-}"
  write_litestream_config "$_url" "$_endpoint"
  exec litestream replicate -config "$LITESTREAM_CONFIG" -exec "$GUNICORN_EXEC"
else
  exec "$GUNICORN_BIN" migration_workbench.wsgi:application --bind 0.0.0.0:8080 \
    --workers "$GUNICORN_WORKERS" --threads "$GUNICORN_THREADS" --worker-class gthread
fi
