# Running on Supabase free tier (managed-Postgres mode)

The backend ships with a **self-hosted default** (local Postgres + MinIO via Docker) and an
opt-in **managed mode** for Supabase-style platforms, switched entirely by environment
variables. Every variable below defaults to the self-hosted behavior, so the bundled Docker
stack is unaffected unless you set them.

> Scope check: a 100%-free Supabase deployment is realistic for a **demo / small pilot**, not a
> dependable production setup — see `docs/performance-and-supabase-report.md`. Supabase cannot
> host Django itself; you still run the Django process somewhere (Render / PythonAnywhere / etc.).

## Env toggle matrix

| Variable | Default (self-hosted) | Supabase / managed |
|----------|----------------------|--------------------|
| `MANAGED_POSTGRES` | `False` — purge suspends triggers with `session_replication_role` (needs DB superuser) | `True` — purge uses the custom `app.allow_immutable_delete` GUC (no superuser) |
| `CONN_MAX_AGE` | `0` | `0` on the transaction pooler (port 6543); a higher value only on a direct/session connection |
| `DISABLE_SERVER_SIDE_CURSORS` | `False` | `True` on the transaction pooler |
| `STORAGE_PRESIGN_METHOD` | `post` — MinIO/S3 browser POST policy (upload-time `content-length-range`) | `put` — Supabase Storage S3 presigned PUT (size re-validated server-side at attach) |
| `CRON_SECRET` | `""` — cron endpoint 404s (disabled) | a long random secret — enables the reminder trigger endpoint |

## 1. Database

1. Create the Supabase project and grab its connection strings.
2. **Run migrations against the DIRECT or session-pooler URL** (port 5432) — the transaction
   pooler can't run the prepared statements migrations need.
3. Point the running app's `DATABASE_URL` at the **transaction pooler** (port 6543) and set
   `CONN_MAX_AGE=0` + `DISABLE_SERVER_SIDE_CURSORS=True`.
4. Set `MANAGED_POSTGRES=True`. This is required: makerspace **purge** otherwise tries
   `SET LOCAL session_replication_role='replica'`, which Supabase forbids (no superuser).
   In managed mode purge instead sets the transaction-scoped `app.allow_immutable_delete`
   GUC that the append-only/immutability triggers honor for DELETE only (UPDATE stays
   blocked; FK triggers stay on and Django deletes the graph in dependency order).
5. **500 MB cap:** audit logs, QR/box scan events, evidence rows, and print/stock history grow
   unbounded. Add a retention/export policy before relying on the free DB. (Pruning those
   immutable tables also requires managed mode's GUC.)

## 2. Object storage (Supabase Storage)

1. Create a Storage bucket; set its name as `AWS_STORAGE_BUCKET_NAME`.
2. Set `AWS_S3_ENDPOINT_URL` **and** `AWS_S3_PUBLIC_ENDPOINT_URL` to the Supabase S3 endpoint
   (`https://<project>.storage.supabase.co/storage/v1/s3`), region in `AWS_S3_REGION_NAME`,
   and the Supabase S3 access key/secret (server-side only — they bypass RLS).
3. Configure bucket **CORS** in the Supabase dashboard (the MinIO `mc cors` bootstrap doesn't
   apply). Allow your frontend origin for `PUT, GET, HEAD`.
4. Set `STORAGE_PRESIGN_METHOD=put`. Evidence + print uploads then use presigned **PUT**, and
   the backend re-validates object size at attach time (`1 ≤ size ≤ *_MAX_BYTES`) since PUT has
   no upload-time `content-length-range`.

### How PUT mode closes the overwrite window
A presigned PUT URL carries no upload-time size policy, and the key it names stays writable
until the URL expires (`EVIDENCE_URL_TTL_SECONDS` / `PRINT_URL_TTL_SECONDS`, default 300s). PUT
mode therefore never presigns the final key. The client uploads to a **staging key**, and
`finalize_upload` (`backend/apps/evidence/storage.py`) does the promotion server-side:

1. HEAD the staging object and reject a size outside `1 ≤ size ≤ *_MAX_BYTES`.
2. Server-side copy staging → the final key, then delete staging.
3. **Re-HEAD the final object** and delete it if the size drifted.

Step 3 is what makes the window closed rather than merely narrow. The final key is never
client-writable, so its post-copy size is authoritative — a racing oversized PUT to the still-
writable staging key between steps 1 and 2 promotes an object that step 3 then rejects. The
recorded `size_bytes` cannot disagree with the stored object.

Operationally you should still keep the TTLs short and watch Storage usage against the free
tier's 1 GB cap, but the size contract holds in PUT mode exactly as it does for POST, where
S3's `content-length-range` condition enforces it at upload time.

Create a second **public** Storage bucket for catalog imagery and set:

```env
PUBLIC_IMAGE_BUCKET=public-images
PUBLIC_IMAGE_BASE_URL=https://<project>.supabase.co/storage/v1/object/public/public-images
PUBLIC_IMAGE_MAX_BYTES=5242880
PUBLIC_IMAGE_URL_TTL_SECONDS=300
```

Only inventory item photos and makerspace logo/cover images belong in this public bucket. Evidence
photos and print files must remain in the private `AWS_STORAGE_BUCKET_NAME`.

## 3. Scheduled return reminders

`pg_cron` can only run SQL, so it can't call `manage.py send_return_reminders`. Instead:

1. Set `CRON_SECRET` to a long random value.
2. Configure the scheduler control plane to disable the job unless the SpaceWorks host marker is `normal`
   or `acknowledged-normal`; a remote scheduler is not fenced by the image entrypoint and is unsupported
   without this.
3. Schedule a daily `POST https://<your-django-host>/api/v1/internal/cron/return-reminders`
   with header `X-Cron-Secret: <CRON_SECRET>` from GitHub Actions cron, cron-job.org, or
   Supabase `pg_cron` + `pg_net`. The endpoint **404s** until `CRON_SECRET` is set and returns
   **403** on a wrong secret; the management command still works for manual runs.

## 4. Email & Telegram

- Per-makerspace + platform SMTP send from the Django host. Free hosts often block outbound
  SMTP — use a transactional email API's SMTP endpoint (Resend/Brevo/Mailgun free tier) via the
  existing `EMAIL_*` vars, or verify the host allows 587/465.
- Telegram outbound is HTTPS and works from most hosts; inbound webhooks need a stable public
  HTTPS URL (a sleeping free host can drop callbacks).

## 5. Secrets

Set `SECRET_KEY`, `API_CLIENT_ENC_KEY` (Fernet), Supabase DB + S3 keys, SMTP secrets, and the
Telegram token as host env vars. **Back up `API_CLIENT_ENC_KEY` offline** — losing it makes every
encrypted field (API-client secrets, makerspace SMTP passwords, Telegram tokens) unreadable.

## 6. Free-tier reliability

Free Supabase projects pause after ~7 days idle and free Django hosts sleep, which can delay the
reminder cron and Telegram responsiveness. Acceptable for a demo; for real use, pay for the
Django host and/or Supabase Pro.
