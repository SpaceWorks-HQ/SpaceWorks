#!/usr/bin/env bash
# Run the Playwright end-to-end suite against a host-topology stack on spare ports.
#
#   ./scripts/e2e-local.sh            # seed, start Django (:8100) + Vite (:5100), run, stop
#   E2E_KEEP=1 ./scripts/e2e-local.sh # leave the servers up afterwards for debugging
#
# Ports 8100/5100 are deliberately NOT the dev ports (8000/5000), so this can run next to a
# running dev stack. Postgres/Redis/MinIO come from the same infrastructure dev-local.sh uses;
# override PG_PORT / MINIO_PORT / DATABASE_URL exactly as you would for `dev-local.sh test`.
# The suite seeds and RESETS the `e2e-space` makerspace only; nothing else in the database
# is touched, and the command refuses to run against a database that is not DEBUG.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
E2E_API_PORT="${E2E_API_PORT:-8100}"
E2E_WEB_PORT="${E2E_WEB_PORT:-5100}"
export E2E_API_URL="http://localhost:${E2E_API_PORT}"
export E2E_BASE_URL="http://localhost:${E2E_WEB_PORT}"
export E2E_SEED_ALLOWED=1
export CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-http://localhost:${E2E_WEB_PORT}}"
# The suite signs in several times per run from one IP and the rate-limit counters live in the
# shared Redis, so the production login throttle (10/min) would trip on the second run.
export THROTTLE_LOGIN="${THROTTLE_LOGIN:-200/min}"

cleanup() {
  if [[ "${E2E_KEEP:-0}" != "1" ]]; then
    [[ -n "${VITE_PID:-}" ]] && kill "$VITE_PID" 2>/dev/null || true
    [[ -n "${DJANGO_PID:-}" ]] && kill "$DJANGO_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

"$ROOT/scripts/dev-local.sh" manage migrate --noinput >/dev/null
"$ROOT/scripts/dev-local.sh" manage seed_e2e --reset --write-json "$ROOT/frontend/e2e/.seed.json"

"$ROOT/scripts/dev-local.sh" manage runserver "0.0.0.0:${E2E_API_PORT}" --noreload >"${TMPDIR:-/tmp}/e2e-django.log" 2>&1 &
DJANGO_PID=$!
(
  cd "$ROOT/frontend"
  # The app calls the API by absolute URL (VITE_API_URL, default :8000), not through the Vite
  # proxy, so point it at this run's Django or the browser talks to whatever else is on 8000.
  VITE_API_URL="${E2E_API_URL}/api" VITE_DEV_PROXY_TARGET="$E2E_API_URL" npx vite --port "$E2E_WEB_PORT" --strictPort >"${TMPDIR:-/tmp}/e2e-vite.log" 2>&1
) &
VITE_PID=$!

for _ in $(seq 1 60); do
  curl -sf "${E2E_API_URL}/api/v1/health/" >/dev/null 2>&1 && curl -sf "${E2E_BASE_URL}/" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf "${E2E_API_URL}/api/v1/health/" >/dev/null || { echo "Django did not come up; see ${TMPDIR:-/tmp}/e2e-django.log" >&2; exit 1; }
curl -sf "${E2E_BASE_URL}/" >/dev/null || { echo "Vite did not come up; see ${TMPDIR:-/tmp}/e2e-vite.log" >&2; exit 1; }

cd "$ROOT/frontend"
npx playwright test "$@"
