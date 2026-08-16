#!/usr/bin/env bash
# Privileged host supervisor for an app-recorded Phase 5A restore intent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.prod.yml)
OPS_DIR="${SPACEWORKS_OPS_HOST_DIR:-/var/lib/spaceworks/ops}"
RESTORE_ID="${1:-}"
IDENTITY_FILE="${BACKUP_AGE_IDENTITY_FILE:-$OPS_DIR/age-identity.txt}"

say() { printf '[Space Works restore] %s\n' "$*"; }
die() { printf '[Space Works restore] ERROR: %s\n' "$*" >&2; exit 1; }
backend_stopped=0
control() {
  if [[ "$backend_stopped" == 1 ]]; then
    "${COMPOSE[@]}" run --rm --no-deps -T backend python manage.py backup_control "$@"
  else
    "${COMPOSE[@]}" exec -T backend python manage.py backup_control "$@"
  fi
}

[[ "$RESTORE_ID" =~ ^[0-9a-fA-F-]{36}$ ]] || die "Usage: scripts/restore.sh <restore-uuid>"
command -v docker >/dev/null 2>&1 || die "Docker is required."
command -v flock >/dev/null 2>&1 || die "flock is required; Windows cannot run in-place restore."
[[ -d "$OPS_DIR" ]] || die "$OPS_DIR is missing; run setup on this host first."
[[ -f "$IDENTITY_FILE" ]] || die "The age identity file is missing: $IDENTITY_FILE"

exec 9>"$OPS_DIR/operation.lock"
flock -n 9 || die "Another backup, restore, verification, or update is running."

WORK="$OPS_DIR/restore-$RESTORE_ID"
ARCHIVE="$WORK/archive.tar.age"
PLAIN="$WORK/archive.tar"
BUNDLE="$WORK/bundle"
JOURNAL="$WORK/swap-journal.jsonl"
PRE_DB="$WORK/pre-restore.dump"
CONTROL_RECORD="$WORK/restore-control.json"
DESTRUCTIVE_MARKER="$WORK/destructive-started"
mkdir -p "$BUNDLE"
if [[ "$(id -u)" == "0" ]]; then
  chown -R 10001:10001 "$WORK"
fi

destructive=0
finished=0
workers_stopped=0
metadata=""
restart_workers() {
  if [[ "$workers_stopped" == 1 ]]; then
    "${COMPOSE[@]}" up -d worker beat >/dev/null 2>&1
    workers_stopped=0
  fi
}
restart_backend() {
  if [[ "$backend_stopped" == 1 ]]; then
    "${COMPOSE[@]}" up -d backend >/dev/null 2>&1
    backend_stopped=0
  fi
}
cleanup() {
  code=$?
  trap - EXIT
  set +e
  if [[ "$finished" == 0 ]]; then
    if [[ "$destructive" == 1 ]]; then
      say "Restore failed after database replacement; rolling objects and database back."
      control stage "$RESTORE_ID" rolling_back >/dev/null 2>&1 || true
      control rollback-objects "$RESTORE_ID" >/dev/null 2>&1 || true
      "${COMPOSE[@]}" exec -T db sh -c \
        'pg_restore --clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
        < "$PRE_DB" >/dev/null 2>&1 || true
      control reconcile-journal "$RESTORE_ID" \
        --journal "/var/lib/spaceworks/ops/restore-$RESTORE_ID/swap-journal.jsonl" \
        >/dev/null 2>&1 || true
      control fail "$RESTORE_ID" --message "Privileged host restore failed; inspect $JOURNAL." \
        >/dev/null 2>&1 || true
    else
      control pause "$RESTORE_ID" --message \
        "Privileged host restore paused before destructive work; rerun the supervisor." \
        >/dev/null 2>&1 || true
    fi
  fi
  restart_backend
  restart_workers
  exit "$code"
}
trap cleanup EXIT

if [[ -f "$DESTRUCTIVE_MARKER" ]]; then
  prior_metadata="$(control describe "$RESTORE_ID" 2>/dev/null | tail -n 1 || true)"
  prior_stage="$(printf '%s' "$prior_metadata" | sed -n 's/.*"stage": "\([a-z_]*\)".*/\1/p')"
  if [[ "$prior_stage" == "completed" || "$prior_stage" == "restored_quarantined" ]]; then
    rm -f -- "$DESTRUCTIVE_MARKER"
    finished=1
    say "A completed restore marker was reconciled; no rollback was required."
    exit 0
  fi
  [[ -s "$PRE_DB" ]] \
    || die "Interrupted destructive restore lacks its pre-restore database dump."
  say "Interrupted destructive restore detected; restoring the pre-restore database and objects."
  "${COMPOSE[@]}" stop backend worker beat >/dev/null
  backend_stopped=1
  workers_stopped=1
  "${COMPOSE[@]}" exec -T db sh -c \
    'pg_restore --clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    < "$PRE_DB"
  control reconcile-journal "$RESTORE_ID" \
    --journal "/var/lib/spaceworks/ops/restore-$RESTORE_ID/swap-journal.jsonl" >/dev/null
  control rollback-objects "$RESTORE_ID" >/dev/null
  control fail "$RESTORE_ID" --message \
    "Interrupted destructive restore was rolled back from the durable host journal." >/dev/null
  rm -f -- "$DESTRUCTIVE_MARKER"
  finished=1
  restart_backend
  restart_workers
  die "The interrupted restore was rolled back safely; inspect the failed operation before retrying."
fi

claim_result="$(control claim "$RESTORE_ID" | tail -n 1)"
[[ "$claim_result" == "claimed" || "$claim_result" == "resume" ]] \
  || die "Restore intent is not at a resumable pre-destructive stage."
metadata="$(control describe "$RESTORE_ID" | tail -n 1)"
archive_id="$(printf '%s' "$metadata" | sed -n 's/.*"archive_id": "\([0-9a-f-]*\)".*/\1/p')"
kind="$(printf '%s' "$metadata" | sed -n 's/.*"kind": "\([a-z_]*\)".*/\1/p')"
requested_by="$(printf '%s' "$metadata" | sed -n 's/.*"requested_by": \([0-9]*\).*/\1/p')"
[[ -n "$archive_id" && -n "$kind" && -n "$requested_by" ]] || die "Could not read restore metadata."

backend_container="$("${COMPOSE[@]}" ps -q backend)"
image_id="$(docker inspect --format '{{.Image}}' "$backend_container")"
oci_digest="$(docker image inspect --format '{{index .RepoDigests 0}}' "$image_id" 2>/dev/null || true)"
control export-archive "$RESTORE_ID" --output "/var/lib/spaceworks/ops/restore-$RESTORE_ID/archive.tar.age" >/dev/null
"${COMPOSE[@]}" exec -T backend age -d \
  -i "${IDENTITY_FILE/$OPS_DIR/\/var\/lib\/spaceworks\/ops}" \
  -o "/var/lib/spaceworks/ops/restore-$RESTORE_ID/archive.tar" \
  "/var/lib/spaceworks/ops/restore-$RESTORE_ID/archive.tar.age"
"${COMPOSE[@]}" exec -T backend python - \
  "/var/lib/spaceworks/ops/restore-$RESTORE_ID/archive.tar" \
  "/var/lib/spaceworks/ops/restore-$RESTORE_ID/bundle" <<'PY'
import pathlib
import sys
import tarfile

archive, destination = map(pathlib.Path, sys.argv[1:])
with tarfile.open(archive) as bundle:
    bundle.extractall(destination, filter="data")
PY
[[ -s "$BUNDLE/manifest.json" && -s "$BUNDLE/database.dump" ]] \
  || die "The archive is missing its manifest or database dump."
control preflight "$RESTORE_ID" \
  --manifest "/var/lib/spaceworks/ops/restore-$RESTORE_ID/bundle/manifest.json" \
  --current-oci-digest "$oci_digest" >/dev/null

drain_seconds="$(control quiesce "$RESTORE_ID" | tail -n 1)"
[[ "$drain_seconds" =~ ^[0-9]+$ ]] || die "The app returned an invalid presign drain window."
"${COMPOSE[@]}" stop worker beat >/dev/null
workers_stopped=1
say "Writers are excluded; draining presigned uploads for ${drain_seconds}s."
sleep "$drain_seconds"

say "Taking the mandatory pre-restore database snapshot."
"${COMPOSE[@]}" exec -T db sh -c \
  'pg_dump --format=custom --no-owner --no-acl -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "$PRE_DB"
[[ -s "$PRE_DB" ]] || die "The pre-restore database snapshot is empty."

if [[ "$kind" == "rollback_in_place" ]]; then
  temp_db="spaceworks_restore_${RESTORE_ID//-/}"
  temp_db="${temp_db:0:60}"
  "${COMPOSE[@]}" exec -T db sh -c \
    'dropdb --if-exists -U "$POSTGRES_USER" '"$temp_db"' && createdb -U "$POSTGRES_USER" '"$temp_db"
  "${COMPOSE[@]}" exec -T db sh -c \
    'pg_restore --no-owner --no-acl -U "$POSTGRES_USER" -d '"$temp_db" \
    < "$BUNDLE/database.dump"
  archive_url="$("${COMPOSE[@]}" exec -T backend python - "$temp_db" <<'PY'
import sys
import os
from urllib.parse import quote
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.conf import settings
d=settings.DATABASES['default']
print(f"postgres://{quote(str(d.get('USER') or ''))}:{quote(str(d.get('PASSWORD') or ''))}@{d.get('HOST') or 'db'}:{d.get('PORT') or 5432}/{sys.argv[1]}")
PY
)"
  say "Computing every-table diff in one live snapshot; choose before the console countdown expires."
  decision="$(control diff-wait "$RESTORE_ID" --archive-database-url "$archive_url" | tail -n 1)"
  "${COMPOSE[@]}" exec -T db sh -c \
    'dropdb --if-exists -U "$POSTGRES_USER" '"$temp_db" >/dev/null 2>&1 || true
  [[ "$decision" != "abort" ]] || { finished=1; say "Restore aborted without destructive effect."; exit 0; }
else
  decision="reset"
fi

control export-control "$RESTORE_ID" \
  --output "/var/lib/spaceworks/ops/restore-$RESTORE_ID/restore-control.json" \
  --decision "$decision" >/dev/null

printf '%s\n' "$RESTORE_ID" > "$DESTRUCTIVE_MARKER"
sync -f "$WORK"
control stage "$RESTORE_ID" db_restoring >/dev/null
"${COMPOSE[@]}" stop backend >/dev/null
backend_stopped=1
destructive=1
say "Replacing the database."
"${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()" >/dev/null && pg_restore --clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$BUNDLE/database.dump"

control rehydrate "$RESTORE_ID" --archive-id "$archive_id" --kind "$kind" \
  --requested-by "$requested_by" \
  --control-record "/var/lib/spaceworks/ops/restore-$RESTORE_ID/restore-control.json" \
  --manifest "/var/lib/spaceworks/ops/restore-$RESTORE_ID/bundle/manifest.json" >/dev/null
control restore-objects "$RESTORE_ID" --bundle-root "/var/lib/spaceworks/ops/restore-$RESTORE_ID/bundle" \
  --manifest "/var/lib/spaceworks/ops/restore-$RESTORE_ID/bundle/manifest.json" \
  --journal "/var/lib/spaceworks/ops/restore-$RESTORE_ID/swap-journal.jsonl" >/dev/null
control stage "$RESTORE_ID" validating >/dev/null
control validate "$RESTORE_ID" >/dev/null

if [[ "$kind" == "disaster" || "$decision" == "reset" ]]; then
  control quarantine "$RESTORE_ID" --reason \
    "Disaster/cross-server restore or operator-selected authority reset." >/dev/null
  say "Restore completed in quarantine. Run recover_superadmin, then acknowledge the residual risk in the console."
else
  control complete "$RESTORE_ID" >/dev/null
  say "In-place rollback completed without authority reset after the reviewed diff."
fi
rm -f -- "$DESTRUCTIVE_MARKER"
finished=1
control cleanup-rollback "$RESTORE_ID" >/dev/null
restart_backend
restart_workers
say "Restore supervisor completed."
