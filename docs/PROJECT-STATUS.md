# SpaceWorks project status — what exists today

> **This is the what-exists-today half of `CLAUDE.md` / `AGENTS.md`.** It was split out when that
> file crossed the harness's memory-file size warning; nothing was dropped in the move. It has no
> `AGENTS.md`-style twin — both names of that document point at this one path, so edit it in place.
>
> This is a description of the shipped platform, not a rule set: the superadmin control plane, the
> security posture, the non-technical installer, the release-title convention, per-tenant
> integrations and overall implementation status. The rules these areas impose live in
> `docs/INVARIANTS.md`; when a feature landed is in `docs/PROJECT-HISTORY.md`.

## Admin control plane (superadmin-only)

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

**Non-technical install:** the root `install.sh` curl flow on supported Linux families or Windows Git Bash
(preflight → tagged source archive → published-image pull → `setup.sh` secrets/instance/live module ticks →
version marker), with `SPACEWORKS_DIR` override and an existing-install update/module menu.
`setup.sh --build` is the explicit source-build path via `docker/compose.build.yml`. Native Windows covers
install/run/update, using the crash-recoverable PID/timestamp update lock when `flock` is unavailable;
restore and compound host recovery stay WSL2-only because they require AF_UNIX sockets and
root-owned-file trust semantics. See
`docs/setup-for-makerspaces.md`. TLS is env-gated (`ENABLE_HTTPS`, default off). First-run
`setup_instance` seeds `superadmin`/`super123` + `must_change_password` (surfaced by login + `/auth/me`,
cleared by `/auth/change-password`).

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
