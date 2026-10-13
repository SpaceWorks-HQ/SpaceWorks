#!/usr/bin/env bash
# Install the host-only consumer; the network receiver never executes this script.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/install-owner.sh"
require_install_owner "$ROOT/scripts/install-deploy-webhook.sh" "$@"
source "$ROOT/scripts/spaceworks-repository.sh"
OPS_DIR="${SPACEWORKS_OPS_HOST_DIR:-$(repository_env_value SPACEWORKS_OPS_HOST_DIR)}"
OPS_DIR="${OPS_DIR:-/var/lib/spaceworks/ops}"
REQUEST_DIR="${SPACEWORKS_DEPLOY_REQUEST_DIR:-$OPS_DIR/deploy-requests}"
case "$ROOT$REQUEST_DIR" in
  *"'"*|*'"'*|*'%'*|*'\\'*|*$'\n'*) echo 'ERROR: install/ops paths cannot contain quotes, percent, backslash or newlines.' >&2; exit 1 ;;
esac
owner="$(id -un)"
mkdir -p "$ROOT/backups"
chmod 700 "$ROOT/backups"
source "$ROOT/scripts/retire-update-polling.sh"
retire_update_polling
if [[ "$(uname -s)" != Linux ]] || ! command -v systemctl >/dev/null 2>&1 \
  || [[ ! -d /run/systemd/system ]]; then
  printf 'No running systemd. Add this one-minute job to %s\x27s crontab (crontab -e):\n' "$owner"
  printf "* * * * * PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; SPACEWORKS_OPS_HOST_DIR='%s' bash '%s/scripts/deploy-from-request.sh'\n" "$OPS_DIR" "$ROOT"
  echo 'This checks only local requests; it never polls GitHub without a delivery.'
  exit 0
fi
privileged=()
if [[ "$(id -u)" != 0 ]]; then
  command -v sudo >/dev/null 2>&1 || { echo 'ERROR: Installing systemd units needs sudo.' >&2; exit 1; }
  privileged=(sudo)
fi
unit_dir="${SPACEWORKS_SYSTEMD_DIR:-/etc/systemd/system}"
temp="$(mktemp -d)"
trap 'rm -f "$temp/spaceworks-deploy.path" "$temp/spaceworks-deploy.service"; rmdir "$temp"' EXIT
cat > "$temp/spaceworks-deploy.path" <<EOF
[Unit]
Description=SpaceWorks GitHub release requests
[Path]
PathExistsGlob=$REQUEST_DIR/*.json
Unit=spaceworks-deploy.service
[Install]
WantedBy=multi-user.target
EOF
cat > "$temp/spaceworks-deploy.service" <<EOF
[Unit]
Description=SpaceWorks release deployment
After=docker.service network-online.target
Wants=network-online.target
[Service]
Type=oneshot
User=$owner
WorkingDirectory=$ROOT
Environment="SPACEWORKS_OPS_HOST_DIR=$OPS_DIR"
ExecStart=/bin/bash "$ROOT/scripts/deploy-from-request.sh"
TimeoutStartSec=infinity
EOF
"${privileged[@]}" install -m 0644 "$temp/spaceworks-deploy.path" "$temp/spaceworks-deploy.service" "$unit_dir/"
"${privileged[@]}" systemctl daemon-reload
"${privileged[@]}" systemctl enable --now spaceworks-deploy.path
printf 'Installed spaceworks-deploy.path and service; deployments run as %s.\n' "$owner"
