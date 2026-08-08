# Lean-paid production deploy

This is the recommended always-on path for one makerspace: Supabase Pro Postgres
(about $25/mo), Render Starter for Django (about $7/mo), Cloudflare R2, optional
Brevo SMTP, static frontend hosting, and a free daily cron. Total baseline is about
$32/mo before custom domains. For the terse env matrix, see
`docs/supabase-deployment.md`.

## 1. Create Supabase Pro Postgres

Create a Supabase Pro project. Copy two database URLs:

- Direct or session-pooler URL on port 5432: use only for one-off migrations.
- Transaction pooler URL on port 6543: use as the runtime `DATABASE_URL`.

Set these runtime variables:

```env
DATABASE_URL=<supabase transaction pooler URL, port 6543>
MANAGED_POSTGRES=True
CONN_MAX_AGE=0
DISABLE_SERVER_SIDE_CURSORS=True
```

The transaction pooler is the right runtime path, but it cannot run Django
migrations reliably. Keep the direct/session URL available for the migration step.

## 2. Create Cloudflare R2 storage

Create an R2 bucket and an S3 API token with access to that bucket. Set both
endpoint variables to the R2 S3 API domain:

```env
AWS_STORAGE_BUCKET_NAME=<bucket>
AWS_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
AWS_S3_PUBLIC_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
AWS_ACCESS_KEY_ID=<r2 access key>
AWS_SECRET_ACCESS_KEY=<r2 secret key>
AWS_S3_REGION_NAME=auto
STORAGE_PRESIGN_METHOD=put
```

Do not use an `r2.dev` or custom public domain for either endpoint. This app signs
private upload/download URLs, and those signatures must be for the S3 API host.

In the R2 bucket CORS settings, allow the frontend origin for `PUT`, `GET`, and
`HEAD`. Add a lifecycle rule that expires stale objects under the `staging/`
prefix. Presigned PUT finalize is write-once, but abandoned uploads can leave
staging objects behind.

Create a second R2 bucket for public catalog images and enable public access on it
with an `r2.dev` or custom public domain:

```env
PUBLIC_IMAGE_BUCKET=<public-image-bucket>
PUBLIC_IMAGE_BASE_URL=https://<public-image-domain>
PUBLIC_IMAGE_MAX_BYTES=5242880
PUBLIC_IMAGE_URL_TTL_SECONDS=300
```

This bucket is intentionally anonymous-readable. Store only inventory item photos
and makerspace logo/cover images there; evidence and print files stay in the
private `AWS_STORAGE_BUCKET_NAME`.

With `STORAGE_PRESIGN_METHOD=put`, browsers upload images directly to this bucket,
so it needs its **own CORS rule** (separate from the evidence bucket): allow the
staff-console origin for `PUT`, `GET`, and `HEAD`. Add a `staging/`-prefix
lifecycle expiry rule here too — without CORS on the public bucket, item/logo/cover
image uploads fail in the browser even though evidence uploads work.

## 3. Configure Brevo SMTP, optional

If email is enabled, create a Brevo SMTP key and verify the sender address:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_PORT=587
EMAIL_HOST_USER=<brevo smtp login>
EMAIL_HOST_PASSWORD=<brevo smtp key>
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=Makerspace <noreply@example.org>
```

`EMAIL_BACKEND` is required. If it is not set to Django's SMTP backend, mail only
logs and `email_enabled()` reports off. Skipping email is supported: the "Forgot
password?" link is hidden, and the admin on-screen reset flow is the recovery path.

## 4. Deploy the app

Use `render.yaml` from the repository root as the Render Blueprint. It creates:

- a Render Starter Docker web service for the Django backend;
- a Render worker service for Celery email delivery;
- a Render Redis instance for the Celery broker;
- a static frontend service for the Vite app;
- an env var group matching `.env.production.example`.

Phase 3 email delivery uses Redis + a Celery worker, so the production baseline now
includes that paid Redis/worker capacity. The Django web service only records the
email log and enqueues delivery; the worker performs SMTP delivery and retries.

This blueprint deploys a **single-tenant, self-hosted** instance, which is what almost
everyone wants. Multi-tenant managed hosting — tenant subdomains under a platform domain,
tenant self-serve custom domains, fair-use resource limits — is a separate blueprint at
`deploy/render.managed.yaml`, and you have to point Render at it deliberately. The two are
kept apart because managed mode is dormant by default and must stay that way: it turns on
when `PLATFORM_DOMAIN_SUFFIX` is non-blank, so an optional variable in this file would put
a live switch one stray value away from a self-hosted deployment, and the failure is quiet
— you would start handing tenants subdomains of a domain you may not control.

You can also put the same Vite build on Cloudflare Pages or Netlify and set its
runtime `config.js` `apiUrl` or `VITE_API_URL` to the backend API root.

Paste the production values into the Render dashboard. Set:

```env
DEBUG=False
ALLOWED_HOSTS=<render backend host>
CORS_ALLOWED_ORIGINS=<frontend origin>
CSRF_TRUSTED_ORIGINS=https://<render backend host>
ENABLE_HTTPS=true
TRUST_X_FORWARDED_PROTO=true
PUBLIC_APP_BASE_URL=<frontend origin>
```

Behind a CDN or reverse proxy, also set `TRUSTED_PROXY_COUNT` to the number of trusted
proxies in front of the backend (e.g. `1` for a single nginx/Cloudflare hop). Without it,
per-IP rate limits key on the proxy's IP (all users share one bucket → false lockouts) or
trust a spoofable `X-Forwarded-For`. Leave it unset when the backend is reached directly.

Start with `SECURE_HSTS_SECONDS=0` or a short value while verifying domains. When
`SECURE_HSTS_SECONDS > 0`, the app also enables HSTS `includeSubDomains` and
`preload`; do not preload until the entire apex domain and every subdomain are
HTTPS-ready.

The backend start command is Gunicorn only:

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 60
```

It intentionally does not run migrations because runtime `DATABASE_URL` points at
the transaction pooler. A VPS using `docker-compose.prod.yml` is the alternative
deployment path.

## 5. Run one-off setup

Run migrations against the direct/session URL on port 5432, not the runtime
transaction pooler:

```powershell
cd backend
$env:DATABASE_URL="<supabase direct-or-session URL, port 5432>"; python manage.py migrate
```

Then create the first superadmin and makerspace:

```powershell
cd backend
$env:DATABASE_URL="<supabase direct-or-session URL, port 5432>"; python manage.py setup_instance
```

On a Linux shell, use `DATABASE_URL="<direct-or-session URL>" python manage.py migrate`
and the same prefix for `setup_instance`.

## 6. Schedule return reminders

Set a long random `CRON_SECRET`, then schedule a daily POST from cron-job.org,
GitHub Actions, or another free cron:

```text
POST https://<backend-host>/api/v1/internal/cron/return-reminders
X-Cron-Secret: <CRON_SECRET>
```

The endpoint returns 404 while `CRON_SECRET` is unset and 403 for the wrong secret.

## 7. Backups and secret rotation

Supabase Pro includes daily backups; set an RPO/RTO expectation for the makerspace
and run a restore drill periodically. Keep a manual fallback export:

```bash
pg_dump "<supabase direct-or-session URL>" --format=custom --file=makerspace-$(date +%Y%m%d).dump
```

Back up `API_CLIENT_ENC_KEY` offline. Losing it makes stored makerspace SMTP
passwords, Telegram tokens, and API-client secrets unreadable.

Rotation runbook:

- Supabase DB password: rotate in Supabase, update `DATABASE_URL`, run a one-off
  migration smoke check, redeploy.
- R2 keys: create a new S3 API token, update `AWS_ACCESS_KEY_ID` and
  `AWS_SECRET_ACCESS_KEY`, verify upload and signed download, then revoke the old key.
- Brevo SMTP key: create a new SMTP key, update `EMAIL_HOST_PASSWORD`, send a test
  email, then revoke the old key.
- Telegram token: rotate with BotFather, update the encrypted per-makerspace token
  or `TELEGRAM_BOT_TOKEN`, then re-register the webhook secret if needed.
- `SECRET_KEY`: rotate only during a maintenance window; it invalidates sessions
  and signed tokens.
- `API_CLIENT_ENC_KEY`: decrypt all encrypted fields with the old Fernet key,
  generate the new key, re-encrypt every value, update the env var, and verify
  SMTP/Telegram/API-client flows before deleting the old key.

## 8. Monitoring and manual cleanup

Monitor Render health, Supabase database size, R2 object count, failed email sends,
and the daily cron result. The readiness endpoint is:

```text
GET /api/v1/health/readiness/
```

Automatic immutable-row pruning is intentionally not built in this batch. Supabase
Pro's 8 GB database is ample for one makerspace, and traceability records should
not disappear without an explicit operator decision. If storage growth ever matters,
export the relevant audit/scan/evidence metadata, take a fresh `pg_dump`, verify
the restore, then run a manual cleanup with a maintenance note. Keep audit logs
append-only and preserve any evidence tied to active accountability workflows.
