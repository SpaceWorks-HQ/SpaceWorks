#!/bin/sh
# Process supervisor for the single-box image. Deliberately a shell script and not a
# supervisor daemon: the container must die when any essential process dies, so the
# orchestrator restarts the whole unit and no half-alive box serves requests without a
# worker or without its stream. Every Django process is launched through the fail-closed
# entrypoint with its own role, exactly as the multi-service compose files do.
set -eu

ENTRYPOINT="python /app/scripts/spaceworks_entrypoint.py"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://127.0.0.1:6379/0}"
export CACHE_URL="${CACHE_URL:-redis://127.0.0.1:6379/1}"
export LIVE_REDIS_URL="${LIVE_REDIS_URL:-$CELERY_BROKER_URL}"

# Runtime config for the SPA (TENANT_API_URL / TENANT_TOKEN), same script as the nginx image.
TENANT_CONFIG_PATH=/srv/www/config.js /app/allinone/write-config.sh

mkdir -p /var/lib/spaceworks/nginx/body /var/lib/spaceworks/nginx/proxy \
  /var/lib/spaceworks/nginx/fastcgi /var/lib/spaceworks/nginx/uwsgi /var/lib/spaceworks/nginx/scgi

pids=""
launch() {
  name="$1"; shift
  "$@" &
  pid=$!
  pids="$pids $pid"
  echo "[allinone] started $name (pid $pid)" >&2
}

# Redis first (broker, cache, live pub/sub): bound to loopback only, persisted under
# /var/lib/spaceworks/redis so rate-limit counters survive a restart.
launch redis redis-server --bind 127.0.0.1 --port 6379 --dir /var/lib/spaceworks/redis \
  --save 60 1 --appendonly no --loglevel warning
until redis-cli -h 127.0.0.1 ping >/dev/null 2>&1; do sleep 0.5; done

# Static files once, then the API, the SSE process, the worker and the scheduler loop.
$ENTRYPOINT --role management python manage.py collectstatic --noinput >/dev/null

launch backend $ENTRYPOINT --role backend gunicorn config.wsgi:application \
  --bind 127.0.0.1:8000 --workers "${GUNICORN_WORKERS:-3}" --timeout "${GUNICORN_TIMEOUT:-60}" \
  --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 \
  --access-logfile - --error-logfile -
launch live $ENTRYPOINT --role backend gunicorn config.wsgi:application \
  --bind 127.0.0.1:8001 -k gthread --threads "${LIVE_THREADS:-32}" --timeout 0 \
  --access-logfile - --error-logfile -
launch worker $ENTRYPOINT --role worker celery -A config worker -l info \
  --concurrency "${CELERY_CONCURRENCY:-2}"
launch cron $ENTRYPOINT --role cron sh -c \
  "while true; do python manage.py run_scheduled_tasks --due-only || true; python manage.py flush_email_outbox || true; sleep ${CRON_INTERVAL_SECONDS:-900}; done"
launch nginx nginx -c /app/allinone/nginx.conf

# Exit as soon as any child exits; the container restart policy brings the box back whole.
wait -n $pids
status=$?
echo "[allinone] a process exited with status $status; stopping the box" >&2
kill $pids 2>/dev/null || true
exit "$status"
