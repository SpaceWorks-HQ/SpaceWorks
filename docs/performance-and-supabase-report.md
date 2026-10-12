# Backend Performance + Supabase Free-Tier Report

> Generated 2026-06-19 from three parallel Codex (gpt-5.5) read-only audits.
> Agents: backend performance, Supabase DB compatibility, Supabase infra/storage feasibility.
> Every finding cites `file:line`. Nothing in this report has been changed in code yet.

---

## Part 1 — Backend Performance

### Verdict
The app is functionally sound but carries the classic DRF performance debt: **`SerializerMethodField` N+1s** and **missing composite indexes** on the hot list/report endpoints, plus **heavy synchronous work in the request thread** (email, Telegram, ZIP, XLSX). None are correctness bugs; all are latency/throughput wins.

### Ranked top 10 (do these first)
1. **Composite indexes on `HardwareRequest`** for queue/report filters — `models.py:80` only has `(makerspace, status)`, but queues order by `-created_at/-issued_at/-updated_at` (`queue_views.py:32,58,87,121`) and reports by `issued_at/closed_at` (`operations/reports.py:89,101`). Add `(makerspace, status, -created_at)`, `(makerspace, status, -issued_at, -created_at)`, `(makerspace, status, -updated_at, -created_at)`, `(makerspace, status, -closed_at)`. **High**
2. **`PrintPrinterSerializer` filtered-prefetch N+1** — `serializers_printers.py:70`. `get_active_spool/_queue/get_current_request/get_is_free/...` call `.filter()` on related managers, bypassing the `prefetch_related` in `views_printers.py:45`. Use `Prefetch(..., to_attr=...)` or annotate `is_free`/queue minutes with `Exists`/`Sum`. **High**
3. **`PrintRequest` indexes** — `models.py:299` has none. Add `(requester, -created_at)`, `(bucket, status, -created_at)`, `(bucket, payment_status, status)`; consider denormalizing `makerspace` onto `PrintRequest` with `(makerspace, status, -created_at)`. Covers `views_requests.py:36,83-108`, `public_views.py:244`, `reports.py:289`. **High**
4. **Defer out-of-band work from the request thread** — Telegram + email run in `on_commit` but still in-process (`notifications.py:152,201`; Telegram has a 5s blocking timeout at `integrations/telegram.py:44`). Same for QR ZIP (`views_qr_batches.py:100`) and XLSX (`views_reports.py:179-186`). Move to a durable outbox / Celery / RQ. **High**
5. **Ledger full in-memory load + Python sort** — `ledger.py:7` loads all outstanding rows, builds dicts, sorts in Python; `views_reports.py:160` does `len(rows)` after full materialization, no pagination. Order in SQL, `.values()`-project, paginate. **High**
6. **Direct-loan `request.items` N+1** — `self_checkout_serializers.py:22` queries `obj.request.items.select_related("product")` per loan; `direct_loan_views.py:33` doesn't prefetch it. Add `Prefetch("request__items", ...)`. **High**
7. **Operations indexes** — `StockTransfer`/`StocktakeSession`/`QrPrintBatch` (`operations/models.py:10,41,129`) lack `(makerspace, -created_at)` / `(makerspace, status, -started_at)` for their list views (`views_transfers.py:29`, `views_stocktake.py:36`, `views_qr_batches.py:43`). **Med**
8. **Cache RBAC hidden/archived sets per request** — `rbac.py:163,174` (`superadmin_hidden_makerspace_ids()` / `archived_makerspace_ids()`) hit the DB repeatedly across permission checks, reports, and scoped querysets. Cache per request or short Redis cache invalidated on makerspace update/archive. **Med**
9. **`BoxSerializer.get_qr_code_id` N+1** — `boxes/serializers.py:28` runs a `QrCode.objects.filter().first()` per box; affects `operations/views_containers.py:34,108`. Annotate with `Subquery` or prefetch active box QR. **Med**
10. **`CONN_MAX_AGE`** — `settings.py:88` `DATABASES = {"default": env.db()}` has no persistent connections. Set `CONN_MAX_AGE` (e.g. 60) + `CONN_HEALTH_CHECKS=True`. **Med** *(but see Supabase pooler caveat in Part 2)*

### Other findings (11–20)
- **`QrScanEvent` indexes** missing — `boxes/models.py:160`; add `(makerspace, qr_code, -created_at)`, `(makerspace, context)`. **Med**
- **`_summary` per-metric queries** — `operations/reports.py:53-69` runs separate `.count()`/`.aggregate()` per metric; collapse into conditional aggregation. **Med**
- **Filament reports loop in Python** — `printing/reports.py:179,239`; use `Sum(Greatest(F("initial")-F("remaining"),0))`. **Med**
- **Report exports materialize everything** — `views_reports.py:93,126`; stream CSV, use openpyxl write-only mode, background large exports. **High**
- **Public print submit does S3 HEAD inside the txn** — `public_workflow.py:96,114`; verify object size before opening the txn or defer to an async finalizer. **Med**
- **`procurement` list has `pagination_class = None`** — `procurement/views.py:42,45` + `created_by_username` without `select_related("created_by")` (`serializers.py:9,53`, export `views.py:166`). Restore pagination + select_related. **Med**
- **`require_module` double-fetches the makerspace** — `guards.py:7,11`; pass loaded objects / cache on request. **Med**
- **`staff_origin_scope` scans all makerspaces in Python** — `origin_scope.py:19-31`; parse host once and `frontend_domain__iexact=host, archived_at__isnull=True`. **Med**
- **Middleware re-resolves makerspace/ApiClient** the view resolves again — `inventory/middleware.py:88,190` (also reads `request.body` at :75); attach `request.public_makerspace`/`request.api_client` and reuse. **Med**

---

## Part 2 — Run Completely on Supabase Free Tier

**Two agents, two angles. Combined verdict: feasible only as a low-volume demo/pilot, NOT a dependable free production deployment.** Supabase replaces Postgres and (with code changes) MinIO, but **it cannot host Django**, and there is **one hard DB blocker**.

### 2A. Database compatibility — *not compatible as-is*

**Hard blocker:** the makerspace **hard-purge** path uses `SET LOCAL session_replication_role = 'replica'` (`apps/makerspaces/lifecycle.py:123-132`). That requires superuser/replication privilege, which **Supabase never grants to the project role**. Purge aborts before deleting anything, and the immutable-row deletes that follow (`lifecycle.py:155-161` for `BoxScan`/`QrScanEvent`/`RequesterAccountability`/`ReturnEvent`/`EvidencePhoto`, and `lifecycle.py:172` for `AuditLog`) hit their BEFORE-DELETE triggers and raise.

**Important nuance:** the append-only/immutability **triggers themselves are fine** on Supabase (creating PL/pgSQL functions + row triggers does not need superuser when run as the table owner — `audit/migrations/0002`, `evidence/migrations/0002`, `boxes/migrations/0004` & `0006`, `hardware_requests/migrations/0004`). Only the *trigger-bypass during purge* breaks.

**Not found (good news):** no `CREATE EXTENSION`, `ALTER SYSTEM`, `ALTER ROLE`, `DISABLE TRIGGER`, `LISTEN/NOTIFY`, advisory locks, or server-side cursors anywhere in app/config. Health check is just `SELECT 1` (`operations/views_health.py:26`).

**Pooler caveat:** README recommends the Supabase transaction-pooler URL, but `settings.py:88` is a bare `env.db()`. Transaction pooling forbids prepared statements — run `migrate` against the **direct/session-pooler** URL, and for transaction-pooler runtime keep `CONN_MAX_AGE=0`. *(This directly tempers perf-finding #10 — don't blindly raise `CONN_MAX_AGE` if you land on the transaction pooler.)*

**500 MB cap risk:** unbounded history tables — `AuditLog`, `EvidencePhoto` (keys only), `BoxScan`, `QrScanEvent`, `ReturnEvent`/`RequesterAccountability`, `ManualPrintLog`, `PrintRequest(File)`, stock transfers/adjustments, `PublicToolLoan`. Needs a retention/export policy before relying on free Postgres.

**Exact DB change list:**
1. Remove `SET LOCAL session_replication_role` from `lifecycle.py`.
2. Choose a purge policy: **(a)** disable hard purge on Supabase = archive-only *(minimal)*, or **(b)** relax DELETE triggers (keep UPDATE blocked) so an ORM purge can run.
3. Use direct/session-pooler URL for migrations; transaction-pooler runtime only with prepared statements off.
4. Add retention/export for the history tables.

### 2B. Infrastructure / storage — *demo-only*

| Area | Gap | Free-tier workaround |
|---|---|---|
| **Django runtime** (`docker-compose.yml:66`, `docker-compose.prod.yml:62`) | **Biggest gap.** Supabase runs Deno Edge Functions, not a long-lived Gunicorn/WSGI Django process. | Host Django on Render free web service (512MB/0.1 CPU/5GB egress) or PythonAnywhere free (restricted outbound). |
| **Object storage presigned POST** — evidence (`evidence/storage.py:39`, caller `views.py:69`) & printing (`printing/storage.py:51`, caller `public_views.py:153`) | Code uses boto3 `generate_presigned_post` with exact `Content-Type` + `content-length-range` policy. Supabase S3 supports `Put/Get/HeadObject` and signed URLs but **not** the browser POST-policy form. | Switch to presigned **PUT** against `https://<project>.storage.supabase.co/storage/v1/s3` + verify size after upload, **or** rewrite to Supabase signed-upload URLs (changes the frontend upload shape from `{url, fields}` POST to token upload). Keep server-side MIME/ext validation. |
| **Bucket bootstrap / CORS** (`docker-compose.yml:19,37`) | `mc mb` + `mc cors set` won't exist; Supabase S3 compat table excludes bucket-CORS endpoints. | Create bucket + set CORS via Supabase dashboard/API. |
| **S3 endpoint split** (`settings.py:131`, `evidence/storage.py:27`) | MinIO uses internal + public endpoints; Supabase uses one public hostname. | Point both `AWS_S3_ENDPOINT_URL` and `AWS_S3_PUBLIC_ENDPOINT_URL` at the Supabase S3 endpoint; keys are server-only (bypass RLS). |
| **Scheduled jobs** (`send_return_reminders.py:9`, `notifications.py:125`) | `pg_cron` only runs SQL — it can't call `manage.py`. | Add a protected Django endpoint and hit it from GitHub Actions schedule / cron-job.org / `pg_cron`+`pg_net`. |
| **Email** (`settings.py:193`, `integrations/email.py:9`, `printing/emails.py:35`) | App sends platform + per-makerspace SMTP; free hosts often block outbound SMTP. | Use an email API with a free tier, or verify 587/465 on the chosen host; don't promise arbitrary per-makerspace SMTP on a restricted host. |
| **Telegram** (`integrations/telegram.py:14`) | Outbound HTTPS is fine, but a sleeping free host delays/fails callbacks; inbound webhook needs a stable public HTTPS URL. | Keep in Django if the host stays awake, else proxy via an Edge Function. |
| **Secrets / Fernet** (`settings.py:225`, `apiclients/crypto.py:5`, `makerspaces/secrets.py:6`) | `API_CLIENT_ENC_KEY` decrypts API-client secrets, SMTP passwords, Telegram tokens — losing it bricks stored secrets. | Store `API_CLIENT_ENC_KEY`/`SECRET_KEY`/Supabase keys in host env; **back up the Fernet key offline.** |
| **1 GB storage cap** (`settings.py:154,157`) | Evidence 10MB images, **print files 100MB** → ~10 max-size prints fills the budget; S3 lifecycle cleanup unsupported. | Lower upload caps, add app-level cleanup/purge, monitor usage. |
| **Project pausing** | Free Supabase pauses after 7 days idle; free hosts sleep too. | Acceptable for demos; pay for the Django host / Supabase Pro for reliability. |

### Minimal 100%-free architecture (demo/pilot)
```
Supabase Free      → Postgres (DB)  +  Storage (S3-compatible, ~1GB)
Render / PythonAnywhere free → Django (Gunicorn)         ← the piece Supabase can't host
Cloudflare Pages / Netlify / Vercel → React static build
GitHub Actions cron (or pg_cron+pg_net → protected Django endpoint) → send_return_reminders
Email API free tier (or host SMTP)  → notifications
```
**Final call:** fine for a demo or a very small makerspace with disciplined file cleanup; not a dependable "completely free" production deployment. The required code changes are: remove the purge superuser SQL (pick archive-only or trigger-relax), rework presigned uploads (POST→PUT or Supabase signed URLs), add a cron HTTP endpoint, and tighten upload caps + DB retention.


## Status 2026-09-03 (phase 0 close-out)

Re-measured on `dev` at `0039f2f9`. The report's `file:line` citations are from June and many files have
since moved or been retired; each verdict below names where the code is today.

| # | Finding | Verdict | Where / why |
|---|---|---|---|
| 1 | `HardwareRequest` composite indexes | **Done** | `hardware_requests/models.py` carries `hwreq_ms_status_{created,issued,updated,closed}_idx` |
| 2 | `PrintPrinterSerializer` N+1 | **Superseded** | the printing kernel was tombstoned (`911f4589`); `serializers_printers.py` no longer exists |
| 3 | `PrintRequest` indexes | **Superseded** | same; print jobs are `machine_service` requests |
| 4 | Out-of-band work off the request thread | **Done for notifications**, open for exports | email + non-email channels run in `deliver_email_task` / `deliver_notification_task`; QR ZIP and XLSX exports remain synchronous → phase 6 (streamed exports) |
| 5 | Ledger in-memory sort | **Done** | `operations/ledger_query*.py` filters and paginates in SQL |
| 6 | Direct-loan `items` N+1 | **Done** | `direct_loan_views.py` uses `Prefetch("request__items", …)` |
| 7 | Operations list indexes | **Done** | `operations/models.py` indexes on transfers, stocktake, print batches |
| 8 | RBAC hidden/archived cache | **Declined for now** | `servability.unservable_makerspace_ids()` is two indexed queries; caching adds an invalidation surface for a cost not measured in production. Revisit with metrics from phase 0 |
| 9 | `BoxSerializer.get_qr_code_id` N+1 | **Done** | `views_containers.py` annotates `_active_qr_code_id` |
| 10 | `CONN_MAX_AGE` | **Done (this phase)** | default 60 + `CONN_HEALTH_CHECKS`; pooler deployments keep `0` |
| 11 | `QrScanEvent` indexes | **Done** | `qrscan_ms_qrcode_created_idx`, `qrscan_ms_context_idx` |
| 12 | `_summary` per-metric queries | **Superseded** | reports moved to the report registry (`operations/report_registry.py`) |
| 13 | Filament reports loop | **Superseded** | printing retired |
| 14 | Exports materialize everything | **Open → phase 6** | streamed CSV, write-only XLSX |
| 15 | Public print submit S3 HEAD in txn | **Superseded** | public printing intake replaced by machine-service intake |
| 16 | `procurement` unpaginated list | **Open → phase 1** | `procurement/views_items.py` still `pagination_class = None`; `select_related` is in place. Pagination changes the response shape, so it lands with the frontend list work |
| 17 | `require_module` double fetch | **Declined** | one indexed PK lookup; callers may pass the object |
| 18 | `staff_origin_scope` Python scan | **Open, low** | `makerspaces/origin_scope.py` still iterates servable makerspaces per request; bounded by makerspace count |
| 19 | Middleware re-resolves client | **Done** | `inventory/middleware.py` attaches `request.api_client` |

Guard added: `tests/perf/test_list_query_budgets.py` puts a fixed query ceiling on the hot list endpoints
so an N+1 regression fails CI instead of slowing a queue.

---

## Source agents
- Performance — Codex run `b1palif1n` (~193k tokens)
- Supabase DB — Codex run `bxjye6yyf` (~231k tokens; web-verified against Supabase + PostgreSQL docs)
- Supabase infra — Codex run `bi979vnbc` (~150k tokens; web-verified against Supabase/Render/PythonAnywhere docs)
