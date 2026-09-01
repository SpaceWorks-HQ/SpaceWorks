# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working with code in this repository.

> **This file has two names, and they must stay byte-identical.** `CLAUDE.md` and `AGENTS.md` are the *same
> document* under the two filenames the tooling looks for — Claude Code reads the first, Codex and
> other-model agents (GPT, Gemini, Copilot, Cursor) read the second. **Any edit to one must be copied to the
> other in the same commit**; `diff CLAUDE.md AGENTS.md` must print nothing, and that emptiness is the drift
> guard. Do not let them diverge into a "full" and a "summary" version: `AGENTS.md` was once a hand-written
> short mirror and silently rotted for months, still routing state transitions through the tombstoned
> `apps/printing/workflow.py`. One document with two names cannot rot in only one of them.

> **This file is orientation; the reference material lives in five sibling docs.** Order here: what the
> system is, the two architectural rules, the state machine, tenancy, the Hard Rules, the engineering
> conventions, the standing rules for working in the repo, then routers into the reference docs.
>
> - **`docs/INVARIANTS.md`** — the long-form load-bearing "do not regress" rules, read **per area, on
>   demand**. The "Invariants" section below is the index of which section to open.
> - **`docs/SOURCE-MAP.md`** — what each backend app and frontend directory owns.
> - **`docs/DEV-WORKFLOW.md`** — program state, the Codex gates, worktrees, the test harness and the three
>   local run topologies. Read it **before starting a build**.
> - **`docs/PROJECT-STATUS.md`** — what exists today: control plane, security posture, installer, releases.
> - **`docs/PROJECT-HISTORY.md`** — the condensed changelog.
>
> All five were split out when this file crossed the harness's memory-file size limit; **nothing was
> dropped in the move**, and none of them has an `AGENTS.md`-style twin — both names of this document point
> at those same paths, so edit them in place. Rules an agent must obey without knowing to look them up stay
> *here*; the siblings hold what you consult on purpose. When changing a shipped feature, prefer
> `git log`/`git blame` for its history and `docs/INVARIANTS.md` for the rules you must not break.

## What This System Is

A multi-tenant system for managing community hardware loans across makerspaces. The central concern is
**traceability of physical handovers**: every issue and return must produce evidence (QR scans + photos +
remarks + audit log). Photo bytes may expire under the configured retention policy, while immutable photo
metadata, remarks, scans and audit history preserve the durable accountability trail. Public users
browse and request; when self-checkout is enabled they may also issue/return eligible QR tools after
authentication and evidence upload. Staff physically issue reviewed requests and direct handouts according
to action scope.

## Architecture: Concepts That Span Multiple Modules

UIs are thin clients over an API server composed of deep modules; Telegram is an outbound notification
channel only. Two architectural rules are load-bearing and easy to violate if you only read one module:

1. **The Request Workflow Module is the single source of truth for state transitions.** The web admin
   panel, the guest-admin app and the `/control/` review page must all route through the *same* workflow
   service — never mutate `HardwareRequest.status` directly. **Chat is not a decision surface**: the
   Telegram accept/reject buttons and their callback route were removed, so there is no bot path into the
   state machine to keep consistent any more. Re-introducing one means going through the workflow module,
   never the database.

2. **The Inventory Availability Module owns all quantity math.** Reserve / issue / return / mark-lost all
   flow through it. No other module computes available/reserved/issued counts. The invariant "availability
   never goes below zero" lives here.

### Module responsibilities

- **Auth & RBAC** — enforces the role/action matrix AND makerspace scoping on every query. Super Admin is
  global; every other role is a per-makerspace membership resolved through an editable `MakerspaceRole` row,
  action-based. `roles.DEFAULT_ROLE_DEFINITIONS` + `MEMBER_ROLE_DEFINITION` seed **four** protected defaults
  per makerspace — Space Manager, Inventory Manager, Machine Manager, Member. **Guest Admin and Print
  Manager are both retired** — handover is a custom role, and `print_manager` survives only as the frozen
  legacy fallback in `_MEMBERSHIP_ROLE_ACTIONS` (migrations and enum archaeology under **Handover roles**
  in `docs/INVARIANTS.md`). Inventory Manager is membership-only and covers the full hardware lifecycle but
  not printing, staff, or makerspace settings. Also blocks restricted/suspended users. Interface:
  `can(actor, action, resource)`, `scope_by_makerspace(actor, query)`. (It no longer verifies Telegram
  actors — that went with the callback route. `assertTelegramActorCan` never existed in the code at all;
  this line asserted it for months.)
- **Request Workflow** — owns the state machine, emits audit logs, triggers Telegram alerts, coordinates
  inventory reservation/issue/return.
- **Inventory Availability** — quantity math + asset status for QR-tracked tools.
- **QR Code & Box** — generates/resolves/revokes QR codes, assigns boxes to requests, tracks scan history.
- **Evidence Photo** — immutable issue/return photo metadata linked to actor + request + QR scans; private
  object bytes may expire under the evidence-retention policy and are never public.
- **Check-In API Client** — **RETIRED** (`73a480c`, Part M7). `apps/checkin/` no longer exists and there is
  no `CHECKIN_MODE` setting. Requester identity now comes from authenticated member accounts, so there is no
  external verify dependency left to fail safe on.
- **Telegram Integration** — sends per-makerspace group alerts. **Outbound only.** The webhook route is
  retained but accept-and-ignores every callback, because a deployment that already ran `setWebhook` would
  otherwise have Telegram retry a 404 for hours; no chat message may carry an inline keyboard.

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
- **Guest Admin is no longer a built-in role**; handover staff get a **custom role** holding the handout
  actions. It issues accepted requests, creates **direct handouts**, processes scoped returns and uploads
  evidence — through the same evidence/QR/remark/audit workflow as staff — and still cannot accept/reject
  requests, edit inventory or manage QR unless granted those actions. `rbac.HANDOUT_ACTIONS` is no longer a
  cap on what a role may hold; it only defines what counts as handover-only for `rbac.is_handout_only`,
  which decides how narrow the console is. The `guest-admin/` **URL paths** in `hardware_requests/urls.py`
  are the handover API surface (module key `guest_handover`), not the role — renaming them would break
  clients. Full detail: **Handover roles** in `docs/INVARIANTS.md`.
- Public request submission requires an **authenticated member** (`RequestSubmitView` → `IsAuthenticated`),
  and request lookup is scoped to that verified identity — it never matches free-text contact fields (no
  enumeration by known email/phone). Since the Check-In retirement (`73a480c`) this is enforced by member
  auth rather than an external verify call.
- Inventory Managers can run the full hardware lifecycle but **cannot** manage printing, staff, or
  makerspace settings.
- Evidence endpoints require per-makerspace `UPLOAD_EVIDENCE` plus active status; QR management also checks
  active status.
- **Every presigned upload lands on the staging key; the final object key is never client-writable.** A workflow promotes it exactly once, so an accepted evidence photo cannot be replaced through a still-valid presign. Before retention expiry, read paths — the evidence endpoint, the admin preview, and backup/tenant-migration object capture — therefore fall back to the staging key, or an uploaded-but-unconsumed photo reads as missing. A terminal expired state returns 410 and never consults storage.
- Evidence photo **rows** and QR scan records are **immutable**; audit logs are **append-only**. Evidence retention may delete every final and staging object version only after the configured window, but it does not update or delete the retained `EvidencePhoto` row.
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
  still import the admin submodules so the `@admin.register` side effects fire. **The ceiling is enforced
  on what you touch, and it is NOT currently met repo-wide: 37 backend files exceed 300 lines** — largest
  first, `config/settings.py` (929, the accepted exception — Django settings are conventionally a single
  file), `admin_api/urls.py` (825), `makerspaces/models.py` (682), `accounts/rbac.py` (609),
  `inventory/availability.py` (596), `admin_api/serializers_makerspaces.py` (561),
  `makerspaces/module_registry.py` (503), `machines/role_scope.py` (489). Measured 2026-08-20; an earlier
  version of this line claimed every file but `settings.py` was compliant, which was false by 36 files.
  **Split an over-ceiling file in its own commit before adding to it**, and when splitting one that other
  modules import from, check for guards pinned to its path: `tests/makerspaces/test_tenant_servability_guard.py`
  pins two function *bodies* to `accounts/rbac.py` by `(path, function)`, and
  `tenant_migration/authority_guards.py` pins whole *files* via `AUTHORIZATION_SOURCES` — the latter goes
  silently blind rather than failing if you move code out from under it.
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

## Working in this repo — the standing rules

**The full account — program state, the Codex gates, worktrees, the test harness, the three local run
topologies and every trap that has already cost a session — is in `docs/DEV-WORKFLOW.md`. Read it before
starting a build.** These are the rules you must not violate without having read it:

- **The Codex gates are LIVE** (Stages 1/2/4 of `~/.claude/CLAUDE.md`), but **re-check `codex doctor`**
  rather than trusting any written claim — that one line has gone stale silently for weeks before.
- **Name Codex in a `Co-Authored-By` trailer only on work Codex actually wrote.** Attribution, not
  ceremony: this overrides the unconditional three-trailer rule in the global config, and the trailer set
  is decided per commit by who really wrote the code.
- **Never `git add`/stage before a Codex workspace-write run** — a non-empty index makes `apply_patch`
  silently fail with a misleading "read-only" error and no files written.
- **The test baseline is ZERO reds** — any failure is a NEW regression, not background noise. Run
  `./scripts/dev-local.sh test` with `spaceworks-db` (:5433), `spaceworks-redis` (:6379) and
  `spaceworks-minio` (:9200) up. **Never run two `pytest` procs against one DB**, and never run the full
  suite concurrently with `codex review` (it runs its own).
- **`tests/backup` and `tests/tenant_migration` need a pg client whose MAJOR equals the server's (16),
  and the host may not have one.** `postgres_client.client_binary` resolves
  `/usr/lib/postgresql/{major}/bin` (Debian/PGDG) or `/usr/pgsql-{major}/bin` (RHEL) and otherwise
  fails closed — so on Arch, where neither path exists and `/usr/bin/pg_dump` is whatever `pacman`
  ships, every one of those tests refuses with `PostgresClientUnavailable`. That is the environment,
  **not a regression**. Run them in Docker instead, and note the DATABASE_URL override: the backend
  container runs as the least-privilege `spaceworks_app` role, which has no CREATEDB, so pytest cannot
  build a test database as itself.

  ```bash
  ./scripts/dev-docker.sh exec -e DATABASE_URL=postgres://makerspace:makerspace@db:5432/makerspace_manager \
    -T backend pytest tests/backup tests/tenant_migration -q
  ```
- **Chain every new migration off the ACTUAL leaf** — `ls backend/apps/<app>/migrations/`, never the number
  a spec quotes.
- **Commits sit local and unpushed on `dev`; pushing is the owner's call alone.** Ask
  `git rev-list --count origin/dev..dev` rather than trusting a count written anywhere.
- **MERGING IS THE OWNER'S ACT ALONE — never merge a branch yourself.** This covers every merge,
  including `dev` -> `main`, a feature branch into `dev`, and a fast-forward that looks trivial.
  Prepare the merge, verify it is clean, report exactly what would land, then STOP and hand it over:
  the owner runs the `git merge` and the `git push`. This is stricter than the push rule above and
  overrides the global config's Stage-5 "merge it into `dev`" step, which no longer applies here.
- **Never run the Docker and host stacks at once** — they bind the same ports (:8000, :5000) and the same
  database.

```bash
./scripts/dev-docker.sh up -d --build                          # default: all in Docker, live reload
./scripts/dev-local.sh infra && ./scripts/dev-local.sh test    # host: faster pytest, most of the suite

# In Docker, pytest needs the DB OWNER: the backend runs as `spaceworks_app`, which has no CREATEDB.
./scripts/dev-docker.sh exec -e DATABASE_URL=postgres://makerspace:makerspace@db:5432/makerspace_manager \
  -T backend pytest
```

Public inventory page: `http://localhost:5000/m/makerspace`. API: `http://localhost:8000/api` — Swagger UI
at `/docs/`, ReDoc at `/redoc/`, schema at `/schema/`.

## Project Status — in `docs/PROJECT-STATUS.md`

**What exists today lives in `docs/PROJECT-STATUS.md`** — the superadmin-only `/control/` control plane and
its two gates, the U-SEC security posture (axes, throttles, CSP), the non-technical installer, the
`SpaceWorks <version>` release-title convention, per-makerspace encrypted integrations, and overall
implementation status. Read it to find out whether something already exists and how it is wired; the rules
those areas impose are in `docs/INVARIANTS.md`.

Two facts from it that bite outside their own area: the Django admin is at **`/control/`**, not `/admin/`
(that is the React staff console SPA route), and superadmin operations are admin **actions routed through
the existing services** — never direct status mutation.

Stack (in use):

- **Backend:** Django 6 + Django REST Framework (`backend/`). Requires Python 3.12+.
- **Frontend:** React 19 + Vite 8 + TypeScript (`frontend/`). Requires Node 20.19+ / 22.12+.
- **Server state:** TanStack Query v5. **Database:** PostgreSQL 16 (via `docker-compose.yml`). **Admin
  theme:** django-unfold; site name via `ADMIN_SITE_NAME` (default "Space Works").
- **Styling:** Tailwind CSS 4 (CSS-first; `src/index.css` uses `@import "tailwindcss"` + `@config
  "../tailwind.config.ts"`; PostCSS via `@tailwindcss/postcss`) with CSS-variable light/dark theme tokens.
  Light default; dark toggle persisted locally.
- **API documentation:** drf-spectacular / OpenAPI (snapshot `frontend/openapi-schema.json` + generated
  `frontend/src/generated/api.ts`; regenerate both when routes/models change — spectacular needs
  `--format openapi-json`).
- **Telegram:** request alerts and test alerts. Outbound only — the webhook acknowledges and discards
  callbacks; decisions are made in the staff console or `/control/`.

## Current source map — in `docs/SOURCE-MAP.md`

**The per-app/per-directory source map lives in `docs/SOURCE-MAP.md`** — what each `backend/apps/*` and
`frontend/src/*` directory owns, which file is the single source of truth for what, and which apps are
tombstoned. Read it when you need to find where something lives; it is a lookup table, not a rule set. Like
the other sibling docs it has no `AGENTS.md` twin — edit it in place, in the same commit as the code
that moved.

The four entry points worth knowing without opening it: `apps/hardware_requests/workflow.py` is the **only**
place request state transitions happen, `apps/inventory/availability.py` is the **only** place quantity
counts change, `apps/makerspaces/module_registry.py` is the single source of truth for module keys, and
`apps/accounts/rbac.py` is the Auth & RBAC module every scoped query must go through.

**Adding or changing a module key means editing `docs/MODULES.md` in the same commit** — it is the
user-facing page the README links every module name into (what the module is, what it adds, what
happens without it, what a purge deletes), and it is hand-written prose over the registry's facts, so
nothing regenerates it for you.

## Public availability rule (resolves PRD §5's two overlapping fields)

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

## Audit + evidence conventions

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
| **Handover roles and the retired Guest Admin** | handout/front-desk custom roles, `rbac.HANDOUT_ACTIONS`, `is_handout_only`, the retired `guest_admin`/`print_manager` enum members and their migrations |
| **Separability and tombstoning** | `apps/separability/`, `TOMBSTONED_APPS`, `SEPARABLE_APPS`, retention vs runtime registries, adding a PII-holding model |
| **Machine scoping** | `MANAGE_MACHINES`, `machines/role_scope.py`, the Machines console, machine-service surfaces, procurement narrowing, dashboard scoping, delegated recipient rules |
| **Events program invariants** | `apps/events/`, registration vs presence, member history and provenance, collaborative events, host waivers, QR check-in |
| **Backup, restore and tenant migration** | `apps/backup/`, `apps/data_export/`, `apps/tenant_migration/`, the deployment recovery gate, the source gate lock protocol, archive projection |
| **Organization accounts and organization-derived authority** | `apps/organizations/`, `OrganizationMembership`, the rbac org branch, `resolve_scope` vs `scope_by_action`, the auth payload `source` field, `EventOrganizer`, org purge scoping |
| **API client scopes and the protected-route registry** | `apps/apiclients/scope_registry*.py`, `legacy:v1`, unknown-route denial, target resolution, the system check, the HMAC signed message and nonce namespace. The client-facing protocol is written up in `docs/api-client-protocol.md` |
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
