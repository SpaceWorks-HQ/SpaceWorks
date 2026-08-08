# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **On this file's structure.** The durable, load-bearing rules live in the lower half
> ("Cross-cutting invariants", "Project Status", "Engineering Conventions", "Architecture",
> "Hard Rules"). The chronological batch history was condensed into the "Condensed changelog"
> — full detail lives in `git log` and in the assistant's memory files. When editing a shipped
> feature, prefer `git log`/`git blame` for its history; use the invariants section for the rules
> you must not regress.

## Current work — FabLab expansion (branch `dev`)

Active multi-part FabLab program built on `dev` via a **Codex-driven workflow** (Codex writes specs
and code in parallel where files don't collide; Claude orchestrates, verifies each phase, and commits
phase-per-commit with three co-author trailers). Per user direction, the **single user QA is deferred
to the very end** (after all Parts) — no per-Part QA gate. Specs live (gitignored) under
`docs/superpowers/specs/2026-07-1*`.

**Shipped on `dev` (see condensed changelog for the module list):** Events, Bookings, Maintenance,
Analytics/reports, Machine Manager role + delegated role assignment, public
self-booking + shared custom forms, per-feature×per-channel notification matrix (Slack/Mattermost),
scoped PII encryption (Parts H1–H4), custom editable per-makerspace roles (Part L), and **Phase C**.
Phase C is complete on `dev`: capabilities toggles; Stripe payments C.2/C.3; advisory geofenced
check-in C.7; C.3 hardening; C.6 custom machine-type config; unified per-space pricing; self-serve
raw Stripe credentials + managed Stripe Connect; reconciliation; booking/event/membership charges;
attested mobile device sessions + native push + Stripe PaymentSheet; and Google/Apple social sign-in
for member and staff surfaces. The one deferred end-to-end user QA remains an owner-run release gate.

**Standing build conventions for this program:**
- **Parallel Codex via git worktree.** A second track runs in a sibling worktree
  (e.g. `../IM-nbuild` on its own branch) with a dedicated test DB, so two Codex builds don't collide
  on shared files (`rbac.py`, `origin_scope.py`, `admin_api/urls.py`, `openapi-schema.json`, `api.ts`).
  Worktrees are fresh checkouts → **gitignored files (e.g. `backend/.env`) must be copied in**. Cap at
  2 heavy builds. At the end: merge the worktree branch → `dev`, `git worktree remove`, drop its DB.
- **Codex gotchas.** Run Codex with skill-free prompts that skip reading this file, in the
  **background** (`run_in_background:true`) — the 10-min foreground ceiling is too short. Stage-4 =
  `codex exec review --uncommitted` (no `--sandbox`, no custom prompt; findings at the literal tail).
  If Codex dies with Windows `-1073741502` / "host exited during handshake", it's desktop-heap
  exhaustion — kill **only** codex PIDs (never `node.exe` = harness/MCP); a reboot clears it.
  **Never `git add`/stage before a Codex workspace-write run** — a non-empty staged index makes
  Codex's `apply_patch` silently fail with a misleading "workspace/tests/ is read-only" or
  "staged index is read-only" error (no files written). Keep the index clean during
  implementation; only `git add` right before the Stage-4 `codex review` (so it sees new
  untracked files), then `git reset` before the next Codex build.
- **Test harness.** Local `spaceworks-db` (:5433), `spaceworks-redis` (:6379), `spaceworks-minio` (:9200) must be
  running — `./scripts/dev-local.sh infra` starts exactly those. Run tests with
  `./scripts/dev-local.sh test` (or `DATABASE_URL="postgres://makerspace:makerspace@localhost:5433/makerspace_manager"
  pytest`, or the worktree's dedicated DB). **Never run two `pytest` procs against one DB** (TRUNCATE-FK teardown
  races + false concurrency failures) and **never run the full suite concurrently with `codex review`**
  (it runs its own pytest). If a background full-suite is killed by the environment, run it as
  **foreground chunks** (`pytest tests/<subdirs>`, `tests/test_[a-l]*.py`, `tests/test_[m-z]*.py`).
  Pre-existing non-regression: `test_machine_image_presign_finalize_delete_and_audit` fails because
  MinIO is on a remapped host port vs the test default :9000.
- **Local dev topology (Arch host) — three ways to run, one set of port remaps.** Host ports are
  remapped in the gitignored, machine-specific `docker-compose.override.yml`: Postgres :5433, Redis
  :6379, MinIO :9200/:9201 (:9100 is taken by a Dart dev tool on this machine). Secrets always come
  from `backend/.env`.
  1. **Everything in Docker with live reload — the default.** `./scripts/dev-docker.sh up -d --build`.
     `docker-compose.dev.yml` (committed) layers onto the base file: `./backend` and `./frontend` are
     bind-mounted, Django runs under autoreloading `runserver` with `DEBUG=True`, and the frontend is
     the Vite dev server with HMR instead of nginx. Frontend `http://localhost:5000`, backend +
     `/control/` + `/docs/` on `http://localhost:8000`. No host virtualenv, no host `npm install`.
  2. **Everything in Docker, production-shaped.** `docker compose up -d --build` — gunicorn + nginx
     serving the baked `dist`, i.e. what a makerspace operator actually runs. Frontend :8080,
     backend :8002. Code changes need a rebuild.
  3. **Infrastructure only in Docker, app on the host — fallback.** `./scripts/dev-local.sh` (gitignored,
     machine-specific) exports host-facing rewrites of the container hostnames. Kept because host
     `pytest` and one-off `manage.py` runs are faster than `exec`-ing into a container.

  **`scripts/dev-docker.sh` exists because passing any `-f` to `docker compose` disables the automatic
  merge of `docker-compose.override.yml`.** It spells the chain out as base → override → dev, in that
  order: the override supplies the infrastructure port remaps, and the dev layer must come last so its
  app-service commands, ports and bind mounts win. Every argument is forwarded verbatim, so it is a
  drop-in prefix for any compose subcommand (`./scripts/dev-docker.sh exec backend python manage.py …`).
  Two traps this topology already hit: **the base file hands `backend`'s environment to
  `migrate`/`worker`/`beat` through a YAML anchor**, so a patch to `backend` alone never reaches them —
  the override applies the MinIO host-port rewrite to all four (the Celery worker builds public image
  URLs into outbound mail). And **`tsc -b` must not emit `vite.config.js` next to `vite.config.ts`** —
  Vite resolves `.js` first, so a stale artifact silently shadows the real config; `tsconfig.node.json`
  therefore emits into `node_modules/.tmp/`.
- **Migration heads drift.** Specs quote stale migration numbers; every Codex prompt must
  `ls backend/apps/<app>/migrations/` and chain off the **actual** leaf, not the spec number. A new
  migration whose dep is a rewound app can break migration-executor tests (rewind the full graph
  forward in the test's `finally`).

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

## Container/deployment invariants (do not regress)

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

## Cross-cutting invariants (from shipped batches — do not regress)

These rules were established across many batches and are load-bearing beyond any single module:

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

**`apps/makerspaces/module_registry.py` is the single source of truth for module keys.** All 24
`ModuleDefinition`s live there (`key`, `label`, `description`, `app_label`, `enforcement`,
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

**Modules are OPT-IN.** `DEFAULT_ENABLED_MODULES` is now **core only** (6 keys) — a new makerspace
installs core plus whatever profile the operator chose (`minimal` 6 / `recommended` 17 / `everything` 24).
`ModuleDefinition.default_enabled` defaults to **False** and core must not set it (core is on by
definition; two sources for one fact is the drift the registry exists to remove). **Existing makerspaces
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
`apps/makerspaces/module_profiles.py` defines **minimal / recommended / everything**; `setup.sh`,
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
host warranty, consumables and service history). Two deletions nothing else performs and that a plan must
declare: **`Payment` rows** (immutable and generic-keyed, so they must go **before** their subject or
survive as dangling references — and only the subject types this module owns, since a whole-tenant delete
would destroy another installed module's charges), and **`PiiBlindIndex` rows** (keyed HMACs of PII with
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

**Social identity is global; authorization remains per makerspace.** `SocialIdentity(provider, sub)` links
Google/Apple to the global `User`; it never grants a role. Provider JWTs are server-verified against bounded,
cached static JWKS endpoints and one-time origin/device-bound nonces. Auto-linking is allowed only when both
provider and local email are verified; staff social login never creates an account or membership. Social
tokens carry `surface=member|staff`: member tokens are rejected by staff APIs, while staff tokens require
the exact trusted staff origin and matching tenant scope on access and refresh. Provider secrets remain
write-only/encrypted, and unconfigured social auth is omitted from public config.

**Presence geofence is ADVISORY, not an access gate (C.7).** Browser-supplied coordinates are spoofable, so
`presence.geofence.evaluate_geofence` only classifies a reading (in_range / distance+accuracy buckets, raw
coords never stored) and records it in the `presence.started` audit — it **never blocks** session creation, and
the client never hard-blocks check-in on a location error. Do **not** convert it into a fail-closed gate
without adding an unforgeable proximity factor (owner decision). Dormant/self-host safe: no geo config ⇒ no
check and the `geofence_enabled` bootstrap flag is **omitted entirely** (byte-for-byte-unchanged invariant).

**Console parity principle.** Every backend lifecycle capability reachable in the Django `/control/`
admin must have a React staff-console surface — a capability with no console surface is a latent
dead/broken feature for normal staff. New workflow actions ship their staff UI in the same batch.

## Condensed changelog (newest first — full detail in `git log`)

Each line names a shipped feature and, where useful, the load-bearing rule it introduced (folded into the
invariants above). Use `git log --oneline`/`git blame` for the implementing commits and per-file history.

- **Phase C final tracks** (2026-07-23, `dev`): encrypted per-space Stripe credentials + managed Stripe
  Connect (`3b43f47`); makerspace-scoped reconciliation dashboard/reports (`1ad63f5`); unified booking,
  event-registration, and membership-dues Payment subjects (`159a88f`, hardened by `396cb27`); attested
  device grants, rotating native refresh, native push, and Stripe PaymentSheet (`1aa2029`); server-verified
  Google/Apple member + staff social sign-in with surface/origin enforcement (`ad2fe42`).
- **Phase C — capabilities + payments + geofence** (2026-07-21/22, `dev`): Track 1 two-level module/feature
  toggles (`41e6a2a`); C.2 Stripe foundation — per-makerspace encrypted creds + verify-only webhook
  (`92eda37`); C.3 machine-service payments — `apps/payments.Payment` as the single payment authority,
  gated non-blocking charge at machine `complete()`, idempotent webhook settlement, member/staff surfaces
  + reconciliation, legacy `payment_*` → read-only historic with a backfill migration (`9c1d928`); C.7
  **advisory** geofenced presence check-in — records proximity buckets, never blocks (`007ef55`);
  C.3-hardening — `Payment` DELETE-immutability trigger + purge-graph wiring + async Stripe checkout
  settlement (`c8225c0`); **C.6 + P1-A** — custom machine-type config (SM-identity authority) + generic
  non-gram `MachineServiceConsole` + seed migration `0017`, and the unified per-space
  `MakerspaceMachineTypePricing` override (pricing out of `capability_config`, built-ins priceable per-space,
  migration `0018` fail-safe backfill) (`8d39cb0`).
- **FabLab Parts C–N + L + H + Settings + K** (2026-07-16→18, `dev`): Events, Bookings (+ public
  self-booking + shared `forms_schema` custom forms + structured event location), Maintenance, Analytics
  reports, public Roadmap (later tombstoned), Machine Manager role + SM-delegated role assignment, per-feature×per-channel
  notification matrix (Slack/Mattermost), scoped PII encryption H1–H4, custom roles L, machine service
  requests N (in worktree). New apps: `events`, `bookings`, `maintenance`, `roadmap`, `forms_schema`,
  `encryption`, machine-service models under `machines`.
- **Machines module M1 + M1.5** (2026-07-14/15): generic `apps/machines/` (types/machine/operators/usage/
  docs/errors), 3-tier authz (`MANAGE_MACHINES` + type-managers via `MachineType.managing_action` +
  per-machine operators), services single-source-of-truth, printer auto-link, custom types, photo,
  warranty (3rd host), consumables (count via inventory + grams ledger), public exposure.
- **Self-host-first + SaaS hosting Parts A/B + space-works.tech** (2026-07-15/16): self-host custom-domain
  auto-trust, managed fair-use limits + subdomain request→approve, one-shared-instance multi-tenant
  hosting (all dormant on blank `PLATFORM_DOMAIN_SUFFIX`). AGPL relicense + repo professionalization.
- **Audit fixes + dependency upgrade P1–P17** (2026-07-08): integration health center, scan-first
  stocktake, ops dashboard, notifications app + inbox + fail-safe emit hooks; force-latest upgrade to
  Django 6 / React 19 / Vite 8 / Tailwind 4 / TS 6.
- **Manager fixes P5–P10** (2026-06-30): direct-loan return resolutions + accountability + public
  report-a-problem, unified asset editor, optional partial approval, accountability dashboard,
  actionable warranty/reports UI.
- **Email/async stack** (2026-06-21): `EmailLog` outbox + single `dispatch_email` choke point + Celery/
  Redis async delivery + retry. Per-makerspace staff-notification recipient matrix.
- **Print filament grams / payment / manual logs** (2026-06-16/28): requester grams estimate, failed-%
  → printer hours, manual-log outcomes, staff-private cash payment on prints (never exposed to requester
  — enforced by serializer split), top-requesters leaderboard by email.
- **Warranty tracking** (2026-06-27): `apps/warranty/` (asset XOR printer XOR machine host, private
  bill/doc uploads, display-only status; per-host RBAC; public-leak invariant tested).
- **UI reskins** (frontend-only): pastel "notebook" theme (2026-06-22, fill/`-ink` token split),
  Blueprint redesign + item/makerspace imagery (2026-06-20).
- **Collaborative self-governance** (2026-06-16): superadmin-access toggle (later hard block),
  API-client self-serve, admin + self-service password resets, Platform Email settings.
- **Console-parity + workflow surfacing** (2026-06-16): broken-at-handover + to-be-fixed shelf,
  ledger specific-unit + staff-return evidence, direct-handout UX, lending history, QR rebind,
  surfacing ~10 orphaned backend lifecycles into the React console.
- **Deploy / production** (2026-06-19): single-tenant branded frontend, Supabase free-tier dual-mode
  (env-toggled; localhost default unchanged), lean-paid production deploy artifacts + perf hardening.

## Project Status

### Admin control plane (superadmin-only)

The **Unfold Django admin is the Super Admin's sole control plane**, mounted at **`/control/`**
(NOT `/admin/` — `/admin` belongs to the React staff console SPA route), locked to superadmins, and
**not exposed on the public frontend port** (`frontend/nginx.conf` does not proxy it — makerspace staff
on port 80 can never reach the Django console; the superadmin reaches `/control/` only via direct backend
access). Gated two ways: `config.admin_access.AdminSuperuserOnlyMiddleware` (denies any authenticated
non-superadmin; the `/api/v1/admin/...` React staff APIs are NOT gated) and
`config.admin_access.SuperuserOnlyModelAdmin` (first base of every `ModelAdmin`). Superadmin operations
are Django admin **actions that route through the existing services** (never mutating status directly);
issue/return remain React-only. Superadmin monitoring surfaces (QR ZIP, inline QR/photo previews, print
file downloads) are read-only and guard storage failures.

**U-SEC:** django-axes admin-login lockout, scoped `login`/`public_request_submit` throttles + write-only
`website` honeypot on public submit, production-gated security headers, always-on CSP via django-csp 4,
and a `pip-audit` CI job. The global CSP `script-src` omits `'unsafe-eval'`; a tiny
`config.admin_access.AdminCspEvalMiddleware` appends `'unsafe-eval'` to `script-src` **and** the S3 public
origin to `img-src` **only for `/control/` responses** (django-unfold ships eval-requiring Alpine.js; the
JSON API + public docs stay on the strict policy). Design spec:
`docs/superpowers/specs/2026-06-13-superadmin-admin-control-plane-design.md`.

**Django admin coverage** is complete (every domain model registered; immutable/workflow-owned models
read-only; a `list_filter` per makerspace-scoped admin). The Unfold sidebar (`config/unfold.py`) is
curated into grouped sections; a test asserts every sidebar link resolves. A drift-guard test
(`tests/test_admin_hidden_scope.py`) walks every registered admin and forces an explicit scoped/global
decision (via `NESTED_MAKERSPACE_LOOKUPS` / `GLOBAL_ADMIN_MODELS`) so a new admin can't silently leak
across the superadmin hide/archive scoping.

**Non-technical install:** `setup.sh` / `setup.ps1` (first-run wizard: Docker check → generate secrets
incl. Fernet `API_CLIENT_ENC_KEY` → write `.env` → build → `setup_instance` → print URL/creds),
`docker/compose.build.yml`, and `docs/setup-for-makerspaces.md`. TLS is env-gated (`ENABLE_HTTPS`,
default off). First-run `setup_instance` seeds `superadmin`/`super123` + `must_change_password` (surfaced
by login + `/auth/me`, cleared by `/auth/change-password`).

**Per-makerspace integrations are backend-only and never leak.** `Makerspace` holds per-tenant
`telegram_bot_token` + `smtp_*`; secrets are encrypted at rest with `API_CLIENT_ENC_KEY` via
`apps/makerspaces/secrets.py` and decrypted only in delivery code. The staff serializer exposes them
**write-only** + a `*_set` boolean. Bootstrap returns only frontend-safe config (module flags, not
secrets). No shared-integration entity exists — makerspaces sharing SMTP/Telegram enter the same
credentials per space (stored/encrypted independently).

**Implementation status.** The multi-frontend platform and open operations/reporting PRDs are implemented
end-to-end (public browse, auth/RBAC, API-client HMAC, QR/box, audit/evidence, 3D Printing Manager,
Hardware Request Workflow, procurement "To Buy", stock transfers incl. true cross-makerspace movement,
stocktake, analytics/ledger/exports, Users CRUD, the FabLab modules in the changelog). The detailed PRDs
(`docs/prd-*.md`) are **internal planning docs kept local only** (gitignored); "PRD §N" references point
to those. Google Sheets OAuth publishing, native apps, and physical label-printer control remain out of
scope.

Stack (in use):

- **Backend:** Django 6 + Django REST Framework (`backend/`). Requires Python 3.12+.
- **Frontend:** React 19 + Vite 8 + TypeScript (`frontend/`). Requires Node 20.19+ / 22.12+.
- **Server-state management:** TanStack Query v5
- **Database:** PostgreSQL 16 (via `docker-compose.yml`)
- **Styling:** Tailwind CSS 4 (CSS-first; `src/index.css` uses `@import "tailwindcss"` + `@config
  "../tailwind.config.ts"`; PostCSS via `@tailwindcss/postcss`) with CSS-variable light/dark theme tokens.
  Light default; dark toggle persisted locally.
- **API documentation:** drf-spectacular / OpenAPI (snapshot `frontend/openapi-schema.json` + generated
  `frontend/src/generated/api.ts`; regenerate both when routes/models change — spectacular needs
  `--format openapi-json`).
- **Admin theme:** django-unfold; site name via `ADMIN_SITE_NAME` (default "Space Works").
- **Telegram:** request alerts, test alerts, authenticated webhook accept/reject callbacks.

### Local development

The default path needs nothing installed on the host but Docker. Migrations run automatically as a
`depends_on: service_completed_successfully` step, so `up` is the whole story:

```bash
# Everything — db, redis, minio, Django, Celery worker/beat, Vite — with live reload.
./scripts/dev-docker.sh up -d --build     # first run; drop --build afterwards
./scripts/dev-docker.sh exec backend python manage.py seed_demo   # first run only
./scripts/dev-docker.sh logs -f backend
./scripts/dev-docker.sh restart worker beat   # Celery has no autoreload
./scripts/dev-docker.sh down

# After changing package.json, recreate the node_modules volume:
./scripts/dev-docker.sh up -d --build -V frontend

# Tests
./scripts/dev-docker.sh exec backend pytest
```

Host fallback (faster `pytest` / one-off `manage.py`; needs `backend/.venv` + `npm install`):

```bash
./scripts/dev-local.sh infra          # db, redis, minio only
./scripts/dev-local.sh migrate
./scripts/dev-local.sh backend        # http://localhost:8000
./scripts/dev-local.sh frontend       # http://localhost:5000
./scripts/dev-local.sh test
```

**Never run both at once** — they bind the same host ports (:8000, :5000) and the same database.

- Public inventory page: `http://localhost:5000/m/makerspace`
- API: `http://localhost:8000/api` — Swagger UI at `/docs/`, ReDoc at `/redoc/`, schema at `/schema/`.

### Current source map (real paths)

- `backend/config/` — Django project (`settings.py`, `urls.py`, wsgi/asgi). All API routes under `/api/`.
  `config/admin_access.py` holds the `/control/` gating, CSP middleware, and the hidden-scope drift-guard
  registries (`NESTED_MAKERSPACE_LOOKUPS`, `GLOBAL_ADMIN_MODELS`).
- `backend/apps/accounts/` — custom `User` model (`AUTH_USER_MODEL`), browser JWT auth, attested device
  grants/rotating refresh families, Google/Apple social identities + nonce/JWKS verification, and `rbac.py` (the Auth &
  RBAC module: `can(...)`, action-based `actions_for_membership`/`makerspaces_for_action`/`scope_by_action`,
  makerspace scoping, superadmin hide/archive exclusion).
- `backend/apps/makerspaces/` — `Makerspace` model (tenant root; unique `slug`; `frontend_domain`,
  module flags, `resource_limit_overrides`, `archived_at`, `superadmin_access_enabled`), bootstrap views,
  dynamic CORS, module guards, `module_registry.py` (canonical module definitions — all module lists
  derive from it), `platform.py` origin helpers, `limits.py` (fair-use quotas), `lifecycle.py`
  (archive/purge), `origin_scope.py` (browser origin→tenant guard), `provisioning.py`/`hosting.py`
  (managed subdomains), `secrets.py`.
- `backend/apps/audit/` — append-only `AuditLog` + `audit.record(...)` (Postgres-trigger immutable).
- `backend/apps/evidence/` — immutable evidence photos, S3 storage helpers, signed upload/view URLs gated
  by per-makerspace `UPLOAD_EVIDENCE` + active status.
- `backend/apps/boxes/` — `QrCode`/`Box` payloads, immutable `BoxScan`/`QrScanEvent`, `qr_render.py`
  (namespaced standalone SVG shared by QR-print + batch ZIP), QR rebind. Camera scanner at
  `frontend/src/components/ui/QrScanner.tsx` (native `BarcodeDetector` + `zxing-wasm` fallback).
- `backend/apps/admin_api/` — staff REST surface: makerspaces, inventory CRUD + per-makerspace category
  CRUD (`EDIT_INVENTORY`), bulk import, staff/membership + role management, user restrict/restore,
  API-client issuance, audit reads, warranty, email-log, notification-recipient, FabLab report views.
- `backend/apps/operations/` — open operations/reporting: health, stock transfers (intra + true
  cross-makerspace), stocktake, adjustments, ledger, `report_registry.py` + `report_scope.py` +
  `reports_*` builders, CSV/XLSX exports, container APIs, QR print batches (`qr_zip.py`), dashboard,
  accountability. `views.py`/`services.py` are thin re-export barrels over `views_*`/`services_*`.
- `backend/apps/integrations/` — Telegram/email/Slack/Mattermost/native-push delivery, encrypted FCM/APNs
  platform credentials + device registrations, `dispatch_email` choke point +
  `EmailLog` outbox + Celery task, webhook (auth via `X-Telegram-Bot-Api-Secret-Token` vs
  `TELEGRAM_WEBHOOK_SECRET`, fail-closed), `PlatformEmailSettings`, `DailyEmailCounter`, staff-notification
  recipient matrix.
- `backend/apps/updates/` — singleton platform update state, audited superadmin controls, and the
  `update_control` management command used by the privileged host scheduler. The web process never gets
  Docker-socket access; host scripts claim queued/automatic releases and report check/backup/result state.
- `backend/apps/inventory/` — `InventoryProduct`/`InventoryAsset`, `availability.py` (**the only place**
  available/reserved/issued/damaged/lost counts change: `reserve_for_request`, `issue_items`/`return_items`,
  `issue_available`/`return_to_available`, `consume_available`; row-locked, never-below-zero,
  `InsufficientStock`), `public_availability.py` (public availability service), allowlist-only public
  serializers/views, `public_image_storage.py`, `seed_demo`.
- `backend/apps/hardware_requests/` — Hardware Request Workflow: `HardwareRequest`/`HardwareRequestItem`,
  `HardwareRequestItemAsset` through-model, immutable `ReturnEvent`/`RequesterAccountability`,
  `PublicToolLoan`, `PublicProblemReport`. `workflow.py` is the **single source of truth** for state
  transitions (atomic + row-locked + audited; also `assign_box`/`issue_request`/`return_items`);
  `permissions.py`, `exceptions.py` (workflow→HTTP map + `ErrorSerializer._EXCEPTION_MAP`),
  `notifications.py` (Telegram seam), public submit/verify/status views, `send_return_reminders` command.
- `backend/apps/payments/` — immutable multi-subject Payment authority, per-space raw credentials + managed
  Stripe Connect resolution, checkout/webhook settlement, reconciliation, and native PaymentSheet intents.
- `backend/apps/printing/` — **TOMBSTONED** (Project B). Contains only an `AppConfig` and an empty
  `models.py`; it stays in `INSTALLED_APPS` solely so its historical migrations remain installed. 3D
  printing is now a `MachineType` inside `apps/machines/` — look there, not here.
- `backend/apps/warranty/`, `apps/machines/`, `apps/maintenance/`, `apps/events/`, `apps/bookings/`,
  `apps/forms_schema/`, `apps/encryption/`, `apps/procurement/`, `apps/notifications/`,
  `apps/operations/report_registry.py` — the FabLab + governance modules (see condensed changelog).
- `backend/apps/roadmap/` — **TOMBSTONED**: the `RoadmapItem` model is retained for migration history
  only. No URLs, no serializers, no admin surface, no frontend.
  `tests/roadmap/test_removed_surfaces.py` asserts the surfaces stay removed.
- `backend/tests/` — pytest behavior tests (external behavior, not implementation).
- `frontend/src/features/inventory/` — public catalog/detail/self-checkout + `ProductCard`/
  `AvailabilityBadge`. `frontend/src/features/staff/` — staff console panels (grouped nav via
  `StaffApp.tsx` `TAB_GROUPS`; capabilities from action-based `staffAccess.ts`; payment reconciliation and
  platform credential panels). `frontend/src/features/auth/` + `members/MemberAuthPanel.tsx` provide the
  provider-config-driven social/member auth surfaces. `frontend/src/features/
  printing|bookings|forms|...` — feature slices. `frontend/src/lib/`, `components/ui/`, `types/`,
  `generated/api.ts`.

### Public availability rule (resolves PRD §5's two overlapping fields)

`public_availability_mode` is the master display switch; `show_public_count` is a safety gate for exact counts:

- `is_public = false` → product excluded from the public list entirely.
- mode `hidden` → product listed, `availability: null`.
- mode `status_only` → `{ mode: "status_only", label }`.
- mode `exact_count` → exact `count` **only if** `show_public_count = true`; otherwise falls back to `status_only`.
- Status label: `available ≤ 0` or `total ≤ 0` → `Unavailable`; `available ≤ ceil(total × 0.2)` → `Limited`; else `Available`.

The API response is DRF-paginated (`PageNumberPagination`, page size 24): `{ count, next, previous, results }`. This is the standing convention for all list endpoints.

### Audit + evidence conventions

- Audit writes go through `apps.audit.services.record(actor, action, ...)`. `AuditLog` is append-only in
  model methods and by Postgres triggers; state-changing services must emit entries.
- Evidence photos live in a private S3-compatible bucket (`EvidencePhoto` rows: `makerspace`,
  `evidence_type`, `object_key`, `uploaded_by`, `created_at`). Workflow records link to these rows.
- Evidence upload uses presigned upload with exact MIME binding + content-length range
  (`EVIDENCE_ALLOWED_MIME`). Upload/detail URLs are scoped by per-makerspace `UPLOAD_EVIDENCE` + active
  status (not global roles — membership-only Inventory Managers can upload/view in their makerspace).
- `AWS_S3_ENDPOINT_URL` = backend-facing; `AWS_S3_PUBLIC_ENDPOINT_URL` = browser-facing presigned URLs
  (dockerized backend needs `http://minio:9000` vs `http://localhost:9000`).
- Object keys are identifiers, not secrets — privacy is the private bucket + short-lived signed URLs.

## Learning And Explanation Contract

This repo is also being used to learn production Django, DRF, React, and TanStack Query through the inventory manager project. When making changes:

- Explain the reason for each meaningful change in plain language.
- Keep explanations brief but logically deep enough to show the production tradeoff.
- For small diffs, explicitly state what changed, why it changed, and what behavior it protects.
- Tie backend changes back to Django/DRF concepts such as models, serializers, viewsets/APIViews, permissions, transactions, migrations, and service modules.
- Tie frontend changes back to React/TanStack Query concepts such as component state, server state, query keys, mutations, invalidation, loading/error states, and cache refresh.
- Avoid unexplained "magic" abstractions. If an abstraction is introduced, explain the repeated problem it removes.
- Prefer teaching through this project's real workflows: request creation, accept/reject, issue, return, QR scan, evidence upload, and audit log.

The goal is not just to ship code, but to understand why each production-quality decision exists.

## Engineering Conventions (apply to all code written here)

- **Follow the global Claude config.** The gated workflow in `~/.claude/CLAUDE.md` (Stages 1–6, Codex delegation, mandatory review/QA gates) governs all work in this repo. Repo-specific rules below add to it; they do not override it.
- **Document every API endpoint in Swagger / OpenAPI.** Every route in the API surface (PRD §14) must have an OpenAPI spec entry — request/response schemas, auth requirements, and error responses. Keep the spec in sync with the code; an undocumented endpoint is incomplete.
- **Keep files modular — target ~200 lines per file, hard ceiling ~300.** One clear responsibility per file. When a module file grows past the target, split it (e.g. route handlers, validation, and service logic in separate files). The deep modules in §12 are logical boundaries, not single files. **Established split pattern:** when an app's `views.py`/`serializers.py`/`admin.py`/`services.py` outgrows the ceiling, split classes/functions into domain submodules (`views_*`, `serializers_*`, `admin_*`, `services_*`) and keep the original file as a **thin re-export barrel** (explicit `from .submodule import (...)`, never `import *`) so `from app.views import X` and `views.X` keep resolving; for `admin.py` the barrel must still import the admin submodules so the `@admin.register` side effects fire. Every backend code file is within the ceiling **except `backend/config/settings.py`** — Django settings are conventionally a single file (accepted exception).
- **Production-level code, not prototype code.** Validate all inputs at the boundary, handle external-service failure explicitly (especially outbound integrations — Stripe, Telegram, SMTP, object storage — fail safe, never crash a request flow), use structured logging, return consistent typed error responses, and never leave `TODO`/stub auth or scoping in a merged path. Every state-changing endpoint must emit its audit log entry (PRD §11). Honor the immutability/append-only and makerspace-scoping invariants already documented above as enforced code, not convention.

## What This System Is

A multi-tenant system for managing community hardware loans across makerspaces. The central concern is **traceability of physical handovers**: every issue and return must produce evidence (QR scans + photos + remarks + audit log) so that accountability for lost/damaged hardware is never ambiguous. Public users browse and request; when self-checkout is enabled they may also issue/return eligible QR tools after authentication and evidence upload. Staff physically issue reviewed requests and direct handouts according to action scope.

## Architecture: Concepts That Span Multiple Modules

The PRD specifies a layered design where UIs and the Telegram bot are thin clients over an API server composed of deep modules. Two architectural rules are load-bearing and easy to violate if you only read one module:

1. **The Request Workflow Module is the single source of truth for state transitions.** Telegram callbacks, the web admin panel, and the guest-admin app must all route through the *same* workflow service — never mutate `HardwareRequest.status` directly. The Telegram module in particular must call the workflow module, not the database. This is what keeps web and bot behavior consistent and audited.

2. **The Inventory Availability Module owns all quantity math.** Reserve / issue / return / mark-lost all flow through it. No other module computes available/reserved/issued counts. The invariant "availability never goes below zero" lives here.

### Module responsibilities

- **Auth & RBAC** — enforces the role/action matrix AND makerspace scoping on every query. Super Admin is global; Space Manager, Inventory Manager, Guest Admin, Print Manager, Machine Manager are per-makerspace memberships (now resolved via editable custom roles, action-based). Inventory Manager is membership-only and covers the full hardware lifecycle but not printing, staff, or makerspace settings. Also verifies Telegram actors and blocks restricted/suspended users. Interface: `can(actor, action, resource)`, `scope_by_makerspace(actor, query)`, `assertTelegramActorCan(...)`.
- **Request Workflow** — owns the state machine, emits audit logs, triggers Telegram alerts, coordinates inventory reservation/issue/return.
- **Inventory Availability** — quantity math + asset status for QR-tracked tools.
- **QR Code & Box** — generates/resolves/revokes QR codes, assigns boxes to requests, tracks scan history.
- **Evidence Photo** — immutable issue/return photo storage linked to actor + request + QR scans; object storage, never public.
- **Check-In API Client** — **RETIRED** (`73a480c`, Part M7). `apps/checkin/` no longer exists and there is no `CHECKIN_MODE` setting. Requester identity now comes from authenticated member accounts, so there is no external verify dependency left to fail safe on.
- **Telegram Integration** — sends per-makerspace group alerts and processes accept/reject callbacks (delegating to Request Workflow).

## Request State Machine

```
draft → pending_approval → {rejected | accepted}
accepted → issued → {partially_returned | returned | closed_with_issue}
```

The workflow module enforces *allowed* transitions only. `closed_with_issue` and the accountability/access-restriction flow (PRD §6.5) are how lost/damaged hardware ties back to a requester's `access_status`.

## Multi-Tenancy (Makerspace Scoping)

Every domain entity is scoped to a `makerspace_id`. A makerspace owns its inventory, public URL, Space Managers, Inventory Managers, Guest Admins, Telegram group chat ID, QR namespace, and audit-log scope. **Any list/query for makerspace-scoped staff actors must be scoped through the Auth module** — forgetting this is a cross-tenant data leak, not just a bug.

## Hard Rules Baked Into Workflows (don't regress these)

- Reviewed-request hardware **cannot be issued** without both a box QR scan and an issue photo.
- Public self-checkout and staff direct handout **cannot be issued** without uploaded issue evidence and an eligible scanned/selected tool.
- Hardware **cannot be returned** without a return photo and a return remark/notes.
- Issued quantity cannot exceed accepted quantity without authorized workflow permission.
- Guest Admins can issue accepted requests and process scoped returns through the same evidence/QR/remark/audit workflow as staff. They **cannot** accept/reject, edit inventory, manage QR, or create direct handouts. Direct handouts (a loan with no reviewed request) require the dedicated `ISSUE_DIRECT_LOAN` action, granted only to Space Manager + Inventory Manager.
- Public request submission requires an **authenticated member** (`RequestSubmitView` → `IsAuthenticated`), and request lookup is scoped to that verified identity — it never matches free-text contact fields (no enumeration by known email/phone). The anti-enumeration invariant is unchanged; since the Check-In retirement (`73a480c`) it is enforced by member auth rather than an external verify call.
- Inventory Managers can run the full hardware lifecycle but **cannot** manage printing, staff, or makerspace settings.
- Evidence endpoints require per-makerspace `UPLOAD_EVIDENCE` plus active status; QR management also checks active status.
- Evidence photos and QR scan records are **immutable**; audit logs are **append-only**.
- Public inventory must never expose: storage locations, box IDs, QR codes, scan history, evidence photos, requester history, or hidden counts. Public visibility is governed per-item by `is_public`, `show_public_count`, and `public_availability_mode` (`exact_count | status_only | hidden`).

## Key References in the PRD

- Roles & permission matrix: §4
- Core workflows (request → accept → issue → return → restrict): §6
- Data model (entities + fields): §13
- API surface (public / auth / admin / guest-admin / telegram routes): §14
- App/dashboard navigation tree: §15
- MVP vs. later scope: §16
- Behaviors that must be tested: §17 (test external behavior, not implementation)
- Unresolved decisions: §18 — **resolve relevant open questions before implementing the affected area** rather than guessing.
