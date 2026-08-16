#!/usr/bin/env bash
# Import a downloaded full-deployment archive, record intent, then run disaster restore.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
COMPOSE=(docker compose -f docker-compose.prod.yml)
OPS_DIR="${SPACEWORKS_OPS_HOST_DIR:-/var/lib/spaceworks/ops}"
IDENTITY_FILE="${BACKUP_AGE_IDENTITY_FILE:-$OPS_DIR/age-identity.txt}"
SOURCE="${1:-}"
USERNAME="${2:-}"

die() { printf '[Space Works backup import] ERROR: %s\n' "$*" >&2; exit 1; }
[[ -f "$SOURCE" && -n "$USERNAME" ]] \
  || die "Usage: scripts/import-backup.sh <archive.tar.age> <target-superadmin-username>"
[[ -d "$OPS_DIR" && -f "$IDENTITY_FILE" ]] || die "The operation directory or age identity is missing."
command -v flock >/dev/null 2>&1 || die "flock is required."

exec 9>"$OPS_DIR/operation.lock"
flock -n 9 || die "Another backup, restore, verification, or update is running."
WORK="$(mktemp -d "$OPS_DIR/import-XXXXXXXX")"
if [[ "$(id -u)" == "0" ]]; then
  chown -R 10001:10001 "$WORK"
fi
CONTAINER_WORK="${WORK/$OPS_DIR/\/var\/lib\/spaceworks\/ops}"
cleanup() { rm -rf -- "$WORK"; }
trap cleanup EXIT
cp -- "$SOURCE" "$WORK/archive.tar.age"
if [[ "$(id -u)" == "0" ]]; then
  chown 10001:10001 "$WORK/archive.tar.age"
fi

"${COMPOSE[@]}" exec -T backend age -d \
  -i "${IDENTITY_FILE/$OPS_DIR/\/var\/lib\/spaceworks\/ops}" \
  -o "$CONTAINER_WORK/archive.tar" "$CONTAINER_WORK/archive.tar.age"
"${COMPOSE[@]}" exec -T backend python - \
  "$CONTAINER_WORK/archive.tar" "$CONTAINER_WORK/manifest.json" \
  "$CONTAINER_WORK/keys-env.json" <<'PY'
import pathlib
import sys
import tarfile

archive, manifest_output, keys_output = map(pathlib.Path, sys.argv[1:])
with tarfile.open(archive) as bundle:
    members = {member.name.lstrip("./"): member for member in bundle.getmembers()}
    for name, output in (("manifest.json", manifest_output), ("keys/env.json", keys_output)):
        member = members.get(name)
        if member is None or not member.isfile():
            raise SystemExit(f"The archive has no regular {name} member.")
        source = bundle.extractfile(member)
        if source is None:
            raise SystemExit(f"The archive member {name} cannot be read.")
        output.write_bytes(source.read())
PY

[[ -f .env ]] || die "The target deployment has no .env file to receive continuity secrets."
cp -p -- .env "$WORK/target.env"
if [[ "$(id -u)" == "0" ]]; then
  chown 10001:10001 "$WORK/target.env"
fi
"${COMPOSE[@]}" exec -T backend python - \
  "$CONTAINER_WORK/target.env" "$CONTAINER_WORK/keys-env.json" <<'PY'
import json
import os
from pathlib import Path
import re
import sys

target, source = map(Path, sys.argv[1:])
required = {
    "SECRET_KEY", "API_CLIENT_ENC_KEY", "PII_MASTER_KEY",
    "PII_MASTER_KEY_PREVIOUS", "PII_SEARCH_HASH_KEY", "HMAC_SECRET",
    "PUSH_TOKEN_HMAC_KEY", "CRON_SECRET",
}
values = json.loads(source.read_text(encoding="utf-8"))
if set(values) != required or not isinstance(values.get("SECRET_KEY"), str) or not values["SECRET_KEY"]:
    raise SystemExit("The archive continuity-secret set is invalid.")
if any(not isinstance(value, str) or "\n" in value or "\r" in value for value in values.values()):
    raise SystemExit("A continuity secret cannot be represented safely in the Compose environment.")
lines = target.read_text(encoding="utf-8").splitlines()
remaining = dict(values)
for index, line in enumerate(lines):
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
    if match and match.group(1) in remaining:
        name = match.group(1)
        value = remaining.pop(name).replace("\\", "\\\\").replace("'", "\\'")
        lines[index] = f"{name}='{value}'"
for name, raw in sorted(remaining.items()):
    value = raw.replace("\\", "\\\\").replace("'", "\\'")
    lines.append(f"{name}='{value}'")
temporary = target.with_suffix(".new")
with temporary.open("w", encoding="utf-8") as handle:
    handle.write("\n".join(lines) + "\n")
    handle.flush()
    os.fsync(handle.fileno())
temporary.replace(target)
PY
env_backup=".env.pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p -- .env "$env_backup"
install -m 600 "$WORK/target.env" .env
printf '[Space Works backup import] Continuity secrets installed; previous environment retained at %s.\n' "$env_backup"
"${COMPOSE[@]}" up -d --force-recreate backend worker beat >/dev/null

restore_id="$("${COMPOSE[@]}" exec -T backend python manage.py import_backup_archive \
  --username "$USERNAME" --encrypted-file "$CONTAINER_WORK/archive.tar.age" \
  --manifest "$CONTAINER_WORK/manifest.json" | tail -n 1)"
[[ "$restore_id" =~ ^[0-9a-fA-F-]{36}$ ]] || die "The app did not record a restore intent."
trap - EXIT
cleanup
flock -u 9
exec "$ROOT/scripts/restore.sh" "$restore_id"
