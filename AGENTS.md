# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working with code in this repository.

> **This file has two names, and they must stay byte-identical.** `CLAUDE.md` and `AGENTS.md` are the *same
> document* under the two filenames the tooling looks for — Claude Code reads the first, Codex and
> other-model agents (GPT, Gemini, Copilot, Cursor) read the second. **Any edit to one must be copied to the
> other in the same commit**; `diff CLAUDE.md AGENTS.md` must print nothing, and that emptiness is the drift
> guard. Do not let them diverge into a "full" and a "summary" version: `AGENTS.md` was once a hand-written
> short mirror and silently rotted for months, still routing state transitions through the tombstoned
> `apps/printing/workflow.py`. One document with two names cannot rot in only one of them.

> **This file is orientation; the reference material lives in two sibling docs.** Order here: what the
> system is, the two architectural rules, the state machine, tenancy, the Hard Rules, the engineering
> conventions, how to work in the repo, Project Status, then routers into the reference docs.
>
> - **`docs/INVARIANTS.md`** — the long-form load-bearing "do not regress" rules, read **per area, on
>   demand**. The "Invariants" section below is the index of which section to open.
> - **`docs/SOURCE-MAP.md`** — what each backend app and frontend directory owns.
> - **`docs/PROJECT-HISTORY.md`** — the condensed changelog.
>
> All three were split out when this file crossed the harness's memory-file size limit; **nothing was
> dropped in the move**, and none of them has an `AGENTS.md`-style twin — both names of this document point
> at those same three paths, so edit them in place. Rules an agent must obey without knowing to look them
> up stay *here*; the three siblings hold what you consult on purpose. When changing a shipped feature,
> prefer `git log`/`git blame` for its history and `docs/INVARIANTS.md` for the rules you must not break.

## What This System Is

A multi-tenant system for managing community hardware loans across makerspaces. The central concern is
**traceability of physical handovers**: every issue and return must produce evidence (QR scans + photos +
remarks + audit log) so that accountability for lost/damaged hardware is never ambiguous. Public users
browse and request; when self-checkout is enabled they may also issue/return eligible QR tools after
authentication and evidence upload. Staff physically issue reviewed requests and direct handouts according
to action scope.

## Architecture: Concepts That Span Multiple Modules

UIs and the Telegram bot are thin clients over an API server composed of deep modules. Two architectural
rules are load-bearing and easy to violate if you only read one module:

1. **The Request Workflow Module is the single source of truth for state transitions.** Telegram callbacks,
   the web admin panel, and the guest-admin app must all route through the *same* workflow service — never
   mutate `HardwareRequest.status` directly. The Telegram module in particular must call the workflow
   module, not the database. This is what keeps web and bot behavior consistent and audited.

2. **The Inventory Availability Module owns all quantity math.** Reserve / issue / return / mark-lost all
   flow through it. No other module computes available/reserved/issued counts. The invariant "availability
   never goes below zero" lives here.

### Module responsibilities

- **Auth & RBAC** — enforces the role/action matrix AND makerspace scoping on every query. Super Admin is
  global; every other role is a per-makerspace membership resolved through an editable `MakerspaceRole` row,
  action-based. `roles.DEFAULT_ROLE_DEFINITIONS` + `MEMBER_ROLE_DEFINITION` seed **four** protected defaults
  per makerspace — Space Manager, Inventory Manager, Machine Manager, Member. **Guest Admin is not among
  them** (retired by `0052`, removed from both role enums by `0053`/`0054` + `accounts/0009`/`0010`;
  handover is a custom role). **Print Manager is retired** (migration `0046` reassigned its memberships to
  Machine Manager, whose `MANAGE_MACHINES` implies `MANAGE_PRINTING`); the string survives only in
  `_MEMBERSHIP_ROLE_ACTIONS` as the frozen legacy fallback for a null-FK membership. Inventory Manager is
  membership-only and covers the full hardware lifecycle but not printing, staff, or makerspace settings.
  Also verifies Telegram actors and blocks restricted/suspended users. Interface: `can(actor, action,
  resource)`, `scope_by_makerspace(actor, query)`, `assertTelegramActorCan(...)`.
- **Request Workflow** — owns the state machine, emits audit logs, triggers Telegram alerts, coordinates
  inventory reservation/issue/return.
- **Inventory Availability** — quantity math + asset status for QR-tracked tools.
- **QR Code & Box** — generates/resolves/revokes QR codes, assigns boxes to requests, tracks scan history.
- **Evidence Photo** — immutable issue/return photo storage linked to actor + request + QR scans; object
  storage, never public.
- **Check-In API Client** — **RETIRED** (`73a480c`, Part M7). `apps/checkin/` no longer exists and there is
  no `CHECKIN_MODE` setting. Requester identity now comes from authenticated member accounts, so there is no
  external verify dependency left to fail safe on.
- **Telegram Integration** — sends per-makerspace group alerts and processes accept/reject callbacks
  (delegating to Request Workflow).

## Request State Machine

```
draft → pending_approval → {rejected | accepted}
accepted → issued → {partially_returned | returned | closed_with_issue}
```

The workflow module enforces *allowed* transitions only. `closed_with_issue` and the
accountability/access-restriction flow (PRD §6.5) are how lost/damaged hardware ties back to a requester's
`access_status`.

## Multi-Tenancy (Makerspace Scoping)

Every domain entity is scoped to a `makerspace_id`. A makerspace owns its inventory, public URL, Space
Managers, Inventory Managers, its own custom roles (handover included), Telegram group chat ID, QR
namespace, and audit-log scope. **Any list/query for makerspace-scoped staff actors must be scoped through
the Auth module** — forgetting this is a cross-tenant data leak, not just a bug.

## Hard Rules Baked Into Workflows (don't regress these)

- Reviewed-request hardware **cannot be issued** without both a box QR scan and an issue photo.
- Public self-checkout and staff direct handout **cannot be issued** without uploaded issue evidence and an
  eligible scanned/selected tool.
- Hardware **cannot be returned** without a return photo and a return remark/notes.
- Issued quantity cannot exceed accepted quantity without authorized workflow permission.
- **Guest Admin is no longer a built-in role** (migration `makerspaces/0052`); handover staff get a **custom
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
- Public request submission requires an **authenticated member** (`RequestSubmitView` → `IsAuthenticated`),
  and request lookup is scoped to that verified identity — it never matches free-text contact fields (no
  enumeration by known email/phone). Since the Check-In retirement (`73a480c`) this is enforced by member
  auth rather than an external verify call.
- Inventory Managers can run the full hardware lifecycle but **cannot** manage printing, staff, or
  makerspace settings.
- Evidence endpoints require per-makerspace `UPLOAD_EVIDENCE` plus active status; QR management also checks
  active status.
- **Every presigned upload lands on the staging key; the final object key is never client-writable.** A workflow promotes it exactly once, so an accepted evidence photo cannot be replaced through a still-valid presign. Read paths — the evidence endpoint, the admin preview, and backup/tenant-migration object capture — therefore fall back to the staging key, or an uploaded-but-unconsumed photo reads as missing.
- Evidence photos and QR scan records are **immutable**; audit logs are **append-only**.
- Public inventory must never expose: storage locations, box IDs, QR codes, scan history, evidence photos,
  requester history, or hidden counts. Public visibility is governed per-item by `is_public`,
  `show_public_count`, and `public_availability_mode` (`exact_count | status_only | hidden`).

> The machine-scoping program (`MANAGE_MACHINES` per role, the Machines console, procurement and dashboard
> narrowing) is documentation of an invariant, not a workflow rule, and lives under **Machine scoping** in
> `docs/INVARIANTS.md`.
## Engineering Conventions (apply to all code written here)

- **Every edit to this file must be made to BOTH `CLAUDE.md` and `AGENTS.md`, in the same commit.** They are
  one document under two filenames; `diff CLAUDE.md AGENTS.md` must print nothing. `docs/INVARIANTS.md` has
  no twin — both names point at that one path, so edit it in place.
- **Follow the global Claude config.** The gated workflow in `~/.claude/CLAUDE.md` (Stages 1–6, Codex
  delegation, mandatory review/QA gates) governs all work in this repo. Repo-specific rules below add to it;
  they do not override it.
- **Document every API endpoint in Swagger / OpenAPI.** Every route in the API surface (PRD §14) must have
  an OpenAPI spec entry — request/response schemas, auth requirements, and error responses. Keep the spec in
  sync with the code; an undocumented endpoint is incomplete.
- **Keep files modular — target ~200 lines per file, hard ceiling ~300.** One clear responsibility per file.
  When a module file grows past the target, split it (route handlers, validation, and service logic in
  separate files). The deep modules in §12 are logical boundaries, not single files. **Established split
  pattern:** when an app's `views.py`/`serializers.py`/`admin.py`/`services.py` outgrows the ceiling, split
  classes/functions into domain submodules (`views_*`, `serializers_*`, `admin_*`, `services_*`) and keep
  the original file as a **thin re-export barrel** (explicit `from .submodule import (...)`, never
  `import *`) so `from app.views import X` and `views.X` keep resolving; for `admin.py` the barrel must
  still import the admin submodules so the `@admin.register` side effects fire. Every backend code file is
  within the ceiling **except `backend/config/settings.py`** (accepted exception — Django settings are
  conventionally a single file).
- **Production-level code, not prototype code.** Validate all inputs at the boundary, handle external-service
  failure explicitly (especially outbound integrations — Stripe, Telegram, SMTP, object storage — fail safe,
  never crash a request flow), use structured logging, return consistent typed error responses, and never
  leave `TODO`/stub auth or scoping in a merged path. Every state-changing endpoint must emit its audit log
  entry (PRD §11). Honor the immutability/append-only and makerspace-scoping invariants as enforced code,
  not convention.

## Learning And Explanation Contract

This repo is also being used to learn production Django, DRF, React, and TanStack Query. When making
changes:

- Explain the reason for each meaningful change in plain language, briefly but deep enough to show the
  production tradeoff.
- For small diffs, explicitly state what changed, why it changed, and what behavior it protects.
- Tie backend changes back to Django/DRF concepts (models, serializers, viewsets/APIViews, permissions,
  transactions, migrations, service modules) and frontend changes to React/TanStack Query concepts
  (component state, server state, query keys, mutations, invalidation, loading/error states, cache refresh).
- Avoid unexplained "magic" abstractions. If an abstraction is introduced, explain the repeated problem it
  removes.
- Prefer teaching through this project's real workflows: request creation, accept/reject, issue, return, QR
  scan, evidence upload, and audit log.

The goal is not just to ship code, but to understand why each production-quality decision exists.

## Working in this repo — program state and build conventions

### Current work — FabLab expansion (branch `dev`)

Active multi-part FabLab program built on `dev`. This is a **Codex-driven workflow** (Codex writes specs and
code in parallel where files don't collide; Claude orchestrates and verifies). **What has shipped is listed
in `docs/PROJECT-HISTORY.md`** — do not maintain a second copy of that list here.

**Programs already shipped on `dev`**, each with its rules in `docs/INVARIANTS.md` and its dated entry in
`docs/PROJECT-HISTORY.md`: the FabLab modules (Events, Bookings, Maintenance, Analytics/reports, Machine
Manager role, public self-booking + shared custom forms, the notification matrix, scoped PII encryption
H1–H4, custom editable roles L); **Phase C** (capabilities toggles, Stripe payments, advisory geofenced
check-in, custom machine-type config, per-space pricing, Stripe Connect, reconciliation, native device
sessions + push + PaymentSheet, social sign-in); machine-scoped `MANAGE_MACHINES`; deployment-removable
`payments`/`updates` + install profiles + `suggest_tombstones`; generic OIDC providers; phone + SMS login;
one module key per notification channel; **Notifications v2**; the **module-architecture program**
(operator-facing module groups, the `payments`/`accounts`/`mobile`/`updates` keys, Razorpay behind a
provider seam, a superadmin modules console, cloud/full deploy profiles and a beat-less scheduler, the
**account-less identity seam + staff-created walk-in members**, **four platform login-method switches**,
**opt-in maker profiles and a member directory**, **staff-side event registration** — its security and
loophole audit is **done and pushed**, `a465a2d`); the **events program** (presence split out of
registration, opt-in attended-events on the maker profile, QR event check-in, cross-makerspace
collaborative events with a host-waiver acceptance); **phases 8, 7, 4 and 5A** (emailed-OTP recovery,
account-less member surfaces, Space-Manager data export, deployment backup/restore); and the
**audit-attestation / API-scope / organizations program** of 2026-08-19 (per-row audit MACs plus signed
Merkle batches, organizations conferring actions across their makerspaces, and a frozen registry of every
protected route behind a `legacy:v1` cutover) — its rules are the two newest sections of
`docs/INVARIANTS.md`.

**Codex is AVAILABLE — verified 2026-08-15: `codex doctor` reports `auth is configured` (ChatGPT tokens,
standalone runtime 0.147.0, all checks green) — so the Stage-1/2/4 gates in `~/.claude/CLAUDE.md` are LIVE
and must be run.** It runs as the `gpt-5.6-sol` model at **high** reasoning effort
(`model = "gpt-5.6-sol"`, `model_reasoning_effort = "high"` in `~/.codex/config.toml`). There was
a stretch when `codex doctor` reported no credentials, during which Claude implemented directly and the
owner waived those gates; that no longer applies. **Re-check `codex doctor` rather than trusting this
paragraph** — it is the one claim here that goes stale without anyone editing the file, and it stayed wrong
for weeks.

**The commit-trailer rule is attribution, not ceremony:** name Codex in a `Co-Authored-By` trailer only on
work Codex actually wrote. A Codex trailer on work it did not write is false attribution, and that overrides
the unconditional three-trailer rule in the global config — so the trailer set is decided per commit by who
really wrote the code, never by the branch or the program.

Per owner direction, the **single user QA is deferred to the very end** (after all Parts) — no per-Part QA
gate. Specs live (gitignored) under `docs/superpowers/specs/2026-07-1*`. Commits sit **local and unpushed on
`dev`**; **pushing is the owner's call alone.** Ask `git rev-list --count origin/dev..dev` rather than
trusting any number written here.

**Phase 5B (per-makerspace tenant migration, managed → self-host) is BUILT on `dev`.** All three review
lenses approved `2026-08-16-phase5b-plan-v13.md` after thirteen adversarial rounds, the owner signed off,
and every part is merged. Its load-bearing conclusions are under **Backup, restore and tenant migration** in
`docs/INVARIANTS.md`. The one deferred end-to-end owner QA is still outstanding.

**Review prompts must be scoped to the DELTA once a plan is large.** Two round-13 reviewers ran **6h11m**
(against a normal 5–10 min) still grepping migrations, because they were handed the full ~900-line
cumulative plan plus the standing "verify every claim against the real code" instruction — unbounded when
the document carries hundreds of `file:line` citations. Re-running them against a 48-line `diff -u v12 v13`
plus their prior verdict returned both approvals in minutes.
### Standing build conventions for this program

- **Parallel Codex via git worktree.** A second track runs in a sibling worktree (e.g. `../IM-nbuild` on its
  own branch) with a dedicated test DB, so two Codex builds don't collide on shared files (`rbac.py`,
  `origin_scope.py`, `admin_api/urls.py`, `openapi-schema.json`, `api.ts`). Worktrees are fresh checkouts →
  **gitignored files (e.g. `backend/.env`) must be copied in**. Cap at 2 heavy builds. At the end: merge the
  worktree branch → `dev`, `git worktree remove`, drop its DB.
- **Codex gotchas.** Run Codex with skill-free prompts that skip reading this file, in the **background**
  (`run_in_background:true`) — the 10-min foreground ceiling is too short. Stage-4 = `codex exec review
  --uncommitted` (no `--sandbox`, no custom prompt; findings at the literal tail). If Codex dies with
  Windows `-1073741502` / "host exited during handshake", it's desktop-heap exhaustion — kill **only** codex
  PIDs (never `node.exe` = harness/MCP); a reboot clears it. **Never `git add`/stage before a Codex
  workspace-write run** — a non-empty staged index makes Codex's `apply_patch` silently fail with a
  misleading "workspace/tests/ is read-only" error and no files written. Keep the index clean during
  implementation; only `git add` right before the Stage-4 `codex review` (so it sees new untracked files),
  then `git reset` before the next Codex build.
- **Test harness.** Local `spaceworks-db` (:5433), `spaceworks-redis` (:6379), `spaceworks-minio` (:9200)
  must be running — `./scripts/dev-local.sh infra` starts exactly those. Run tests with
  `./scripts/dev-local.sh test` (or `DATABASE_URL=…@localhost:5433/makerspace_manager pytest`, or the
  worktree's dedicated DB). **Never run two `pytest` procs against one DB** (TRUNCATE-FK teardown races +
  false concurrency failures) and **never run the full suite concurrently with `codex review`** (it runs its
  own pytest). If a background full-suite is killed by the environment, run it as **foreground chunks**
  (`pytest tests/<subdirs>`, `tests/test_[a-l]*.py`, `tests/test_[m-z]*.py`). **The baseline is ZERO reds** —
  the seven long-standing failures were fixed on 2026-08-12, so any red is a NEW regression, not background
  noise. This bullet once exempted `test_machine_image_presign_finalize_delete_and_audit` as a permitted
  MinIO-host-port failure; that test no longer exists in the tree and the exemption went with it. Do not
  reintroduce a "known failures" allowance without naming the test and the date it was granted.
- **Local dev topology (Arch host) — three ways to run, one set of port remaps.** Host ports are remapped in
  the gitignored, machine-specific `docker-compose.override.yml`: Postgres :5433, Redis :6379, MinIO
  :9200/:9201 (:9100 is taken by a Dart dev tool on this machine). Secrets always come from `backend/.env`.
  1. **Everything in Docker with live reload — the default.** `./scripts/dev-docker.sh up -d --build`.
     `docker-compose.dev.yml` (committed) layers onto the base file: `./backend` and `./frontend` are
     bind-mounted, Django runs under autoreloading `runserver` with `DEBUG=True`, and the frontend is the
     Vite dev server with HMR instead of nginx. Frontend :5000, backend + `/control/` + `/docs/` on :8000.
     No host virtualenv, no host `npm install`.
  2. **Everything in Docker, production-shaped.** `docker compose up -d --build` — gunicorn + nginx serving
     the baked `dist`, i.e. what a makerspace operator actually runs. Frontend :8080, backend :8002. Code
     changes need a rebuild.
  3. **Infrastructure only in Docker, app on the host — fallback.** `./scripts/dev-local.sh` (gitignored,
     machine-specific) exports host-facing rewrites of the container hostnames. Kept because host `pytest`
     and one-off `manage.py` runs are faster than `exec`-ing into a container.

  **`scripts/dev-docker.sh` exists because passing any `-f` to `docker compose` disables the automatic merge
  of `docker-compose.override.yml`.** It spells the chain out as base → override → dev, in that order: the
  override supplies the infrastructure port remaps, and the dev layer must come last so its app-service
  commands, ports and bind mounts win. Every argument is forwarded verbatim, so it is a drop-in prefix for
  any compose subcommand. Three traps this topology already hit:
  - **The base file hands `backend`'s environment to `migrate`/`worker`/`beat` through a YAML anchor**, so a
    patch to `backend` alone never reaches them — the override applies the MinIO host-port rewrite to all
    four (the Celery worker builds public image URLs into outbound mail).
  - **`tsc -b` must not emit `vite.config.js` next to `vite.config.ts`** — Vite resolves `.js` first, so a
    stale artifact silently shadows the real config; `tsconfig.node.json` therefore emits into
    `node_modules/.tmp/`.
  - **The dev frontend must carry its own `image:` tag** (`spaceworks-frontend-dev`): `frontend` is the only
    service overriding `build.target`, so without it both topologies derive the same `spaceworks-frontend`
    name, whichever built last owns the tag, and a later prod `docker compose up -d` **without `--build`**
    silently runs the dev image — `CMD` is `npm run dev`, nginx never starts, `8080->80` points at a dead
    port, and the container sits **unhealthy while its logs read a perfectly normal "VITE ready"**. The
    instant tell is the port: the dev stage is `FROM deps` (no source), so without the dev layer's
    `./frontend:/app` mount there is no `vite.config.ts` and Vite falls back to its default **:5173**
    instead of the configured **:5000**.
- **Migration heads drift.** Specs quote stale migration numbers; every Codex prompt must
  `ls backend/apps/<app>/migrations/` and chain off the **actual** leaf, not the spec number. A new
  migration whose dep is a rewound app can break migration-executor tests (rewind the full graph forward in
  the test's `finally`).
### Local development

The topology bullet above explains *why* there are three ways to run this and what each one is for; this
section is the commands. Keep them adjacent — they were 1,400 lines apart once, which is how the two
accounts drifted.

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
## Project Status

### Admin control plane (superadmin-only)

The **Unfold Django admin is the Super Admin's sole control plane**, mounted at **`/control/`** (NOT
`/admin/` — that belongs to the React staff console SPA route), locked to superadmins, and **not exposed on
the public frontend port** (`frontend/nginx.conf` does not proxy it, so makerspace staff on port 80 can
never reach the Django console). Gated two ways: `config.admin_access.AdminSuperuserOnlyMiddleware` (denies
any authenticated non-superadmin; the `/api/v1/admin/...` React staff APIs are NOT gated) and
`config.admin_access.SuperuserOnlyModelAdmin` (first base of every `ModelAdmin`). Superadmin operations are
Django admin **actions that route through the existing services** (never mutating status directly);
issue/return remain React-only. Superadmin monitoring surfaces (QR ZIP, inline QR/photo previews, print file
downloads) are read-only and guard storage failures. Design spec:
`docs/superpowers/specs/2026-06-13-superadmin-admin-control-plane-design.md`.

**U-SEC:** django-axes admin-login lockout, scoped `login`/`public_request_submit` throttles + write-only
`website` honeypot on public submit, production-gated security headers, always-on CSP via django-csp 4, and
a `pip-audit` CI job. The global CSP `script-src` omits `'unsafe-eval'`; a tiny
`config.admin_access.AdminCspEvalMiddleware` appends `'unsafe-eval'` to `script-src` **and** the S3 public
origin to `img-src` **only for `/control/` responses** (django-unfold ships eval-requiring Alpine.js; the
JSON API + public docs stay on the strict policy).

**Django admin coverage** is complete (every domain model registered; immutable/workflow-owned models
read-only; a `list_filter` per makerspace-scoped admin). The Unfold sidebar (`config/unfold.py`) is curated
into grouped sections and a test asserts every sidebar link resolves. `tests/test_admin_hidden_scope.py`
walks every registered admin and forces an explicit scoped/global decision (via `NESTED_MAKERSPACE_LOOKUPS`
/ `GLOBAL_ADMIN_MODELS`) so a new admin can't silently leak across the superadmin hide/archive scoping.

**Non-technical install:** `setup.sh` / `setup.ps1` (first-run wizard: Docker check → generate secrets incl.
Fernet `API_CLIENT_ENC_KEY` → write `.env` → build → `setup_instance` → print URL/creds),
`docker/compose.build.yml`, and `docs/setup-for-makerspaces.md`. TLS is env-gated (`ENABLE_HTTPS`, default
off). First-run `setup_instance` seeds `superadmin`/`super123` + `must_change_password` (surfaced by login +
`/auth/me`, cleared by `/auth/change-password`).

**Releases are titled `SpaceWorks <version>`** (owner convention, 2026-08-15), where the version is the
git-tag form `v<semver>-<branch>.<n>.<sha>` — e.g. `SpaceWorks v0.5.1-main.12.a9cd82c0dd89`. **The
`SpaceWorks ` prefix is a display title, not part of the version value:** `updates.UpdateState` stores the
bare string in `current_version`/`available_version`/`target_version`, and writing the prefix into those
columns (or comparing against it) would break every version equality check the update flow makes. Compose
`f"SpaceWorks {version}"` at the display layer.

**Per-makerspace integrations are backend-only and never leak.** `Makerspace` holds per-tenant
`telegram_bot_token` + `smtp_*`; secrets are encrypted at rest with `API_CLIENT_ENC_KEY` via
`apps/makerspaces/secrets.py` and decrypted only in delivery code. The staff serializer exposes them
**write-only** + a `*_set` boolean. Bootstrap returns only frontend-safe config (module flags, not secrets).
No shared-integration entity exists — makerspaces sharing SMTP/Telegram enter the same credentials per space
(stored/encrypted independently).

**Implementation status.** The multi-frontend platform and open operations/reporting PRDs are implemented
end-to-end (public browse, auth/RBAC, API-client HMAC, QR/box, audit/evidence, 3D Printing Manager, Hardware
Request Workflow, procurement "To Buy", stock transfers incl. true cross-makerspace movement, stocktake,
analytics/ledger/exports, Users CRUD, and the FabLab modules). The detailed PRDs (`docs/prd-*.md`) are
**internal planning docs kept local only** (gitignored); "PRD §N" references point to those. Google Sheets
OAuth publishing, native apps, and physical label-printer control remain out of scope.

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
### Current source map — in `docs/SOURCE-MAP.md`

**The per-app/per-directory source map lives in `docs/SOURCE-MAP.md`** — what each `backend/apps/*` and
`frontend/src/*` directory owns, which file is the single source of truth for what, and which apps are
tombstoned. Read it when you need to find where something lives; it is a lookup table, not a rule set. Like
the other two sibling docs it has no `AGENTS.md` twin — edit it in place, in the same commit as the code
that moved.

The four entry points worth knowing without opening it: `apps/hardware_requests/workflow.py` is the **only**
place request state transitions happen, `apps/inventory/availability.py` is the **only** place quantity
counts change, `apps/makerspaces/module_registry.py` is the single source of truth for module keys, and
`apps/accounts/rbac.py` is the Auth & RBAC module every scoped query must go through.
### Public availability rule (resolves PRD §5's two overlapping fields)

`public_availability_mode` is the master display switch; `show_public_count` is a safety gate for exact
counts:

- `is_public = false` → product excluded from the public list entirely.
- mode `hidden` → product listed, `availability: null`.
- mode `status_only` → `{ mode: "status_only", label }`.
- mode `exact_count` → exact `count` **only if** `show_public_count = true`; otherwise falls back to
  `status_only`.
- Status label: `available ≤ 0` or `total ≤ 0` → `Unavailable`; `available ≤ ceil(total × 0.2)` → `Limited`;
  else `Available`.

The API response is DRF-paginated (`PageNumberPagination`, page size 24): `{ count, next, previous, results }`.
This is the standing convention for all list endpoints.

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
## Invariants (do not regress) — in `docs/INVARIANTS.md`

**The long-form load-bearing rules live in `docs/INVARIANTS.md`, not in this file.** They were split out
when this file crossed the harness's memory-file size limit; **nothing was dropped in the move**, and that
document has no `AGENTS.md`-style twin — both names of this one point at that path.

They are reference material, read **per area, on demand**: before you touch code in one of the areas below,
open that section and read it. Do not read the whole document, and do not assume an area has no rules
because none are quoted here — this index is a router, not a summary.

| Section of `docs/INVARIANTS.md` | Before you touch |
| --- | --- |
| **Cross-cutting invariants** | self-host vs managed SaaS and fair-use limits; `frontend_domain` and origin scoping; superadmin hide/archive/purge; archival vs member money; the two-key archive request; public borrower names; public image fields and storage accounting; rate-limit cache; object storage; the report registry; scoped PII encryption; custom roles; `module_registry` and opt-in modules; module install/uninstall/purge; the `email` module gate; A6 master switches; two-level capabilities; the `membership` module; payments, credentials and reconciliation; native device grants; OIDC, social, phone and login-method switches; walk-in/account-less identity; maker profiles; staff event registration; notifications v2; presence geofence; the colour vocabulary; the accessibility floor; console parity |
| **Separability and tombstoning** | `apps/separability/`, `TOMBSTONED_APPS`, `SEPARABLE_APPS`, retention vs runtime registries, adding a PII-holding model |
| **Machine scoping** | `MANAGE_MACHINES`, `machines/role_scope.py`, the Machines console, machine-service surfaces, procurement narrowing, dashboard scoping, delegated recipient rules |
| **Events program invariants** | `apps/events/`, registration vs presence, member history and provenance, collaborative events, host waivers, QR check-in |
| **Backup, restore and tenant migration** | `apps/backup/`, `apps/data_export/`, `apps/tenant_migration/`, the deployment recovery gate, the source gate lock protocol, archive projection |
| **Organization accounts and organization-derived authority** | `apps/organizations/`, `OrganizationMembership`, the rbac org branch, `resolve_scope` vs `scope_by_action`, the auth payload `source` field, `EventOrganizer`, org purge scoping |
| **API client scopes and the protected-route registry** | `apps/apiclients/scope_registry*.py`, `legacy:v1`, unknown-route denial, target resolution, the system check, the HMAC signed message and nonce namespace |
| **Container / deployment invariants** | `Dockerfile`, the compose files, Celery beat, MinIO/CORS, browser-facing storage URLs, production compose defaults |

Two rules are repeated here because they bite outside their own area: **a new model must be classified in
`apps/data_export` and have its `accounts.User` FKs decided, or the drift guards refuse the build**, and
**`select_for_update()` cannot be combined with `select_related()` across a nullable FK** — Postgres rejects
it outright.
## Condensed changelog — in `docs/PROJECT-HISTORY.md`

**The condensed changelog lives in `docs/PROJECT-HISTORY.md`** — one line per shipped batch, newest first,
from Phase 5B (2026-08-17/18) back to the first production deploy (2026-06-19). It was split out with the
invariants when this file crossed the harness's memory-file size limit; nothing was dropped. Like
`docs/INVARIANTS.md` it has no `AGENTS.md` twin — both names of this document point at that one path.

Read it when you need to know **when and why a feature landed**, or which decisions were considered and
dropped (per-destination Telegram bot tokens; SAML and per-makerspace auth credentials). The rules those
batches introduced are in `docs/INVARIANTS.md`, not there. For implementing commits and per-file history,
use `git log --oneline` / `git blame`.
## Key References in the PRD

- Roles & permission matrix: §4
- Core workflows (request → accept → issue → return → restrict): §6
- Data model (entities + fields): §13
- API surface (public / auth / admin / guest-admin / telegram routes): §14
- App/dashboard navigation tree: §15
- MVP vs. later scope: §16
- Behaviors that must be tested: §17 (test external behavior, not implementation)
- Unresolved decisions: §18 — **resolve relevant open questions before implementing the affected area** rather than guessing.
