#!/usr/bin/env bash
# Explicit opt-in only. Run as the SpaceWorks install owner, with sudo for systemd.
set -euo pipefail
# Tokens must stay out of shell traces, argv, answer files and the runner's .env.
set +x
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$ROOT" != *$'\n'* && "$ROOT" != *$'\r'* ]] || { echo 'ERROR: Install path cannot contain newlines.' >&2; exit 1; }
source "$ROOT/scripts/install-owner.sh"
require_install_owner "$ROOT/scripts/install-runner.sh" "$@"
source "$ROOT/scripts/spaceworks-repository.sh"
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
mode=install
case "${1:-}" in
  '') ;;
  --remove) mode=remove ;;
  *) die 'Usage: bash scripts/install-runner.sh [--remove]' ;;
esac
[[ $# -le 1 ]] || die 'Usage: bash scripts/install-runner.sh [--remove]'
if [[ "$(uname -s)" != Linux ]] || ! command -v systemctl >/dev/null 2>&1 \
  || [[ ! -d /run/systemd/system ]]; then
  echo 'GitHub Actions runner installation supports only Linux with running systemd; skipping.'
  exit 0
fi
owner="$(id -un)"
privileged=()
[[ "$(id -u)" == 0 ]] || privileged=(sudo)
[[ ${#privileged[@]} == 0 ]] || command -v sudo >/dev/null 2>&1 || die 'systemd service installation requires sudo.'
RUNNER_DIR="${SPACEWORKS_RUNNER_DIR:-/opt/spaceworks-runner}"
[[ "$RUNNER_DIR" == /* && "$RUNNER_DIR" != / && "$RUNNER_DIR" != "$ROOT" \
   && "$RUNNER_DIR" != *$'\n'* && "$RUNNER_DIR" != *$'\r'* ]] || die 'Use a dedicated absolute runner directory.'
[[ ! -L "$RUNNER_DIR" ]] || die 'The runner directory cannot be a symlink.'
if [[ -e "$RUNNER_DIR" ]]; then
  [[ -d "$RUNNER_DIR" && "$(stat -c %u "$RUNNER_DIR")" == "$(id -u)" ]] \
    || die 'The runner directory must belong to the SpaceWorks install owner.'
fi
if [[ "$mode" == remove && ! -f "$RUNNER_DIR/.runner" ]]; then
  echo 'No configured runner to remove.'
  exit 0
fi
repository="${SPACEWORKS_REPOSITORY:-$(repository_env_value SPACEWORKS_REPOSITORY)}"
repository="${repository:-SpaceWorks-HQ/SpaceWorks}"
SPACEWORKS_REPOSITORY="$repository"
configure_release_repository || die 'Invalid GitHub repository.'
read_token() {
  local purpose="$1"
  echo "In https://github.com/$repository: Settings -> Actions -> Runners."
  if [[ "$purpose" == registration ]]; then
    echo 'Choose New self-hosted runner and copy the short-lived registration token.'
  else
    echo 'Select this runner -> Remove and copy the short-lived removal token.'
  fi
  printf '%s token (hidden): ' "$purpose"
  IFS= read -r -s runner_token </dev/tty || die 'A terminal and token are required.'
  runner_token="${runner_token%$'\r'}"
  echo
  [[ "$runner_token" =~ ^[A-Za-z0-9_-]+$ ]] || die 'A non-empty GitHub runner token is required.'
}
configure_runner() (
  # Runner's supported secret-input environment is masked and consumed by its listener.
  # https://github.com/actions/runner/blob/main/src/Runner.Listener/CommandSettings.cs
  export ACTIONS_RUNNER_INPUT_TOKEN="$runner_token"
  [[ "$(id -u)" != 0 ]] || export RUNNER_ALLOW_RUNASROOT=1
  cd "$RUNNER_DIR"
  bash ./config.sh "$@"
)
if [[ "$mode" == remove ]]; then
  read_token removal
  cd "$RUNNER_DIR"
  if [[ -f .service ]]; then
    "${privileged[@]}" bash ./svc.sh stop
    "${privileged[@]}" bash ./svc.sh uninstall
  fi
  configure_runner remove
  unset runner_token
  echo 'Runner registration and systemd service removed. Runner files were retained.'
  exit 0
fi
docker info >/dev/null 2>&1 || die 'The install owner needs Docker access (docker group or root) before installing the runner.'
for binary in curl python3 tar sha256sum; do
  command -v "$binary" >/dev/null 2>&1 || die "Missing $binary. Install it and rerun bash scripts/install-runner.sh."
done
case "$(uname -m)" in
  x86_64|amd64) architecture=x64 ;;
  aarch64|arm64) architecture=arm64 ;;
  *) die 'The runner supports only Linux x64 and arm64.' ;;
esac
temporary="$(mktemp -d)"
trap 'unset runner_token; rm -f -- "$temporary/release.json" "$temporary/runner.tar.gz"; rmdir -- "$temporary"' EXIT
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --connect-timeout 15 --max-time 600 \
  https://api.github.com/repos/actions/runner/releases/latest -o "$temporary/release.json"
selection="$(python3 "$ROOT/scripts/runner-release.py" "$architecture" < "$temporary/release.json")" \
  || die 'Could not verify official runner release metadata.'
IFS=$'\n' read -r url <<< "$selection"
checksum="${selection##*$'\n'}"
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --connect-timeout 15 --max-time 600 "$url" -o "$temporary/runner.tar.gz"
printf '%s  %s\n' "$checksum" "$temporary/runner.tar.gz" | sha256sum --check --status \
  || die 'Runner SHA-256 mismatch; nothing was unpacked or registered.'
if [[ ! -d "$RUNNER_DIR" ]]; then
  "${privileged[@]}" install -d -m 0755 -o "$owner" "$RUNNER_DIR"
fi
cd "$RUNNER_DIR"
if [[ -f .runner ]]; then
  echo 'Reinstalling an existing registration requires its removal token first.'
  read_token removal
  if [[ -f .service ]]; then
    "${privileged[@]}" bash ./svc.sh stop
    "${privileged[@]}" bash ./svc.sh uninstall
  fi
  configure_runner remove
  unset runner_token
fi
read_token registration
tar -xzf "$temporary/runner.tar.gz" --no-same-owner -C "$RUNNER_DIR"
[[ -f config.sh ]] || die 'Official runner archive is incomplete.'
if [[ -f bin/installdependencies.sh ]]; then
  "${privileged[@]}" bash bin/installdependencies.sh
fi
configure_runner --url "https://github.com/$repository" --name "$(hostname)-spaceworks" \
  --labels spaceworks-prod --unattended --replace
unset runner_token
[[ -f svc.sh ]] || die 'Runner configuration did not generate its systemd service helper.'
# config.sh's env.sh creates .env; replace only our entries, preserving runner settings.
python3 - "$RUNNER_DIR/.env" "$ROOT" "$(id -u)" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
if path.is_symlink():
    sys.exit('ERROR: runner .env cannot be a symlink.')
lines = path.read_text().splitlines() if path.exists() else []
lines = [line for line in lines if not line.startswith(('SPACEWORKS_DIR=', 'RUNNER_ALLOW_RUNASROOT='))]
lines.append('SPACEWORKS_DIR=' + sys.argv[2])
if sys.argv[3] == '0':
    lines.append('RUNNER_ALLOW_RUNASROOT=1')
path.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
PY
chmod 600 .env
if [[ ! -f .service ]]; then "${privileged[@]}" bash ./svc.sh install "$owner"; fi
"${privileged[@]}" bash ./svc.sh start
cat <<EOF
Runner installed as $owner. Complete these steps in GitHub repository $repository:
1. Settings -> Secrets and variables -> Actions -> Variables -> New repository variable:
   SPACEWORKS_DEPLOY = true
2. Settings -> Actions -> General -> Fork pull request workflows:
   Require approval for all external contributors
3. Settings -> Actions -> Runners: confirm this runner is Idle with label spaceworks-prod.
4. For an organization, restrict its runner group to this repository and, where the plan
   allows, to release.yml on refs/heads/main.
SECURITY: This public repository's runner controls Docker (effectively root on this server).
GitHub recommends self-hosted runners only for private repositories. Apply the restrictions
above and never add self-hosted labels to pull_request workflows. The deploy job has no
checkout or third-party actions. Keep the runner updated; automatic updates remain enabled.
Reinstall: bash scripts/install-runner.sh; remove: bash scripts/install-runner.sh --remove
EOF
