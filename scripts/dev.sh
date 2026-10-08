#!/usr/bin/env bash
# The single developer entry point; requires Docker and Bash (Git Bash on Windows).
#   up [args]       Compose up -d; retire live and remove successful one-shots.
#   down [args]     Compose down; volumes persist unless you pass -v.
#   test [args]     Pytest in disposable Postgres/Redis/MinIO; default args: -q.
#   e2e [args]      Seed the running dev stack and run host Playwright (needs npm).
#   <other> [args]  Forward verbatim to Compose: logs, exec, run, ps, restart, etc.
# Restart affects long-running services only; up recreates the four one-shots.
# E2E creates a fresh tenant each run; dev.sh down -v wipes the dev database.
# Compose chain: base, machine override if present, then the dev layer.
set -euo pipefail
export MSYS_NO_PATHCONV=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
HOST_ROOT="$ROOT"
if command -v cygpath >/dev/null 2>&1; then
  HOST_ROOT="$(cygpath -m "$ROOT")"
fi
files=(-f docker-compose.yml)
[[ ! -f docker-compose.override.yml ]] || files+=(-f docker-compose.override.yml)
files+=(-f docker-compose.dev.yml)
compose() { docker compose "${files[@]}" "$@"; }

up() {
  local failed=0 svc cid result
  local one_shots=(orchestration-init migrate orchestration-ready createbuckets)
  # A failed `up` can leave a one-shot created but never started, and `docker wait` on that
  # blocks forever, so stop here and let compose's own error stand.
  compose up -d "$@"
  if [[ "$(docker inspect -f '{{.State.Running}}' spaceworks-live 2>/dev/null || true)" == true ]]; then
    docker rm -f spaceworks-live
  fi
  for svc in "${one_shots[@]}"; do
    cid="$(compose ps -a -q "$svc")"
    [[ -n "$cid" ]] || continue
    if ! result="$(docker wait "$cid")" || [[ "$result" != 0 ]]; then
      echo "$svc failed; inspect it with: dev.sh logs $svc" >&2
      failed=1
    fi
  done
  [[ "$failed" == 0 ]] || return 1
  compose rm -f "${one_shots[@]}"
}

test_suite() {
  RUN="spaceworks-test-$$-$(date +%s)"
  cleanup() {
    local status=$? containers=()
    set +e
    mapfile -t containers < <(docker ps -aq --filter "label=spaceworks.test=$RUN")
    if ((${#containers[@]})); then docker rm -fv "${containers[@]}" >/dev/null; fi
    docker network rm "$RUN" >/dev/null 2>&1
    exit "$status"
  }
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  if ! docker image inspect spaceworks-backend >/dev/null 2>&1; then
    echo "Missing spaceworks-backend image; build it with: dev.sh up --build" >&2
    return 1
  fi
  docker network create "$RUN" >/dev/null
  docker run -d --name "$RUN-db" --network "$RUN" --network-alias db \
    --label "spaceworks.test=$RUN" --tmpfs /var/lib/postgresql/data \
    -e POSTGRES_USER=makerspace -e POSTGRES_PASSWORD=makerspace \
    -e POSTGRES_DB=makerspace_manager postgres:16 >/dev/null
  docker run -d --network "$RUN" --network-alias redis \
    --label "spaceworks.test=$RUN" redis:7-alpine >/dev/null
  docker run -d --network "$RUN" --network-alias minio \
    --label "spaceworks.test=$RUN" -e MINIO_ROOT_USER=minioadmin \
    -e MINIO_ROOT_PASSWORD=minioadmin quay.io/minio/minio:latest server /data >/dev/null
  local deadline=$((SECONDS + 60))
  until docker exec "$RUN-db" pg_isready -U makerspace -d makerspace_manager >/dev/null 2>&1; do
    if ((SECONDS >= deadline)); then echo "Test Postgres did not become ready" >&2; return 1; fi
    sleep 1
  done
  docker run --rm --network "$RUN" --label "spaceworks.test=$RUN" \
    --entrypoint /bin/sh quay.io/minio/mc:latest -c '
      until mc alias set local http://minio:9000 minioadmin minioadmin; do sleep 1; done;
      mc mb --ignore-existing local/evidence;
      mc version enable local/evidence;
      mc anonymous set none local/evidence;
      mc mb --ignore-existing local/public-images;
      mc version enable local/public-images;
      mc anonymous set download local/public-images;
    '
  local keys api_key audit_key
  keys="$(docker run --rm --label "spaceworks.test=$RUN" --entrypoint python spaceworks-backend -c \
    'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode()); print(Fernet.generate_key().decode())')"
  api_key="${keys%%$'\n'*}"
  audit_key="${keys##*$'\n'}"
  local TEST_ENV=(
    -e DATABASE_URL=postgres://makerspace:makerspace@db:5432/makerspace_manager
    -e SECRET_KEY=test-only -e DEBUG=True -e TRUSTED_PROXY_COUNT=0 -e PYTHONDONTWRITEBYTECODE=1
    -e ALLOWED_HOSTS=localhost,127.0.0.1 -e CELERY_BROKER_URL=redis://redis:6379/0
    -e AWS_S3_ENDPOINT_URL=http://minio:9000 -e AWS_S3_PUBLIC_ENDPOINT_URL=http://minio:9000
    -e PUBLIC_IMAGE_BASE_URL=http://minio:9000/public-images
    -e AWS_ACCESS_KEY_ID=minioadmin -e AWS_SECRET_ACCESS_KEY=minioadmin
    -e AWS_STORAGE_BUCKET_NAME=evidence -e PUBLIC_IMAGE_BUCKET=public-images
    -e STORAGE_PRESIGN_METHOD=post -e EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
    -e "API_CLIENT_ENC_KEY=$api_key" -e "AUDIT_MAC_MASTER_KEY=$audit_key"
  )
  # The tombstone suite reads TOMBSTONED_APPS at settings import, so it must be set
  # before pytest starts; forward it only when the caller exported it.
  if [[ -n "${TOMBSTONED_APPS:-}" ]]; then
    TEST_ENV+=(-e "TOMBSTONED_APPS=$TOMBSTONED_APPS")
  fi
  (($#)) || set -- -q
  docker run --rm --network "$RUN" --label "spaceworks.test=$RUN" --entrypoint pytest \
    -v "$HOST_ROOT:/workspace" -w /workspace/backend \
    -v "$HOST_ROOT/scripts:/run/spaceworks-privileged-scripts" \
    "${TEST_ENV[@]}" spaceworks-backend -p no:cacheprovider "$@"
}

e2e() {
  local deadline=$((SECONDS + 60)) remaining
  until remaining=$((deadline - SECONDS)) && ((remaining > 0)) && \
    curl -sf --max-time "$remaining" http://localhost:8000/api/v1/health/ >/dev/null && \
    remaining=$((deadline - SECONDS)) && ((remaining > 0)) && \
    curl -sf --max-time "$remaining" http://localhost:5000/ >/dev/null; do
    if ((SECONDS >= deadline)); then
      echo "Dev stack is not ready; start it with: dev.sh up" >&2
      return 1
    fi
    sleep 1
  done
  compose exec -T backend python manage.py seed_e2e --write-json /tmp/e2e-seed.json
  docker cp spaceworks-backend:/tmp/e2e-seed.json "$HOST_ROOT/frontend/e2e/.seed.json"
  cd "$ROOT/frontend"
  E2E_API_URL=http://localhost:8000 E2E_BASE_URL=http://localhost:5000 \
    E2E_SEED_FILE="$HOST_ROOT/frontend/e2e/.seed.json" npx playwright test "$@"
}

case "${1:-}" in
  up) shift; up "$@" ;;
  down) shift; compose down "$@" ;;
  test) shift; test_suite "$@" ;;
  e2e) shift; e2e "$@" ;;
  *) compose "$@" ;;
esac
