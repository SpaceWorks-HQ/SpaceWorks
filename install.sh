#!/usr/bin/env bash
# Pinned, no-git SpaceWorks installer. It is fetched alone (curl | bash), so it is one
# self-contained file by necessity and may exceed the ~300-line ceiling for that reason.
set -euo pipefail
show_guide() {
  cat <<'EOF'

SpaceWorks installer - installs the latest SpaceWorks release built from GitHub main.

What you need first
  - A 64-bit machine (x86_64 or arm64) running Linux (Debian/Ubuntu, Fedora/RHEL/Alma/
    Rocky, Arch or openSUSE), macOS, or Windows Git Bash/WSL.
  - Linux: root, or a user with sudo (you may be asked for your password). The installer
    installs Docker, Docker Compose, curl and tar for you if they are missing.
  - macOS/Windows: Docker Desktop installed and running before you start.
  - Internet access to github.com and ghcr.io.
  - At least 8 GiB free disk and TCP ports 80, 9000 and 9001 free.
  - A terminal: setup asks questions. Have ready the web address (host name or IP),
    your makerspace name, and the admin username, email and password (or let it
    generate one). Google sign-in and Stripe keys are optional and can be skipped.

What it does
  1. Checks everything above. Nothing on the machine changes until those checks pass.
  2. Installs missing packages (Linux) and downloads the release into /opt/spaceworks
     (set SPACEWORKS_DIR=/your/path to use another folder).
  3. Runs guided setup: your details, which modules to turn on, then starts SpaceWorks in
     Docker and offers a weekly automatic update from the main release.
  Run it again later to update or change modules; it detects the existing install.
EOF
}
case "${1:-}" in
  -h|--help) show_guide; exit 0 ;;
  "") ;;
  *) printf 'Usage: install.sh [--help]\n' >&2; exit 64 ;;
esac
REPOSITORY="SpaceWorks-HQ/SpaceWorks"
RELEASE_API="https://api.github.com/repos/$REPOSITORY/releases/latest"
INSTALL_DIR="${SPACEWORKS_DIR:-/opt/spaceworks}"
MIN_FREE_KB=$((8 * 1024 * 1024))
RUN_ROOT=()
SUDO=()
USE_DOCKER_GROUP=0
RUN_INSTALLED_AS_ROOT=0
ACTION=fresh
RELEASE_TAG=""
VERSION=""
STAGE_DIR=""
ARCHIVE=""
CREATED_PARENT=0
say() { printf '[SpaceWorks installer] %s\n' "$*"; }
die() { printf '[SpaceWorks installer] ERROR: %s\n' "$*" >&2; exit 1; }
prompt() {
  local reply
  [[ -r /dev/tty ]] || die "An interactive terminal is required."
  printf '%s' "$1" > /dev/tty
  IFS= read -r reply < /dev/tty || reply=""
  printf '%s' "$reply"
}
cleanup() {
  if [[ -n "$STAGE_DIR" && "$STAGE_DIR" == */.spaceworks-stage.* ]]; then
    ${RUN_ROOT[@]+"${RUN_ROOT[@]}"} rm -rf -- "$STAGE_DIR" 2>/dev/null || true
  fi
  [[ -z "$ARCHIVE" ]] || rm -f -- "$ARCHIVE"
  if [[ "$CREATED_PARENT" == 1 ]]; then
    ${RUN_ROOT[@]+"${RUN_ROOT[@]}"} rmdir -- "$(dirname "$INSTALL_DIR")" 2>/dev/null || true
  fi
}
trap cleanup EXIT
case "$INSTALL_DIR" in
  ""|/|*"'"*|*$'\n'*) die "SPACEWORKS_DIR must be a specific path without single quotes or newlines." ;;
esac
while [[ "$INSTALL_DIR" == */ ]]; do INSTALL_DIR="${INSTALL_DIR%/}"; done
[[ -n "$INSTALL_DIR" ]] || die "SPACEWORKS_DIR cannot be the filesystem root."
[[ "$INSTALL_DIR" == /* ]] || INSTALL_DIR="$PWD/$INSTALL_DIR"
show_guide
say "Preflight only—nothing will be installed until all checks pass."
say "Checking architecture, operating system, dependencies, Docker, release availability, ports, disk space, and existing state."
machine="$(uname -m)"
case "$machine" in
  x86_64|amd64) ARCH=x86_64 ;;
  aarch64|arm64) ARCH=aarch64 ;;
  *) die "Unsupported architecture '$machine'. SpaceWorks release images support only x86_64 and aarch64." ;;
esac
kernel="$(uname -s)"
PACKAGE_FAMILY=""
case "$kernel" in
  Linux)
    [[ -r /etc/os-release ]] || die "Linux distribution metadata /etc/os-release is missing."
    # /etc/os-release is the distribution's canonical data source. Do not infer
    # the family from whichever package-manager binary happens to be present.
    ID=""; ID_LIKE=""
    # shellcheck disable=SC1091
    source /etc/os-release
    distro_words=" ${ID:-} ${ID_LIKE:-} "
    case "$distro_words" in
      *" debian "*|*" ubuntu "*|*" linuxmint "*) PACKAGE_FAMILY=apt ;;
      *" fedora "*|*" rhel "*|*" centos "*|*" rocky "*|*" almalinux "*) PACKAGE_FAMILY=dnf ;;
      *" arch "*|*" manjaro "*) PACKAGE_FAMILY=pacman ;;
      *" suse "*|*" opensuse "*|*" sles "*) PACKAGE_FAMILY=zypper ;;
      *) die "Unsupported Linux distribution '${ID:-unknown}' (ID_LIKE='${ID_LIKE:-}'). Supported families: Debian/Ubuntu, RHEL/Fedora/Alma/Rocky, Arch, and SUSE." ;;
    esac
    HOST_KIND=linux
    ;;
  MINGW*|MSYS*|CYGWIN*) HOST_KIND=windows ;;
  Darwin) HOST_KIND=macos ;;
  *) die "Unsupported host '$kernel'. Use Linux, Windows Git Bash, or macOS with Docker Desktop." ;;
esac
say "Architecture: $ARCH; host: $HOST_KIND${PACKAGE_FAMILY:+/$PACKAGE_FAMILY}."
# Host privilege and install-directory privilege are independent decisions.
if [[ "$HOST_KIND" == linux && "$(id -u)" != 0 ]]; then
  command -v sudo >/dev/null 2>&1 && SUDO=(sudo)
  # Releases stage beside the install, including on a user-owned /opt rerun.
  write_path="$(dirname "$INSTALL_DIR")"
  while [[ ! -e "$write_path" ]]; do write_path="$(dirname "$write_path")"; done
  if [[ ! -w "$write_path" || ( -d "$INSTALL_DIR" && ! -x "$INSTALL_DIR" ) ]]; then
    ((${#SUDO[@]} > 0)) || die "Writing $INSTALL_DIR requires sudo. Install sudo or run this installer as root."
    RUN_ROOT=(sudo)
  fi
elif [[ "$(id -u)" == 0 ]]; then
  RUN_INSTALLED_AS_ROOT=1
fi
missing=()
MISSING_DOCKER=0
MISSING_COMPOSE=0
command -v curl >/dev/null 2>&1 || missing+=(curl)
command -v tar >/dev/null 2>&1 || missing+=(tar)
if ! command -v docker >/dev/null 2>&1; then
  missing+=(docker-engine docker-compose-v2)
  MISSING_DOCKER=1
  MISSING_COMPOSE=1
elif ! docker compose version >/dev/null 2>&1; then
  missing+=(docker-compose-v2)
  MISSING_COMPOSE=1
fi
if ((${#missing[@]} > 0)); then
  if [[ "$HOST_KIND" != linux ]]; then
    die "Missing: ${missing[*]}. Install Docker Desktop (with Compose V2), curl, and tar, then rerun."
  fi
  if [[ "$(id -u)" != 0 ]]; then
    ((${#SUDO[@]} > 0)) || die "Missing ${missing[*]} and sudo is unavailable. Install them as root, then rerun."
  fi
  say "After preflight, the $PACKAGE_FAMILY family installer will install/ensure: curl, tar, Docker Engine, and Docker Compose V2."
else
  say "Dependencies are already present."
fi
if command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1; then
  if [[ "$HOST_KIND" == linux ]]; then
    say "Docker is installed but stopped/inaccessible; after preflight the installer will start it or configure docker-group access."
  else
    die "Docker Desktop is installed but not running. Start it and wait until it is ready, then rerun; no state was changed."
  fi
fi
if ${RUN_ROOT[@]+"${RUN_ROOT[@]}"} test -f "$INSTALL_DIR/.spaceworks-version"; then
  ACTION="$(prompt "
SpaceWorks is already installed in $INSTALL_DIR (version $(${RUN_ROOT[@]+"${RUN_ROOT[@]}"} cat "$INSTALL_DIR/.spaceworks-version" 2>/dev/null || echo unknown)).
What do you want to do?
  1) Update to the latest release - backs up the database, moves to the newest main
     release, runs migrations and restarts. Your modules and data stay as they are.
  2) Change modules only - turn optional modules (events, bookings, machines, membership,
     payments...) on or off. No new version is downloaded.
  3) Update, then change modules - option 1 followed by option 2.
  4) Cancel - exit without changing anything.
Choose 1-4 [4]: ")"
  ACTION="${ACTION:-4}"
  case "$ACTION" in
    1) ACTION=update ;;
    2) ACTION=modules ;;
    3) ACTION=both ;;
    4) say "Cancelled; existing deployment was not changed."; exit 0 ;;
    *) die "Invalid menu choice; existing deployment was not changed." ;;
  esac
  ${RUN_ROOT[@]+"${RUN_ROOT[@]}"} test -f "$INSTALL_DIR/scripts/update.sh" || die "The version marker exists but scripts/update.sh is missing. Repair the install manually."
  if [[ "$(id -u)" != 0 ]] && { [[ ! -w "$INSTALL_DIR" ]] \
    || { [[ "$HOST_KIND" == linux ]] && [[ "$(stat -c %u "$INSTALL_DIR")" == 0 ]]; }; }; then
    command -v sudo >/dev/null 2>&1 || die "The existing install is not writable and sudo is unavailable."
    RUN_ROOT=(sudo)
    RUN_INSTALLED_AS_ROOT=1
  fi
elif ${RUN_ROOT[@]+"${RUN_ROOT[@]}"} test -e "$INSTALL_DIR"; then
  if ${RUN_ROOT[@]+"${RUN_ROOT[@]}"} test -d "$INSTALL_DIR" && [[ -z "$(${RUN_ROOT[@]+"${RUN_ROOT[@]}"} find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    EMPTY_INSTALL_DIR=1
  else
    die "$INSTALL_DIR already contains state but has no .spaceworks-version marker. Refusing to reuse or overwrite it."
  fi
else
  EMPTY_INSTALL_DIR=0
fi
port_in_use() {
  local port="$1" hex file
  if [[ "$HOST_KIND" == linux ]]; then
    printf -v hex '%04X' "$port"
    for file in /proc/net/tcp /proc/net/tcp6; do
      [[ -r "$file" ]] || continue
      awk -v wanted="$hex" 'NR > 1 { split($2, address, ":"); if (toupper(address[2]) == wanted && $4 == "0A") exit 7 }' "$file" || return 0
    done
    return 1
  fi
  netstat -an 2>/dev/null | awk -v pattern="[:.]${port}[[:space:]]" \
    'toupper($0) ~ /LISTEN/ && $0 ~ pattern { found=1 } END { exit !found }'
}
if [[ "$ACTION" == fresh ]]; then
  for port in 80 9000 9001; do
    port_in_use "$port" && die "TCP port $port is already in use. Free it or configure a manual install before running setup."
  done
  say "Required TCP ports 80, 9000, and 9001 are free."
fi
disk_path="$INSTALL_DIR"
while [[ ! -e "$disk_path" && "$disk_path" != / ]]; do disk_path="$(dirname "$disk_path")"; done
available_kb="$(df -Pk "$disk_path" | awk 'NR == 2 {print $4}')"
[[ "$available_kb" =~ ^[0-9]+$ ]] || die "Could not determine free disk space for $INSTALL_DIR."
((available_kb >= MIN_FREE_KB)) || die "At least 8 GiB free is required; $disk_path has $((available_kb / 1024)) MiB."
say "Disk-space check passed."
say "Host preflight passed; preparing dependencies and checking the release."
if [[ "$ACTION" == fresh ]]; then
  plan="Install SpaceWorks into $INSTALL_DIR"
  ((${#missing[@]} == 0)) || plan="Install ${missing[*]}, then install SpaceWorks into $INSTALL_DIR"
  reply="$(prompt "
$plan and start guided setup? [Y/n]: ")"
  [[ ! "$reply" =~ ^[Nn] ]] || { say "Cancelled; nothing was changed."; exit 0; }
fi
install_linux_dependencies() {
  case "$PACKAGE_FAMILY" in
    apt)
      ${SUDO[@]+"${SUDO[@]}"} apt-get update
      ${SUDO[@]+"${SUDO[@]}"} env DEBIAN_FRONTEND=noninteractive apt-get install -y curl tar
      [[ "$MISSING_DOCKER" == 0 ]] \
        || ${SUDO[@]+"${SUDO[@]}"} env DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io
      if [[ "$MISSING_COMPOSE" == 1 ]]; then
        ${SUDO[@]+"${SUDO[@]}"} env DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-v2 \
          || ${SUDO[@]+"${SUDO[@]}"} env DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin \
          || true
      fi
      ;;
    dnf)
      manager=dnf; command -v dnf >/dev/null 2>&1 || manager=yum
      ${SUDO[@]+"${SUDO[@]}"} "$manager" install -y curl tar
      if [[ "$MISSING_DOCKER" == 1 ]]; then
        repo_os=centos
        [[ "${ID:-}" == fedora ]] && repo_os=fedora
        [[ "${ID:-}" == rhel ]] && repo_os=rhel
        if [[ "$manager" == dnf ]]; then
          ${SUDO[@]+"${SUDO[@]}"} dnf install -y dnf-plugins-core
          ${SUDO[@]+"${SUDO[@]}"} dnf config-manager --add-repo "https://download.docker.com/linux/$repo_os/docker-ce.repo" \
            || ${SUDO[@]+"${SUDO[@]}"} dnf config-manager addrepo --from-repofile="https://download.docker.com/linux/$repo_os/docker-ce.repo"
        else
          ${SUDO[@]+"${SUDO[@]}"} yum install -y yum-utils
          ${SUDO[@]+"${SUDO[@]}"} yum-config-manager --add-repo "https://download.docker.com/linux/$repo_os/docker-ce.repo"
        fi
        ${SUDO[@]+"${SUDO[@]}"} "$manager" install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
      else
        ${SUDO[@]+"${SUDO[@]}"} "$manager" install -y docker-compose-plugin || true
      fi
      ;;
    pacman) ${SUDO[@]+"${SUDO[@]}"} pacman -Sy --noconfirm --needed curl tar docker docker-compose ;;
    zypper) ${SUDO[@]+"${SUDO[@]}"} zypper --non-interactive install curl tar docker docker-compose ;;
  esac
}
if ((${#missing[@]} > 0)); then install_linux_dependencies; fi
release_json="$(curl --fail --silent --show-error --location \
  --header 'Accept: application/vnd.github+json' \
  --header 'User-Agent: spaceworks-curl-installer' "$RELEASE_API")" \
  || die "Could not read the latest tagged GitHub release."
RELEASE_TAG="$(printf '%s' "$release_json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
VERSION="${RELEASE_TAG#v}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}$ ]] \
  || die "GitHub returned an unexpected latest release tag: ${RELEASE_TAG:-<empty>}"
say "Pinned release: $RELEASE_TAG."
if ! docker compose version >/dev/null 2>&1; then
  compose_json="$(curl --fail --silent --show-error --location \
    --header 'Accept: application/vnd.github+json' \
    --header 'User-Agent: spaceworks-curl-installer' \
    https://api.github.com/repos/docker/compose/releases/latest)"
  compose_tag="$(printf '%s' "$compose_json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
  [[ "$compose_tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Could not resolve a Docker Compose V2 plugin release."
  ${SUDO[@]+"${SUDO[@]}"} install -m 0755 -d /usr/local/lib/docker/cli-plugins
  ${SUDO[@]+"${SUDO[@]}"} curl --fail --silent --show-error --location \
    "https://github.com/docker/compose/releases/download/$compose_tag/docker-compose-linux-$ARCH" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  ${SUDO[@]+"${SUDO[@]}"} chmod 755 /usr/local/lib/docker/cli-plugins/docker-compose
fi
if ! docker info >/dev/null 2>&1; then
  if [[ "$HOST_KIND" == linux ]] && command -v systemctl >/dev/null 2>&1; then
    ${SUDO[@]+"${SUDO[@]}"} systemctl enable --now docker >/dev/null 2>&1 || true
  fi
fi
if ! docker info >/dev/null 2>&1; then
  if [[ "$HOST_KIND" == linux && "$(id -u)" != 0 && ${#SUDO[@]} -gt 0 ]] && ${SUDO[@]+"${SUDO[@]}"} docker info >/dev/null 2>&1; then
    if [[ "$RUN_INSTALLED_AS_ROOT" == 0 ]]; then
      operator="$(id -un)"
      ${SUDO[@]+"${SUDO[@]}"} usermod -aG docker "$operator" \
        || die "Run sudo usermod -aG docker '$operator' (if the group is missing, run sudo groupadd docker first), sign out and back in, then rerun."
      command -v sg >/dev/null 2>&1 || die "Docker access needs refreshed group membership. Sign out, sign in, and rerun this installer."
      sg docker -c 'docker info >/dev/null 2>&1' || die "Docker is still inaccessible inside the docker group. Sign out and back in, test docker info, and rerun; if needed, configure Docker's socket group before retrying."
      USE_DOCKER_GROUP=1
      say "Added $operator to the docker group; setup will use that group for this run."
    fi
  else
    die "Docker is inaccessible. Run sudo systemctl start docker; then test sudo docker info. For user access, run sudo usermod -aG docker \$(id -un), sign out and back in, then rerun."
  fi
fi
docker compose version >/dev/null 2>&1 || die "Docker Compose V2 is still unavailable after dependency setup."
run_installed() {
  local command="$1"
  if [[ "$RUN_INSTALLED_AS_ROOT" == 1 ]]; then
    ${RUN_ROOT[@]+"${RUN_ROOT[@]}"} bash -c "cd '$INSTALL_DIR' && $command" < /dev/tty
  elif [[ "$USE_DOCKER_GROUP" == 1 ]]; then
    sg docker -c "cd '$INSTALL_DIR' && $command" < /dev/tty
  else
    (cd "$INSTALL_DIR" && bash -c "$command" < /dev/tty)
  fi
}
ARCHIVE="$(mktemp)"
curl --fail --silent --show-error --location \
  "https://github.com/$REPOSITORY/archive/refs/tags/$RELEASE_TAG.tar.gz" -o "$ARCHIVE"
parent="$(dirname "$INSTALL_DIR")"
if [[ ! -d "$parent" ]]; then ${RUN_ROOT[@]+"${RUN_ROOT[@]}"} mkdir -p -- "$parent"; CREATED_PARENT=1; fi
STAGE_DIR="$(${RUN_ROOT[@]+"${RUN_ROOT[@]}"} mktemp -d "$parent/.spaceworks-stage.XXXXXX")"
${RUN_ROOT[@]+"${RUN_ROOT[@]}"} tar -xzf "$ARCHIVE" -C "$STAGE_DIR" --strip-components=1 --no-same-owner
if [[ "$(id -u)" != 0 && ${#RUN_ROOT[@]} -gt 0 ]]; then
  ${RUN_ROOT[@]+"${RUN_ROOT[@]}"} chown -R "$(id -u):$(id -g)" "$STAGE_DIR"
fi
[[ -f "$STAGE_DIR/setup.sh" && -f "$STAGE_DIR/docker-compose.prod.yml" \
  && -f "$STAGE_DIR/scripts/update.sh" && -f "$STAGE_DIR/scripts/spaceworks-compose.sh" \
  && -f "$STAGE_DIR/scripts/module-selection.sh" && -f "$STAGE_DIR/scripts/update-lock.sh" \
  && -f "$STAGE_DIR/scripts/install-owner.sh" && -f "$STAGE_DIR/scripts/setup-first-run.sh" \
  && -f "$STAGE_DIR/scripts/filter-main-releases.py" && -f "$STAGE_DIR/scripts/update-rollback-host.sh" \
  && -f "$STAGE_DIR/scripts/validate-compose-wrapper.py" && -f "$STAGE_DIR/scripts/restore.sh" ]] \
  || die "The pinned release archive is missing required installer files."
${RUN_ROOT[@]+"${RUN_ROOT[@]}"} chmod 755 "$STAGE_DIR/install.sh" "$STAGE_DIR/scripts/spaceworks-compose.sh"
# Re-entry uses the pinned release's updater/helpers, never an older installed updater.
case "$ACTION" in
  update) update_options="--force --no-module-changes" ;;
  modules) update_options="--modules-only" ;;
  both) update_options="--force --modules" ;;
esac
if [[ "$ACTION" != fresh ]]; then
  run_installed "SPACEWORKS_UPDATE_INSTALL_DIR='$INSTALL_DIR' bash '$STAGE_DIR/scripts/update.sh' $update_options"
  exit 0
fi
if [[ "${EMPTY_INSTALL_DIR:-0}" == 1 ]]; then ${RUN_ROOT[@]+"${RUN_ROOT[@]}"} rmdir -- "$INSTALL_DIR"; fi
${RUN_ROOT[@]+"${RUN_ROOT[@]}"} mv -- "$STAGE_DIR" "$INSTALL_DIR"
STAGE_DIR=""
run_installed "MAKERSPACE_IMAGE_TAG='$VERSION' bash setup.sh"
run_installed "printf '%s\\n' '$VERSION' > .spaceworks-version"
say "Installed SpaceWorks $VERSION in $INSTALL_DIR."
