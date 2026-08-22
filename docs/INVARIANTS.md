# SpaceWorks Invariants (do not regress)

> **This is the reference half of `CLAUDE.md` / `AGENTS.md`.** Those two files carry orientation,
> the Hard Rules and the engineering conventions and are loaded into every agent session; this file
> carries the long-form load-bearing rules and is read **per area, on demand** — open the subsection
> covering what you are touching, not the whole document. It was split out when `CLAUDE.md` crossed
> the harness's memory-file size warning; nothing was dropped in the move.
>
> **`CLAUDE.md` and `AGENTS.md` must stay byte-identical to each other.** This file has no twin —
> both of them point at it by path, so edit it in place.

The load-bearing rules, grouped by area. These were established across many shipped batches and matter
beyond any single module. Read the subsection covering what you are touching.

## Cross-cutting invariants (from shipped batches)

**Self-host vs managed SaaS (all managed features dormant by default).** `PLATFORM_DOMAIN_SUFFIX`
blank/whitespace ⇒ `domain_verification.is_self_host()` is True ⇒ **every managed feature is inert**
and single-domain behavior is byte-for-byte unchanged (self-hosters unaffected). Self-host trusts a
superadmin-set custom `frontend_domain` immediately (no DNS TXT challenge — the challenge only ever
defended the shared managed box). The self-host branch is strictly superadmin-only (the staff-origin/
CORS allowlist is process-global; letting any tenant set a trusted origin is a cross-tenant token-theft
vector). Managed mode adds `<slug>.space-works.tech` provisioning + tenant self-serve custom domains on one
shared instance (no per-tenant DB). **VERIFIED is the trust gate** — a `frontend_domain` grants CORS/
staff-origin/bootstrap/Host/TLS trust only when `frontend_domain_status=VERIFIED` and non-archived.

**Managed fair-use limits (dormant on self-host).** `apps/makerspaces/limits.py` `resource_limit(ms, key)`
(self-host → None = unlimited; per-space `resource_limit_overrides` JSON, else `MANAGED_RESOURCE_LIMITS`)
+ `check_quota(ms, key, *, adding)` called **inside each creation service's `transaction.atomic()`**
(self-locks the makerspace row; raises DRF 400 `{"limit": …}` / typed `limit_reached` at cap). Storage
counter (`add_storage`/`free_storage`) charged at finalize; `recompute_storage` management command is the
authoritative reconciler. Email daily cap via `integrations.DailyEmailCounter`.

**One domain per makerspace.** `Makerspace.frontend_domain` (case-insensitively unique) is the single
frontend-registry field (the old per-type `TenantFrontend` model is deleted). Two origin helpers in
`platform.py`: `makerspace_staff_origins` (ONLY the exact `https://<frontend_domain>`, feeds refresh/
logout CSRF + the origin→tenant guard) vs `makerspace_public_origins` (that ∪ `cors_allowed_origins`,
feeds general CORS + publishable-key validation) — so an API-client/public origin can make
publishable-key calls but **can never mint a staff session**. `origin_scope.py` hard-scopes a browser
staff request to its domain's makerspace; origin-less (server) requests fall back to `MakerspaceMembership`.

**Superadmin access is a HARD block, not a soft hide.** `Makerspace.superadmin_access_enabled=False`
excludes the space for a GLOBAL superadmin across `rbac.can`/`scope_by_action`/`makerspaces_for_action(s)`
etc. (a superadmin with an explicit membership keeps only that role's actions). Status contract: hidden
→ **403** on action/permission-gated endpoints, **404** on object-lookup detail + re-enable PATCH,
**empty 200** on scope-filtered lists. Existence stays visible as a slim row (governance). True→False is
rejected unless Platform Email is configured (forgot-password recovery). Re-enable is space-manager-only.
Break-glass: superadmin may create a fresh SPACE_MANAGER / reset a hidden-only SM. Application-layer only
(DB/`manage.py` access always overrides).

**Makerspace archive → purge (superadmin, `/control/` only).** `Makerspace.archived_at` is the
single soft-delete flag; archive scoping is threaded through central rbac + all aggregates + public +
token-status surfaces (archived is invisible everywhere but `/control/`). `lifecycle.py` is the single
lifecycle source. **Purge** is break-glass: collects S3 keys, writes a platform-scoped audit, then in
one `transaction.atomic()` suspends immutability triggers **transaction-scoped** and deletes the full
`PROTECT` object graph in verified dependency order, then best-effort deletes S3.
- Self-host: `SET LOCAL session_replication_role='replica'` (all triggers off; FK off — ORM does
  CASCADE/SET_NULL in Python).
- Managed Postgres (`MANAGED_POSTGRES=True`, e.g. Supabase forbids `session_replication_role`):
  `SET LOCAL app.allow_immutable_delete='on'` (only OUR immutability triggers bypass; FK stays on).
- **Every append-only/immutability trigger is purge-aware**: DELETE allowed only under GUC
  `current_setting('app.allow_immutable_delete', true)='on'`; UPDATE always blocked (audit/0003 style).
  A new PROTECT-FK + immutable model must add itself to the purge graph **and** the drift-guard.

**Archiving a makerspace must never strand its members' money (phase 1 of the five open items).**
`Payment.makerspace` outlives archival and `member_payment_queryset` deliberately never filtered
`archived_at`, but four separate gates defeated that intent. Fixing only the obvious one would have
been **worse than doing nothing**, which is the lesson worth keeping here.
- **THE PER-MAKERSPACE WEBHOOKS MUST SETTLE AFTER ARCHIVAL, and this was a live money-loss bug.**
  `StripeWebhookView`/`RazorpayWebhookView` looked the tenant up with `archived_at__isnull=True` and
  404'd. Since `MemberPaymentCheckoutView` has **no membership gate at all**, a member could already
  reach checkout for an archived space, have Stripe take the money, and have the callback refused —
  the charge stayed PENDING forever and the member was out of pocket. The 404 never prevented the
  charge, only the **recording** of it, so it directly contradicted the documented "webhook always
  settles / a real charge is never stranded" invariant. Archived is no longer refused: the public
  code is **addressing**, the unchanged per-space signature secret is **authorization**, and a purged
  row still 404s naturally because it is gone. Its origin is worth knowing before anyone
  "restores" it: both the filter and the test asserting it landed in `92eda37`, whose webhook was
  **verify-only** — it settled nothing, so refusing cost nothing. Settlement arrived in C.3 and
  nobody revisited the filter.
- **`member_activity_service.active_member_memberships(user)` is the ONE identity predicate**, and it
  deliberately does not filter archival — each caller applies its own rule (`active_membership` adds
  the archived filter, `payments.member_access` does not). It lives in `makerspaces`, not `payments`,
  because `apps.payments` is separable and a tombstoned deployment must still resolve member identity.
  An `include_archived=` flag was rejected: it would put a security-relevant relaxation in reach of
  every caller. So was restating the predicate in `payments` — that shipped briefly and produced two
  copies of the same five-part check in two apps, which is drift nobody notices until an audit.
- **`member_payment_actor` is payments-only and must NEVER grow a waiver gate.** `active_membership`
  never checked the waiver (that is `presence.guard.require_active_member`); adding one would let a
  newly revised waiver block someone from **discharging an existing debt**, recreating the stranding.
- **An API fix alone does not reach anybody.** `platform.resolve_frontend` and
  `views_memberships.MyMembershipsView` both exclude archived, and `MemberArea`'s payments query is
  gated on both, so the fixed endpoint had no route to it. The answer is the narrow
  `GET /member/archived-payments` discovery endpoint plus a `/member/archived` page that depends on
  **authentication only** — never on `bootstrapTenant` or `/memberships/me`. **Do NOT widen those two
  instead**: they would resurrect the archived space across every unrelated feature.
- **The discovery LINK must survive a failed bootstrap, and that is pinned by a test rather than by
  reading.** `MemberArea` does not early-return when `bootstrapTenant` rejects — it renders an error
  panel *inside* the shell — and the archived banner sits above every bootstrap-dependent section, so
  central `/member` still offers the link to a member holding nothing but an archived space.
  `MemberAreaArchivedLink.test.tsx` asserts exactly that (bootstrap rejects, `/memberships/me` returns
  empty, link present), because the people this route exists for are precisely the people who would
  otherwise have to guess its URL. **Residual limit, deliberate:** on the space's own archived custom
  domain the API calls fail (an archived domain loses origin trust), so the banner does not render
  there and the member must reach the central app. Closing that would mean re-granting origin trust to
  archived domains, which is the isolation archival exists to create.
- **A checkout must return the payer to the space that ROUTED the charge, not the one that owns it.**
  `create_checkout` reads `payment.via_makerspace or payment.makerspace`: for a collaborative-event
  charge, host A owns the row but member space B is the only member area the visitor can sign into,
  so deriving the URL from A lands them where they hold no membership. `platform.member_payment_
  return_url` then sends an ARCHIVED space to the central `/member/archived` instead of
  `member_area_url`'s dead `/member` or `/m/<slug>/member`. Both the Stripe branch and the provider
  seam read that one value, so every rail is fixed at once, and the two arms compose: host archived +
  home live correctly returns to the live home rather than the recovery page, which deliberately
  lists only archived spaces. The seam is monkeypatched **by name** in `test_connect.py` and
  `test_machine_payments.py`. **Known limit:** a session created *before* archival keeps its original
  return URL — the provider stores it and `MemberPaymentCheckoutView` hands back the saved
  `stripe_checkout_url` when present.
- **The bootstrap bypass must read the ROUTER's location, never `window.location`.** `App` short
  circuits to `/member/archived` before the tenant "Loading site" / "Site unavailable" screens,
  which is what an archived member has to get past. Reading `window.location.pathname` made that
  branch non-reactive: a client-side `Link` updates router context without touching
  `window.location`, so every **click** on the recovery CTA fell through to the central table and
  rendered not-found, while a direct page load worked perfectly — which is exactly what made it easy
  to miss. `useLocation()` fixes it. Pinning this needs a REAL `Link` under `MemoryRouter`; a stub
  using `history.pushState` does change `window.location` and would pass against the broken code.
- **`/member` must exist in BOTH route tables, and a component test cannot tell you it does.**
  The central table defined only `/m/:slug/member`, so `/member` fell through to not-found — and the
  member this recovery route exists for cannot supply a slug they can no longer discover. Rendering
  `MemberArea` directly proves the link renders, never that anyone can reach it;
  `App.centralMemberRoute.test.tsx` drives the real router instead. Same shape as the tombstone-suite
  lesson: the test that passes is not always the test that matters.
- **A 404 from the discovery endpoint means TOMBSTONED, and must be told apart from every other
  error.** `payments` is separable, so on such a deployment the endpoint is spliced out; treating
  that like a network failure renders a call-to-action whose destination immediately 404s. The
  recovery page reads the same signal and renders as not-found. It cannot ask tenant bootstrap which
  modules exist — not depending on bootstrap is the whole reason the route exists.
- **`lifecycle.archive_impact()` reports, never blocks.** It counts pending charges the space
  **owns** and pending collaborative-event charges merely **routed** through it (`via_makerspace`,
  de-duplicated) — the second arm is easy to miss and is exactly the visiting-member money at risk.
  `archive()` recomputes it under the row lock into the audit meta and still returns the makerspace
  (seven call sites depend on that return). The count is **advisory**: payment creation does not
  universally take that lock, so it cannot be frozen against concurrent inserts. "Never blocks" means
  a non-zero count is not an error — not that database failures are swallowed. The admin action grew
  a per-makerspace confirmation screen because it previously archived **immediately**, so there was
  nowhere to show a count.

**Archiving is TWO-KEY: a Space Manager requests, a superadmin confirms (phase 3).**
`makerspaces.MakerspaceArchiveRequest` + `archive_requests.py` (the one workflow service; never
mutate status outside it). Direct SM archive was rejected as a **self-lockout** — archiving
removes the space from RBAC scope and `unarchive` is `/control/`-only, so the person who pressed
the button loses the space and any way to undo it.
- **THE HIDDEN-SPACE HOLE, and it is why this feature is safe.** A manager can set
  `superadmin_access_enabled=False` themselves; a hidden space is excluded from `/control/`
  querysets **and** `lifecycle.archive()` refuses it. So `file request → hide space` made the
  request vanish from the superadmin's queue while rendering it unapprovable — a manager
  escaping the exact oversight the design exists to impose. **Both directions are closed:**
  creation refuses a hidden space, and disabling superadmin access refuses while a request is
  pending. Do not remove either half.
- **Authority is the `MANAGE_MAKERSPACE` ACTION, never `rbac.is_space_manager_identity`.** That
  helper documents itself as deliberately not inferring identity from actions, so it refuses a
  custom role granted the action — and editable custom roles are the Part L architecture this
  project runs on. It was wrong in **two** places (view and service); fixing only the view left
  the test still 403-ing, which is how the second one was found. Both gates must agree or one is
  decorative.
- **The requester must be emailed the outcome**, including auto-approval from a direct archive.
  Once archived they lose RBAC scope, the console, the request history and their tenant domain,
  so no in-app surface can ever tell them. Sends go through `transaction.on_commit`, catch and
  log, and do **no SMTP work under the makerspace lock** — an SMTP failure must never roll back
  an archive. Platform mail (`makerspace=None`), so no module toggle can mute it.
- **A direct `/control/` archive AUTO-APPROVES any pending request atomically.** Leaving it
  pending is false state that is invisible once archived and blocks a fresh request after an
  unarchive.
- **A COLLEAGUE's withdrawal notifies the requester; your own does not.** Because authority is
  the action rather than "the person who filed it", any `MANAGE_MAKERSPACE` holder can withdraw
  someone else's request — and without the mail that request simply vanishes with no trace the
  requester can see. Withdrawing your own needs no mail: you just did it. This is the one
  transition the design review got wrong ("withdrawal needs no email"), because it assumed the
  actor and the requester are the same person.
- **Approving from the request queue must show the same impact screen as the direct route.**
  Approving *is* archiving; without it a superadmin could archive without ever seeing the
  owned/routed pending charges — two ways to do one thing, one of them uninformed.
- **Never copy `reason`/`resolution_note` into audit metadata** (append-only ⇒ undeletable), do
  not put `reason` in the broad superadmin mail, and send `resolution_note` with
  `persist_body=False`. The text is makerspace-scoped operational text like
  `ApiKeyRequest.reason` — length-bounded, **not** `ScopedPiiModelMixin`.
- Lock order is **`Makerspace` → `MakerspaceArchiveRequest`** on every transition. The partial
  unique index (one PENDING per space) is the backstop, and its `IntegrityError` becomes a typed
  409, not a 500. A **per-space one-hour cooldown** stops `request → withdraw → request` fanning
  mail at every superadmin; it deliberately does **not** consume the OTP/SMS quotas, because a
  governance-mail flood must never be able to suppress password-reset mail.
- `makerspace` is **CASCADE** (the `SubdomainRequest` precedent); both user FKs are **SET_NULL**,
  because durable attribution lives in the append-only audit log and PROTECT here would only
  widen the user-deletion graph. No module key, purge plan, tombstone entry or PII registration:
  `makerspaces` is core and archival is governance, not an optional feature.
- **DRF field errors are not the `detail`/`code` shape.** A blank/overlong `reason` returns
  `{"reason": [...]}`, so the 400 is documented with its own serializer (the
  `ProvisionSubdomainValidationErrorSerializer` precedent) rather than the typed error schema a
  generated client would destructure and find empty.

**Publishing a borrower's NAME is opt-in, and the guard must short-circuit (phase 2).**
`inventory.public_stats_hardware.current_loans` served `holder_name` on the **unauthenticated**
stats endpoint, resolving the free-text `requester_name`, then `requester_username`, then
`get_full_name()` — a real person's name bound to a specific tool and a due date, readable by
anyone. `Makerspace.public_stats_show_holder_names` now gates it, **default off**, and migration
`makerspaces/0060` backfills **True unconditionally** for existing rows (the `0050`/`0056`
precedent: an opt-in default silently removes behaviour a space relies on). Accepted consequence,
written in the migration: a currently stats-disabled space will publish names if it enables stats
later, unless its manager turns this off first.
- **The OFF branch must not CALL `public_display_name` at all** — not call it and discard the
  result. `HardwareRequest` is a `ScopedPiiModelMixin` and `requester_name` is encrypted **and
  Bloom-indexed**, so reading it transparently decrypts; a names-disabled public request must not
  depend on PII decryption or key availability for a value it throws away. A test spies on the
  helper and asserts **zero calls**, because every output-only assertion passes against a
  compute-then-replace implementation — verified by writing that regression and watching the four
  output tests stay green while only the spy failed.
- **`'Member'` is not anonymisation.** The row still carries exact `due` and `since` timestamps
  with the item, so an observer who was in the space can still correlate. The toggle removes the
  directly searchable identifier; coarsening dates or suppressing `current_loans` outright is a
  broader policy decision that was **not** taken.
- The view is mounted at **two** URL aliases (`/api/public/<slug>/stats/` and
  `/api/v1/public/<slug>/stats/`) fed by one builder, so guarding the builder covers both. Neither
  the machines nor printing stats builders carry requester identity — `current_loans` is the only
  identity-bearing section. `/control/` gained `public_stats_enabled` too, which it had never
  exposed: a privacy switch the superadmin cannot see is not a control plane.

**A new public image field must register in FOUR places, and three of them fail silently.**
`Event.image_key` (phase 22) is the worked example. Adding the column and an upload view is the
visible half; the half nothing will remind you about is that
`inventory/public_image_storage.build_object_key` validates the **kind** against an allowlist (a
missing kind is the only one that fails loudly — `ValueError: Invalid public image kind`), while
`makerspaces/lifecycle._collect_public_image_keys` (makerspace purge),
`module_purge_collectors` + `module_purge_plans.public_image_keys` (per-module purge) and
`recompute_storage._public_image_keys` (the authoritative storage reconciler) each fail **open**:
skip one and the objects simply outlive every row that could name them, or the reconciler silently
writes a total that omits them. `public_image_key_in_use` also has to learn the new model, or two
entities can claim one key and clearing either blanks the other. The `BookableSpace` gap this
paragraph used to name is **FIXED** — `recompute_storage._public_image_keys` now includes it, with
a comment recording why. **The surviving instance of the same bug is `MaintenanceLogDocument`**: it
is charged to quota on upload (`maintenance/services_documents.py`), collected by the makerspace
purge **and** by its module purge plan, but is **absent from `recompute_storage`**, so the
authoritative reconciler writes a total omitting every maintenance document and silently lowers a
space's recorded usage. This list exists because that failure mode keeps recurring in the one
mechanism that fails silently. Storage accounting itself is a **no-op on self-host** (`limits.add_storage`/`free_storage`
return early), so a test asserting `storage_bytes_used` must force managed mode with
`monkeypatch.setattr(limits, 'is_self_host', lambda: False)` and wrap `on_commit` object deletes in
`django_capture_on_commit_callbacks(execute=True)`.
- **A purge that deletes image-holding rows must free the quota, and the accounting belongs
  POST-COMMIT with the object deletion — never inside the purge transaction.**
  `module_purge._delete_public_images_and_free_storage` is generic over the plan's `public_keys` and
  handles each key in one loop: HEAD the size, delete the object, then free the quota **only when
  deletion reports success**. `public_image_storage.delete_object` returns `True`/`False`; swallowing
  its own `BotoCoreError`/`ClientError` without reporting failure once let the counter fall while the
  object survived, permanently granting free storage. The HEAD still has to precede deletion or the
  size is lost, but accounting must follow confirmed deletion. The whole loop runs after commit and
  best-effort: inside `purge_module`'s `atomic()` those network calls would hold the makerspace
  `select_for_update` lock and could roll back rows that were correctly deleted. An absent size or a
  failed deletion frees nothing.
- **External I/O must never run inside a transaction that holds a row lock.** HTTP and object-storage
  calls have network-bounded latency and failure modes; putting them under `select_for_update()` turns
  a slow dependency into lock contention and lets an unrelated transport failure roll back valid
  database work. Scheduled work follows `run_scheduled_tasks`' **claim-then-work** shape: a short
  transaction locks the `PeriodicTaskRun`, checks due-ness and stamps `last_run_at`, then the runner
  executes after commit. The same rule was violated twice in one review session, so it is recorded
  here as a general transaction boundary rather than left as two per-site fixes.
- **A TEST THAT ASSERTS ON SOURCE TEXT PROVES NOTHING ABOUT BEHAVIOUR.** Prefer an observable: the
  scheduler lock-boundary test records `transaction.get_connection().in_atomic_block` while the task
  runs. When a test exists to prevent a specific regression, reintroduce that regression and verify
  the test fails before trusting it.
- **A presigned upload is a hole in all three row-walking mechanisms, and it is a PLATFORM property,
  not a bug in any one endpoint.** `presigned_upload` hands out write access to a key before any row
  claims it, and in POST mode (the default; MinIO) it targets the **final** key. An unattached upload
  is therefore invisible to `limits.add_storage` (charged at attach), to `recompute_storage` (sums
  rows) and to every purge collector (enumerates rows) simultaneously. `MemberImagePresignThrottle`
  caps the one presign an ordinary member can reach — per **account**, POST-only, so a member who
  spends their uploads does not lose the ability to *clear* an image, the one action that frees
  storage. That bounds the damage; it does not eliminate orphans. **Eliminating them means either
  presigning into the `staging/` prefix in POST mode too (so an unclaimed object never enters the
  served namespace and a bucket lifecycle rule can expire it) or a sweeper for unclaimed keys** —
  both touch every image path in the system and are their own phase. Do not add a new member-reachable
  presign without a per-account cap.

**Rate limits are global only when their cache is global.** `CACHES` must stay configured to use
Django's `RedisCache` when `CACHE_URL` or an explicitly set `CELERY_BROKER_URL` supplies Redis; a
per-process cache silently multiplies every DRF throttle by the Gunicorn worker count and loses its
counters when a worker recycles. The fallback must be Django's shared `DatabaseCache`, never
`LocMemCache`: the brokerless cloud profile sets `CELERY_BROKER_URL` empty but runs three Gunicorn
workers by default with `--max-requests 1000`, so a per-process cache multiplies every rate limit and
then resets its counters as workers recycle. The operations migration creates the cache table; no
separate operator step is required.

**Object storage.** Two buckets per env: a private evidence/docs bucket and a separate **public-read**
image bucket (`PUBLIC_IMAGE_BUCKET`, served via `PUBLIC_IMAGE_BASE_URL`, kept distinct from the signing
host). New file types use the **prefix model** (single shared bucket, isolated by
`<module>/<makerspace_id>/<machine_or_resource_id>/<category>/<uuid>` — NOT bucket-per-makerspace, which
would hit S3's ~100-bucket limit) — applied to NEW files only, no re-keying. Presign follows
`STORAGE_PRESIGN_METHOD` (POST for MinIO, PUT for Supabase; PUT-mode re-validates size server-side at
attach). Object keys are identifiers, not secrets — privacy is the private bucket + short-lived signed
URLs. Upload validation: strict magic-sniff for PDF/image; the private maker/CAD allowlist
(`apps/maker_file_formats.py`) accepts STL/OBJ/3MF/STEP/etc. on ext+MIME (+signature for 3MF/STEP);
public-image + evidence buckets stay strictly image-only.

**Reports/analytics extend one registry** (never a parallel system). `apps/operations/report_registry.py`
holds canonical `ReportDefinition`s (module-gated, `report_scope.eligible_makerspaces` excludes archived
+ reports-disabled + superadmin-hidden). FabLab domain builders (`reports_events`/`_bookings`/
`_maintenance`/`_machine_usage`/`_inventory` + fail-safe `reports_health`) mirror printing's date-range
contract; **aggregate output groups by `makerspace_id` and never flattens cross-tenant data**. Per-makerspace
report rows are gated by query-level scope (no per-row Python check → no N+1).

**One narrow, deliberate exception to the no-flattening rule, added 2026-08-20 by owner decision** after a
Stage-4 review correctly flagged the organization dashboard as a regression of it: **a single
organization's server-resolved OWNER set may carry a combined total, and that total may only ACCOMPANY —
never replace — the per-makerspace breakdown.** The rule exists to stop unrelated tenants being mixed and
provenance being lost; a total over one organization's own OWNER-linked makerspaces, resolved server-side
and always shown beside the per-space rows, does neither. The exception is bounded by four conditions, all
of which must hold: (1) the id set comes from `operations/org_report_scope.py`'s resolver, never from
client-supplied ids; (2) `relationship = OWNER` only — MANAGER and AFFILIATE links are excluded; (3) the
per-makerspace breakdown is always present in the same response; (4) `ReportScopeMode.COMBINED` is the only
mode permitted to flatten, and only for that resolved set. Anything wider is still a regression. Deployment
-wide aggregates are unchanged: they stay grouped by `makerspace_id`.

**Scoped PII encryption (Part H, `apps/encryption/`; dormant unless enabled).** Per-makerspace DEK via a
key broker (local/AWS-KMS), AAD-authenticated envelope crypto, `ScopedPiiModelMixin` on the 6 PII-holding
models with a save-boundary that single-INSERTs envelopes + dual-read cache. Blind-index search
(domain-separated HMAC bloom + exact + event-email hashes) for enabled deployments; disabled deployments
search plaintext via ORM. Write-fence (`PiiGlobalWriteFence`/`PiiMakerspaceWriteFence` + PG
`pii_assert_mapped_write_allowed()` triggers with global-then-tenant advisory locks) blocks mapped writes
during maintenance; mapped services acquire the fence **before** their domain row lock. Enabling is a
staged dual-read rollout; `decrypt_scoped_pii` is the fenced rollback. **Encryption is never enabled
before H3 (search) ships.**

**Custom editable per-makerspace roles (Part L).** The 5 legacy roles are now editable protected default
`Role` rows; authority is **action-based** via the assigned role (dual-read with legacy fallback:
`rbac.actions_for_membership` resolves assigned-role-first, tenant-match-else-fail-closed, strips
unknown/forbidden actions, null-FK → frozen legacy). `can()`/`makerspaces_for_action()`/hidden-block all
route through it. `/auth/me` + `/auth/login` carry typed effective `actions` per membership; the frontend
`staffAccess.ts` derives every capability from action strings, not role names. Role CRUD +
membership/role-assignment APIs enforce non-escalation (can't grant a role you don't hold; can't touch a
MANAGE_MAKERSPACE target/role) with makerspace-first lock ordering.

**`apps/makerspaces/module_registry.py` is the single source of truth for module keys.** All 32
`ModuleDefinition`s live there (`key`, `label`, `description`, `app_label`, `enforcement`, `group`,
`requires_modules`, `default_enabled`, `is_core`, `frontend_exposed`, `frontend_workflows`), and the
lists that used to be hand-kept in parallel now **derive** from it: `models.DEFAULT_ENABLED_MODULES`,
`platform.MODULE_WORKFLOWS`, `capabilities.FEATURE_MODULES`, and the former hardcoded
`printing → machine_service` branch (now `requires_modules` data). Add a module **only** in the registry.
Two rules the registry must not break: it **never imports `makerspaces.models`** (models imports it, so
the reverse edge is a cycle), and `default_enabled_module_keys()` returns a **fresh list** because it
backs a JSONField default. `frontend_exposed=False` marks an internal master switch and drops the key
from both the bootstrap `modules` array and `MODULE_WORKFLOWS`, preserving the byte-for-byte payload
invariant; unknown legacy keys stay exposed (`_canonical_modules` deliberately preserves them).
`is_core` marks the six un-toggleable modules — `public_inventory`, `request_workflow`, `staff_admin`,
`evidence_uploads`, `qr_management`, `scanner` — because the Hard Rules require a box QR scan **and** an
issue photo to issue hardware. `tests/makerspaces/test_module_registry.py` is the drift guard: it
AST-parses `apps/` and fails if a registered module has no real guard call site, if a guarded key is
unregistered, if the derived lists change, or if a migration-referenced callable stops resolving.

**Modules are OPT-IN.** `DEFAULT_ENABLED_MODULES` resolves to **10 keys** — the 6 core ones plus
`accounts`, `payments`, `mobile` and `updates`, which carry `default_enabled=True` because each was
introduced as a *key over behaviour that already existed*, and an opt-in default would have switched
that behaviour off for every deployment on upgrade (the `0050`/`0051` backfill reasoning, expressed
in the registry instead of a migration). Everything else is off, and a new makerspace installs core
plus whatever profile the operator chose (`minimal` 6 / `workshop` 14 / `lending` 17 /
`recommended` 20 / `cloud` 24 / `everything` = `full` 32).
`ModuleDefinition.default_enabled` defaults to **False** and core must not set it (core is on by
definition; two sources for one fact is the drift the registry exists to remove) — so the four
above are the only registry entries that set it, and `default_enabled_module_keys()` is the one
place to ask rather than counting by hand. (This paragraph read "core only (6 keys)" until those
four keys landed; it is the kind of count that goes stale silently, which is why the README table
is generated from the registry rather than written out.) **Existing makerspaces
are untouched** — a default change never rewrites stored JSON rows, and `_canonical_modules` preserves
unknown keys. Because almost every backend test exercises a module's behaviour rather than the install
default, `tests/conftest.py` has an autouse fixture that patches **only the `enabled_modules` field
default** to the `everything` profile; anything reading `default_enabled_modules()` /
`DEFAULT_ENABLED_MODULES` directly still sees the real opt-in value, which is how
`tests/makerspaces/test_module_registry.py` and `test_module_install.py` still assert production
defaults. A test asserting a module's *disabled* path must now disable it explicitly.

**Module install path (opt-in modularity).** `/control/` is deliberately not proxied on the public
frontend port, so it can never be the only way to enable a module — a non-technical operator cannot
reach it. `apps/makerspaces/module_install.py` is the single service behind
`python manage.py list_modules | install_module <key> | uninstall_module <key>` (`--makerspace <slug>`,
defaulting to the only makerspace). Installing resolves `requires_modules` transitively; uninstalling
**refuses core modules and modules another installed module requires**, and only clears the capability
key — **data is always retained** and reinstalling restores the surfaces. Every mutation locks the
makerspace row, validates through `validate_capabilities`, and audits `makerspace.capabilities_changed`.
`apps/makerspaces/module_profiles.py` defines **minimal / lending / workshop / recommended / everything**
(`lending` = a tool library with no machines; `workshop` = machines + service queue + maintenance, no
lending extras). **No profile can go below core**, so `workshop` still ships the request/evidence/QR
spine — the Hard Rules make the loan flow the system rather than a feature of it. Going leaner than
that is the *other* axis: `python manage.py suggest_tombstones` reads what every makerspace actually
has installed and prints the `TOMBSTONED_APPS=` line to paste into `.env`. It is conservative by
construction — an app is suggested only when **no** makerspace uses any of its modules, because a
tombstone is process-global and would break the one tenant still using it. Apps owning no module key
(`warranty`, `presence`, `payments`, `updates`) are listed separately for a by-hand decision. `setup.sh`,
`setup.ps1` and `setup_instance --profile` (env `SETUP_MODULE_PROFILE`, default `recommended`) apply one,
**only when the makerspace is first created** so a re-run never rewrites an operator's choices.
Core modules are **added back by `_canonical_modules`, not rejected** — no caller has to carry the core
set and no otherwise-valid save fails on a row that lost one. Because `public_inventory` is core, the
module can no longer express "private makerspace"; the existing `Makerspace.public_inventory_enabled`
switch does, and the **minimal profile turns it off** so a minimal install publishes nothing until the
operator opts in.

**Disabling a module is race-safe under the row lock, never at the form.** `require_module` at a view
boundary reads an **unlocked** row, so a concurrent uninstall can commit in the window between that check
and the create. `guards.require_module_locked(makerspace, key)` re-checks under `select_for_update` and
must be called **inside the creation service's `transaction.atomic()`, next to `check_quota`** — every
`module_install` mutation takes the same makerspace lock, so one lock and one ordering serializes creators
against disablers exactly the way `check_quota` serializes creators against each other. Validating on the
disable side instead does not help: it loses the same race from the other end. Guarded creation paths:
event create + publish, booking create, machine create + unretire, machine-service submit
(`service_workflow._require_module(..., locked=True)`, whose error shape stays identical to the unlocked
call). Calling it outside `atomic()` raises `TransactionManagementError` rather than silently not locking.

**Per-module purge is NEW semantics, and is the irreversible second step after uninstall.**
`lifecycle.purge()` deletes an entire archived makerspace; `makerspaces/module_purge.py` deletes **one
module's rows while the makerspace stays live**. Contract: the module must **already be uninstalled**
(uninstall retains everything and is reversible — no single command may both hide and destroy),
**superadmin-only**, re-checked under the makerspace lock inside one `transaction.atomic()` that suspends
immutability triggers transaction-scoped the same two ways the makerspace purge does
(`session_replication_role='replica'` self-host, `app.allow_immutable_delete` GUC on
`MANAGED_POSTGRES`), with object-storage keys collected **before** the delete and removed **after** the
commit, best-effort. `module_purge_plans.py` is the per-module declaration; a module absent from it either
owns no data or is listed in `NOT_SEPARABLE` with the reason (core modules, and `machines`, whose rows
host warranty, consumables and service history). **NO MODULE PURGE DELETES A `Payment` — reversed
deliberately on 2026-08-11, and `payment_subjects` is gone from `ModulePurgePlan` entirely.** Switching a
module off and purging its rows is not grounds to destroy the record of money that really changed hands: a
receipt must stay visible and a pending charge payable, which is the same reasoning that always retained
membership dues. A `Payment` is **payments**-module data; its subject vanishing is not its business. Three
things this required, and the first two are what made it safe rather than reckless:
- **`Payment.clean()` had to learn to tolerate a missing subject**, because `save()` calls `full_clean()`
  unconditionally. Without it, every WRITE path broke once the subject went: hosted checkout created the
  provider session then failed persisting its URL, mobile intent 503'd, offline reconcile/waive raised an
  untranslated `ValidationError`, and **webhook settlement 500'd and rolled back its idempotency row**, so
  a charge that really settled at Stripe could never be recorded. `_subject_identity_unchanged()` gates it
  and is deliberately narrow — a **saved** row still naming the same makerspace, subject and member.
  Skipping merely because `pk` exists would let an existing payment be repointed at a foreign subject, and
  a **new** payment still requires a real same-tenant subject.
- **`Payment.subject_label` is snapshotted at creation** and read **FIRST**, before any live lookup
  (`payments/subjects.py`). Snapshot-first is not an optimisation: event titles and space names stay
  editable after a charge exists, so live-first silently rewrites what a paid receipt appears to have been
  for. The live fallback exists only for legacy blanks and now carries the owning makerspace/member ids,
  because it was keyed on **global subject pk with no ownership check at all**. It must never return an
  empty string — Stripe rejects a blank `product_data.name`, and this value feeds the checkout line item.
  The column is financial metadata and **must never carry PII**: titles and space names, never a person's
  name, contact details or custom-form answers.
- **KEEPING A CHARGE PAYABLE MEANS KEEPING IT SETTLEABLE, and machine scoping broke the second
  half.** `reconciliation._require_machine_scope` compared the *scoped* service-request ids against
  every machine-service `subject_id`, so once the request was purged the sets could never be equal
  and **both mark-offline and waive 403'd for every actor** — the pending charge was stranded
  forever: unwaivable, and unrecordable if the member paid cash at the desk. Preserving a payment to
  keep it payable while making it impossible to settle is the same failure wearing the opposite mask.
  The comparison is now against the ids that still **exist**, and the orphans are gated separately.
  Failing **open** to every `MANAGE_MACHINES` holder was rejected: machine scoping is documented as
  failing closed and that would silently widen a role narrowed to one team. An orphan names no
  machine, type or team, so there is nothing left for scoping to answer — it is actionable only by
  the actors that mechanism **already exempts** (space manager, superadmin, null-`assigned_role`
  legacy fallback), all of whom are unscoped everywhere else. **Only machine-service was affected**:
  the booking/event/membership arm scopes `Payment` rows by makerspace and never dereferences the
  subject, which is why the bug hid — three of the four subject types were fine.
- **`lifecycle.purge` (whole makerspace) still deletes every payment** and is untouched, because
  `Payment.makerspace` is `PROTECT` — the rows cannot outlive their makerspace. Preservation is a
  module-purge property only. (The archive gap noted here is **fixed** — see the archive section below.)
Still declared per plan: **`PiiBlindIndex` rows** (keyed HMACs of PII with
**no FK** to the source row, so nothing cascades them — leaving them is a real leak). Encrypted envelopes
live on the source row itself, so they go with it. **A per-module purge must respect the modules that are
still installed**, which is why `_machine_service_delete` is not `service_lifecycle.delete_for_makerspace`:
consumable **pools stay** (they are gated by `require_module(..., "machines")` and are PROTECT-referenced
by surviving manual usage entries), while usage entries **derived from a purged service request go** —
they carry the requester's name/email/phone copied off the request, and their blind-index rows are cleared
**per object id, not per label**, or the surviving manual entries lose their search rows. Consumable ledger
rows are deleted, not reversed: the material really was consumed, so a pool keeps its `remaining_grams` and
loses only the trail. `MakerspaceMembership` survives a `membership` purge
(core RBAC state, plan A7); its waiver acceptance is under an all-or-none check constraint, so the three
acceptance fields are cleared **together** before the waivers go. Membership-dues Payments are deliberately
retained — their subject still exists. CLI: `python manage.py purge_module_data <key> [--makerspace slug]
[--actor username] [--yes|--list]`, slug-typed confirmation, and a platform-scoped
`makerspace.module_purge_started`/`module_purged` audit pair naming a real superuser actor.

**The `email` module gates tenant mail only.** `integrations.dispatch.email_module_blocks(makerspace,
stream, event)` is the single gate, and it is checked in **three** places, not one: `dispatch_email()`
(new mail), `_deliver()` (a row can sit in Celery across an uninstall, and retry re-enters here), and
transitively `retry_email_log()`, whose existing FAILED/SENDING whitelist already refuses the new status.
A blocked message becomes a **terminal `EmailLog.Status.SKIPPED`** row — recorded, not dropped, so the
operator can see what the toggle suppressed — and `SKIPPED` is neither a delivery nor a failure:
`notify._dispatch_email_delivery` counts it as neither, because `notify_return_due` returns
`bool(delivered_counts)` and a skip must not read as a reminder that went out. Three messages are
**exempt, matched on stream AND event** (an event name alone is not unique across streams):
`("account","password_reset")`, `("account","email_verification")` — missing the second leaves a new
account unable to verify and therefore unable to join — and `("hardware","return_reminder")`, a
duty-of-care message in the accountability flow. **Platform mail (`makerspace=None`) is never gated**:
no tenant owns it, and the platform-level `integrations.email.email_enabled()` behind `/api/v1/config`
is *deliverability*, not tenant enablement — conflating them hides forgot-password from the login screen.
Because modules are opt-in, a newly registered key is off by default, which is right for a new makerspace
and catastrophic for an existing one; migration `makerspaces/0050` is the one-time backfill (with a working
reverse) that keeps every pre-existing space sending mail across the upgrade. Any future default-on module
key needs the same treatment.

**A6 master switches are additive `AND`s, never replacements.** `payments.enabled`, `mobile.push` and
`presence.geofence` are standalone (`parent_module=None`) features that sit **in front of** the readiness
check each capability already had — `online_payments_enabled` still requires the per-domain
`payments.<domain>` feature *and* resolved credentials; `deliver_native_push` still requires platform
FCM/APNs; `evaluate_geofence` still requires `geofence_effective`. Turning a master switch **on** can
therefore never make an unconfigured capability start working, and turning `presence.geofence` **off**
returns `None` ("not checked") — the geofence stays **advisory** and gains no power to block. They must
stay **independently switchable**: do *not* express the coupling as `requires_features` on the domain
features, because that would make the kill switch un-flippable until every domain was unticked first.
All three **default enabled** so their introduction changed nothing, and migration `makerspaces/0051`
backfills them onto pre-existing rows (`enabled_features` is stored per row, so a `default_enabled` flip
alone would read as OFF for every existing space). Bootstrap omits `geofence_enabled` entirely when the
feature is off, preserving the byte-for-byte dormant-payload invariant. A test that enables
`payments.<domain>` by assigning `enabled_features` wholesale must now include `payments.enabled` too.

**Social sign-in is platform-scoped and must never become a tenant feature** — it resolves before a
makerspace is selected, so a `social.*` feature key would be unreachable at token-verification time and
read as disabled for everyone (`test_a6_toggle_scoping.py` pins this). Disabling a provider is the
dangerous direction: `accounts/social_lockout.py` refuses, at the `/control/` form, to clear the last
credential of accounts that have that provider, no other provider, and no usable password — those users
cannot be recovered by forgot-password because there is no password to reset. Inactive users don't block
the change. This is the platform-wide twin of the per-user `last_credential` guard in
`unlink_social_identity`.

**The staff console's feature list is a hand-kept mirror and is drift-guarded.**
`frontend/src/lib/features.ts` `FEATURE_DEFINITIONS` backs the Space-Manager feature checkboxes;
`tests/test_capabilities.py::test_frontend_feature_definitions_match_the_backend` parses that file and
fails if it diverges from `capabilities.FEATURE_DEFINITIONS` (keep the one-object-literal-per-line shape
the guard reads). A feature missing there is invisible to the Space Manager who owns it, and a stale
`parent_module` renders a wrongly-disabled checkbox — which is omitted from the PATCH and silently clears
the capability. **Regenerating the OpenAPI snapshot requires the pinned toolchain**: `requirements.txt`
pins `drf-spectacular>=0.30`, and regenerating with an older installed version rewrites ~240 unrelated
lines (`allow_blank` `oneOf` wrappers, `nullable` on file fields) — check `pip show drf-spectacular`
before `manage.py spectacular`, and expect the diff to contain only what you changed.

**Two-level capabilities (modules + features).** `Makerspace.enabled_modules` (whole modules) is
**superadmin-only** — edited only in the `/control/` capability matrix; a staff-API PATCH containing
`enabled_modules` is a hard **403**. `Makerspace.enabled_features` (namespaced sub-features via the
`apps/makerspaces/capabilities.py` registry — `payments.machines|bookings|events|membership`,
`inventory.self_checkout`) is **Space-Manager-writable** (`MANAGE_MAKERSPACE`), validated so a feature can
be enabled only when its parent module (and any `requires_*`) is on, and audited (`makerspace.features_changed`).
A `FeatureDefinition.parent_module` of **None** = a standalone feature with no module prerequisite (effective
purely when enabled) — `inventory.self_checkout` is standalone (self-checkout + staff direct handouts are
per-makerspace loan capabilities independent of the public catalogue; they must NOT be reparented under
`public_inventory`). `feature_enabled`/`require_feature` (typed key `feature`) mirror the module guards;
bootstrap exposes effective `features: string[]` + feature-workflows. `payments.*` keys are **dormant
substrate** in the capabilities layer — enforcement lands in the payment tracks (C.2/C.3), not here. The
`/control/` matrix widget must derive its disable rule from each feature's real `parent_module` (never
disable a parentless feature — a disabled checkbox is omitted from POST and would silently clear the
capability). Widget templates live in the **app** templates dir (`apps/<app>/templates/...`), not project
`templates/`, so the form renderer (app-dirs only) finds them. The matrix's **module** choices come from
`module_registry.MODULES`, never from "defaults + keys already on the row" — that older rule made any
non-default module unreachable for a makerspace that didn't already have it (`notifications` was enforced
but un-enableable), and under opt-in defaults it would have hidden nearly the whole registry. Core is
**labelled, not disabled**, and unrecognised stored keys stay selectable so an untouched save can't drop
them.

**The `membership` module gates the community feature, not RBAC (A7).** `MakerspaceMembership` is core
RBAC state, so gating it wholesale would lock a makerspace out of its own staff administration.
**Never gated:** membership list/create, role assignment, revoke, capabilities, staff roster,
`memberships/me`. **Gated by `membership`:** public join request, request queue/approve/revoke,
verify/unverify, member waiver + accept, member activity, referrals. Invitations run staff and community
intent down **one** path in `membership_services.invite_membership`, discriminated by the assigned role's
`granted_actions` — a role granting no actions is a community invitation (gated) however it is named; a
role granting actions is a staff invitation and must keep working with the module off. Module gates are
**additive `AND`s** — `refer_membership` still checks `referrals_enabled` and `can_refer`.

**Payments (Stripe, C.2/C.3; dormant until configured).** `apps/payments.Payment` is the **single payment
authority** (one row per subject via unique `(makerspace, subject_type, subject_id)`; positive amount;
statuses pending/paid_online/paid_offline/waived/canceled; terminal rows immutable — **enforced by a Postgres
BEFORE UPDATE/DELETE trigger that blocks terminal-row mutation AND blocks DELETE unless the purge GUC
`app.allow_immutable_delete='on'` is set; `Payment`+`ProcessedStripeEvent` are in the lifecycle purge graph**).
Effective online payment = `feature_enabled(ms,"payments.<domain>")` AND `MakerspacePaymentSettings.is_configured`
— blank creds fail closed; no platform-wide Stripe fallback (a **Stripe-Connect creds track** for managed hosting
is planned, self-host stays per-makerspace raw keys). The webhook settles both synchronous
(`checkout.session.completed` payment_status=paid) and **asynchronous** (`checkout.session.async_payment_succeeded`,
matched by session id) charges. **Machine-service pricing lives in `apps/machines.MakerspaceMachineTypePricing`
(per makerspace × machine_type; built-in AND custom types; `rate_per_unit`/`flat_fee`/`payment_enabled`),
NOT in `MachineType.capability_config` (which is structural-only — no pricing/payment keys); currency = the
makerspace default currency snapshotted into `Payment`; the charge quantity is `service_payments.effective_quantity`
(minutes→`actual_minutes`, else `actual_consumed_quantity`, else grams). Configuring machine types AND their
pricing is gated by `rbac.is_space_manager_identity` (space-manager membership only — NOT `MANAGE_MACHINES`
breadth — honoring archived/hard-hidden scoping; surfaced to the console via the per-membership
`can_configure_machine_types` flag).** **Never-block:** machine `complete()`/`collect()` succeed even if
Payment creation or Stripe checkout fails; checkout is created post-commit best-effort (and can be regenerated
on demand via the member endpoint). **Webhook always settles:** `apply_webhook_event` verifies the
per-makerspace signature on `request.body`, is idempotent via `ProcessedStripeEvent`, and settles a matching
pending Payment to paid_online **regardless of the live feature toggle** (a real charge is never stranded); a
paid event for an already-terminal payment is audited (`payment.paid_after_terminal`), not dropped. Reconciling
(mark_offline/waive) best-effort **expires** any live Checkout session. Checkout return URLs come from
`platform.member_area_url` (VERIFIED custom domain → `/member`, else shared `/m/<slug>/member`). Legacy
`MachineServiceRequest.payment_*` are **read-only historic** (a backfill migration maps them into Payment);
refunds are out of scope. Amounts are staff-private (serializer split); requesters/members see status + own
checkout link only.

**Payment credentials, subjects, and reconciliation (Phase C final tracks).** Self-hosted makerspaces
may manage their own encrypted Stripe credentials; managed hosting resolves through platform Stripe
Connect without exposing secret values. Credential mutation validates live Stripe ownership and protects
in-flight checkout/webhook sessions. Booking, event-registration, membership-dues, and machine-service
charges all create the same immutable `Payment` subject rows. Reconciliation is makerspace-scoped through
RBAC, reports/dashboard aggregates never flatten tenants, and offline/waive actions audit the actor and
best-effort expire live online sessions.

**Native clients use attested device grants, never browser-token shortcuts.** Device login starts with a
short-lived attestation challenge and creates a revocable `DeviceGrant`; access tokens carry
`device_grant_id`, refresh tokens rotate in a grant family, and replay revokes that family. Native
makerspace selection uses `X-Makerspace-Id` only with a valid grant and active scoped membership. Push
tokens are encrypted with an HMAC dedup fingerprint, owned by a device grant, and disabled when a provider
reports them invalid. Native Stripe PaymentSheet delegates to the same Payment/Connect resolution and
idempotency rules as web checkout.

**Generic OIDC providers are configuration, not a second verification path (phase 17).**
`accounts/models_oidc.OidcProvider` (superadmin-only, platform-scoped) holds `issuer`, `jwks_url`,
`client_id` and two switches; `social_oidc.verify_oidc_token` reuses the same
`social_jwt.decode_rs256_token` the built-ins use, because two RS256 implementations means two
places to get RS256 wrong. This covers Keycloak, Authentik, Azure AD, Okta and Google Workspace —
they differ only in configuration. Load-bearing details:
- **No client secret is stored.** This is the ID-token flow: verifying a signature needs only the
  JWKS, so there is no secret to leak and none is modelled.
- The stored provider key is **`oidc:<slug>`**, namespaced so a provider slugged `google` cannot
  shadow the built-in. `SocialIdentity.provider`/`SocialLoginNonce.provider` widened to 64 and lost
  their `choices` — validity is answered by configuration (`provider_for_slug`), which an enum never
  could. `_available_username` now strips the colon, which Django's username validator rejects.
- **`allow_auto_link` exists for an IdP that does not verify email ownership.** With it off, an email
  match demands an explicit link instead of silently handing over the account. Auto-link still
  additionally requires provider-asserted `email_verified` **and** a locally verified address — the
  switch only allows it to be considered. `email_verified` is parsed strictly: a missing claim must
  never read as verified.
- **`issuer` is compared verbatim, never normalized.** The built-ins accept two spellings only
  because Google genuinely issues both; tolerating a trailing slash generally is how an issuer check
  stops being a check. A provider row **cannot be deleted** in `/control/`, only disabled — deleting
  it orphans every `SocialIdentity` naming it and locks out anyone who never set a password, the same
  lockout `social_lockout` refuses for the built-ins.
- **SAML is deliberately NOT included.** It is not a configuration variant of the same flow: it needs
  XML signature verification (a new security-sensitive dependency), a POST binding, and its own
  assertion/replay handling. It is its own phase, not a footnote to this one.

**Social identity is global; authorization remains per makerspace.** `SocialIdentity(provider, sub)` links
Google/Apple to the global `User`; it never grants a role. Provider JWTs are server-verified against bounded,
cached static JWKS endpoints and one-time origin/device-bound nonces. Auto-linking is allowed only when both
provider and local email are verified; staff social login never creates an account or membership. Social
tokens carry `surface=member|staff`: member tokens are rejected by staff APIs, while staff tokens require
the exact trusted staff origin and matching tenant scope on access and refresh. Provider secrets remain
write-only/encrypted, and unconfigured social auth is omitted from public config.

**Phone is a login identity on a SEPARATE column, and only when VERIFIED (phase 18).**
`User.phone` stays free-text contact info (non-unique — two members may share a landline, and it is
copied onto requests as text). The identity is `User.phone_e164` + `phone_verified_at`, with a
partial unique constraint on non-empty `phone_e164` (the `uniq_telegram_user_id` shape). Reusing
`phone` was rejected: it would have meant rewriting existing free-text values in a migration and
putting a unique index on a column that already holds duplicates in real deployments; `phone_e164`
starts empty everywhere, so its constraint always applies cleanly.
- **`save()` clears `phone_verified_at` whenever `phone_e164` changes — unconditionally.** That is
  the guard stopping an edited number from inheriting a verified stamp, and `/control/` can edit the
  field, so it cannot live only in the service. Consequence: the linking service must write the
  stamp **after** `save()` via `User.objects.filter(...).update(...)`, exactly as
  `confirm_challenge` does for `email_verified_at`. Setting both in one `save()` silently loses it.
- **Deferred raise, or the attempt cap is inert.** `confirm_link`/`confirm_login` collect a failure
  and raise **after** `transaction.atomic()` exits. Raising inside rolls back the
  `failed_attempts` increment with everything else, so the counter never rises and a code stays
  guessable — the bug that shipped in the first draft and that `test_attempts_are_capped_per_challenge`
  caught. `services_registration.confirm_challenge` defers for the same reason.
- **MEMBER SURFACE ONLY.** `refresh["surface"]` is hardcoded `"member"`, never derived from the
  request. An SMS code is the weakest factor here (SIM swap, number recycling) and staff hold
  destructive powers, so staff must come through password or a social provider on the trusted origin.
- **The login start endpoint is a uniform 200 in every case** — unknown, malformed, suspended, or on
  cooldown. `ChallengeCooldown` is swallowed there on purpose: a 429 only for real numbers leaks
  exactly what the generic ack protects. `LINK` and `LOGIN` challenges are discriminated by
  `purpose`, so an abandoned link code cannot sign anyone in, and the code digest is
  **domain-separated by number** because a login challenge is resolved by number, not by user.
- **Requesting a code and guessing a code have SEPARATE per-number budgets**
  (`phone_otp_number` vs `phone_confirm_number`). One shared bucket meant three typos locked a
  member out for an hour holding a valid code.
- **E.164 is required, never guessed.** `phone_numbers.normalize_e164` strips only separators humans
  type and accepts a leading `00`; a bare local number is rejected rather than assigned a default
  region, because an ambiguous identity is a login that hands one person's account to another. No
  `phonenumbers` dependency.
- **SMS is platform-scoped and dormant by default.** `PlatformSmsSettings` (singleton, encrypted
  token, `/control/`-only) rather than env vars, matching `PlatformEmailSettings` — no new variable
  through four compose services and both installers. `apps/integrations/sms/` is the provider seam
  (`base.py` protocol, `twilio.py` the one impl, stdlib `urllib`), shaped like the encryption key
  broker so a self-hoster outside Twilio's footprint can add one without touching call sites.
  `get_sms_provider()` returns **None** when unconfigured and `/api/v1/config` **omits
  `phone_login` entirely**, preserving the dormant-payload invariant. `reserve_platform_otp_sms_quota`
  is the one quota that **also applies on self-host** — every text is billed to the operator, so it
  is a cost ceiling, not fair use — and it fails **open**, because the security controls are the
  cooldown and the attempt cap.
- **`accounts.User` is deliberately absent from the PII encryption registry**, which is what makes a
  plaintext unique index and a direct login lookup possible: scoped encryption is per-makerspace and
  `User` is platform-global, so it could never be scoped-encrypted.

**`Makerspace.clean()` NORMALIZES capabilities; the explicit call sites VALIDATE.** `clean()` prunes
features whose module is absent (and already adds core modules back rather than rejecting), because a
row must never be unsaveable: `enabled_features` takes its field default independently of
`enabled_modules`, so a makerspace created with a narrow module list is born holding the default-on
`payments.enabled`/`mobile.push` without their modules — and a strict `clean()` then rejected **every
later save, including ones touching neither field**. The operator-facing strictness lives at the two
direct `validate_capabilities` call sites (`/control/`'s capability matrix, `module_install`), so a
conflict somebody actually expressed is still reported instead of silently cleared, and
`MakerspaceSerializer.validate` prunes **only when the request does not carry `enabled_features`** —
if the caller sent features they expressed the combination; if they did not, it is not their conflict.
This reverses a phase-3 rule; `tests/makerspaces/test_module_install.py` carries the reversal and the
reasoning.

**Account-less identity: `accounts` removes the ECOSYSTEM, never identity (module program phase 9).**
`apps/accounts/member_identity.py` is the one seam every member-facing login surface asks, and it has
two exemptions that are load-bearing:
- **Staff authentication is never gated.** Core RBAC — a deployment that could switch off its own staff
  logins could not be administered (the A7 reasoning). The gate is therefore keyed on the login
  *surface*, not merely on the provider.
- **A configured `oidc:*` provider is never gated.** Those rows are the space's own directory and are
  precisely the identity source an accounts-off install authenticates against; gating them would remove
  the alternative at the moment it removes the default. `is_external_provider` reuses
  `slug_from_provider_key`, so the namespace has one parser.
Reads fail **OPEN** (a broken capability lookup must never lock people out), which is deliberately the
opposite of the access rules — do not "fix" one to match the other. Gated on the member surface only:
phone sign-in (checked on start **and** confirm, so a code issued before the switch cannot still mint a
session), the built-in Google/Apple providers, and self sign-up. `/api/v1/config` emits
`member_accounts` **only when off**, preserving the byte-for-byte payload; that key is discovery, and
`SocialLoginView` is enforcement — `social_auth` still advertises the built-ins because the STAFF login
screen reads the same endpoint.
- **`makerspaces/walk_in_services.py` is the substitute, and is gated by NO module.** `membership`
  requires `accounts`, so gating walk-ins by either would remove the substitute and the thing being
  substituted together. It creates a real `User` with an **unusable password** — naming a person, not
  provisioning a login — so every downstream PROTECT FK keeps working. Two rules: a typed number goes
  to free-text `User.phone` and **never `phone_e164`** (a login identity under a partial unique
  constraint, and a counter-typed number proves nothing), and a **known email is refused, never bound**
  — attaching an existing account to a roster is a `MANAGE_MAKERSPACE` decision, and binding would
  silently reactivate a deliberately revoked membership through the one form meant for strangers. The
  endpoint is gated on `ISSUE_DIRECT_LOAN`, because naming the stranger at the counter is the same
  front-desk act as handing them a tool.
- **The unusable password is NOT the boundary — `User.is_walk_in` is** (`accounts/0014`).
  `set_password` replaces an unusable password perfectly happily, so `ForgotPasswordView` finding the
  record by the email staff typed at the counter, and `ResetPasswordConfirmView` setting a password on
  it, is a complete path from person record to real login — past disabled self-registration, into a
  membership somebody else created. The flag is checked on **both** paths (request *and* confirm, so a
  link minted before the record was marked still fails), and both keep their generic response, because
  refusing visibly would disclose which addresses belong to walk-ins. Generalise it: an unusable
  password is a statement about the present, and every path that can *set* a password must know the
  record is not supposed to have one. **That means EVERY path**: `admin_api.services_user_access.
  reset_user_password` hands back a usable temporary password and is refused for a walk-in in the
  **shared service**, because the REST endpoint and the Django admin action both call it and a check
  in one leaves the other open. Migration `accounts/0015` backfills the marker from the **union** of
  the append-only `member.walk_in_created` audit trail and usernames beginning `walkin_`, and revokes
  any password/refresh token already acquired through the hole for both sets. The second signal is
  load-bearing: audit rows are makerspace-scoped and die with a tenant purge, while the username lives
  on the global `User` row and survives untouched. `walk_in_services._available_username()` assigns
  every walk-in the `walkin_<name>_<random>` namespace; self-registration uses `member_<uuid>`, so the
  two cannot collide. A marker that leaves the credential working changes nothing for exactly the
  accounts it exists for. Enforcement lives at credential *creation*, never at login: after these
  guards no application path can give a walk-in a password, so a login check would guard an
  impossible state while blocking a superadmin who deliberately set one in `/control/`. **The
  backfill must also clear what a working session was used to LINK** — `SocialIdentity` (whose
  login path returns on an existing identity match *before* the auto-link guard), `phone_e164` +
  `phone_verified_at` (a login identity resolved by number, which never reads the marker) and
  `DeviceGrant` (its own rotating refresh family, so blacklisting today's tokens is not enough).
  Revoking the password alone leaves three doors open. **And `_explicit_link` refuses a walk-in
  outright** — the migration cannot reach a live *access* token for ~15 minutes, and that window is
  long enough to link a fresh provider and undo the revocation. The guard sits inside
  `_explicit_link` (after its `select_for_update`), because that function is where every explicit
  link in the system is created.
- **AN ACCEPTED RISK IS A CLAIM ABOUT THE CODE AND MUST BE VERIFIED LIKE ONE.** A6 was accepted on
  the assertion that no durable signal identified a walk-in after tenant purge, even though the
  function generating exactly that global-row signal had already been read in the same session.
  Writing the dismissal into a report did not settle it; the next review correctly re-raised it.
- **Phone linking is guarded too** — `services_phone.confirm_link` writes a verified `phone_e164`,
  and a verified number IS a login identity resolved by number. The check sits inside its
  `transaction.atomic()` on a `select_for_update` re-read (the caller's `user` came off a JWT and
  may be stale) and uses the file's **deferred-raise** pattern, because raising inside the block
  rolls back the `failed_attempts` increment and silently disables the attempt cap. `start_link` is
  refused as well: it writes a challenge row and spends real SMS credit.
- **A guard that runs after a challenge or token has been consumed is itself a state-changing path
  and must emit an audit entry.** Phone `_confirm` persists `consumed_at` before the walk-in refusal,
  so that branch records `member.phone_link_refused_walk_in`; returning an error does not make the
  already-committed consumption read-only.
- **THE COMPLETE LIST of guarded credential-writers for a walk-in** — forgot-password,
  reset-password confirm, change-password, member sign-up, `admin_api` staff reset, social auto-link,
  social explicit link, phone `start_link` + `confirm_link`, plus username-collision assertions in
  `seed_demo` / `setup_instance`. The CLI checks protect data integrity rather than access control —
  shell access already overrides the application. **Adding any new way to set or verify a credential
  means adding it here.**
- **Audited and deliberately NOT guarded: phone unlink only.** `views_phone.py` only clears a login
  identity. A guard on that revocation path would make a walk-in's phone identity impossible to
  remove, which is the opposite of the marker's purpose. Change-password now refuses explicitly even
  though `check_password` already failed against an unusable password; member sign-up now returns
  silently before stamping `email_verified_at` on a reused walk-in row, preserving the endpoint's
  account-enumeration-safe response; and the two CLI commands now assert against collisions. The
  social new-user branch creates a fresh account and therefore has no existing walk-in target.
- **The meta-rule, learned across FIVE review rounds on this one seam:** when a marker means "this
  record must never hold a credential", **enumerate every writer of a credential once, as a list,
  and guard them together** — never close paths one at a time as a reviewer points at them. Each of
  the seven above was found in a separate round, all the same mistake. Note that this rule was
  already written here after round 5 and the *next* commit still guarded a single path: writing the
  lesson down did not apply it, so the list above exists instead of the advice alone.
- **A walk-in may carry neither an email nor a phone, and downstream models often require both.**
  `EventRegistration` has two non-blank contact columns, so the members this seam made registrable
  were exactly the ones that could not be registered. Each such surface needs a **caller-supplied
  fallback** (`member.email or email`, `member.phone or phone` — account first, so the fallback can
  never redirect a real member's mail) **and the matching console field**: a fallback the staffer
  cannot type is the same as no fallback. **A conditional console field must key off
  `StructuredApiError.body`, never `.message`** — the message is built from `Object.values(body)`
  alone, so a DRF field error arrives as the bare `"This field cannot be blank."` with the field
  name stripped. Matching the message for `/phone/i` looked right and never once fired, so the
  prompt it gates had been dead since the day it shipped.
- **Known gap: OIDC has no browser flow.** The backend accepts an ID token only, and no frontend renders
  configured providers, so on the web an accounts-off deployment today means staff-created walk-ins.
  Adding the browser flow (PKCE, redirect, discovery) is its own phase.

**Login methods are four independent platform switches (module program phase 10).**
`accounts.PlatformLoginMethods` (`pk=1`, superadmin-only) governs password / social / phone /
self-registration. Platform-scoped and never a tenant feature, for the reason that keeps social sign-in
off the capability registry: each resolves before a makerspace is selected. All four default **on** and
are additive `AND`s in front of the readiness each method already had, so switching one on can never
make an unconfigured method work. `load()` deliberately does **not** `get_or_create` — this is read on
every unauthenticated login attempt, and a read path that writes is a write per login attempt.
- **The `social` switch covers the built-ins AND every OIDC provider**, because they share one endpoint,
  one nonce contract and one config entry. Disabling one provider is what `is_enabled` is for.
- **`login_methods.py` has two halves with opposite failure directions**: the reads fail OPEN, the
  lockout guards refuse whenever they cannot prove the change is survivable. `users_stranded_without_social`
  is the platform-wide twin of `social_lockout` (someone holding Google *and* Apple survives either being
  cleared and is stranded by social being switched off), and `superadmins_without_social` is the floor
  that keeps `/control/` reachable. Password + social both off is refused outright: **phone issues member
  sessions only** (the refresh claim is a hardcoded `"member"`), so it can never rescue an administrator.

**Maker profiles hang off `MakerspaceMembership`, and are deliberately NOT PII-encrypted (phase 12).**
`User` is platform-global and scoped encryption is per-makerspace, which is why `accounts.User` is
outside the PII registry — so a profile attached to the user could be scoped to nothing. Per-membership
is also the truer model: what someone publishes to one space is not theirs to publish in another.
`ScopedPiiModelMixin` is omitted on purpose (`separability.E001` only fires for models that take it, and
its own hint names dropping the mixin as the right answer): every field is content the member wrote and
asked to have shown, so encrypting it buys nothing and drags in the envelope/dual-read machinery.
- **Visibility is opt-in and defaults off**, and no profile row is the same answer as an invisible one.
  Directory rows carry display name, headline and avatar and **nothing else** — everyone who did not opt
  in becomes part of `hidden_count`, so a space can show its size without naming anyone. One 404 covers
  "no such member", "not a member here" and "has not published".
- **`member` is a fifth public-image kind and needed all four registrations plus the collision check.**
  `build_object_key`, `lifecycle._collect_public_image_keys`, `recompute_storage._public_image_keys`,
  `module_purge_plans["membership"].public_image_keys` and `public_image_key_in_use` (new `profile_id` /
  `project_id` exclusions). All but the first fail **open**. Profiles are reached through
  `membership__makerspace`, since the row carries no makerspace column.
- **Profiles go with a `membership` purge; the membership itself still does not** (plan A7 unchanged).
- **Link URLs are restricted to http/https**, because they render as an `href` on a page other members
  read — a stored `javascript:` URL is stored XSS and escaping the text does nothing for an href. Every
  member-writable list is length-capped.
- **GitHub is never fetched on a read path.** `refresh_github_contributions` (command + Celery) does it;
  a failure keeps the last known count and still stamps `github_synced_at` so a throttled API backs off.
  Unset `GITHUB_API_TOKEN` = dormant, count stays `None`, section omitted. Changing the handle clears the
  cached count outright, or one account's total shows under another account's name. **The write-back
  is filtered on the handle that was FETCHED, not just the pk**: a member can change their handle
  while the HTTP call is in flight, and an unconditional `.update()` then lands the old account's
  total under the new name. A count under the wrong name is a false claim about a person, not stale
  data, so the raced write is dropped rather than applied.

**Staff event registration is the SAME service, with exactly one relaxation (phase 13).**
`services_registration.register(..., staff_registration=True)` relaxes only the `is_public` check —
that flag means "listed in the public catalogue", and a staffer at the door is not the public, so
without it a members-only event could not be registered for by anyone. Published, not-ended, capacity,
waitlisting, duplicates, the custom form, the write fence and the charge are all unchanged, because the
state machine has one home. The endpoint takes a `member_id` only: a person with no account is given a
walk-in record first, so there is one identity path instead of the events surface minting
half-identified attendees. `phone` is a **fallback used only when the account has none** (`member.phone
or phone`) — `EventRegistration.phone` is non-blank, so an account without a number was previously a
dead end; the public path passes none and is unchanged. The picker hangs off the EVENT
(`EventEligibleMemberListView`), inheriting `_manageable_event` rather than inventing a second answer to
"who may see this makerspace's members", and excludes the already-registered.

**A login-method switch is enforced on `/control/` too — but only while another way in exists.**
`password_enabled` lives in `LoginView` (the JWT API) *and* in `AdminSuperuserOnlyMiddleware`, which
refuses a POST to `admin:login` **before the form authenticates**, so no session is minted. Enforcing
only the API left a password door on the one surface that can turn the switch back on. Existing
sessions are deliberately not revoked: a login-method switch is a policy change, not a revocation.
- **The middleware check ALSO requires `settings.PLATFORM_ADMIN_SSO`, and that is load-bearing.**
  Social sign-in mints **JWTs for the React console and never a Django session**, so there is no
  password-free route into `/control/` today — enforcing unconditionally sealed the only page that
  can undo the switch, the moment the last admin session expired, with no application-level recovery.
  The flag is declared in settings (default False) rather than read with a `getattr` default so it is
  findable and an operator building such a route has somewhere to flip. **Do not "tighten" this back
  to unconditional without first shipping the alternative route** — the accepted consequence (a
  superadmin can still sign into `/control/` with a password) is written up as A5 in
  `docs/module-program-security-report.md`, and the enforcement path is already tested.
- **The rule this came from: a fix to an auth path needs its own "what is now unreachable?" check**,
  not just "is the hole closed?". The original fix was correct about the hole and created a permanent
  lockout that only the next review pass caught.

**Member profile writes are audited WITHOUT their content.** `member.profile_updated` /
`member.profile_image_updated` / `member.profile_image_cleared` record the fields touched, the
visibility transition and the project counts — never the bio, the education entries or the object
key. The audit log is append-only, so anything written there is permanently undeletable member PII,
and an object key logged there outlives the image and every row that could name it.

**Notification channels are modules, one key each (phase 20).** `email`, `telegram`, `slack`,
`mattermost` and `discord` each own a module key, so a space living in Discord ships no Slack
surface. Each is an additive **AND** in front of the credential check that already existed:
enabling a key cannot make an unconfigured channel send, and disabling it stops delivery while the
**stored webhook survives**, so re-enabling needs no re-entry.
- **`dispatch_channels.channel_module_blocks` is checked in TWO places**, mirroring the email gate:
  `dispatch_channel` (new alerts) and `_deliver_notification` (a PENDING row can sit in Celery
  across an uninstall, and a retry re-enters there). A blocked message becomes a terminal
  `NotificationDeliveryStatus.SKIPPED` — recorded, not dropped — and `notify._run_guarded` counts
  SKIPPED as **neither** delivered nor failed, because `bool(delivered_counts)` must not read a
  suppressed channel as a reminder that went out. It fails **open** on a lookup error: a broken
  capability check must not silently mute a space's alerts.
- **`makerspaces/0056` backfills `slack`+`mattermost` UNCONDITIONALLY onto existing rows** — the
  `0050` email precedent. Both were previously governed by webhook presence alone, so the opt-in
  default would have muted every upgrading space silently. Unconditional (not "only spaces that
  already hold a webhook") because granting the key restores the old rule *including* for a space
  that configures Slack for the first time next month. `discord` is **not** backfilled: it is new,
  so opt-in is correct for it.
- **The notification matrix OMITS a channel whose module is uninstalled** rather than rendering it
  disabled (`views_notification_rules._response_data` filters both `channels` and `preferences`).
  A tickable column would accept the tick, store the preference, and then SKIP every send — the
  same reasoning as pruning a tombstoned sidebar entry instead of permission-hiding it.
- **Discord is not Slack-shaped.** `webhooks.py` maps channel → body key because Discord names the
  field `content` and ignores `text` (400, nothing delivered), and trims to its hard 2000-character
  limit, which rejects rather than clips. `native_push` has **no** module key — it is governed by
  the standalone `mobile.push` feature.
- **Chat credentials are per-makerspace by nature, identity credentials are platform-wide.** The
  tenant owns the destination channel and pays for it; identity resolves before a tenant exists.
  Do not re-propose per-makerspace auth credentials — that was considered and cancelled.

**Notifications v2 — recipients, rooms, templates, scoping (phase 21).** Four additions on top of the
per-feature×per-channel matrix, all additive and dormant until configured. The governing rule: this area
fails **OPEN** to the action-based default — a broken selection, scope, module or template lookup must
never mute a makerspace. Deliberately the opposite of the *access* rules, which fail closed.
- **`integrations/recipients.py` — per-event recipient selection, where NO ROWS MEANS TODAY'S BEHAVIOUR,
  not "nobody"** (`DEFAULT_CHANNEL_STATE` has bookings email+telegram ON, so default-nobody would have
  silently stopped booking mail that flows in production). Rows become authoritative only once one exists
  for a (feature, event); deleting them all restores the action-based default. Only
  `events`/`bookings`/`maintenance`/`members` are selectable — **`hardware_requests` and `printing` keep
  `EmailNotificationMute` untouched**, being the alerts a space cannot afford to lose to a wrong backfill.
  Kinds: `role` (a real FK, so a rename keeps its rules and a delete removes them), `requester` (a **flag
  the caller reads**, never an address this layer emits), `members`, `user`. **A named `user` must hold a
  membership of that makerspace**, enforced at the picker AND re-checked at send time — bodies carry
  requester names, machine detail and booking info, so an arbitrary platform account is a hand-operated
  cross-tenant leak. A member's `receives_notifications` opt-out **always wins**, filtered in the query so
  no branch can forget it. The module gate lives inside `selection_rows`, not in front of the resolver, so
  stale rows for an uninstalled module fall back rather than mute. Native push is filtered by the same
  selection, which is why `dispatch_channel` stores the scope on the log — push resolves recipients at
  DELIVERY time and would otherwise match nothing.
- **`NotificationDestination` — one row per room, and `[None]` means the legacy column.**
  `destinations.resolve_destinations` returns rows **or the single sentinel `None`**, which every sender
  already handles. No rows for a channel ⇒ `[None]` ⇒ byte-for-byte the old behaviour, which is what makes
  migration `0021` (one space-wide destination per configured webhook **and per Telegram chat id**) safe;
  the `Makerspace.*_webhook_url` columns stay readable for a release. The query is deliberately **not**
  filtered on `is_active` — that would make a deactivated sole room read as "no rooms" and fall back to the
  credential underneath. **No scope links ⇒ space-wide**, the OPPOSITE default to role machine-scope (an
  unscoped *role* must reach nothing; an unscoped *room* is not a permission); an alert naming no subject
  reaches no *scoped* room. Credentials are typed per channel with a check constraint, never one overloaded
  column. One log row per destination (D13), quota charged per room, and `destination_label` is snapshotted
  so a queued row whose room was deleted goes terminal instead of falling through to the space-wide webhook.
- **Telegram is the channel every "all four platforms" claim fails on.** It never went through
  `send_webhook` (`telegram.send_message` reads the makerspace directly), so both senders take a
  destination. **Telegram destinations carry NO bot token** (`resolve_bot_token` is makerspace →
  `settings.TELEGRAM_BOT_TOKEN`): the accept/reject buttons post back to ONE webhook authenticated by a
  single `TELEGRAM_WEBHOOK_SECRET`, so a second bot's callbacks could not be authenticated or routed and
  its buttons would be dead. Per-bot destinations need per-bot secrets and inbound routing — its own phase.
  Inbound routing resolves the actor from `from.id` and the request from the callback data, never a chat
  id, so rooms cannot strand a callback. `notification_enums.MAX_MESSAGE_LENGTH` is one table for all four
  (Telegram 4096, Slack 40000, Mattermost 16383, Discord 2000) because Telegram and Discord **reject** an
  oversized body rather than clipping it.
- **Templates extend `email_templates_registry`, never a second engine.** Four FabLab streams
  (`events`/`bookings`/`maintenance`/**`membership`**) × both audiences × 20 events = 40 entries with
  declared `fields`, `sample_context` and defaults reproducing what each adapter sent inline. The `members`
  feature maps to the **`membership`** stream — the one pair where feature key and stream name differ,
  because existing `EmailLog` rows carry `membership`. `ChatTemplate` is **one body per (makerspace,
  feature, event) shared by all four chat channels** (per-channel bodies quadruple the editing surface),
  falling back to `LifecyclePayload.text` when absent, inactive, unknown, empty or broken. **Chat is a
  STAFF surface, enforced in code**: `render_chat_text` raises on a requester audience and resolves only
  STAFF entries — a webhook is a room, so "your booking is confirmed" would expose that member's name to
  everyone with channel access. Native push takes `payload.text`, not the chat body.
- **Recipient object scoping composes as `role_scope AND (rule_scope OR all)` — narrowing only.** Rule
  links reuse the destination shape (`no links ⇒ everything`); the role floor reuses `machines/role_scope`
  via the batch `manage_scopes_for_memberships` (two queries, not an N+1), never a parallel resolver. **The
  floor applies to `kind=role` rows ONLY** — applying it to `members`/`user` would make those kinds
  unusable for maintenance, since a plain member holds no machine grant and resolves to the fail-closed
  `NOTHING`.
- **Staff API + console are mandatory, not optional** — `/control/` is not proxied on the public frontend
  port, so without `notification-recipient-rules` and `notification-destinations` a space manager could not
  configure any of this. Saves **replace** rather than merge (a merge makes unticking impossible), an
  unknown/foreign scope id is a **400, never a silent drop**, a room's channel cannot be changed after
  creation, and the credential is **write-only** (blank on update keeps the stored value).
  `admin_api/notification_scope.py` is the one scope writer shared by both surfaces. Email-template
  `STREAM_ACTIONS` gained the four streams (membership is `MANAGE_MAKERSPACE`-only: it carries applicant
  identity) plus a module gate.
- **G4/G5 fallout:** `integrations/health.py` gained a `chat_destinations` section reporting every room
  (configured / last delivery / last error, never the credential) plus the channels still on the legacy
  path. And `module_purge_plans` gained one plan per chat channel key: a destination holds an encrypted
  secret, so uninstall-then-purge of `discord` must destroy it. Delivery history survives (`SET_NULL` +
  label).

**Presence geofence is ADVISORY, not an access gate (C.7).** Browser coordinates are spoofable, so
`presence.geofence.evaluate_geofence` only classifies a reading (in_range / distance+accuracy buckets, raw
coords never stored) and records it in the `presence.started` audit — it **never blocks** session creation,
and the client never hard-blocks check-in on a location error. Do **not** convert it into a fail-closed gate
without an unforgeable proximity factor (owner decision). Dormant/self-host safe: no geo config ⇒ no check,
and the `geofence_enabled` bootstrap flag is **omitted entirely** (byte-for-byte-unchanged invariant).

**One colour vocabulary, and `tone-*` is GONE.** The four pastels existed twice under two names —
`--color-accent` == `--color-tone-blue`, `secondary` == `tone-pink`, `success` == `tone-mint`, `warn` ==
`tone-yellow` — so which name a component reached for was historical accident. The semantic vocabulary won
(`bg-success` says why the colour is there; `bg-tone-mint` does not) and the `tone-*` tokens are deleted
from `index.css` and `tailwind.config.ts`.
- **THE MIGRATION WAS NOT A RENAME, and treating it as one breaks dark mode.** Only the FILLS were
  byte-identical: `tone-*-ink` stays **fixed dark** in dark mode like `on-*`, while `{name}-ink` goes
  **light**. So all 39 `tone-*-ink` call sites map to **`on-*`**; mapping them to `-ink` puts light text on
  a light pastel fill. Fills map straight across.
- **Colour is surface-coded**: `accent` = interaction, primary actions, active nav, staff chrome;
  `secondary` (pink) = every stranger-facing surface (public catalogue, member area, auth, kiosk);
  `success`/`warn` keep their status meaning; `danger` is the only non-pastel.
- **The display face was never unused — it was suppressed.** `@layer base` maps every `h1`–`h6` to Clash
  Display; `Panel` simply rendered its `h2` as `text-sm font-semibold text-muted`. The scale lives in
  `@layer components` as `.title-page` / `.title-panel` / `.title-section` / `.eyebrow` (the JetBrains Mono
  voice for labels, units and column headers) so the decision sits in one place, not in 200 class strings.
- `tests/test_frontend_theme_contrast.py` also guards `success-ink`, `warn-ink`, `info-ink` — omitted while
  the palette was effectively one colour and those inks appeared only inside solid fills.
- **Buttons are a CLOSED FAMILY in `@layer components`**, not per-component class strings: `desk-button`
  (neutral), `-primary` (staff main action), `-secondary` (public/member main action), `-success`, `-warn`,
  `-danger`, `-ghost` (quiet tertiary). Each carries `min-h-11` and the same `focus-visible` ring, so
  adopting one fixes the touch target and the keyboard focus together — most of why the family exists.
- **Colour VARIES but is never RANDOM.** A repeating set distributes the four tones so a screen shows the
  whole system, but the tone is a **stable** property of the thing — assigned by meaning
  (`DashboardPanel.TILES`) or derived from identity (`MemberDirectory.identityTone`, a character-sum hash).
  Never `Math.random()`, never index-by-render-order, never over something already semantically coloured.
- **A tone is NEVER expressed as `border-l-4` on a card.** A side-tab accent stripe is the most recognisable
  generated-UI tell and the design detector fails on it; it was reached for twice, so the rule is written
  into `docs/superpowers/specs/2026-08-13-design-language-brief.md`. Carry the tone in the heading ink, the
  number, a badge, a `/15` tint, or a 1px full border.
- **On a filled tile every text colour must come from the fixed `on-*` set** (or `text-bg` for `danger`).
  `status-box-danger` is `bg-danger text-bg`, and a tile that added `text-danger` to the number and left
  the label `text-muted` rendered dark red on red and grey on red.

**Accessibility floor (phase 22).** Four rules, each with a real counter-example in the tree:
- **Text contrast is drift-guarded from the backend suite.** `tests/test_frontend_theme_contrast.py` parses
  `frontend/src/index.css` and fails any text token below AA (4.5:1) on `bg`/`surface`/`panel`, or
  `--color-focus` below 3:1. It lives in pytest because **vitest resolves CSS imports to an empty string**
  under its default config (`?raw` included), so the check is impossible there; `docker-compose.dev.yml`
  already mounts `./frontend:ro` into the backend for this class of guard (`features.ts` is the precedent).
  Parse with comments stripped: the theme's own notes contain `{name}-ink`, whose brace ends a naive block
  scan early and hides every token after it.
- **`focus:outline-none` is banned.** Tailwind applies it on `:focus`, which subsumes `:focus-visible`, and
  `@layer components` outranks `@layer base` — so one `focus:outline-none` in a `.desk-*` class silently
  defeats any global focus style. Components carry `focus-visible:outline-2 focus-visible:outline-offset-2
  focus-visible:outline-focus` on a dedicated `--color-focus` token, not the pastel accent at `/40` alpha,
  which never reached 3:1.
- **A skip link needs `tabIndex={-1}` on its target, and the target must always render** (outside any
  conditional — the print page put `#main-content` inside `{enabled ? ... : null}`, so the link pointed at
  nothing while the module was loading or off). Without the tabindex the browser scrolls but leaves focus
  behind. The target is the **content region, not `<main>`** — these pages nest `<header>` inside `<main>`.
  `MemberArea` deliberately has no skip link: its shell has no nav.
- **Collapsed content is unmounted, never `hidden`-but-present** (`CollapsibleSection`), or keyboard users
  tab into controls they cannot see. Its count is one text node (`` `${n} items` ``) because the
  accessible-name algorithm trims each node and joins with no separator — `{n}<span> items</span>` is
  announced as "3items".

**Console parity principle.** Every backend lifecycle capability reachable in the Django `/control/` admin
must have a React staff-console surface — a capability with no console surface is a latent dead/broken
feature for normal staff. New workflow actions ship their staff UI in the same batch.
## Handover roles and the retired Guest Admin

**Guest Admin is no longer a built-in role** (migration `makerspaces/0052`); handover staff get a **custom
role** holding the handout actions. `rbac.HANDOUT_ACTIONS` is no longer a cap on what a role may hold
(`role_services._validate_actions` dropped that branch) and now only defines what counts as handover-only
for `rbac.is_handout_only`, which decides how narrow the console is. A handout role issues accepted
requests, creates **direct handouts** (`ISSUE_DIRECT_LOAN` is in the set, pinned by
`test_guest_admin_can_create_direct_loan`), processes scoped returns, and uploads evidence — through the
same evidence/QR/remark/audit workflow as staff. It still cannot accept/reject requests, edit inventory,
or manage QR unless granted those actions. **Both enum members are gone**: `makerspaces/0053` moved every
remaining `role="guest_admin"` membership onto a real role row (reusing the space's untouched handover
role only when its actions still equal the frozen six, else creating a collision-safe "Front Desk" role)
and `0054` dropped the choice; `accounts/0009`/`0010` did the same for `User.Role.GUEST_ADMIN`. The
`_MEMBERSHIP_ROLE_ACTIONS` fallback entry went with them, so `print_manager` is the only frozen legacy
string left. Tests build a front-desk staffer through `tests/handout_roles.py`
(`handout_role`/`grant_handout`/`make_handout_member`), whose default action set
is deliberately the exact six the built-in granted. The `guest-admin/` **URL paths** in
`hardware_requests/urls.py` are untouched: they are the handover API surface (module key
`guest_handover`), not the role, and renaming them would break clients.

**Print Manager is retired too** — migration `makerspaces/0046` reassigned its memberships to Machine
Manager, whose `MANAGE_MACHINES` implies `MANAGE_PRINTING`. The string survives only in
`_MEMBERSHIP_ROLE_ACTIONS` as the frozen legacy fallback for a null-FK membership.

## Separability and tombstoning

**Separability: two registries, and the gap that fails OPEN (Phase 7, `apps/separability/`).**
An app can be **tombstoned** — surfaces gone, rows and migrations retained (`apps/printing`,
`apps/roadmap` are the precedent) — and that forces two registries with opposite lifetimes.
**Retention** (PII field mappings, purge plans, storage collectors, historical payment subjects) is
registered **even when tombstoned**: deregistering it makes retained rows unpurgeable and
unencryptable and strands private S3 objects nothing can name. **Runtime** (URLs, reports, admin,
frontend surfaces, origin-scope routes) registers only while the app is active.
- **A missing PII registration fails OPEN, which is why B3 is a system check and not an assertion.**
  `ScopedPiiModelMixin` asks the registry for a model's fields and reads an empty answer as "holds no
  PII"; every protection then no-ops in the safe-looking direction — `__getattribute__` returns the raw
  column, the `bulk_create` guard passes, the save boundary writes no envelope, the write fence is
  skipped — and the row lands in the clear with nothing raised. `separability.E001` now **refuses
  startup** (verified: deleting `bookings.Booking` from the map makes `manage.py check` a
  `SystemCheckError`), and `UnmappedPiiModel` is the runtime backstop for a `--skip-checks` process.
  The check is deliberately **not** gated on `PII_ENCRYPTION_ENABLED` — the deployment that has not
  enabled encryption yet is exactly the one that will, and the gap must be caught before the flip.
- **Registration happens in `AppConfig.ready()`, so it must be query-free and idempotent** — `ready()`
  also runs for `migrate`, `makemigrations`, tests, Celery workers and management commands.
- **`apps.separability` must stay LAST in `INSTALLED_APPS`.** Django imports every models module, then
  calls every `ready()` in list order; being last is what guarantees all registration precedes
  `finalize()`, which freezes the maps. Registering after the freeze raises rather than mutating a map
  some consumers already read.
- **Duplicate keys are fatal, never last-write-wins** — two apps claiming one purge node or PII model
  means one is silently unprotected, and the loser is invisible.
- **Consumers call accessors (`fields_for_label`, `all_fields`, `registered_labels`, `runtime_active`),
  never `from ... import BY_MODEL`/`ALL_FIELDS`** — a module-level import binds an import-time snapshot
  that stops being true once registration is per-app.
- **`runtime_active(app_label)` replaces `apps.is_installed()`** at the two call sites that had it
  (`member_activity_service`, `reports_health`): a tombstoned app is still installed — it must be, or
  its migrations unapply — so `is_installed()` answers "are the tables there?" when the caller means
  "are the surfaces live?". Unregistered defaults to **active**, so no app must opt in to keep working.

**Tombstoning an app: `TOMBSTONED_APPS` + `SEPARABLE_APPS` (Phase 8+, `separability/tombstones.py`).**
A tombstone is a **deployment** decision, never per-tenant — URL routing, admin registration and the
OpenAPI schema are process-global, so an app's surfaces are present for everyone or absent for everyone.
It composes with, and does not replace, the per-makerspace `enabled_modules` switch: a module is usable
only when the tenant enabled it **and** the deployment ships the app. The env var names **app labels,
not module keys** (one app can own several keys — `printing`/`machines`/`machine_service` are all
`apps.machines`), and it never touches data: rows, migrations, purge plans and PII mappings all stay.
- **`payments` and `updates` joined `SEPARABLE_APPS` (phase 16).** A makerspace that takes no money
  online ships **no Stripe surfaces at all**, and a deployment updated by its own host tooling ships
  no in-app release control. The import counts are a red herring — 26 modules import `apps.payments`
  and every one keeps working, because a tombstone removes *surfaces*, never models: the rows stay
  readable, purgeable and nameable by the retention registry. Three things this needed beyond the
  standard pattern:
  - **The Stripe webhook is spliced out, not left answering.** An endpoint that still verified and
    settled a charge for an app whose reconciliation console is gone would move real money nobody
    can see. `config.urls.separable_paths` is the shape of `separable()` for inline single-view
    routes rather than an app urlconf.
  - **Some routes live in another app's urlconf.** `admin_api` owns the staff surface for payments
    and updates, so those cannot be removed by dropping an `include()` — `admin_api/urls.py` has its
    own in-place `_separable()` gate. The tombstone tests assert a **neighbouring** route in the
    same list still resolves, because splicing in place is exactly where an off-by-one removes too
    much.
  - **`_managed_item` had to become None-safe.** It called `_item(...)` and then subscripted the
    result; `_item` returns `None` for a tombstoned app, so the Stripe Connect entry would have
    turned a supported tombstone into a boot crash.
  Both apps own **feature** keys or no key at all, so `available_modules` has nothing to drop and
  `unavailable_apps()` is what tells the console to hide the tabs — the same reason it exists for
  `warranty` and `presence`. `TOMBSTONE_PROFILE_APPS` in `tests/tombstone/conftest.py` was extended
  in step, and the profile is now **ten** apps — `tenant_migration` joined it in Phase 5B, whose
  whole superadmin surface is separable.
- **Still NOT separable, with reasons:** `integrations` (platform mail carries password reset and
  email verification — removing it locks users out of their own accounts), `encryption` (the
  `ScopedPiiModelMixin` substrate six models depend on), `operations` (owns six module keys and the
  report registry that `machines`/`bookings`/`events` builders extend), `apiclients` (its HMAC
  middleware authenticates the whole public API surface), plus the core apps. `machines` is
  removable in principle and is the remaining piece for an inventory-only install; it has the widest
  surface area of any candidate and is deliberately left to its own phase.
- **`SEPARABLE_APPS` is declared, not derived.** Nothing in the module registry encodes "can this app's
  surfaces be removed without leaving the rest incoherent" — `is_core` comes closest and is a different
  question (`apps.makerspaces` owns only non-core modules yet is the tenant root; `apps.inventory` owns
  a core module *and* two optional ones). Anything in `TOMBSTONED_APPS` but absent from `SEPARABLE_APPS`
  **refuses startup** (`separability.E007`), which is what turns a typo, a dotted path or a core app
  from a silently inert setting into a boot failure. The set grows one app per B6 phase.
- **`module_enabled()` is the chokepoint**, ANDing `module_registry.module_available(key)` in, so a
  guard written later inherits the check without knowing it exists. `platform.available_modules()` is
  the read side — used by the bootstrap payload and both staff makerspace serializers, because the
  console turns those keys straight into tabs and a stale key renders a tab whose every request 404s.
  `/control/` and `module_install` keep reading the **raw** field: a superadmin must see what is stored.
- **Admin registration cannot ask the manifest.** `django.contrib.admin` sits above every `apps.*` entry
  in `INSTALLED_APPS`, so autodiscovery imports every `admin.py` *before* the owning app's `ready()` has
  registered anything. An `admin.py` must therefore call `app_is_tombstoned()` (settings) rather than
  `runtime_active()` (manifest); both derive from `tombstoned_app_labels()`, so they cannot disagree.
- **A sidebar entry must be omitted, not permission-hidden.** Unfold calls `str(link)` on every item to
  compute `active` **before** consulting the permission callback, so a `reverse_lazy` to a route the
  tombstoned app no longer registers raises `NoReverseMatch` and 500s the whole console.
  `_item(..., app_label=...)` returns `None` and `_prune_navigation` drops it (and any group left
  empty). `config/unfold.py` reads the env directly because settings *imports* it.
- **URL includes are spliced in place, never appended** (`config.urls.separable`): resolution is
  order-sensitive. `include()` is evaluated only when the app is active, because a genuinely gutted app
  has no urlconf to import.
- **The tombstone suite is a separate pytest run** (`tests/tombstone/`), because import-time surfaces
  cannot be re-derived in-process and the all-active suite asserts the opposite for the same objects:
  `TOMBSTONED_APPS=bookings,events,maintenance,notifications,payments,presence,procurement,tenant_migration,updates,warranty
  pytest tests/tombstone` — the conftest demands the **whole ten-app profile** and names the exact
  string it wants, so a single app (this line said `procurement` alone until 2026-08-11) is a hard
  `UsageError`, not a partial run. A whole-tree run skips the directory; an
  explicit run without the profile is a hard `UsageError`, never a green no-op. `TOMBSTONE_PROFILE_APPS`
  in its conftest must stay in step with `SEPARABLE_APPS`.

## Machine scoping — `MANAGE_MACHINES` is per role, and fails CLOSED

Moved here from "Hard Rules", where it had been appended and had grown to ~430 lines. Content is
unchanged.

- **`MANAGE_MACHINES` is scoped per role, and the scoping fails CLOSED.** `machines/role_scope.py`
  narrows **tier 1** of `access.py` using two link tables (`RoleMachineTypeScope`,
  `RoleMachineScope`, migration `0019`): a role holding `MANAGE_MACHINES` reaches a machine when
  **its type is linked or the machine itself is linked** — a union, not a hierarchy, so "all
  printers plus that one laser" needs no third concept. **No links ⇒ no machines.** Two exemptions,
  both in `role_scope` and neither optional: a role holding `MANAGE_MAKERSPACE` covers everything
  *including types created later* (making a space manager enumerate types to administer their own
  lab is a worse failure than the broad grant this replaces), and a membership with a **null
  `assigned_role`** resolves through the frozen legacy fallback, which is not a role row and has
  nothing to link — scoping it would silently strip a legacy Machine Manager.
  - **Two seeding paths keep it from being a regression.** Migration `0020` links every existing
    `MANAGE_MACHINES` role to every type that existed at that moment — **types, not machines**, so
    coverage keeps extending to hardware bought after the upgrade; freezing each role at that day's
    fleet would make the first new printer unmanageable. And `roles.ensure_default_roles` calls
    `role_scope.grant_builtin_type_scope` on **creation**, because the seeded Machine Manager
    default would otherwise be born inert on every makerspace created after the upgrade — grant
    without links, and a Machines tab that never appears. Space Manager gets no links (it is exempt;
    rows would be dead data misrepresenting the role in the console).
  - **Tier 2 now requires a DIRECTLY granted `managing_action`** (`role_scope.grants_directly`, and
    its query-level twin `makerspaces_granting_directly`). This is the hole that made the whole
    feature nearly worthless: `IMPLIED_ACTIONS[MANAGE_MACHINES]` contains `MANAGE_PRINTING`, and the
    built-in `3d_printer` type's `managing_action` **is** `manage_printing` — so a role scoped to
    lasers alone still satisfied the type-manager check for every 3D printer in the lab, straight
    through tier 1's links. A real Print Manager holds `manage_printing` outright and keeps its
    unscoped type authority; a `MANAGE_MACHINES` holder gets printer authority through tier 1, where
    the links apply. `rbac.can` is untouched, so nothing outside `machines/` changes. The object
    check and the list filter **must stay in step** — disagreeing is how a row lists and then 403s
    on click, which is why `capabilities_for_machines`' `_type_mgr` carries the same check.
  - **Tier 3 (per-machine operators) is untouched** — an operator row already names one machine.
  - **A MACHINE-TYPE SLUG IS NOT UNIQUE, and three surfaces assumed it was.** Uniqueness is
    *scoped* (`uniq_global_machinetype_slug` among globals, `uniq_lab_machinetype_slug` per
    makerspace), so a makerspace may legally create a local type carrying a built-in's slug — and
    a global type must be `is_builtin` (`machinetype_builtin_is_global`). Filtering service data
    by slug therefore returned **both** types' rows, so one type's jobs appeared under another and
    a manager could accept or reject from the wrong section. The staff queue and typed manual
    usage now accept **`machine_type_id`**, which takes precedence; the slug parameter stays for
    existing callers, and a malformed id is a **400 via `_query_int`, never a silent fall-through**
    to the printer default. The frontend `isBuiltinPrinterType` mirrors
    `printer_capabilities.is_printer_type` (`makerspace === null && slug === "3d_printer"`) —
    matching the bare slug mounted the printer console for a generic service.
  - **The machine-service REPORT still discriminates on the SLUG, and switching it to the id is a
    crash.** `MakerspaceMachineServiceReportView` branches on `machine_type` to decide whether to
    emit `printer_metrics`; sending an id returns the generic report, and `PrinterServiceConsole`
    dereferences `printer_metrics`, taking the **whole Machines panel** into its error boundary.
    Requests and manual usage use the id; the report keeps the slug. A test that stubs the
    transport cannot catch this — the existing report test answered regardless of query string, so
    the regression test asserts on the **request URL**.

**Staff Machines console is organised as machine type → everything of that type, on PER-TYPE
SUBPAGES.** `MachinesPanel` is the container: it owns the queries (machines, types, and ONE
canonical pool query), the status filter, the service drafts, the create form and the drawer, and
routes between an index of type cards (`MachineTypeCards`) and one type's page (`MachineTypePage`,
which replaced the collapsible `MachineTypeSection`); `SharedConsumablesSection` owns unbound pools.
- **The URL is `/admin/machines/<id>-<slug>` and THE ID IS AUTHORITATIVE.** Machine-type slug
  uniqueness is only *scoped* (`uniq_global_machinetype_slug` / `uniq_lab_machinetype_slug`), so a
  makerspace may legally own a local type carrying a global built-in's slug and both appear in one
  console — three shipped surfaces have already served one type's jobs under another by keying on
  the slug. `parseMachineTypeSegment` reads the leading integer; a malformed segment is "no
  selection" (the index), never a silent fall-through to a default type.
- **`StaffWorkspace` canonicalizes the URL to the active tab's path, so the subpath had to be
  threaded through it** (`keptStaffSubPath`) — otherwise the redirect fires on every load and strips
  the segment, and no per-type link can survive its first render. Subpaths are opt-in per tab
  (`TABS_WITH_SUBPATHS`): every other tab still normalises trailing junk away, and relaxing that
  globally would change how existing bookmarks resolve. The rule is extracted from the component
  precisely so a test can hold it — the panel's own tests mount a router at the deep link and stay
  green with it reverted.
- **A single reachable type renders its page INLINE at the index URL; it does NOT redirect.**
  Redirecting would make the index — and with it machine creation, machine-type configuration,
  shared pools and the delegated recipient picker — permanently unreachable for exactly the scoped
  maintainer those controls exist for. Rendering inline also removes the redirect loop, the
  flash-redirect and the one-versus-many decision during loading.
- **An unknown or unreachable id normalises to the index, and only once BOTH server-scoped sources
  have settled successfully.** Judging on the types query alone contradicts the navigable nested
  fallback; judging while loading bounces every direct link; judging after a failure turns a network
  blip into an apparent permission revocation.
- **The machines query walks EVERY page** (`?page=N`, never DRF's absolute `next`, which
  `staffRequest` would prefix with the API base into a malformed URL). The cards state a count and a
  status roll-up as fact, so a first-page-only read prints a wrong number rather than an obviously
  truncated list.
- **`useServiceDrafts` lives in the container, not the page.** Only one type is mounted at a time
  now, so a hook inside the page would discard a half-typed service form on every navigation.

Load-bearing details that carried over unchanged:
- **Three DISTINCT pool concepts.** *Type display* pools are bound to a machine of that type;
  *shared display* pools (`machine_id === null`) appear ONLY in the Shared section, ending the
  duplication where a shared pool rendered under every compatible type; *form-usable* pools are
  shared pools **plus pools bound to the machine selected in that form** — the UI previously
  offered every pool bound anywhere in the type while the backend rejected them. Pool **creation**
  lives in the Shared section only, because both former create forms omitted `machine_id` and
  could therefore only ever produce shared pools.
- **Pages derive from TYPES, never from status-filtered machine rows** — a status filter
  matching nothing must still render that type's queue, manual usage and bound pools. But the
  type list is **merged with the nested `machine.machine_type`** as a display-only fallback: the
  two requests are independent, so building the index from the types response alone makes machines
  **vanish** whenever it fails or goes stale. Those fallback types **are navigable** (the machines
  list is server-scoped too, so a machine the server returned implies a reachable type) but grant no
  creation authority, because nested copies carry no `can_create_machine`. The governing rule is
  "navigate from server-scoped responses only, never from inferred action strings".
- **Drafts must reset after a completed ACTION.** Drafts live in `useServiceDrafts` keyed by
  machine-type id;
  clearing only `action` on success left the previous job's machine, pool and grams in the form, so
  confirming a prefilled value could **reserve or reconcile the wrong consumable amount**.
  `clearedActionDraft` resets the values with it.
- **Service transitions must invalidate `machineKeys.list`**, not just service queries: they change
  the assigned machine's status and usage hours, and the integrated row would otherwise stay stale.
- **Two service implementations, never three** — `MachineServiceConsole` takes a fixed
  `machineType` prop; the printer console keeps its genuine differences (planned/actual grams,
  reprint, printer reports) and **lost its duplicate roster/create panel**, which meant restoring
  `type_payload.model` to the shared create form and the machine row: that roster was the only
  place a printer model was ever written *or* displayed, and `run_machine_model` reads it.
- Pool load failure renders at **panel level**, because pools feed every type's forms while the
  Shared section may be collapsed; and the empty-machine copy requires a **successful** load, or a
  failed request tells the operator no machines are registered.
  - **FIVE SERVICE SURFACES BYPASSED THE SCOPE ENTIRELY until Phase 5 (2026-08-12).** Each resolved
    a machine (or a service request) by **makerspace alone**, so a laser-scoped maintainer reached
    every printer: typed manual-usage **GET** and **POST** (`views_machine_service_printer`), the
    optional `service_request_id` on that POST (scoped machine, unscoped request — attach a laser
    job's usage to a printer), **pool creation**'s bound `machine_id`, and **staff service-request
    submission** (`views_machine_service`), where an out-of-scope maintainer created a request that
    fired notifications, audit and quota and which they then could not see.
  - **`service_workflow.start()` takes a REQUIRED resolved machine scope, and the scope constrains
    the CANDIDATE QUERYSET, not the winner.** `FIRST_IDLE` picks the first idle machine before any
    scope consideration, so checking the chosen machine afterwards **rejects an authorized start**
    whenever an unauthorized machine sorts earlier — the failure is a wrong outcome, not a 403,
    which is why the regression test asserts on `assigned_machine_id` rather than status. The
    argument is **required** so a future call site cannot silently revert to unscoped behaviour; the
    view resolves the actor's scope and passes it, keeping general RBAC out of the workflow kernel,
    and trusted kernel tests pass `role_scope.EXEMPT` explicitly.
  - **The machine-type list is scoped, and VISIBILITY IS NOT CREATION AUTHORITY.** It previously
    returned every global and tenant type once the actor could see any machine, so per-type sections
    would render headings a role cannot reach. "Reachable" is the union of linked types (**including
    types with zero machines**), types of individually linked machines, types reached through direct
    type-manager authority, and explicit operator machines; a **shared machine-less pool does NOT
    make a type reachable**. `can_create_machine` needs a **type** link — a per-machine link exposes
    the type without authorizing another machine of that kind — and the console must filter its
    creation selector by it, or it offers an action that can only 403. The field lives on a
    **dedicated** `serializers_machine_types.MachineTypeAccessSerializer`, never on the shared
    `MachineTypeSerializer`, which is nested inside machine responses and reused by create/update
    where the actor context is absent; for the same reason the frontend `MachineType.can_create_machine`
    is **optional** — nested copies genuinely lack it, and absent correctly reads as no authority.
  - **The makerspace-level surfaces AND it in too** (Phase 3), or the narrowing would have been
    cosmetic: the queue, the detail view, service files, consumable pools, machine payments,
    publicity and the machine-service report were each gated on `MANAGE_MACHINES` alone, so a
    laser-scoped role still read every printer job, its costs, its uploaded CAD and its requester's
    contact details. `role_scope.scoped_related_q` is the shared helper; **callers name the lookup
    paths explicitly** because the route from a row to a machine is genuinely per-model and often
    plural — a service request reaches one through `assigned_machine` (null until allocated),
    through its bucket, and through its queue's machine **type**. Naming them at the call site is
    what makes a missed path reviewable. Reports take a resolved scope
    (`build_machine_service_report(..., machine_scope=)`); `None` means "no actor to scope by" (the
    report registry, the superadmin aggregate) and matches everything, and an EXEMPT actor resolves
    to an empty `Q()` so their report is the query it always was.
    - **A collect-only role is added back untouched.** Machine scoping narrows the
      `MANAGE_MACHINES`-derived scope only; `COLLECT_SERVICE_REQUEST` is a different action and
      front-desk handover has nothing to do with which machines a team runs.
    - **Consumable pools with no machine stay visible to everyone** holding `MANAGE_MACHINES` in the
      space — shared stock belongs to no team, and hiding it would make shared filament unmanageable
      by everyone rather than by the wrong people.
    - **Deliberately NOT narrowed:** `views_notification_recipients` (`MANAGE_MACHINES` there
      selects who *receives* maintenance alerts — makerspace configuration, not machine data) and
      `reconciliation.list_payments` (already gated on `MANAGE_MAKERSPACE`, which is exempt anyway).
      The reconciliation **bulk** path is narrowed, via `_require_subject_authority`.
  - **The console owns the links** (Phase 4): `PUT/GET /admin/makerspaces/<id>/roles/<role_id>/machine-scope`
    (`RoleMachineScopeView` → `machines/role_scope_services.py`), rendered by
    `RoleMachineScopeEditor.tsx` inside the role editor. Console parity is not optional here —
    scoping fails closed, so without this surface a Space Manager could create a machine-managing
    role and have **no way to make it manage anything** short of `/control/` (unreachable for staff)
    or the shell. The service lives in `apps.machines`, not `makerspaces.role_services`, so it
    disappears with a `machines` tombstone instead of lingering as a management surface for an app
    with nothing to manage. It takes the **makerspace lock before the role lock**, matching
    `role_services` exactly — a concurrent role edit and scope edit take both, and a different order
    between them deadlocks. Saves **replace** rather than merge (a merge makes unticking impossible),
    an unknown/foreign id is a **400 rather than a silent drop** (a save that quietly discards half
    the selection leaves the administrator believing a team has access it does not), and a change
    audits `role.machine_scope_changed` — `role.updated` covers the action list and would not show it.
    The payload carries `scoping_applies:false` for an exempt or non-machine role so the editor
    renders inert rather than offering ticks `role_scope` will ignore. A role being **created** has no
    id to link to, so the editor appears on reopen and says so.
  - `can_create_machine` needs a **type** link specifically: a machine link granted one machine, not
    the right to add more of its kind. `can_see_machines` requires a link too, since a tab that
    renders an empty list and 403s on every action is worse than no tab. Resolution always ANDs the
    makerspace, so a link written across tenants is **inert, not a leak**.
- **`COLLECT_SERVICE_REQUEST` splits job handover out of `MANAGE_MACHINES`.** Collecting a finished machine job is a front-desk act; `MANAGE_MACHINES` is the whole machine lifecycle, so requiring it to hand someone their print forced a front-desk role to also be able to retire a printer. `IMPLIED_ACTIONS[MANAGE_MACHINES]` now includes it, which is why the split needed **no migration and caused no regression** — every Space Manager and Machine Manager already holds `MANAGE_MACHINES`. `_manageable_request(actor, pk, action)` in `views_machine_service` takes the required action per operation: **only** collect passes the narrow one; accept/reject/start/complete/fail/reprint/create keep `MANAGE_MACHINES`. A collect-only actor's queryset is narrowed to `COMPLETED` rows (`_collect_only`), so the queue, drafts and in-progress work stay invisible — the list and detail reads are allowed on the narrow action precisely so the narrowed view has something to show. The action was deliberately **not** granted to anyone by migration: widening real permissions on deployments that never asked is not a migration's job.
- **Collection is CUMULATIVE with machine scope, and the two partitions must stay separate
  (phase 6a).** A role holding scoped `MANAGE_MACHINES` **and** a **directly** granted
  `COLLECT_SERVICE_REQUEST` previously got neither the union nor front-desk breadth, because the
  code recognised only makerspaces that were collect-*only*. The contract is now
  `machine-scoped rows (all statuses) UNION makerspace-wide COMPLETED rows where collect is
  granted DIRECTLY`, split across **two** querysets in `views_machine_service_common.py`:
  `_read_or_collect_queryset` (list, detail, collect) and `_manage_queryset` (every lifecycle
  mutation, plus service files). Adding the union to one shared queryset would have let an
  out-of-scope completed job reach `reprint` and any future completed-state action. An
  **implied** collect grant must never activate the second arm.
  - **`role_grants_directly` exists because `grants_directly` short-circuits on superadmin.**
    That short-circuit is right for tier-2 type authority (it does not come from a role row) and
    wrong for "did this role grant this?". A global superadmin who *also* holds an explicit
    machine-scoped membership in a **hard-hidden** space is reduced to that role's authority by
    design, and `superadmin_hidden_block_applies` resolves through `actions_for_membership`,
    which **expands implied actions** — so `MANAGE_MACHINES` implying collect made the union fire
    for a role that never stored it. The role-only variant reads `granted_actions` directly.
  - **Organization collection has its own direct-grant predicate and no machine arm.**
    `organization_grants_directly` uses the filtered organization vocabulary and the centralized
    hidden/servable organization-membership query, and is ORed only into the makerspace-wide
    `COMPLETED` collection partition. It never participates in `grants_directly`, type-manager
    authority, `_manage_queryset`, or service-file access. Thus a direct organization
    `collect_service_request` grant can list/detail/collect finished jobs, while pending and
    in-progress jobs and every lifecycle/file operation stay unavailable; organization
    `manage_printing` likewise grants no machine or machine-type manager authority.
  - **`_machine_partition_q` resolves exemption with `role_scope.manage_scope_for`, NOT with
    `makerspaces_for_action(...) is rbac.ALL`.** Those disagree for exactly that same hidden-space
    superadmin, who still answers `ALL` at the action level — so the `ALL` shortcut (inherited from
    the pre-6a `_narrow_to_machine_scope`) handed them every row and their machine links did
    nothing. `manage_scopes_for` already answers correctly for both shapes: EXEMPT when a
    superadmin has no membership there, the role's links when they do.
  - **AN EMPTY `Q()` IS THE IDENTITY FOR `filter` AND AN ANNIHILATOR FOR `|`.** Django's
    `Q._combine` short-circuits a falsy operand, so `Q() | Q(status=COMPLETED)` returns
    `Q(status=COMPLETED)` — not "everything OR completed". Representing "unrestricted" as `Q()`
    therefore **inverted** the union for unrestricted actors, narrowing them to COMPLETED rows and
    hiding the whole live queue (a superadmin's detail view 404'd on every pending job).
    Unrestricted is now `None` and callers branch on it. `scope_q_for` may still return `Q()`
    because every one of its callers only ever passes it to `.filter()`.
- **The dashboard narrows machine counters and OMITS non-machine ones — two INDEPENDENT
  decisions (phase 6a).** `build_dashboard` takes `machine_scope` (narrows machine-derived
  counters) and `machine_only` (whether the non-machine counters appear at all). Conflating them
  was wrong, because roles here are **editable and action-based**: a custom role can hold
  `VIEW_INVENTORY` *and* a scoped `MANAGE_MACHINES`, and treating "has a machine scope" as "is a
  maintainer" silently removed hardware and stock counts that role is independently authorized
  for. Machine scoping must narrow machine data without revoking another granted action.
  - **The response carries a server-derived `scope_mode: "machine" | "full"`.** `DashboardPanel`
    renders an absent field as `0`, so omission alone silently reads as "nothing to do". The
    frontend must **not** infer exemption from effective actions — that cannot express a
    null-`assigned_role` legacy membership, which is exempt.
  - **Printing is identified by the GLOBAL built-in printer type ID, never the slug.** Slug
    uniqueness is scoped (`uniq_global_machinetype_slug` / `uniq_lab_machinetype_slug`), so a
    makerspace may legally own a local type slugged `3d_printer`; filtering by slug counts its
    jobs as prints. Mirrors `printer_capabilities.is_printer_type`.
  - **`prints_awaiting_collection` follows COLLECTION authority, not machine scope**, or the tile
    disagrees with the Handover queue it links to — a job actionable there and invisible here. It
    is built as a **separate queryset** rather than by OR-ing the scope clause, precisely because
    of the empty-`Q` collapse above.
  - **Asset warranties are inventory data.** A machine-only maintainer sees only their own
    machines' warranty rows; a mixed role also keeps asset rows, which machine scoping has nothing
    to say about. Maintenance schedules are always scoped, since a schedule names a machine and
    there is no non-machine remainder.
  - **Organization-only authority deliberately does not open this dashboard or the notification
    inbox.** Both remain rooted in local membership visibility: their mixed, makerspace-wide
    projections have narrower parity than the action-specific surfaces converted for organization
    reach. This exclusion is intentional, not a missed `scope_by_visibility_or_action` conversion.
- **The hardware `requests` tab is hidden when `canSeeHardware` is false.** It previously also
  passed for `canSeePrinting`, so a machine-only role got a tab whose panel renders no hardware
  rows at all — only a pointer to Machines. Hardware API authorization is **untouched**; a
  deep-linked or stored route normalises to the actor's first allowed tab rather than rendering a
  dead-tab denial.
- **A NARROWED RECIPIENT RULE MUST NOT SUPPRESS THE DEFAULT FOR SUBJECTS IT DOES NOT COVER
  (phase 6c2).** This was a live bug, not a consequence of the delegation feature.
  `staff_emails_for_feature` and `staff_user_ids_for_feature` asked
  `has_selection(makerspace, feature, event)`, which **ignored `scope`** — so once any row existed
  for a (feature, event) the selection became authoritative, and if every row was scoped to the
  lasers while the alert was about a printer, `selected_*` matched nothing and **the printer
  warning reached nobody**. `has_selection` now takes `scope` and is True only when at least one
  row **covers** the subject (`recipient_scope_matching.rule_covers`), so an uncovered subject falls
  through to the action-based default. That restores the module's governing rule: everything here
  fails **OPEN** — over-notifying is recoverable, a missed maintenance warning is not.
- **PRECEDENCE APPLIES ONLY AMONG ROWS THAT COVER THE SUBJECT (phase 6c2).**
  `_selected_memberships` chose one responsible row per membership — members-wide first, then
  role, then user — and tested `rule_covers` **after**. So a members row scoped to the printers
  was picked for a laser alert, failed coverage, and skipped the membership, meaning the
  laser-scoped role row that *did* cover it was never consulted and **the alert reached nobody**.
  That is the same suppression `has_selection` was fixed for, one level further down, and 6c2 makes
  the pairing ordinary: a delegated laser rule sits beside a preserved space-wide members rule by
  design. Rows are filtered by coverage **before** precedence is applied.
- **THE ACTION-BASED FALLBACK IS SCOPED TOO, BUT NO LINKS MEANS UNCONFIGURED, NOT "REACHES
  NOTHING" (phase 6c2).** Once `has_selection` learned to fall through per subject, the fallback
  became reachable for an alert naming a machine — and it predates machine scoping, so it would
  mail every `MANAGE_MACHINES` holder the printer's maintenance detail, including a laser-only
  maintainer who cannot open that machine in the console. `recipients.reach_filter_for` narrows it.
  **The asymmetry with access is deliberate and must not be "fixed":** for access, a
  machine-managing role with no links reaches nothing (fail closed); here the same state means the
  role was never configured, and treating it as "reaches no machine" would mute a space's
  maintenance mail the instant an alert named a machine. The filter therefore removes a membership
  only when its role holds links that genuinely exclude the subject. Exempt actors always admit,
  so a machine nobody is scoped to still reaches whoever administers the space, and alerts naming
  no machine admit everyone — leaving every non-machine feature untouched.
- **Delegated recipient rules: a maintainer edits their own partition and nothing else
  (phase 6c2).** Behind the `notifications.delegated_recipients` feature (SM-writable,
  **default OFF**, and OFF means *invisible* — today's 403, not a greyed editor). Authority is
  `feature_enabled(...) AND role_scope.is_machine_only(...)`, and **maintenance only**;
  `MANAGE_MAKERSPACE` keeps full authority over every feature.
  - **`PUT` deletes by an explicit id list, and for a delegated actor that list is only the rows
    ENTIRELY within their reach.** A full replace would have destroyed space-wide and other-team
    rows the actor cannot even see. `row_fully_reachable` returns **False for a row with no scope
    links** — that is what preserves a space-wide policy — and False for any category link, since
    `manage_scope_for` grants no category reach (fail closed).
  - **A rule with no scope links means "everything", so a delegated actor may never write one**, or
    a narrow grant authors space-wide policy. A multi-type rule needs **full** coverage to edit, or
    one team silently narrows another's.
  - **Identities are validated, not merely offered.** The picker shows a delegated actor their own
    role and the teammates holding it; the API refuses anything else. Accepting identities the
    editor never presents is the inverse of a list that 403s on click — it would let a narrow grant
    point alerts at an arbitrary colleague or a role it does not hold.
  - **Hidden policies surface as an identity-free marker** (`{feature, event, count}`) — never full
    rows (which expose recipient identities and role configuration to a narrow grant) and never
    silence (which makes the operator reason wrongly about fallback).
  - **Chat destinations and `receives_notifications` stay Space-Manager-only** and were deliberately
    not widened.
  - **A `requester`/`members` row is SHARED, and is merged rather than replaced.**
    `uniq_notification_recipient_special` is `(makerspace, feature, event, kind)`, so exactly one
    such row can exist per event — two teams wanting "notify the requester for MY machines" are
    describing one row, and delete-then-insert cannot express that (the second team's insert tripped
    the constraint and surfaced as a misleading "a Space Manager-managed policy already uses one of
    these recipients"). `recipient_rule_merge` therefore strips only the links inside the delegate's
    reach and adds their submission back. Refusing the two kinds outright was tried and reverted: it
    removes a capability the design intends, and a pre-existing test asserts a delegate CAN write a
    scoped `requester` rule.
    - **`_manageable_identity` returns True for these two kinds**, reversing the original rule.
      They name no identity at all, so scope is the only question — and refusing them meant a
      delegate could not round-trip their own save. **The accepted consequence is that SCOPE IS
      OWNERSHIP here: `created_by` is never consulted, so a delegate may delete a Space Manager's
      special row lying entirely inside their reach.** That is already the contract for a `role`
      row naming their own role, and the schema carries no per-link contributor provenance to
      express anything finer. Pinned by a test rather than left implicit.
    - **A partially-overlapping row is PROJECTED, not hidden.** `payload` would otherwise omit it
      and the delegate's successful save would read back as absent — the same "looks dropped"
      defect the merge exists to remove. `project_special_row` emits their own links only, with
      **`id: None`** (PUT is not id-addressed, nothing reads it, and the real key would disclose a
      row they do not own), and the row is *still* counted in `managed_policy_markers`. The
      projection and the merge **share `owned_links`**, or an untouched form silently changes
      policy on save.
    - **A link-less row is refused with a 400, never narrowed or silently no-oped.** No links means
      EVERYTHING, so adding the delegate's links would shrink somebody else's space-wide policy.
      Omitting the kind leaves it untouched.
    - **Delete-on-last-link is UNREACHABLE by construction** (a preserved row always keeps an
      out-of-reach, cross-tenant or category link) and is kept only as a fail-safe, because a
      linkless leftover would silently promote a narrow rule to space-wide. It counts remaining
      links **through the link models, never `row.machine_type_scopes.count()`** — the service hands
      these rows over `prefetch_related`, and a populated related manager answers `.count()` from
      that stale cache, reporting one link for a row that has none. Driven by a direct unit test,
      since no API path reaches it.
    - The marker copy names **no author**: with a shared row the hidden remainder may be another
      maintainer's links, so "a Space Manager-managed policy" would often be false.
  - **`revalidate` refreshes the identity gate as well as the reach**, and the success response
    serializes with `keep.reach` — both were resolved before the makerspace lock, so a concurrent
    role reassignment or scope narrowing left the write and the reply using authority the actor no
    longer held.
- **`role_scope.is_machine_only` is the ONE answer to "is this actor a per-type maintainer and
  nothing else" (phase 6c1).** Shared by the dashboard's non-machine counters and the in-app
  notification inbox, because two copies would drift and the failure is silent — a surface that
  keeps appearing for the very role it was meant to hide from. Three conditions: holds
  `MANAGE_MACHINES`; resolves to a **non-EXEMPT** scope (so space managers, membership-less
  superadmins and null-`assigned_role` legacy Machine Managers are excluded); and holds neither
  `VIEW_INVENTORY` nor `MANAGE_MAKERSPACE`. `MANAGE_PRINTING` deliberately does not count —
  `MANAGE_MACHINES` implies it, so asking `rbac.can` would make the answer always False and the
  whole predicate inert. A role that **stores** `manage_printing` is exempt, read through
  `role_grants_directly` — same distinction, and the same reason, as
  `procurement.access.machine_type_scope`. The batched copy in `accounts/serializers.py` must read
  the stored grant too: its `actions` set is the *expanded* one, where the implication is always
  present.
  - **`AuthMembershipSerializer` in `accounts/views.py` is the documented contract for this
    payload, and it is easy to forget.** `user_payload` emits the dict; the inline serializer is
    what reaches `openapi-schema.json` and `api.ts`. Adding a key to the dict alone leaves a
    generated client unable to discover it — and a schema-sync check still passes, because nothing
    told spectacular the field exists. `can_configure_machine_types` had been undocumented that way
    since it shipped. **Two exact-payload tests pin this dict** (`tests/accounts/test_auth_payload_l4.py`
    and `tests/test_auth_profile_scope.py`); both must be updated, and they exist to catch exactly
    this drift.
  - **The inbox is withheld, not scoped.** A `Notification` carries no machine provenance and its
    `read_at` is makerspace-wide, so one team's acknowledgement silences the row for everyone.
    Accepted cost: a scoped maintainer gets no in-app alerts and relies on email/chat, where
    per-event recipient rules already narrow by machine. Adding provenance plus a per-recipient
    read state is the alternative and is its own phase. All four endpoints share
    `_makerspace_for_manager`, so the denial is one check rather than four.
  - **The console reads `is_machine_only` off the membership** (`/auth/me` + `/auth/login`, beside
    `can_configure_machine_types`) and passes it into `getStaffAccess`; it must not be re-derived
    from effective actions, for the same reason as `scope_mode` and `machine_type_required`. It is
    resolved with the **batch** `manage_scopes_for_memberships` — the per-actor call would put an
    N+1 behind both endpoints, which is the query budget that payload is written to protect. The
    tab is **omitted**, not permission-hidden, and the unread badge lives inside that link so it
    stops polling with it. The flag defaults permissive so a caller that has not loaded it yet does
    not flicker the tab away.
- **`ToBuyItem.machine_type` narrows procurement, and `NULL` means LEGACY — never "shared"
  (phase 6b).** `MANAGE_MACHINES` implies `MANAGE_PRINTING`, and `procurement/access.py` keys the
  PRINTING stream off that action, so a laser-scoped role read **every** printing To Buy row in the
  space: `vendor_name`, `actual_unit_cost`, `purchaser`, `link` and every attached receipt.
  - **A NULL row is visible only to scope-exempt actors**, under an explicit "Unassigned" heading.
    Reading NULL as "shared" would have exposed every pre-migration row to every maintainer — the
    exact leak the phase exists to close. Migration `procurement/0007` therefore infers a type
    **only from durable provenance**, in order: `resulting_machine`, then a **machine-bound**
    `source_pool`, then a machine-bound `resulting_pool`. Everything else stays NULL. Never guess
    from `name`, `kind` or the creator's role: a wrong stamp hides a row from the Space Manager who
    created it, which is worse than leaving it unassigned.
  - **`access.machine_type_scope` returns `None` for "not narrowed" and an EMPTY SET for "narrowed
    and reaches nothing".** Callers must test `is None`; conflating them makes a role with no links
    fail *open*. Three exits, in this order: no `MANAGE_MACHINES`; scope-EXEMPT; or the role
    **stores** `MANAGE_PRINTING`. The last one matters because only the *implied* grant is the leak
    — a role whose `granted_actions` really lists `manage_printing` was given that stream
    deliberately, and revoking it because the role also gained machine duties is the mixed-role
    mistake from the dashboard. EXEMPT is checked first, or a legacy null-role membership's frozen
    action set would answer that question instead. Read with `role_grants_directly`.
  - **Use the linked TYPE ids only, never types derived from per-machine links.** A machine link
    granted one machine, not authority to procure for its whole kind; a role holding only machine
    links reaches no To Buy rows at all.
  - **`kind` stays server-derived and orthogonal**, and the narrowing applies to PRINTING rows only
    — hardware rows survive for a role that independently holds `EDIT_INVENTORY`.
  - **Scoping the list is not enough; `procurement/access.py` is stream-based, so the object
    endpoints were the real hole.** One `scope_items` helper feeds list, detail get/patch/delete,
    export, both move endpoints and `resolve_item` — and `resolve_receipt` delegates to
    `resolve_item`, so the receipt-pk paths (url, delete) are scoped transitively rather than by a
    second copy of the rule.
  - **`machine_type_required` is SERVER-derived** (`access.machine_type_is_required`, the same
    predicate `validate_machine_type` enforces) and shipped on the options endpoint. The console
    originally inferred it from effective actions plus `role_id !== null`, which is the mistake
    `scope_mode` exists to prevent: a null-`assigned_role` legacy membership is exempt and cannot be
    expressed client-side, and "holds `manage_machines`" is a different question from "is narrowed"
    (a `MANAGE_MAKERSPACE` role holds it and is exempt). It defaults to `false` while the query is
    in flight, so the form never demands a value before the options that satisfy it exist.
  - **`select_for_update()` cannot be combined with `select_related()` on a NULLABLE FK.** Postgres
    rejects it outright — *"FOR UPDATE cannot be applied to the nullable side of an outer join"* —
    so `move_to_printing` must not select-related `machine_type`; it lazy-loads in one extra query,
    free next to the writes that transaction already performs. `makerspace` is non-nullable, so its
    INNER JOIN is fine to lock against.
  - **The type cannot be retagged away from durable provenance.** Because `scope_items` treats the
    column as an authorization label, relabelling a row that came from a real machine (or clearing
    it to the exempt-only NULL bucket) hides it from the team owning that machine and shows it to
    another, while contradicting the asset it names. Only a scope-exempt actor can reach that PATCH,
    so this is an **integrity** rule, not an escalation one. `validate_machine_type_provenance`
    refuses a mismatch; re-asserting what provenance already implies is a no-op and rows with no
    provenance stay freely taggable, so nothing is trapped — a mislabelled row is fixed by
    correcting the provenance, not the label.
  - **A BARREL SPLIT MUST NOT MAKE SUBMODULES IMPORT EACH OTHER.** Extracting the export view into
    `views_items_export.py` while leaving the shared constants in `views_items.py` created a real
    cycle — `views_items_export` imported `views_items`, which imported `ToBuyExportView` back at
    the **bottom of the file** — so importing the export module *first* raised
    `ImportError: cannot import name ... from partially initialized module`. It stayed hidden
    because the urlconf always imported `views_items` first. Shared constants and query helpers
    live in a neutral `views_common.py`; submodules depend on it and never on each other, and
    `views.py` is the only thing that names the public surface. Verified by importing **each**
    submodule first in its own process, which is the check that fails when this regresses.
  - **A migration test must pin every app whose historical model it instantiates.**
    `MigrationExecutor.project_state(targets)` replays only the named targets and their
    dependencies, so `makerspaces` left unpinned yields a historical `Makerspace` behind the real
    table; Django applies field defaults in Python rather than DDL, so the INSERT omits newer
    columns and Postgres rejects the NOT NULL. Rewind the full graph forward in `finally`.

## Events program invariants (four phases, `f16896f`..`dab0354`)

- **Registering for an event does NOT require a `PresenceSession`; check-in does.**
  `require_active_member` (identity + membership + waiver) was split out of
  `require_active_member_presence`, and **only** `PublicEventRegistrationView` switched. The other
  **nine invocations across six surfaces** — self-checkout ×3, direct handout, public request submit,
  public booking, and the two machine-service surfaces — still require a session, because those are
  hardware and facility acts where "is this member here right now" is the whole question. Signing up
  is planning to attend; presence is proven later by the staff-scanned QR, which is stronger evidence
  than a self-declared session.
- **`events.member_history.registrations_for_space` is the ONE answer to "which registrations does
  this member hold in this space"**, shared by the profile counts, the profile's recent-attended list,
  member activity and the QR lookup. It filters on **durable provenance**
  (`EventRegistration.registered_via_makerspace`, `SET_NULL`), **not** current collaboration: accepted
  collaboration authorizes *discovery and creation*, provenance records *where participation
  happened*, so an administrator editing a collaborator list cannot retroactively delete a member's
  history or break a QR someone already holds. A **NULL provenance falls back to the host**, so the
  read fails OPEN to pre-provenance behaviour and the backfill is tidiness rather than load-bearing.
  History still stops at the **host's** archival or withdrawn `events` module.
- **Presentation and PAYMENT are gated differently, and conflating them loses money.**
  `payments.member_scope.member_payment_queryset` widens the three member payment surfaces (history,
  web checkout, native intent) to an `EVENT_REGISTRATION` charge raised by another host when the
  member's own registration names this space as provenance — otherwise a visitor's charge exists and
  is undiscoverable, since the host 403s them and their own space filters it out. It is gated by
  **neither** the host's module **nor** archival: a module toggle must never hide a receipt or block a
  pending charge, and the separability contract keeps historical payment subjects usable when
  tombstoned.
- **PAYMENT ROUTING LIVES ON `Payment.via_makerspace`, NOT ON THE REGISTRATION'S PROVENANCE.**
  One column cannot serve both: `module_purge_collectors.events_delete` must clear
  `registered_via_makerspace` (destroying activity history is what a purge is *for*), and keying
  payment visibility on that same column meant a collaborator's purge made a host-raised charge
  invisible in the member's area while the host still 403s them — a receipt gone and a **pending
  charge unpayable**. The routing therefore sits on the money record, which no purge touches:
  stamped at creation by `service_payments._get_or_create` as
  `registered_via_makerspace or event.makerspace`, read directly by `member_scope`'s second arm, and
  **never cleared by any collector**. The `subject_type=EVENT_REGISTRATION` clause stays on that arm
  so it can never widen to "every payment this user has anywhere". Two traps this hit: the backfill
  (`payments/0011`) stamps **only where the registration's member matches the payment's member** —
  `Payment.clean()` does not validate that, and the old subquery did, so stamping blindly would newly
  expose one member's charge through another space; and a payment whose registration was already
  deleted by an earlier purge is **unrecoverable and reported**, not silently skipped. The immutability
  trigger permits the backfill because it raises only when `status` or `amount` change.
- **A DELAYED charge needs routing preserved BEFORE the purge, which `Payment` cannot do.** A
  waitlisted registration has no `Payment` at all — one is raised only when `_promote()` lifts it to
  REGISTERED — so if the collaborator purges `events` in between, provenance is already NULL and the
  charge falls back to the **host**, where the visiting member holds no membership: refused there,
  filtered out at home, payable from neither. `EventRegistration.payment_via_makerspace` is the second
  durable copy, written beside `registered_via_makerspace` at registration and **deliberately not
  cleared** by `events_delete`; `_get_or_create` reads it first. Keeping it resurrects nothing —
  member history, the maker profile and the QR lookup all read `registered_via_makerspace`, never
  this column. **Both columns are scoped to the COLLABORATOR's purge, not the host's** — and what
  the HOST's purge does has since CHANGED, so the text that stood here is corrected rather than
  preserved. It read that a host purging `events` destroyed every host-owned event charge
  (visitors' included) through the plan's `payment_subjects=("event_registration",)`, deleting
  payments before their subject so none survived as a dangling generic reference, and it recorded
  that as an **open question**. That question is now **settled the other way, and the mechanism it
  described no longer exists**: `ModulePurgePlan` has no `payment_subjects` field at all (removed
  2026-08-11 — see "NO MODULE PURGE DELETES A `Payment`" under the per-module purge invariant),
  `module_purge_plans.py` carries a comment saying so deliberately, and
  `tests/payments/test_payment_survives_module_purge.py` asserts
  `not hasattr(ModulePurgePlan, "payment_subjects")` for every plan. **A host purge therefore leaves
  a visiting member's receipt readable and their pending charge payable.** The dangling generic
  subject the old design refused to accept is exactly what `Payment.subject_label`'s creation-time
  snapshot and the relaxed `Payment.clean()` were built to tolerate. This contradiction survived in
  this file because the two programs were written weeks apart and neither re-read the other —
  **verify against `module_purge_plans.py` before relying on any account of purge-versus-payment.**
- **`create_for_registered_registration` SWALLOWS EVERY EXCEPTION**, so a signature mismatch against
  `payments.services.create_payment` does not raise — it silently stops creating charges while
  registration still returns 201. Any test covering event charging must drive the real path; one that
  fabricates a `Payment` row proves nothing about the wiring. `create_payment`'s `via_makerspace`
  keyword defaults to `None`, so bookings/membership/machine-service call sites are unaffected (their
  charges are owned by the member's own space, which arm 1 already covers).
- **The collaborative registration route shares the CREATE budget and splits the RETRY budget.**
  `_collaborative_events()` deliberately includes the member's own space's events, so the same event
  is reachable through both `MemberCollaborativeEventRegistrationView` and
  `PublicEventRegistrationView`; throttling only one is a bypass. Both therefore use
  `ClientTierRateThrottle` + scope `event_register` — **not** `MemberPrincipalRateThrottle`, whose
  `member:<pk>` ident is a *different* DRF cache key and would hand out the limit twice, closing half
  the bypass. But DRF checks throttles in `initial()`, before `post()`, so a blanket throttle 429s the
  `DuplicateRegistration` retry that is a member's **only** way to repair a registration holding no
  waiver acceptance — and since the bucket is shared, the public route could exhaust it and strand
  them at the door. `check_throttles` therefore reassigns `self.throttle_scope` to
  `event_registration_retry` when a registration already exists (`self.kwargs` is set by `dispatch()`
  before `initial()`). Retries stay bounded; they are never blocked by the create budget.
- **`checkin_token` is surfaced only while the registration is REGISTERED AND the event is still
  checkable.** `services.cancel()` changes only `Event.status` and leaves registrations REGISTERED, so
  gating on the registration alone hands out an admission code nothing can ever confirm. The QR route
  and `member_activity_service` must agree, or a token is advertised whose route refuses it.
- **Resolve answers unknown, malformed and wrong-event tokens identically.** Distinguishing them makes
  it an oracle for "this code is real but belongs elsewhere". **UUID4 entropy** is what makes
  enumeration infeasible; authorization + event scoping + the uniform 404 stop a stolen token crossing
  tenants; the staff-keyed throttle only bounds abuse. Resolve is **read-only** and confirm reuses the
  existing pk-authorized `mark-attended`, so a scanned token never mutates anything.
- **A route kwarg feeding `MODEL_LOOKUPS` MUST be named `pk`** — `origin_scope_routes` reads
  `kwargs['pk']` and marks the request invalid when absent, so `<int:event_id>` is **denied on every
  tenant custom domain despite being registered**.
- **The collaboration API has TWO tenant scopes and needs four DISTINCT route names**, because
  `origin_scope_routes` is keyed by route name, not HTTP method: host invite/list → `events.Event`,
  host remove → `EventCollaborator.event__makerspace_id`, collaborator inbox → its `makerspace_id`
  kwarg, accept/decline → `EventCollaborator.makerspace_id`. Registering accept against the host would
  **403 it from the collaborator's own domain**, which is the entire feature.
- **Lock order in `apps.events` is `event → makerspace(s)`**, matching shipped `publish()`,
  `update_event()` and image attach. `require_module_locked` goes **after** `_locked_event` in
  `register()` (before would deadlock against `publish`), two makerspaces lock in **sorted pk order**,
  and `remove_collaborator` reads the event id **unlocked** first — a `select_for_update()
  .select_related("event")` locks both rows in the wrong order.
- **The host waiver lives on the `EventRegistration`, not a membership** (a visitor membership would
  corrupt the host's member reporting, roster, quota and dues — `reports_members` counts every row).
  Three fields under an all-or-none check constraint, `PROTECT`, with acceptance an **explicit API
  field** — inferring it from a submitted id lets any caller manufacture evidence about a real person.
  Re-read under the host lock so a superseded version is refused. Stamping is one helper shared by the
  create and idempotent-retry paths. Audited with id + version, **never the body**: the purge clears
  the columns, so the append-only log is the surviving evidence, and the body would be undeletable
  member data. A registration with **no** acceptance yields no QR — but **not** gated on the *current*
  version, or revising a waiver strands a legitimate member at the door.
- **Waiver evidence lives in TWO places, and reading one reports a falsehood about a real person.**
  A visitor's acceptance is stamped on the `EventRegistration`; a **host member's lives on their
  `MakerspaceMembership`**, because the registration path deliberately does not re-record an agreement
  the member already gave their own space. The check-in resolve payload shipped as
  `bool(registration.host_waiver_id)`, which is therefore **structurally false for every host member**
  — the scanner told correctly-accepted members to "take one at the desk", and said the same when the
  host had configured no waiver at all. `views_checkin.host_waiver_state()` is the one answer:
  `not_required` when the host has no active waiver, `on_file` when either location holds an
  acceptance, `missing` otherwise. Not compared against the *current* version, matching the QR gate.
  **"Not a visitor" is NOT "not required"** — `views_admin`'s staff registration only checks that a
  membership exists, never `require_active_member`, so a host member genuinely can hold a registration
  with an active waiver and no acceptance anywhere. That contract had **no test at all** before
  (nothing ever asserted on the field), which is how it shipped wrong.
- **`confirmable` mirrors `mark_attended`'s own precondition** (`status == REGISTERED` **and**
  `event.status in CHECKABLE_EVENT_STATUSES`) rather than inventing a second rule. Resolve accepts
  waitlisted/cancelled/attended rows and previously omitted event status, so a registered row on a
  **cancelled event** rendered a Confirm button whose request could only ever 409. Everything on this
  screen stays reported-never-enforced: it is the button that is withheld, never the door.
- **That `PROTECT` FK breaks BOTH purges if unhandled**: `membership_delete` must clear the
  registration's three fields alongside the membership's, and `lifecycle.purge` must clear them for
  registrations hosted **elsewhere** before its explicit
  `EventRegistration.objects.filter(event__makerspace=makerspace).delete()` (placed after the
  `ProcessedStripeEvent` delete, since Payment must precede its generic subject). Verified: removing
  either clearing step raises `ProtectedError`.
- **The member QR route lives in its own separable `events/urls_member.py`.** Declared alongside the
  rest of the `member/` surface it kept resolving, and stayed in the OpenAPI schema, on a deployment
  that ships no events app — caught by the tombstone suite.
- **Purging `events` at a collaborator must clear `registered_via_makerspace` on registrations hosted
  elsewhere**, or reinstalling resurrects supposedly purged activity and profile history.
- **`MemberProfile.show_attended_events` is consent, not configurability.** `is_visible` publishes the
  fields the member typed into the profile form; attendance is neither typed nor on that form. The
  `activity` payload is now a typed nested serializer that **omits** absent keys — a zero says
  "attended nothing", an absent key says "this space does not run events".

## Backup, restore and tenant migration (Phase 5A shipped; 5B plan-approved, unbuilt)

### Archive-recipient custody: the two-recipient admission floor (BUILT 2026-08-22)

**A makerspace archive is encrypted to its own verified recipients, and the platform is added as a
recipient ONLY when `superadmin_access_enabled` is true** (`backup/recipient_selection.py`). That is the
whole custody model: with the switch off, the operator can *run* a tenant backup but cannot *open* it.

**Lane E readable-main exclusion is BUILT (E1–E3, 2026-08-22).** A deployment archive keeps
`manifest.json` and `database.dump` at the bundle root for restore compatibility and carries sealed tenant
slices under `slices/`. The exclusion registry assigns every physical table either a deployment-global
retain disposition or a tenant-owner predicate, and it assigns retained-row foreign keys into sliced tables
an explicit project-null or drop-row disposition. A sovereign row is excluded from the readable main only
after the same frozen makerspace has a plaintext-verified slice. The resulting main dump is restored into a
fresh PostgreSQL verification database before packaging; its ownership postconditions, row-identity ledger,
catalog and sequence high-water state are checked there. Slice rows and object digests are checked while
plaintext is available before sealing. After sealing, the platform verifies only ciphertext size and digest;
the platform cannot perform semantic verification without a tenant-held identity.

**Lane E object ownership and W8 rewrap are fail-closed (E4, 2026-08-23).** Deployment capture builds one
typed pre-projection multimap for every declared object-bearing field plus the exact object-bearing
`AuditLog.meta` variants. Bucket selection is row-dependent where the schema says it is
(`RestoreRollbackObject.copy_key` uses that row's `bucket_kind`). The same physical `(bucket_kind, key)`
may have only one canonical component candidate: a main/slice or slice/slice conflict refuses the whole
archive; first ship never duplicates bytes and has no shared envelope. Historical audit object strings and
recursive archive pointers are explicit coordination references, not generic JSON discoveries. Each
component then proves reference/manifest equality, binds immutable captured size and SHA-256 facts, and
re-reads every packaged byte against them before the readable main can be projected.

`MakerspaceEncryptionKey` is tenant-owned for Lane E projection even though manager data export omits it.
Its source-broker row must not survive in the readable main. Inside the same immutable snapshot, W8 freezes
the exact raw row identity, makerspace/version/status, broker coordinates, wrapped-DEK bytes and wrapped-byte
digest. Only that frozen tuple may enter `backup/dek_rewrap.py`; inside `dek_cache_disabled()` the adapter
unwraps those exact bytes and streams each plaintext DEK through stdin directly into an age envelope for
the complete frozen tenant-recipient set. Plaintext DEKs never enter a manifest, filesystem member, process
argv, log, exception or database row. Missing, duplicate, extra, unsupported or digest-substituted rows and
any sealed-inventory or ciphertext-ledger mismatch fail the slice before outer sealing.

**The PostgreSQL client major must equal the server major for anything that dumps or restores THIS
deployment**, and `apps/backup/postgres_client.py` is the only place that resolves those binaries. The
image ships two client majors on purpose: `pg_dump` must be at least as new as any *source* server tenant
migration reads (14-17), so the newest is on `PATH`, while the deployment's own dump and restore need the
server's own major. Getting this wrong does not degrade, it breaks silently in both directions: `pg_dump`
17 writes archive header version **1.16**, which `pg_restore` 16 refuses outright, and `pg_restore` 17+
emits an unconditional `SET transaction_timeout = 0;`, a GUC that does not exist before 17, so a PG16
server rejects it and `--exit-on-error` aborts. This was not hypothetical: until 2026-08-23 the backend
dumped with client 17 against `postgres:16` while `scripts/restore.sh` restored inside the `db` container
with client 16, so **every deployment archive produced was unrestorable through the shipped restore path**.
Never call a bare `pg_dump`/`pg_restore`/`createdb`/`dropdb` from application code, and keep the archive
build's readiness gate checking the *resolved* binaries rather than `PATH`.

**Auto-created many-to-many through tables are physical tables, not fields embedded in their owning
model's row.** Each must therefore have its own literal physical-table disposition and its own count,
identity digest and concrete-column row digest. The owning model's digest covers only its concrete columns.
Never bypass `raw_projection.fixture_payload`'s refusal to synthesize missing auto-created M2M rows: a new
through table without an explicit disposition is registry drift and must fail the build.

> **The guarantee:** the platform-readable portion of a deployment artifact excludes sovereign tenant
> content. The artifact still carries that content as opaque ciphertext, together with slice identifiers,
> sizes, ciphertext digests and recipient facts. Opening the readable main does not open a sovereign slice;
> doing that requires a matching tenant-held identity.

This guarantee **does not establish** physical absence, data residency, deletion, storage reduction,
concealment of a tenant's existence, or reduced subpoena/discovery scope. It is a custody and readability
boundary only. Infrastructure snapshots, database PITR, the live service, older application artifacts and
copies downloaded by their holders remain governed by their own controls and retention. No UI, API, audit
event, log line, manifest field, docstring or comment may describe this as removal from the archive or claim
one of those excluded properties.

**The decision is snapshotted at request time, and selection FAILS CLOSED without it.** An archive is
requested in a web process (`create_archive`) and built later in a Celery worker (`run_archive` via
`run_backup_archive_task`), so the switch can be flipped in between. `create_archive` therefore
re-reads the makerspace under `select_for_update()` and stores `superadmin_access_at_decision`; a NULL
snapshot on a makerspace-scoped archive **raises** rather than falling back to the live flag. Falling
back to the live flag is the bug this closes — never reintroduce it. Rows predating the field carry
`legacy_pre_decision_snapshot` and are exempt from the constraint.

**The floor is an ADMISSION floor, not an absolute invariant.** Ordinary revocation may not take a
makerspace below **two** verified, non-revoked, non-compromised recipients, and switching
`superadmin_access_enabled` off requires two. But **compromise always proceeds immediately**, even if
that breaches the floor — security response must never wait for redundancy. A makerspace left at **one**
recipient **continues** to back up under a recorded degraded state (owner decision); at **zero** it
fails closed. Creating a makerspace with the switch already off is refused: at creation no recipient can
exist, so the supported sequence is **create on → enrol and verify two → switch off**.

**Every transaction that changes the effective recipient count must go through
`backup/custody.py::with_makerspace_custody_lock`, which locks the MAKERSPACE ROW FIRST, then recipient
rows in `pk` order.** The full count-changing set is revoke, compromise, verify, reactivate, switch
changes and restore activation. Archive creation directly locks the makerspace first to snapshot the
switch decision; it changes no recipient count, so it does not widen that lock to recipient rows. A
uniform order is mandatory: `verify_recipient` once locked the
recipient row first and `reactivate_recipient` locked nothing at all, which is a deadlock and a lost
update. **This supersedes Lane K1's "recipient mutation takes no lock".** K1's actual concern still
holds — a backup build holds a *file* lock and its own `REPEATABLE READ` snapshot, never the makerspace
row, so an urgent revocation is still never blocked by a running backup.

**`MakerspaceArchiveCustodyState` is the authoritative alarm record**, written in the same transaction
as the mutation that caused it. Custody is `not_applicable` while superadmin access is enabled;
`alarm_revision` advances once for every state-or-reason transition and is the delivery identity.
`alarm_episode` remains the reporting identity for repeat unhealthy episodes. The state is **derived,
recomputable**, so backfilling it is idempotent. `ArchiveCustodyAlarmDelivery` is the recoverable outbox:
tenant repair-capable staff receive the primary warning, and platform operators receive zero-recipient,
unreachable-recipient, and exhausted-delivery escalations. Delivery is **at-least-once** — SMTP may accept
a message before a worker dies and its retry may duplicate it, but the outbox never knowingly drops it.
Readiness surfaces below-floor, zero-recipient, undelivered, and missing-operator-address counts.

**Never combine a `RunPython` data migration and an `AddConstraint` on the same table in one
migration.** PostgreSQL raises *"cannot ALTER TABLE because it has pending trigger events"* as soon as
there are rows to update, so the migration passes on a fresh database and aborts on a real upgrade.
This cost a real bug here and is why the constraint lives in its own migration. `makemigrations --check`
cannot catch it — **a `MigrationExecutor` test that actually runs the migration over pre-seeded rows is
required** (pattern: `tests/test_procurement_machine_type_migration.py`).

**The deployment recovery gate reads live state on EVERY request, deliberately uncached.**
`apps/backup/middleware.py` is first in `MIDDLEWARE` and resolves `DeploymentRecoveryState.mode`
before anything else. A cache was written and **reverted**, and the reasoning is the invariant: a TTL
leaves a deployment that has *just* been quarantined still serving traffic, which is the one failure
a default-deny gate exists to prevent. It also made the per-request query count depend on cache
warmth, which broke three query-count tests that capture a count with N rows and assert **equality**
with N+1 — the first request paid for the lookup and later ones did not. The cost is one primary-key
lookup on a single-row table. **If it ever needs optimising, use an invalidation mechanism with no
staleness window (connection-level or `LISTEN`/`NOTIFY`), never a TTL.** A cache miss must still
query and still fail closed; treating a miss as `NORMAL` makes the gate fail open.

**Consequence for query-count tests:** the gate is a constant **+1 on every request**, not an N+1.
`tests/events/test_public_api.py`'s constant is 3 for that reason. The tests that capture-then-assert
equality (`test_perf_query_counts.py`, `test_machines.py`) stay correct **because** the count is
deterministic — which is the second reason not to reintroduce caching.

**A new app must classify its models in `apps/data_export`, or the drift guards refuse the build.**
Phase 5A added six `backup.*` models and four user edges and hit this, exactly as phases 7 and 8 did
at their integration. Deployment-scoped operational state is `OmittedModel` even when a row names a
makerspace: `BackupArchive.makerspace` records which tenant an archive covers, and exporting the row
would carry its single-use download token into a tenant archive. **Archives are outside the purge
guarantee, so they must not travel inside one either.**

**`select_for_update()` + `select_related()` across a NULLABLE FK is rejected by Postgres** — *"FOR
UPDATE cannot be applied to the nullable side of an outer join"*. Already documented under
procurement (`move_to_printing`); Phase 5A hit it again in three places. Drop the `select_related`
and lazy-load; the extra query is free next to the writes the transaction already performs. **This
is now a recurring trap, not a one-off.**

**Phase 5B (tenant migration) is BUILT on `dev`.** The plan is
`docs/superpowers/specs/2026-08-16-phase5b-plan-v13.md` (gitignored) — **cumulative and standalone;
v1–v12 are history only**. Conclusions that cost thirteen review rounds and must not be re-derived:

**Lane D D1 adds a separate deny-by-default source catalog.** Its literal model and
concrete-or-M2M field snapshots are checked against `apps.get_models(include_auto_created=True)` and a
pinned graph digest before source projection reads a row. A new field, M2M, model, generated through table,
unmanaged model or model-bearing app fails closed until classified. The projection reuses
`backup.raw_projection` under its no-decrypt guard. Owner decision 22 deliberately reverses the older
portable-import rule: every `MachineOperator` assignment travels as live authority with `assigned_at` and
`assigned_by`, and a missing machine, operator or non-null assigner refuses the build.

- **Phase 4's archive projection DECRYPTS mapped PII.** `archive.source_value` reads fields through
  `getattr`, and `ScopedPiiModelMixin.__getattribute__` decrypts — so a PORTABLE archive built on it
  contains **plaintext**, and the target then calls `parse_envelope()` on plaintext and aborts.
  PORTABLE needs a raw-column path (`row.__dict__[attname]` / `.values()`).
- **Do not reuse Phase 7's `PendingImportedMembership` / `ImportedUserReconciliation` for migration.**
  Both are makerspace-FK'd (so cannot hold a pre-tenant decision), the former rejects an empty email
  at the database level, and its adoption path discovers rows by `email__iexact` **on every social
  login**. The anonymous OIDC walk-in transition has the same shape. **Phase 7 built safe mechanisms
  whose safety depends on a target-authorized person having authored the input** — a foreign archive
  is not that person.
- **A Space Manager must never obtain a PORTABLE archive**, and authorizing the export *request* does
  not authorize the *closure*: a manager can plant unrelated global accounts into the user closure
  with an ordinary invitation or a membership for an existing username, and PORTABLE emits their
  email and phone. Phase 4 already forces `REDACTED` for Space Managers.
- **`REDACTED` is NOT a PII-free fidelity, and its name has already misled one review.** The line
  above is a narrow, true contrast — the **global-user closure** at `REDACTED` emits only `id` and
  `username` (`data_export/fields.py:9`), so platform account email/phone do not travel. But every
  field without an explicit disposition falls through to `Emitted()` (`fields.py:139`), so the
  scoped-PII mapped fields on makerspace-owned rows — requester/attendee names, emails and phones on
  `HardwareRequest`, `EventRegistration`, `Booking`, `MachineServiceRequest`, `MachineUsageEntry`,
  `EmailLog` — **are decrypted and emitted in plaintext**. That is deliberate, shipped and pinned by a
  byte-regression test (`tests/data_export/test_portable_external_refs.py:190` locks `requester_name`
  readable), so **do not "fix" it as a leak**. What it redacts is audit meta and custom-form answers.
  Owner decision 2026-08-22: behaviour unchanged, the label and disclosure copy now say so.
- **Verification must measure authority CONFERRED BY THE IMPORT**, not total effective authority —
  the latter is unsatisfiable for a legitimately linked target superadmin, since `rbac` grants
  superusers everything.

**The source gate holds a SESSION-scoped advisory lock; it must NEVER wrap the request or the task
in a transaction.** The drain guarantee needs every tenant writer to hold a shared advisory lock
that quiescence's exclusive acquisition must wait on — but the first implementation got that by
wrapping every state-changing request in `transaction.atomic()` and giving Celery a `task_cls` that
did the same. The full suite refused it, and the two failures are the argument: SMTP then ran inside
a transaction (`test_deliver_email_task_releases_lock_before_smtp` is an existing invariant test
asserting `in_atomic_block` is 0), and the delivery task's `attempts` increment was **rolled back**
by the very SMTP failure it was counting, so a failing send recorded zero attempts. Session locks
(`pg_advisory_lock_shared` / `pg_advisory_unlock_shared`, released in `finally`, holding the physical
connection so a reopened connection cannot release another session's reference) give the identical
race-freedom — session and transaction advisory locks share one lock space — with none of that.
`assert_write_allowed` therefore supports three shapes: inside an existing `atomic()` it takes the
transaction-scoped lock, at a request/task boundary it uses the already-held session lock, and a
direct non-atomic call takes a temporary session one. External I/O inside a lock-holding transaction
stays banned; this is that rule applied to the gate itself.

**The gate may refuse a request; it may never CHANGE one.** `_makerspace_id()` resolved the tenant
with `get_public_makerspace()`, which raises `Http404` for an unknown, archived or non-public slug —
so a route that was going to answer 403 answered 404 instead, and the gate had silently rewritten an
authorization outcome (`test_every_refused_matrix_entry_returns_403[public-membership-request-POST]`
caught it). Every resolution helper the gate calls must be non-raising: unresolvable means "no tenant
known here", which falls through to the unscoped lock, never a rejection. Refusal requires a
*resolved* tenant — an unresolved one must not 423 either, or a single tenant's migration takes down
every unscoped POST on the deployment (login, refresh, password reset, the import control plane).
The shared lock still covers those requests, so the drain guarantee survives the fail-open refusal;
totality is then the AST coverage guard's job, not the middleware's.

**A new model needs BOTH a model classification and a user-edge decision, and the second is the one
that gets missed.** `SourceMigrationGate.actor` and then `TenantImportJob.actor` each failed
`test_complete_registry_is_valid` after being correctly registered as `OmittedModel` — the model
classification says nothing about the model's FKs to `accounts.User`, and a stray user edge would
pull that account into the PORTABLE global closure. Both are declared as excluded. This was missed
twice in consecutive parts; when adding a model, enumerate its user FKs as a separate step.

**Deployment-global uniqueness is now introspected, not hand-listed.** `projection_guards` scans
every model in `EXPORTED_MODELS` for uniqueness rules **not scoped by makerspace** — field-level
`unique=True` included, which is how `boxes.QrCode.payload` slipped through and blew up a same-
deployment round trip on `boxes_qrcode_payload_key`. All **39** discovered rules carry an explicit
disposition in `unique_values.py`. Eight are **preserve-unless-collision** (`QrCode.payload`,
`Box.code`, and the six private-bucket `object_key` columns): preservation is the default because a
regenerated QR payload silently invalidates a label physically stuck to a box, and regeneration is
per-colliding-value, never per-model, is added to `regenerated_fields` so the pre-commit uniqueness
check covers it, and is **counted in the operator report** so the regeneration is visible.

**A raw cursor returns `jsonb` as a STRING.** Django's psycopg2 backend decodes JSON at the *field*
layer, not the connection layer, so `ReferenceState`'s temp-table reads handed back `detail` as text.
Every consumer had only ever tested the record for existence, so it went unnoticed until the first
caller read into it. `get()` now parses it. Expect the same anywhere this codebase reads `jsonb`
through `connection.cursor()`.

**A same-deployment round trip can never observe key PRESERVATION, and that is the harness, not the
rule.** Source and target share one database and one bucket in tests, so every carried object key
and QR payload collides with its own source row. A preservation test must first remove the source
row and object *after* the archive is built — which is exactly what a target deployment that has
never seen the key looks like. The collision check itself consults the **object store** (`head_object`),
not the row table, because the constraint being protected is storage-key uniqueness in the target
bucket; that also catches an orphaned object squatting a key.

**A DROP disposition is enforced at BOTH ends, and they are not redundant.** PORTABLE export omits a
drop-disposition row entirely (`admission.export_row_policy`) — `MembershipRequest.invite_email` is a
stranger's email address, and a row that can never become live has no business travelling to a
foreign deployment. The importer still refuses such a row, because the archive is not always one your
own export produced: a crafted or older archive is precisely what that guard exists for. Export-side
omission is PORTABLE-only, so the Space Manager's REDACTED export is unchanged.

**Closure admission, as built.** The export computes the exact global-user closure **after** the
retain/drop/stage dispositions are applied, canonicalizes it, and binds a source-superadmin approval
to its **digest** — if the closure changes, the approval is void and the export refuses rather than
disclosing someone new. An unapproved identity's PII is omitted and replaced with an opaque inert
reference; if a retained non-null relationship cannot be reconstructed without it, the export aborts.
Two adversarial tests plant an invitation and an active Member membership for an unrelated global
account and assert on the **archive bytes** that a blanket approval discloses neither.

**Do not discover a field by guessing its vocabulary.** `target_state._state_field_name()` scanned
every concrete field for one whose `choices` contained `IMPORTING`/`ACTIVE`/`ABORTED`. That existed
only while the lifecycle column was hypothetical; it crashed the moment a field with `choices=None`
appeared (`getattr(field, "choices", ())` returns `None`, not the default, when the attribute exists
and is None) and it would have bound to the wrong column the first time another field shared those
values. `Makerspace.lifecycle_state` is real — name it.

**One genuinely pre-existing flake was fixed, not papered over.** The encryption tests corrupt
ciphertext by flipping a base64url character, but non-canonical endings can decode to identical
bytes because the difference lives only in discarded padding bits — so roughly 1 in 16 corruptions
decoded cleanly and no rollback happened. The decoder now requires canonical base64url. Our own
encoder always emits canonical output, so stored envelopes are unaffected.

## Organization accounts and organization-derived authority

- **An `Organization` is a platform entity, not a module.** It is creatable before any makerspace
  exists, spans makerspaces through `OrganizationMakerspace` (`owner | manager | affiliate`, at most
  one owner per space), and is therefore **not** a `module_registry` key: registry keys are
  capabilities stored in each makerspace's `enabled_modules`, and per-space enablement of a
  cross-space entity is incoherent. Always present, inert when unused.
- **Org grants confer ACTIONS, never IDENTITY.** This is the distinction that makes the whole
  feature safe, and every part of it is load-bearing:
  - `OrganizationMembership.granted_actions` is resolved into
    `rbac.makerspaces_for_action`, `effective_actions` and `can`; those are the canonical
    effective-action paths. The auth payload and locked role-service revalidation mirror that
    same filtered resolver, while completed-job collection alone inspects a direct organization
    grant for its deliberately narrower partition. None of these turns the grant into identity.
  - `_membership_for`, `membership_role`, `is_space_manager_identity` and `_membership_is_space_manager`
    stay membership-only, so an org admin holding `manage_inventory` across the org's spaces becomes a
    Space Manager nowhere.
  - `resolve_scope` / `scope_by_makerspace` stay membership-only too. They are **action-agnostic**, so
    unioning org scope there would let a single org action open every scoped list query in that space.
    Action-gated surfaces must prefilter with `scope_by_action` instead — that is what the events and
    bookings helpers now do, and what any other surface must do before org authority can reach it.
  - Staff-list endpoints keep listing `MakerspaceMembership` only: an org grant must never appear as a
    local staff row.
- **Mirroring memberships is impossible — do not try again.** `UniqueConstraint(makerspace, user)`
  (`uniq_makerspace_user`) allows exactly one membership row per user per space, so a mirrored org row
  cannot coexist with a local one, two orgs cannot both grant one user access to one space, and
  deleting one org's grant could strip locally-granted authority.
- **Org grants never reach a hard-hidden makerspace, and both superadmin branches ignore them.**
  `OrganizationMembership` has no `makerspace` FK, so it lives in `GLOBAL_ADMIN_MODELS` and the admin
  hide-scoping never narrows it. Without the exclusion a superadmin could use the global membership
  admin to grant a third party authority inside a space that is hard-hidden *from that superadmin* and
  exercise it by proxy. A real local membership in a hidden space still confers authority; an
  organization grant never does. Excluded in SQL inside `_organization_authority_memberships`, together
  with `servable_q`, so every present and future consumer inherits it.
- **`manage_machines` cannot be granted through an organization, at the RBAC layer.**
  `ORGANIZATION_GRANTABLE_ACTIONS` is `ROLE_GRANTABLE_ACTIONS - {MANAGE_MACHINES}` and every
  organization consumer filters through it **before** `expand_implied_actions`: `can`,
  `effective_actions`, action query scopes, staff-authority discovery and auth-payload projection.
  Therefore even a raw stored `["manage_machines"]` confers neither that action nor its implied
  `manage_printing` / `collect_service_request`. The organization admin form still rejects it as a
  second validation layer with an operator-facing error. `machines.role_scope.manage_scope_for`
  remains local-membership-derived; direct organization `manage_printing` is not type-manager
  authority.
- **Action-specific organization reach preserves 404 vs 403.** Role management, machine-service
  list/detail resolution, integration health, domain verification, asset warranty host/document
  resolution, the mixed warranty report, and procurement machine-type options resolve the union of
  local visibility and their explicitly accepted action scope. An unlinked or hidden/unservable
  tenant remains 404 through `_organization_authority_memberships`; a visible local actor lacking
  the action reaches the row and receives 403. The warranty report separately checks its accepted
  union (`EDIT_INVENTORY` or machine-derived authority), so visible actors with neither do not get a
  misleading 200/empty response. Dashboard and notification inbox remain deliberately
  membership-only.
- **Role mutations revalidate organization authority under locks.** After the makerspace and local
  membership/role are locked, `role_services` locks the relevant organization link, organization,
  and organization-membership rows and recomputes the filtered effective action set. Create,
  grant validation, rename/update and delete therefore cannot pass the org-aware view and then fail
  a local-only service check, nor race a concurrent organization authority change.
- **Native device payloads stay membership-only.** `X-Makerspace-Id` selection requires
  `validate_native_makerspace_scope()` to find an active local membership, so an organization-only
  space in a device payload would be advertised to the app and rejected on every selected request.
- **Auth payload contract:** every entry carries `source=membership|organization`. An org-derived entry
  has `role`, `role_id` and `role_slug` null with `role_name` naming the organization; a makerspace
  reached both ways appears **once**, as the membership entry, with the actions unioned. `user_payload`
  is deliberately O(1) in queries — resolve org spaces in one batched query, never per makerspace.
- **Purge scoping is the cross-tenant footgun.** Purging makerspace C deletes only
  `OrganizationMakerspace(makerspace=C)` and only `EventOrganizer` rows whose **event is hosted by C**.
  Never delete organizers via `organization__makerspaces=C`, and never delete the shared `Organization`
  or its memberships during a makerspace purge, however few links remain.
- **`Event.makerspace` remains BOTH venue and tenancy anchor.** Payments, PII key custody
  (`encryption/registry.py` scopes `events.EventRegistration` to `event.makerspace_id`), `host_waiver`,
  audit scope, storage quota and public venue routing all key on it. An organizer is attribution plus a
  narrow permission, never tenancy, and no organizer feature may move a number, a key, a quota or a
  route away from the venue.

## API client scopes and the protected-route registry

- **`apps/apiclients/scope_registry*.py` is the single source of truth for what an `ApiClient` may
  reach**, and it is keyed on the **fully qualified versioned `view_name`** — never the bare name.
  Five inventory endpoints are exposed under both `/api/public/` and `/api/v1/public/`, so bare names
  collide.
- **Unknown-route denial is evaluated BEFORE any wildcard.** So neither `legacy:v1` nor `public:*` nor
  `admin:*` can ever authorize a route that is not registered. A protected route with no entry denies.
- **`legacy:v1` is frozen.** It authorizes exactly the entries marked `legacy_v1=True` at cutover. A
  route added later defaults to `False`: **legacy authority never auto-extends.** It exists because an
  empty `scopes` list used to authorize everything; migration `0004` preserved those clients without
  pretending their original read/write intent could be inferred. Tenant staff now explicitly grant only
  `public:read` and `public:write`; wildcards, every `admin:*`, `reports:read`, and `legacy:v1` remain
  global-superadmin-only. `ApiClient.issue()` requires a non-empty scope list, while `ApiClient.save()`
  keeps the compatibility fallback for `/control/` model forms and `seed_demo` direct construction.
- **Target resolution is independent of scopes, and an unresolved target denies.** The old
  `_path_makerspace()` returned the same `None` for "this path names no tenant" and "the tenant lookup
  failed" — a fail-open. `resolve_target` returns `(target, resolved)` so those are distinguishable.
- **The drift guard is measured per concrete `(view_name, method)` key of the protected routes.**
  Comparing view names alone would leave an obsolete authorization key behind when a handler drops a
  method or a route moves out from behind a protected prefix; a protected route whose methods cannot be
  derived at all is reported as its own drift class rather than silently skipped.
- **A widened `HMAC_PROTECTED_PATH_PREFIXES` must fail as a misconfiguration, not as blanket 401s.**
  A Django system check reports unregistered protected routes. Register checks with the
  **`app_configs` keyword** — Django calls them by keyword, and a mismatched parameter name makes
  `manage.py check`, `migrate` and `runserver` raise `TypeError` before startup. **pytest does not run
  system checks**, so a test must call the check the way Django does.
- **The HMAC signed message must stay unambiguous about the nonce.** The message is
  `METHOD \n PATH \n TIMESTAMP [\n NONCE] \n BODY`, so the nonce part exists only when `X-Nonce` is
  sent — which made a nonced request and a nonce-less request whose body is `NONCE + "\n" + body`
  encode to **identical bytes**, letting a captured signature be replayed without ever claiming the
  nonce. A nonce-less request whose first line is itself a well-formed nonce followed by a newline is
  therefore refused. The real fix is a fixed part count (always sign an empty nonce slot); it is
  specified as **protocol v2** because it changes the message for every existing nonce-less client,
  i.e. the default deployment.
- **The nonce namespace is `(client_id, nonce)` and is claimed exactly once per request**, shared
  across secrets. Never clear nonces on rotation.

## Container / deployment invariants

**The images run unprivileged.** `backend/Dockerfile` creates uid 10001 `app`, uses `COPY --chown`
(a later `chown -R /app` would duplicate the whole tree into a second layer) and drops `USER app`
before CMD. Two paths must therefore stay writable and owned by `app`: `STATIC_ROOT`
(`/app/staticfiles`, written by the boot-time `collectstatic`) and `/var/lib/celery`. In **dev** the
`./backend` bind mount is owned by the host user, and `makemigrations` has to write into it, so
`docker-compose.dev.yml` sets `user: "${DEV_UID:-1000}:${DEV_GID:-1000}"` on `backend` only —
worker/beat stay on the image uid because they only ever write to `/var/lib/celery`.

**Celery beat must be given an explicit `--schedule`.** It otherwise drops its shelve in the CWD:
under the dev bind mount that wrote a **root-owned `celerybeat-schedule` into the repo working tree**,
and post-hardening `/app` is not writable at all. Both the base and prod compose point it at the
`celerybeat_data` named volume so last-run timestamps survive a restart (otherwise every periodic task
re-fires on boot).

**Never split a shell command across lines in a YAML folded scalar (`>`).** A more-indented line keeps
its newline instead of folding to a space, and a newline inside `sh -c` terminates the command. Splitting
gunicorn's flags one-per-line made it run bare — silently falling back to its **127.0.0.1** default while
each flag became a failing command. The killer detail: the healthcheck probes `localhost`, so the
container reported **healthy** while nginx got connection-refused and every request 502'd. Keep the whole
invocation on one line. A healthcheck that probes localhost cannot detect a localhost-only bind.

**`mc cors set` is unusable — CORS lives on the MinIO server.** Modern `mc` sends S3 XML and rejects the
JSON the compose file used to write ("decoding xml: EOF", exit 1). Because `backend` has
`depends_on: createbuckets: service_completed_successfully`, that exit-1 left backend and frontend stuck
in `Created` — **`setup.sh` could never bring the app up**. Origins are now set with
`MINIO_API_CORS_ALLOW_ORIGIN` (comma-separated) on the `minio` service, fed by `MINIO_CORS_ALLOWED_ORIGINS`;
`createbuckets` provisions buckets/policies only and runs under `set -e`. The old
`MINIO_CORS_ALLOWED_ORIGINS_JSON` is gone from compose, both installers and the docs.

**Browser-facing storage URLs must name the real host, never `localhost`.**
`AWS_S3_PUBLIC_ENDPOINT_URL` / `PUBLIC_IMAGE_BASE_URL` are baked into presigned evidence upload/view URLs
and every public image `src`. The compose default (`http://localhost:9000`) makes a deployment work only
from the server console and show broken images to everyone else, so `setup.sh`/`setup.ps1` now write both
from the answered web address. The compose default is kept (not made `:?` required) so existing
deployments don't hard-break on upgrade.

**`.dockerignore` patterns are root-anchored.** A bare `__pycache__`/`*.pyc` does not match nested
directories — every `apps/*/__pycache__` was shipping inside the image. Nested patterns need `**/`.

**Production compose defaults that are not optional:** every long-running service carries
`restart: unless-stopped` (via the `x-restart` anchor) or the stack does not survive a host reboot, and a
capped `json-file` `logging` block (via `x-logging`) or container logs fill the host disk. Third-party
images are pinned to a verified release tag — **verify a tag actually resolves before pinning it**
(`minio/mc` release tags do not match the epoch in the image's `release` label).
