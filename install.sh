#!/usr/bin/env bash
# Pinned, no-git SpaceWorks installer.
set -euo pipefail

REPOSITORY="SpaceWorks-HQ/SpaceWorks"
RELEASE_API="https://api.github.com/repos/$REPOSITORY/releases/latest"
INSTALL_DIR="${SPACEWORKS_DIR:-/opt/spaceworks}"
MIN_FREE_KB=$((8 * 1024 * 1024))
RUN_ROOT=()
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
    "${RUN_ROOT[@]}" rm -rf -- "$STAGE_DIR" 2>/dev/null || true
  fi
  [[ -z "$ARCHIVE" ]] || rm -f -- "$ARCHIVE"
  if [[ "$CREATED_PARENT" == 1 ]]; then
    "${RUN_ROOT[@]}" rmdir -- "$(dirname "$INSTALL_DIR")" 2>/dev/null || true
  fi
}
trap cleanup EXIT

case "$INSTALL_DIR" in
  ""|/|*"'"*) die "SPACEWORKS_DIR must be a specific path and cannot contain a single quote." ;;
esac

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
    command -v sudo >/dev/null 2>&1 || die "Missing ${missing[*]} and sudo is unavailable. Install them as root, then rerun."
    RUN_ROOT=(sudo)
  fi
  say "After preflight, the $PACKAGE_FAMILY family installer will install/ensure: curl, tar, Docker Engine, and Docker Compose V2."
else
  say "Dependencies are already present."
  if [[ "$HOST_KIND" == linux && "$(id -u)" != 0 && ! -w "$(dirname "$INSTALL_DIR")" ]]; then
    command -v sudo >/dev/null 2>&1 || die "Writing $INSTALL_DIR requires root and sudo is unavailable."
    RUN_ROOT=(sudo)
  fi
fi
if command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1; then
  if [[ "$HOST_KIND" == linux ]]; then
    say "Docker is installed but stopped/inaccessible; after preflight the installer will start it or configure docker-group access."
  else
    die "Docker Desktop is installed but not running. Start it and wait until it is ready, then rerun; no state was changed."
  fi
fi

if [[ -f "$INSTALL_DIR/.spaceworks-version" ]]; then
  ACTION="$(prompt $'Existing SpaceWorks install detected.\n  1) Update to latest release\n  2) Change modules\n  3) Update and change modules\n  4) Cancel\nChoose [4]: ')"
  ACTION="${ACTION:-4}"
  case "$ACTION" in
    1) ACTION=update ;;
    2) ACTION=modules ;;
    3) ACTION=both ;;
    4) say "Cancelled; existing deployment was not changed."; exit 0 ;;
    *) die "Invalid menu choice; existing deployment was not changed." ;;
  esac
  [[ -f "$INSTALL_DIR/scripts/update.sh" ]] || die "The version marker exists but scripts/update.sh is missing. Repair the install manually."
  if [[ "$(id -u)" != 0 && ! -w "$INSTALL_DIR" ]]; then
    command -v sudo >/dev/null 2>&1 || die "The existing install is not writable and sudo is unavailable."
    RUN_ROOT=(sudo)
    RUN_INSTALLED_AS_ROOT=1
  fi
elif [[ -e "$INSTALL_DIR" ]]; then
  if [[ -d "$INSTALL_DIR" && -z "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
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

if [[ "$ACTION" != modules ]]; then
  release_json="$(curl --fail --silent --show-error --location \
    --header 'Accept: application/vnd.github+json' \
    --header 'User-Agent: spaceworks-curl-installer' "$RELEASE_API")" \
    || die "Could not read the latest tagged GitHub release."
  RELEASE_TAG="$(printf '%s' "$release_json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
  VERSION="${RELEASE_TAG#v}"
  [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}$ ]] \
    || die "GitHub returned an unexpected latest release tag: ${RELEASE_TAG:-<empty>}"
  say "Pinned release: $RELEASE_TAG."
fi
say "All preflight checks passed; state-changing work starts now."

install_linux_dependencies() {
  case "$PACKAGE_FAMILY" in
    apt)
      "${RUN_ROOT[@]}" apt-get update
      "${RUN_ROOT[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y curl tar
      [[ "$MISSING_DOCKER" == 0 ]] \
        || "${RUN_ROOT[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io
      if [[ "$MISSING_COMPOSE" == 1 ]]; then
        "${RUN_ROOT[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-v2 \
          || "${RUN_ROOT[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin \
          || true
      fi
      ;;
    dnf)
      manager=dnf; command -v dnf >/dev/null 2>&1 || manager=yum
      "${RUN_ROOT[@]}" "$manager" install -y curl tar
      if [[ "$MISSING_DOCKER" == 1 ]]; then
        repo_os=centos
        [[ "${ID:-}" == fedora ]] && repo_os=fedora
        [[ "${ID:-}" == rhel ]] && repo_os=rhel
        if [[ "$manager" == dnf ]]; then
          "${RUN_ROOT[@]}" dnf install -y dnf-plugins-core
          "${RUN_ROOT[@]}" dnf config-manager --add-repo "https://download.docker.com/linux/$repo_os/docker-ce.repo" \
            || "${RUN_ROOT[@]}" dnf config-manager addrepo --from-repofile="https://download.docker.com/linux/$repo_os/docker-ce.repo"
        else
          "${RUN_ROOT[@]}" yum install -y yum-utils
          "${RUN_ROOT[@]}" yum-config-manager --add-repo "https://download.docker.com/linux/$repo_os/docker-ce.repo"
        fi
        "${RUN_ROOT[@]}" "$manager" install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
      else
        "${RUN_ROOT[@]}" "$manager" install -y docker-compose-plugin || true
      fi
      ;;
    pacman) "${RUN_ROOT[@]}" pacman -Sy --noconfirm --needed curl tar docker docker-compose ;;
    zypper) "${RUN_ROOT[@]}" zypper --non-interactive install curl tar docker docker-compose ;;
  esac
}
if ((${#missing[@]} > 0)); then install_linux_dependencies; fi

if ! docker compose version >/dev/null 2>&1; then
  compose_json="$(curl --fail --silent --show-error --location \
    --header 'Accept: application/vnd.github+json' \
    --header 'User-Agent: spaceworks-curl-installer' \
    https://api.github.com/repos/docker/compose/releases/latest)"
  compose_tag="$(printf '%s' "$compose_json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
  [[ "$compose_tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Could not resolve a Docker Compose V2 plugin release."
  "${RUN_ROOT[@]}" install -m 0755 -d /usr/local/lib/docker/cli-plugins
  "${RUN_ROOT[@]}" curl --fail --silent --show-error --location \
    "https://github.com/docker/compose/releases/download/$compose_tag/docker-compose-linux-$ARCH" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  "${RUN_ROOT[@]}" chmod 755 /usr/local/lib/docker/cli-plugins/docker-compose
fi

if ! docker info >/dev/null 2>&1; then
  if [[ "$HOST_KIND" == linux ]] && command -v systemctl >/dev/null 2>&1; then
    "${RUN_ROOT[@]}" systemctl enable --now docker >/dev/null 2>&1 || true
  fi
fi
if ! docker info >/dev/null 2>&1; then
  if [[ "$HOST_KIND" == linux && "$(id -u)" != 0 ]] && "${RUN_ROOT[@]}" docker info >/dev/null 2>&1; then
    operator="$(id -un)"
    "${RUN_ROOT[@]}" usermod -aG docker "$operator"
    command -v sg >/dev/null 2>&1 || die "Docker was installed, but group membership needs a new login. Sign out, sign in, and rerun this installer."
    USE_DOCKER_GROUP=1
    say "Added $operator to the docker group; setup will use that group for this run."
  else
    die "Docker is installed but not running or not accessible. Start Docker, then rerun."
  fi
fi
docker compose version >/dev/null 2>&1 || die "Docker Compose V2 is still unavailable after dependency setup."

run_installed() {
  local command="$1"
  if [[ "$RUN_INSTALLED_AS_ROOT" == 1 ]]; then
    "${RUN_ROOT[@]}" bash -c "cd '$INSTALL_DIR' && $command" < /dev/tty
  elif [[ "$USE_DOCKER_GROUP" == 1 ]]; then
    sg docker -c "cd '$INSTALL_DIR' && $command" < /dev/tty
  else
    (cd "$INSTALL_DIR" && bash -c "$command" < /dev/tty)
  fi
}
case "$ACTION" in
  update) run_installed "bash scripts/update.sh --force --no-module-changes"; exit 0 ;;
  modules) run_installed "bash scripts/update.sh --modules-only"; exit 0 ;;
  both) run_installed "bash scripts/update.sh --force --modules"; exit 0 ;;
esac

ARCHIVE="$(mktemp)"
curl --fail --silent --show-error --location \
  "https://github.com/$REPOSITORY/archive/refs/tags/$RELEASE_TAG.tar.gz" -o "$ARCHIVE"
parent="$(dirname "$INSTALL_DIR")"
if [[ ! -d "$parent" ]]; then "${RUN_ROOT[@]}" mkdir -p -- "$parent"; CREATED_PARENT=1; fi
STAGE_DIR="$("${RUN_ROOT[@]}" mktemp -d "$parent/.spaceworks-stage.XXXXXX")"
"${RUN_ROOT[@]}" tar -xzf "$ARCHIVE" -C "$STAGE_DIR" --strip-components=1
[[ -f "$STAGE_DIR/setup.sh" && -f "$STAGE_DIR/docker-compose.prod.yml" \
  && -f "$STAGE_DIR/scripts/update.sh" && -f "$STAGE_DIR/scripts/spaceworks-compose.sh" \
  && -f "$STAGE_DIR/scripts/module-selection.sh" && -f "$STAGE_DIR/scripts/update-lock.sh" ]] \
  || die "The pinned release archive is missing required installer files."
"${RUN_ROOT[@]}" chmod 755 "$STAGE_DIR/install.sh" "$STAGE_DIR/scripts/spaceworks-compose.sh"
if [[ "${EMPTY_INSTALL_DIR:-0}" == 1 ]]; then "${RUN_ROOT[@]}" rmdir -- "$INSTALL_DIR"; fi
"${RUN_ROOT[@]}" mv -- "$STAGE_DIR" "$INSTALL_DIR"
STAGE_DIR=""
if [[ "$(id -u)" != 0 && ${#RUN_ROOT[@]} -gt 0 ]]; then
  "${RUN_ROOT[@]}" chown -R "$(id -u):$(id -g)" "$INSTALL_DIR"
fi

run_installed "MAKERSPACE_IMAGE_TAG='$VERSION' bash setup.sh"
printf '%s\n' "$VERSION" > "$INSTALL_DIR/.spaceworks-version"
say "Installed SpaceWorks $VERSION in $INSTALL_DIR."
