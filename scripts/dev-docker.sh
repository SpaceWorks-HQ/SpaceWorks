#!/usr/bin/env bash
# Run the entire stack in Docker with live reload — db, redis, minio, Django,
# Celery worker/beat and the Vite dev server. Nothing needs to be installed on
# the host beyond Docker itself.
#
#   ./scripts/dev-docker.sh up -d --build      # first run (builds images)
#   ./scripts/dev-docker.sh up -d              # afterwards
#   ./scripts/dev-docker.sh logs -f backend
#   ./scripts/dev-docker.sh exec backend python manage.py seed_demo
#   ./scripts/dev-docker.sh restart worker beat
#   ./scripts/dev-docker.sh down
#
# Frontend: http://localhost:5000   API/admin: http://localhost:8000/control/
#
# Any argument is forwarded verbatim to `docker compose`, so this is a drop-in
# prefix for every compose subcommand.
#
# Why a wrapper exists: passing -f to `docker compose` turns OFF the automatic
# merge of docker-compose.override.yml, so the whole file chain has to be spelled
# out. The order matters — the machine-specific override supplies infrastructure
# port remaps, and the dev layer comes last so its app-service commands, ports and
# bind mounts win over the production-shaped defaults.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

files=(-f docker-compose.yml)
if [[ -f docker-compose.override.yml ]]; then
  files+=(-f docker-compose.override.yml)
fi
files+=(-f docker-compose.dev.yml)

exec docker compose "${files[@]}" "$@"
