# Self-Hosting Guide

This project is Docker-first for operators who do not want to build Django or Vite locally.

## Pinned curl install

The supported fresh-install path needs no Git clone:

```bash
curl -fsSL https://raw.githubusercontent.com/SpaceWorks-HQ/SpaceWorks/main/install.sh | bash
```

The installer defaults to `/opt/spaceworks`; override it on the `bash` process with, for example,
`curl -fsSL https://raw.githubusercontent.com/SpaceWorks-HQ/SpaceWorks/main/install.sh | SPACEWORKS_DIR="$HOME/SpaceWorks" bash`.
It resolves the latest published, non-draft, non-prerelease GitHub release built from `main`,
from `SPACEWORKS_REPOSITORY` (default `SpaceWorks-HQ/SpaceWorks`), downloads that tag's archive, and pins the published backend/frontend images to its immutable version.
The accepted version format is `X.Y.Z-main.<run>.<12-hex sha>`; there is no release channel choice.
Before mutating the host it checks x86_64/aarch64 support, distribution/dependency handling, Docker,
ports 80/9000/9001, 8 GiB of free disk, release availability, and existing state. Linux dependency
installation supports apt, dnf/yum, pacman and zypper families identified from `/etc/os-release`.

Running the installer as a normal sudo-capable user keeps the install owned by that user, including
under `/opt/spaceworks`; sudo handles privileged host setup and directory creation where needed.
Running `curl ... | sudo bash` or `sudo bash install.sh` creates a root-owned install and uses root for
setup, updates and the version marker. The deploy service runs as the install owner; non-systemd
hosts use that owner's request-consumer cron. Rerunning the installer or updater as a normal sudo user
against a root-owned install re-enters as root; it does not transfer ownership.
Host Python is optional. Setup runs database URL configuration in the pulled backend image; the Compose
wrapper also validates inside that image when host Python is missing or older than 3.10, using the
caller's UID and supplementary groups to preserve the same ownership checks.

If `.spaceworks-version` already exists, pasting the command again offers update, module changes, both,
or cancel; it never reruns first-instance setup. A non-empty install root without the marker is refused.
An update rerun downloads the latest main archive and runs its updater against the existing
installation. After the database backup it replaces the closed host runtime bundle (scripts, Compose
layers, edge configuration and receiver), keeps replaced files in `backups/host-config-*`, and
refreshes the Compose trust records. `.env`, database/object volumes and backups stay in place.

## Production Compose

Use the production Compose file when deploying published images:

```bash
cp .env.example .env
# Fill the required values, then provision the root-owned pointer/key/config state once.
bash scripts/init-host-orchestration.sh
scripts/spaceworks-compose.sh bundled up -d
```

Set these values before first boot:

```env
POSTGRES_PASSWORD=replace-with-a-strong-password
POSTGRES_APP_PASSWORD=replace-with-a-different-strong-password
SECRET_KEY=replace-with-a-long-random-secret
ALLOWED_HOSTS=inventory.example.org
CORS_ALLOWED_ORIGINS=https://inventory.example.org
MINIO_ROOT_USER=replace-with-a-random-access-key
MINIO_ROOT_PASSWORD=replace-with-a-long-random-secret
AWS_S3_PUBLIC_ENDPOINT_URL=https://files.inventory.example.org
MINIO_CORS_ALLOWED_ORIGINS=https://inventory.example.org
MAKERSPACE_IMAGE_TAG=latest
```

Optional image overrides:

```env
MAKERSPACE_BACKEND_IMAGE=ghcr.io/spaceworks-hq/spaceworks-backend
MAKERSPACE_FRONTEND_IMAGE=ghcr.io/spaceworks-hq/spaceworks-frontend
```

### Build from source (explicit opt-in)

Release images are published to GHCR and `setup.sh` pulls them by default. A developer with a full
source tree can explicitly build locally:

```bash
bash setup.sh --build
```

For a guided first run that generates secrets, the atomic pointer and `.env`, use the curl installer or
`setup.sh` at the repo root (see [setup-for-makerspaces.md](setup-for-makerspaces.md)).

Windows has two explicit support tiers. Install, normal Compose operation, upgrades and module changes
work natively with Docker Desktop plus Git Bash. In-place restore, backup import and compound recovery
must run under WSL2: their security boundary depends on Linux AF_UNIX sockets and root-owned-file trust
semantics and is deliberately not emulated on Windows.

> The frontend container's nginx proxies `/api/`, `/static/`, and the docs routes to the backend.
> The **single published port (80)** serves the public app, the React staff console at `/admin`,
> and Swagger. The Django control plane is mounted at `/control/` on the backend and is
> intentionally **not exposed** on the public frontend port; access it only through direct backend
> access.

## First Run

Create the first superadmin and makerspace:

```bash
scripts/spaceworks-compose.sh bundled run --rm --no-deps backend --role management python manage.py setup_instance \
  --username admin \
  --email admin@example.org \
  --password "replace-with-a-strong-password" \
  --makerspace-name "My Makerspace"
```

The command is idempotent. It creates missing records and upgrades the named user to a superadmin if needed.

## Health Checks

Backend:

```text
GET /api/v1/health/
GET /api/v1/health/readiness/
```

The Compose files include health checks for Postgres, backend readiness, and frontend HTTP serving.

## Scheduled Jobs

Return reminder emails are sent by a management command. The bundled Compose profiles run it through the
role-aware image entrypoint. An external cron, systemd timer, Windows Task Scheduler, or provider scheduler
must additionally be disabled by its control plane unless the host restore marker is `normal` or
`acknowledged-normal` (or it must call the same host gate); otherwise that topology is refused because it
can retain credentials and bypass the
container marker. Once that fence is configured, schedule it every 15-60 minutes:

```bash
scripts/spaceworks-compose.sh bundled run --rm --no-deps backend --role management python manage.py send_return_reminders
```

The command is idempotent. It only sends reminders for issued or partially returned requests whose `return_due_at` is in the past and whose reminder has not already been sent. Requests returned before the due time are skipped.

## Updating

For installations made before this webhook updater shipped, rerun the installer once to replace the
host tooling. Subsequent updates can use the webhook or the manual command below.

Production deploys start with a GitHub **release published** webhook, or an operator running:

```bash
bash scripts/update.sh --force
```

Setup asks for the GitHub repository to follow (`SpaceWorks-HQ/SpaceWorks` by default) and whether to
set up automatic deploys. It saves `SPACEWORKS_REPOSITORY` and generates a strong
`SPACEWORKS_DEPLOY_WEBHOOK_SECRET` in the private `.env`, showing the secret once. On Linux with
systemd it installs `spaceworks-deploy.path` and `spaceworks-deploy.service`. The service runs as the
install owner. On other hosts setup prints a one-minute cron command for
`scripts/deploy-from-request.sh`; this consumes queued webhook requests and does not poll GitHub.

In the repository you follow, configure **Settings -> Webhooks -> Add webhook**:

1. **Payload URL:** `https://<your address>/hooks/deploy`.
2. **Content type:** `application/json`.
3. **Secret:** paste the secret printed once by setup.
4. Choose **Let me select individual events**, select **Releases** only, and enable **Active**.

The server must be reachable from GitHub over HTTPS. The existing nginx/Caddy web front sends
`POST /hooks/deploy` to an internal receiver. The receiver checks the raw-body HMAC signature, repository,
non-draft/non-prerelease `published` action and tag `vX.Y.Z-main.<run>.<12-hex sha>`; it answers signed
GitHub pings, deduplicates deliveries and limits request rate. It writes an atomic request containing
only the validated tag and delivery ID. It has no database, Docker socket, `.env` or host marker access.

The host consumes and coalesces requests and runs `update.sh --force --no-module-changes`. The payload
only triggers a check: the updater independently selects the newest eligible published main release
from GitHub. Release publication happens after the release workflow has published both images.
There is no in-app update panel, weekly update cron or release polling.

The updater holds the portable update lock (and shared host operation lock where `flock` is available),
creates a PostgreSQL dump in `backups/pre-update-<timestamp>.sql.gz`, pulls the pinned images, then runs
Compose `up -d`: orchestration-init, migrate and orchestration-ready gate the application startup.
After readiness succeeds it writes `.spaceworks-version` and removes successfully finished run-once
containers. Failed jobs remain available for inspection. Database dumps are retained for 14 days and
contain rows, not uploaded object bytes; keep separate object-storage backups.

If deployment or readiness fails after replacement begins, the updater starts the previous application
images and checks readiness again. A successful image rollback restores the previous version marker
and removes successfully completed run-once jobs. **Forward database migrations remain applied**;
the SQL backup is retained and is never restored automatically. Keep migrations compatible with the
previous application release. If rollback fails, leave the failed containers for inspection and recover
in a maintenance window using the database backup and previous image tag. See
[Database recovery after an update](update-recovery.md).

### Following your fork

Self-hosters who do not own the upstream repository configure their own fork's webhook. Set
`SPACEWORKS_REPOSITORY=YourOwner/YourFork` during install (environment or questionnaire); it is persisted
in `.env`. Only a strict GitHub `owner/repo` value is accepted. The install source, release checks and
webhook repository check follow that value. By default images come from
`ghcr.io/yourowner/spaceworks-backend` and `ghcr.io/yourowner/spaceworks-frontend`, using the lower-cased
repository owner. `MAKERSPACE_BACKEND_IMAGE` and `MAKERSPACE_FRONTEND_IMAGE` override those image names.
The fork's own release workflow must have run at least once so those images and a main release exist.

For example:

```bash
curl -fsSL https://raw.githubusercontent.com/SpaceWorks-HQ/SpaceWorks/main/install.sh | \
  SPACEWORKS_REPOSITORY=YourOwner/YourFork bash
```

### Module changes

When run in a terminal, the updater can review the live module tick list after the release is healthy.
Automatic deployments use `--no-module-changes`. Explicit operator forms are:

```bash
bash scripts/update.sh --force --modules
bash scripts/update.sh --force --no-module-changes
bash scripts/update.sh --modules-only --makerspace my-space
bash scripts/update.sh --all-modules --without=printing,payments \
  --makerspace my-space --confirm-removals
bash scripts/update.sh --all-modules --all-makerspaces
```

With several makerspaces select `--makerspace <slug>` or explicitly use `--all-makerspaces`.
Unticking modules retains their rows; setup and update never invoke the destructive purge command.
Native Windows Git Bash uses the crash-recoverable PID/timestamp directory lock when `flock` is absent.
A live or unreadable owner is never discarded automatically; use `--override-lock` only after checking
no update is active. Backup restore supervisors require Linux/WSL2 host trust and locking semantics.

## Publishing new images (maintainers)

Every push to `main` runs `release.yml`, publishes matching backend and frontend images, and creates a
GitHub Release titled `SpaceWorks vX.Y.Z-main.<run>.<12-hex sha>` using the version series from `VERSION`.
Its tag identifies the exact build used by the updater. When both images succeed for the current branch
head, the workflow promotes them to the rolling `:X.Y`, `:main`, and `:latest` tags, then prunes older GHCR
image versions. GitHub releases and their tags remain permanently available.
The current and immediately previous builds remain available so a failed deployment can roll its
application containers back automatically.

The root **`VERSION`** file selects the semantic release series. Edit it (for example, to `1.0.0`) only
when starting a new series; the workflow adds the run number and commit SHA to every release automatically.

The `spaceworks-backend` / `spaceworks-frontend` GHCR packages must be set to **Public** (org → Packages)
so operators can `docker compose pull` without authenticating.

## HTTPS & security hardening

TLS-dependent settings are **env-gated, not `DEBUG`-gated**, so the default HTTP stack works out of
the box. The default frontend nginx does **not** trust inbound `X-Forwarded-Proto`; it forwards only
its own scheme to Django.

For a real domain with automatic TLS, use the Caddy overlay:

```env
PUBLIC_DOMAIN=inventory.example.org
CSRF_TRUSTED_ORIGINS=https://inventory.example.org
AWS_S3_PUBLIC_ENDPOINT_URL=https://files.inventory.example.org
MINIO_CORS_ALLOWED_ORIGINS=https://inventory.example.org
```

```bash
SPACEWORKS_COMPOSE_LAYER=tls scripts/spaceworks-compose.sh bundled --profile tls up -d
```

The overlay enables `ENABLE_HTTPS=true` and `TRUST_X_FORWARDED_PROTO=true` for the backend. Caddy is
then the trusted TLS boundary: `/api`, `/static`, and docs paths go directly to Django with
`X-Forwarded-Proto: https`, while the React app goes to the frontend container. Keep any direct
backend/frontend HTTP ports private when the TLS overlay is active.



Always-on protections (any transport): `django-axes` locks out brute-force admin logins
(`AXES_FAILURE_LIMIT`, keyed by ip+username), a scoped throttle limits the JWT login endpoint, the
public submit endpoint has its own anti-spam throttle + a honeypot, and a Content-Security-Policy is
sent on every response. The Django control plane at `/control/` is restricted to active
superusers only and must be reached through direct backend access, never through the public
frontend port.

Secrets (`SECRET_KEY`, `API_CLIENT_ENC_KEY`, makerspace Telegram bot tokens, makerspace SMTP
passwords) live only in the backend. `API_CLIENT_ENC_KEY` is the Fernet key that encrypts the
per-makerspace integration secrets at rest — **back it up and do not rotate it casually**, or
previously stored tokens/passwords can no longer be decrypted.

## Custom domain (self-host)

On a self-hosted instance (the default — `PLATFORM_DOMAIN_SUFFIX` is **blank**) you own both DNS and
the server, so a makerspace's custom domain is **trusted the moment a superadmin sets it** — there is
no DNS TXT challenge. (The TXT-verification flow only exists to defend the shared managed `space-works.tech`
box; it stays dormant here.) End-to-end:

1. **Point DNS at the server.** Create an `A`/`AAAA` record for the hostname (for example
   `tools.example.org`) pointing at this deployment's public IP.
2. **Enable automatic HTTPS.** Staff login on a custom domain requires HTTPS — the staff-auth
   allowlist only trusts the `https://` origin (localhost dev is the sole `http` exception). Set the
   TLS env and bring up the Caddy overlay:

   ```env
   PUBLIC_DOMAIN=tools.example.org
   CSRF_TRUSTED_ORIGINS=https://tools.example.org
   # Django's own host check (CommonMiddleware) is separate from the tenant host
   # middleware — add every custom hostname here or requests 400 with DisallowedHost.
   ALLOWED_HOSTS=localhost,127.0.0.1,tools.example.org
   ```

   ```bash
   SPACEWORKS_COMPOSE_LAYER=tls scripts/spaceworks-compose.sh bundled --profile tls up -d
   ```

   Caddy (`deploy/Caddyfile`) terminates HTTPS and forwards both the public site and the `/admin`
   staff console to this deployment.
3. **Set the domain in Settings.** As a **superadmin**, open the makerspace's Settings → **Custom
   domain**, enter the hostname, and Save. It shows **Active** immediately (no TXT record, no Verify
   step). Only a superadmin may set it — the staff-auth/CORS allowlist is process-global (not
   tenant-scoped), so on a multi-makerspace box an untrusted Space Manager must never be able to inject
   a globally-trusted origin. This holds even for a makerspace hidden from the superadmin
   (`superadmin_access_enabled=False`): to set its domain, have its Space Manager re-enable superadmin
   access, set the domain as the superadmin, then re-hide it.
4. **Point the branded frontend at this backend.** Set the frontend container's
   `TENANT_ORIGIN_BOOTSTRAP=true` (resolve the makerspace by request origin) **or**
   `TENANT_TOKEN=<public_code>`, plus `TENANT_API_URL=/api`. See
   [single-tenant-frontend.md](single-tenant-frontend.md).

If an instance flips from managed → self-host after deploy, run
`python manage.py reconcile_selfhost_domains` once to promote any existing custom domains to trusted
(the migration does this automatically on a fresh self-host deploy).

## Environment reference

The variables a self-hosted deployment usually decides are below. **The complete list —
every variable the backend reads, with its default — is
[environment-reference.md](environment-reference.md).**

| Variable | Required | Purpose |
|---|---|---|
| `POSTGRES_PASSWORD` | yes | Maintenance/owner database password; never used by application processes |
| `POSTGRES_APP_PASSWORD` | yes | Separate non-owner runtime database password used by backend/worker/beat/cron |
| `SECRET_KEY` | yes | Django cryptographic secret |
| `ALLOWED_HOSTS` | yes | Comma-separated hostnames the backend will serve |
| `DATABASE_URL` | no | Never put this in static `.env`; the atomic ops pointer is its only Compose source |
| `CORS_ALLOWED_ORIGINS` | no | Browser origins allowed to call the API |
| `API_CLIENT_ENC_KEY` | recommended | Fernet key encrypting integration secrets at rest |
| `MINIO_ROOT_USER` | yes | MinIO/S3 access key used by the backend |
| `MINIO_ROOT_PASSWORD` | yes | MinIO/S3 secret key used by the backend |
| `AWS_STORAGE_BUCKET_NAME` | no (default `evidence`) | Private object-storage bucket for evidence and print files |
| `PUBLIC_IMAGE_BUCKET` | no (default `public-images`) | Anonymous-read bucket for public item photos and makerspace logo/cover images |
| `PUBLIC_IMAGE_BASE_URL` | yes for public images | Browser public base URL for `PUBLIC_IMAGE_BUCKET` (for example `https://files.inventory.example.org/public-images`) |
| `PUBLIC_IMAGE_MAX_BYTES` | no (default `5242880`) | Maximum public image upload size |
| `PUBLIC_IMAGE_URL_TTL_SECONDS` | no (default `300`) | Presigned upload URL lifetime for public images |
| `AWS_S3_ENDPOINT_URL` | no (default `http://minio:9000`) | Backend-to-MinIO endpoint inside Compose |
| `AWS_S3_PUBLIC_ENDPOINT_URL` | yes for uploads | Browser-reachable MinIO/S3 endpoint used in presigned URLs |
| `MINIO_CORS_ALLOWED_ORIGINS` | yes for uploads | Comma-separated frontend origins allowed to POST/GET objects (sets MinIO's `MINIO_API_CORS_ALLOW_ORIGIN`; defaults to `*`) |
| `ENABLE_HTTPS` | no (default false) | Turns on SSL redirect, Secure cookies, HSTS |
| `TRUST_X_FORWARDED_PROTO` | no (default false) | Trusts `X-Forwarded-Proto` only for the TLS proxy overlay |
| `CSRF_TRUSTED_ORIGINS` | when HTTPS | `https://` origin(s) trusted for login POSTs |
| `AXES_FAILURE_LIMIT` | no (default 5) | Failed admin logins before lockout |
| `HTTP_PORT` | no (default 80) | Published frontend port |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | no | Global fallback SMTP (per-makerspace SMTP overrides it) |
| `MANAGED_POSTGRES` | no (default `False`) | `True` on managed Postgres (Supabase): purge suspends immutability triggers via a custom GUC instead of `session_replication_role` (which needs superuser) |
| `CONN_MAX_AGE` | no (default `60`) | Persistent DB connection lifetime in seconds; set `0` on the Supabase transaction pooler (port 6543), which hands back a different server connection per transaction |
| `CONN_HEALTH_CHECKS` | no (default `True`) | Verify a persistent connection before reuse so a restarted Postgres does not surface as a request error |
| `LOG_LEVEL`, `LOG_JSON` | no (`INFO`; JSON when `DEBUG` is off) | Log verbosity and format. Every line carries the `X-Request-ID` of the request that produced it |
| `LIVE_REDIS_URL`, `LIVE_MAX_STREAM_SECONDS` | no (Celery broker; `3600`) | Redis the live-update stream (`/api/v1/live/`) publishes and subscribes on, and the longest a single stream stays open before the browser reconnects. Empty makes the stream answer 503 and the console keeps polling |
| `METRICS_TOKEN` | no (unset) | Bearer token for `GET /api/v1/metrics/` (Prometheus text). Unset means the route answers 404 |
| `SENTRY_DSN` | no (unset) | Opt-in error tracking; the SDK is only imported when set, and PII is never sent |
| `DISABLE_SERVER_SIDE_CURSORS` | no (default `False`) | Set `True` on the Supabase transaction pooler (no server-side cursors) |
| `STORAGE_PRESIGN_METHOD` | no (default `post`) | `put` for Supabase Storage presigned PUT uploads (server re-validates size at attach) |
| `CRON_SECRET` | no (default empty) | Enables `POST /api/v1/internal/cron/return-reminders` (header `X-Cron-Secret`); 404s while unset |
| `DEVICE_SIGNATURE_MAX_SKEW_SECONDS`, `DEVICE_NONCE_TTL_SECONDS`, `DEVICE_ENROLLMENT_TTL_SECONDS` | no (`300`, `86400`, `900`) | Enrolled-device protocol (module `devices`): signed-request clock skew, replay-nonce lifetime (must be at least twice the skew, or startup refuses with `devices.E003`) and one-time enrollment lifetime. The backend must sit behind a server that exposes the raw request target (gunicorn `RAW_URI`, uWSGI `REQUEST_URI` or ASGI); see [device-protocol.md](device-protocol.md) |

> **Supabase free-tier deployment** (managed Postgres + Storage, env-toggled, demo/pilot scope):
> see **[supabase-deployment.md](supabase-deployment.md)** for the full runbook. All five vars
> above default to the self-hosted behavior, so this Compose stack is unaffected unless you set them.

## Object Storage

Production Compose includes Silo (`pgsty/silo`, the maintained fork of the archived MinIO server; it keeps
the `MINIO_*` variables, ports and data layout, so existing `minio_data` volumes carry over unchanged) because the backend stores evidence photos and 3D-print files in
S3-compatible object storage by default. The backend talks to MinIO at `http://minio:9000`; browsers
use `AWS_S3_PUBLIC_ENDPOINT_URL` in presigned upload/download URLs, so that value must be reachable
from staff/requester browsers.

Public catalog images use a separate `PUBLIC_IMAGE_BUCKET` that is anonymous-readable by design.
The bundled Compose bootstrap creates it, sets `download` policy, and applies the same upload CORS
policy. Keep evidence and print files in the private `AWS_STORAGE_BUCKET_NAME`; only item photos and
makerspace logo/cover images belong in the public bucket.

For HTTPS deployments, put MinIO behind the same TLS proxy as the frontend, for example:

```env
AWS_S3_PUBLIC_ENDPOINT_URL=https://files.inventory.example.org
MINIO_CORS_ALLOWED_ORIGINS=https://inventory.example.org
```

If you expose MinIO directly on a LAN during a local pilot, set `AWS_S3_PUBLIC_ENDPOINT_URL` to the
server address and port that browsers can reach, for example `http://192.168.1.20:9000`. The MinIO
console binds to `127.0.0.1:9001` by default; keep it private or put it behind authenticated VPN/admin
access.

## Backups

Operational data lives in Postgres and object files live in the `minio_data` Docker volume. Back up
both before upgrades:

```bash
scripts/spaceworks-compose.sh bundled exec -T db \
  pg_dump -U makerspace makerspace_manager > backup-$(date +%F).sql

mkdir -p backups
scripts/spaceworks-compose.sh bundled run --rm --entrypoint sh \
  -v "$PWD/backups:/backup" \
  minio \
  -c 'tar -czf /backup/minio-$(date +%F).tgz -C /data .'
```

Also keep a copy of your `.env` (it holds `API_CLIENT_ENC_KEY`, without which encrypted integration
secrets are unrecoverable, and the MinIO credentials needed to read object backups).

Restore order is database first, then object files. Stop the stack, restore the Postgres dump into the
`db` service, unpack the MinIO archive into the `minio_data` volume, then start the stack and check
`/api/v1/health/readiness/`.

## Tenant Frontends

One backend can serve **many makerspaces**. A makerspace without its own server can be hosted as an
additional tenant on another makerspace's instance — each tenant gets its own makerspace record,
public URL/slug, branding, and (optionally) its own branded domain, all isolated by makerspace
scoping. To give a tenant its own branded site, set its **Custom domain**
(`Makerspace.frontend_domain`) in the staff console Settings tab; that single field drives CORS,
bootstrap resolution, and the staff-auth allowlist. See `docs/single-tenant-frontend.md`.

Browser frontends must use publishable configuration only. Do not place HMAC secrets in JavaScript bundles.

Use `GET /api/v1/bootstrap?tenant=<public-code>` or `GET /api/v1/bootstrap?slug=<makerspace-slug>`
(or simply serve the branded site from its `frontend_domain`, which bootstrap resolves by origin) to load:

- makerspace identity
- enabled modules and workflows
- theme and branding
- publishable public API hints

The React public and staff frontends use `enabled_modules` as live navigation gates. If a tenant does
not see a workflow, check the makerspace module flags first: `self_checkout` gates public
self-checkout and staff direct handout, `printing` gates 3D-printing workflows, `stocktake` gates
stocktake, `containers` gates container tools, `qr_management` gates QR tools/scanner, and reports
appear for `reports` or printing-related workflows.

A makerspace's `frontend_domain` and its `cors_allowed_origins` (API-client origins) are used for
per-tenant browser access; only the `frontend_domain` origin may hold a staff session.

## The single-box install

`setup.sh` asks "How should it run?". **Single box** runs nginx, the built frontend, gunicorn, the live
update stream, a Celery worker, the scheduler loop and Redis in ONE container (`spaceworks-allinone`,
built from `Dockerfile.allinone`) beside Postgres and MinIO. It is the same code and the same fail-closed
process entrypoint per role; it only reduces what an operator has to run. The choice is persisted in
`.spaceworks-layer`, which `scripts/spaceworks-compose.sh` reads so updates keep the shape. To switch by
hand: `SPACEWORKS_COMPOSE_LAYER=single scripts/spaceworks-compose.sh bundled up -d` (or write `single`
to `.spaceworks-layer`). The container listens on 8080 internally and is published on `HTTP_PORT`; the
Django control plane (`/control/`) is still not proxied through it. Redis state lives in the
`allinone_state` volume so rate-limit counters survive a restart; queued deliveries do not need to (tasks
acknowledge late and are re-enqueued on commit).


Connected printer delivery uses `DEVICE_COMMAND_LEASE_SECONDS=60` and `DEVICE_COMMAND_MAX_ATTEMPTS=10`. These positive operational knobs govern acknowledgement and bounded delivery retries. An acknowledged print may finish after its delivery lease expires. Device key rotation/revocation invalidates prior command ownership. Automatic terminal application defaults off per printer binding; staff review uses existing machine scope and charging rules.
