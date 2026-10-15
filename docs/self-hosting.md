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
8 GiB of free disk, release availability, and existing state. Linux dependency
installation supports apt, dnf/yum, pacman and zypper families identified from `/etc/os-release`.

Running the installer as a normal sudo-capable user keeps the install owned by that user, including
under `/opt/spaceworks`; sudo handles privileged host setup and directory creation where needed.
Running `curl ... | sudo bash` or `sudo bash install.sh` creates a root-owned install and uses root for
setup, updates and the version marker. The optional runner service runs as the install owner;
automatic deploys require Linux with systemd. Rerunning the installer or updater as a normal sudo user
against a root-owned install re-enters as root; it does not transfer ownership.
Host Python is optional unless installing the runner, which needs Python 3 for release verification. Setup runs database URL configuration in the pulled backend image; the Compose
wrapper also validates inside that image when host Python is missing or older than 3.10, using the
caller's UID and supplementary groups to preserve the same ownership checks.

If `.spaceworks-version` already exists, pasting the command again offers update, module changes, both,
or cancel; it never reruns first-instance setup. A non-empty install root without the marker is refused.
An update rerun downloads the latest main archive and runs its updater against the existing
installation. After the database backup it replaces the closed host runtime bundle (scripts, Compose
layers and edge configuration), keeps replaced files in `backups/host-config-*`, and
refreshes the Compose trust records. `.env`, database/object volumes and backups stay in place.

## Deployment questionnaire and confirmation

The pinned archive is first unpacked in temporary storage. Its shared questionnaire asks hosting model
(one space, several `/m/<slug>` spaces, or subdomain platform), whether to run the website here, HTTPS,
standard/single-box containers, and bundled/external storage. It then asks the web address if needed,
makerspace name/subdomain, eight yes/no areas with immediate follow-up settings, a derived edition,
organization labels, quiet hours/digest defaults, staff MFA and admin identity/password,
optional Google/Stripe credentials, the GitHub repository to follow, and
"Install a GitHub Actions runner on this server for automatic deploys? [y/N]" (default No).
Only Linux with systemd supports runner installation; other hosts skip it.
The curl installer asks the repository before downloading that repository's questionnaire. Every prompt displays its
default; required values and invalid combinations are asked again.

One summary lists all answers (secrets hidden), services, DNS/proxy requirements and host actions, followed
by `Proceed? [Y/n]`. It shows whether the runner will be installed and explains:
"migrate builds the database tables. It runs once and stops. It's required."
"orchestration is a start-up safety check. It runs once and stops. It's required."
If requested, runner registration begins only after confirmation. No dependency
installation, Docker changes, install-directory creation, image pull or `.env` write occurs before yes. curl or wget and tar must already exist to read the questionnaire;
missing bootstrap utilities cause a read-only refusal with instructions. Ports are checked after the
answers: 80/443 for Caddy, 8080 for an existing proxy, 80 for plain HTTP, and 9000/9001 with bundled
storage (the SaaS layer keeps storage ports internal). Point DNS at the server before certificate issuance.
Wildcard tenant DNS is convenient, but certificates are issued individually for registered tenant hosts.

`bash setup.sh` from a fresh checkout asks the same questions first. A fetched install supplies a private
`.spaceworks-answers` file, mode 600, which setup reads without questions and removes after initial
configuration. Secrets travel through this file and container environment, never credential-bearing
command arguments. A failed run may retain the file privately for retry. `.env` remains mode 600.
Native Windows transports the confirmed answers through inherited process environment instead of a
file, because Git Bash cannot reliably represent POSIX mode 600 on NTFS.
Existing `.env` installations retain their topology; updates never repeat the deployment questionnaire.
Module-only reruns still use the live module selector without downloading a release.

Only the superadmin and operator-named makerspace are provisioned, along with configuration defaults.
Production setup never calls `seed_demo` or `seed_e2e`. The developer demo seeder refuses `DEBUG=False`
unless explicitly invoked with `--allow-production-demo`.

## API-only and external storage

Choose **No, API only** to host React on Netlify or another service. The installer requires HTTPS API
hosting, sets CORS/CSRF origins and the makerspace's verified `frontend_domain` to the first supplied
site. Additional origins are public origins; the first is the staff site. A shared multi-tenant staff site
is registered in `PLATFORM_STAFF_ORIGINS`. Set the external frontend's `VITE_API_URL` to
`https://<server-domain>/api` (for a platform, the apex or first tenant API subdomain works).

`SPACEWORKS_RUN_FRONTEND=no` adds `docker/compose.api-only.yml`: the website is behind an inactive
profile and nginx `api-edge` exposes API, docs/static and live-event routes, while `/control/` and internal
routes stay private. Automatic HTTPS adds `compose.api-only-edge.yml`, moves the public listener to
Caddy on 80/443, and removes its website dependency. With an existing reverse proxy, nginx binds only
`127.0.0.1:8080`; forward the public API domain there, preserving Host, client forwarding and
`X-Forwarded-Proto: https`. A normal local website behind an existing proxy uses the same loopback port.
Single box supports a local website over HTTP; choose standard containers for HTTPS, hosted platforms,
API-only or a source build.

For bundled Silo with HTTPS, point `files.<server-domain>` (or `files.<platform-domain>`) to the server.
Caddy serves this hostname automatically. With your own proxy, forward it to `127.0.0.1:9000`.
The Silo console stays at loopback 9001. Configure proxy upload-size limits for your evidence files.

Choose **External S3-compatible buckets** to set both backend/browser endpoint URLs, region, private
evidence bucket, public-image bucket, credentials, public image base URL and presign method.
`SPACEWORKS_STORAGE=external` adds `docker/compose.external-storage.yml`: `minio` and `createbuckets`
have inactive profiles, and backend/candidate/single-app dependencies no longer start them. All app
processes inherit external credentials through the base environment anchor. Provision private evidence
access, public image reads, bucket versioning and browser-origin CORS in the provider dashboard;
the installer never changes remote bucket policies. HTTPS sites require HTTPS storage/image URLs.
These overlays need Docker Compose 2.24.4 or newer (`!override` and `!reset`).

The primary layer (`none`, `tls`, `saas`, `single`) persists in `.spaceworks-layer`; frontend/storage
selectors persist in `.env`. The wrapper appends those overlays and validates the matching hashed
`compose-topology[-<layer>][-api-only][-external-storage].json` record. Source builds retain the selected
TLS/SaaS layer. Updates exclude the website from their image list when disabled; failed-update rollback,
explicit snapshot rollback and restore all reuse the same wrapper/topology. The live-event process is
included in image updates and writer fencing. Never activate `website-disabled` or `storage-disabled`
profiles manually on a deployment that selected those services off.

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

Production deploys run locally on the server, either from the release workflow's optional GitHub
Actions runner job or as the install owner:

```bash
bash scripts/update.sh --force
# Optional: deploy this exact published main release, never a draft or prerelease.
bash scripts/update.sh --force --version 0.9.1-main.42.a1b2c3d4e5f6
```

Without `--version`, the updater selects the newest published main release of `SPACEWORKS_REPOSITORY`.
A pinned version must match `X.Y.Z-main.<run>.<12-hex sha>` and exist as a published, non-draft,
non-prerelease release in that repository; unavailable or invalid versions refuse deployment.

### Install the runner and enable deploys

The installer asks whether to install a runner, default **No**, because GitHub configuration is also
required. Linux with systemd is supported. After confirmation, it asks silently for the short-lived
registration token from **GitHub repository Settings -> Actions -> Runners -> New self-hosted runner**.
The token is never echoed, persisted or passed in command-line arguments. The helper downloads the latest
`actions/runner` release for x64 or arm64 and verifies its SHA-256 against that release's published checksum
before extracting anything. Missing checksums and mismatches refuse installation.

The runner lives in `/opt/spaceworks-runner` by default, owned by the install owner, with label
`spaceworks-prod` and name `<hostname>-spaceworks`. Its `.env` sets `SPACEWORKS_DIR` to the installation;
the deploy job defaults to `/opt/spaceworks` if absent. The systemd service runs as the install owner,
who needs the same Docker access as manual updates (docker group or root).

After registration complete these GitHub steps:

1. **Settings -> Secrets and variables -> Actions -> Variables -> New repository variable**:
   set `SPACEWORKS_DEPLOY` to `true`.
2. **Settings -> Actions -> General -> Fork pull request workflows**:
   select **Require approval for all external contributors**.
3. **Settings -> Actions -> Runners**: confirm the runner is **Idle** with label `spaceworks-prod`.
4. For an organization, put it in a runner group restricted to this repository and, if the plan allows,
   to `.github/workflows/release.yml` on `refs/heads/main`.

The release workflow's final `deploy` job waits for published images and the visible GitHub release,
requires both `main` and `SPACEWORKS_DEPLOY=true`, uses the `production` environment, and serializes
deploys without cancelling an active one. Repositories without the variable never queue a runner job.
It runs the installed `scripts/update.sh --force --no-module-changes --version "$VERSION"`; it does not
check out source. You may add production environment protection rules later.

Existing-install menu updates do not register the runner again. Install or deliberately replace it with
`bash scripts/install-runner.sh`. Remove it with `bash scripts/install-runner.sh --remove`; this asks
silently for a short-lived removal token from GitHub and uninstalls its service and registration.
Before enabling a runner on an existing server, stop and uninstall any previous custom deployment
services and cron jobs. Updating the repository does not uninstall host-managed services. The updater
removes obsolete Compose containers when it replaces the application.

### SECURITY

This repository is public. [GitHub's security guidance](https://docs.github.com/en/actions/reference/security/secure-use#hardening-for-self-hosted-runners)
recommends self-hosted runners only for private repositories because
a fork's pull request can modify workflows to target your runner. A runner with Docker access has
effectively root control of the production server. Enabling the deploy variable alone does not protect
against a modified pull request workflow.

Required mitigations:

- Require approval for **all external contributors'** workflow runs, including returning contributors.
  Review workflow changes before approving a run.
- Register the runner to this repository only. For an organization, restrict its runner group to this
  repository and, where available, to `release.yml` on `refs/heads/main`.
- Never add the self-hosted label to any `pull_request`-triggered workflow. Other workflows, including
  `security-audit.yml`, stay on GitHub-hosted runners.
- Keep the deploy job free of `actions/checkout` and third-party actions. It runs only the installed
  updater, has empty GitHub token permissions, and receives its version through environment variables.
- Keep the runner updated; it auto-updates by default. Do not disable automatic updates.

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

Self-hosters follow their own fork's release workflow and register their own runner. Set
`SPACEWORKS_REPOSITORY=YourOwner/YourFork` during install (environment or questionnaire); it is persisted
in `.env`. Only a strict GitHub `owner/repo` value is accepted. The install source and release checks
follow that value. By default images come from
`ghcr.io/yourowner/spaceworks-backend` and `ghcr.io/yourowner/spaceworks-frontend`, using the lower-cased
repository owner. `MAKERSPACE_BACKEND_IMAGE` and `MAKERSPACE_FRONTEND_IMAGE` override those image names.
The fork's own release workflow must have run at least once so those images and a main release exist.
Register the runner in that fork and set the fork's own `SPACEWORKS_DEPLOY=true` repository variable;
apply all the security settings above. No upstream runner or setting is shared with forks.

For example:

```bash
curl -fsSL https://raw.githubusercontent.com/SpaceWorks-HQ/SpaceWorks/main/install.sh | \
  SPACEWORKS_REPOSITORY=YourOwner/YourFork bash
```

### Module changes

When run in a terminal, the updater can review the live area menu after the release is healthy.
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
Turning areas off retains their rows; setup and update never invoke the destructive purge command.
Inventory off keeps the six core modules and disables `loans.enabled`.
See [the area mapping](MODULES.md#areas-used-by-setup) and
[all questions and defaults](setup-for-makerspaces.md#area-follow-up-questions).
Use `--areas=events,reports` to select an exact area set; `--confirm-removals` acknowledges
retained-data uninstalls. Existing automation flags continue to work. Area application reads
JSON from stdin (`manage.py apply_setup_areas --answers-json -`), validates its settings,
and writes an audit for each change. Already matching answers are safe to apply again.
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
