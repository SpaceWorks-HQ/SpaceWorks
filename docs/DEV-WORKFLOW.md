# SpaceWorks dev workflow — program state and build conventions

> **This is the how-we-build half of `CLAUDE.md` / `AGENTS.md`.** It was split out when that file
> crossed the harness's memory-file size warning; nothing was dropped in the move. It has no
> `AGENTS.md`-style twin — both names of that document point at this one path, so edit it in place.
>
> Read it before starting a build on this program: it carries the current program state, the Codex
> gates, the worktree/test-harness conventions and the three ways to run the stack locally. The
> non-negotiable one-liners are quoted in `CLAUDE.md`; everything else — the *why*, and every trap
> that has already cost a session — is here.

## Current work — FabLab expansion (branch `dev`)

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

## Standing build conventions for this program

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

## Local development

The topology bullet above explains *why* there are three ways to run this and what each one is for; this
section is the commands. Keep them adjacent — they were 1,400 lines apart once, which is how the two
accounts drifted.

The default path needs nothing installed on the host but Docker. Migrations run automatically as a
`depends_on: service_completed_successfully` step, so `up` is the whole story:

```bash
# Everything — db, redis, minio, Django, Celery worker/beat, Vite — with live reload.
./scripts/dev-docker.sh up -d --build     # first run; drop --build afterwards
./scripts/dev-docker.sh run --rm --no-deps backend --role management python manage.py seed_demo   # first run only
./scripts/dev-docker.sh logs -f backend
./scripts/dev-docker.sh restart worker beat   # Celery has no autoreload
./scripts/dev-docker.sh down

# After changing package.json, recreate the node_modules volume:
./scripts/dev-docker.sh up -d --build -V frontend

# Tests. The DATABASE_URL override is REQUIRED: the backend container runs as the
# least-privilege `spaceworks_app` role, which has no CREATEDB, so pytest cannot build
# its test database as itself (every django_db test errors in setup without this).
./scripts/dev-docker.sh exec -e DATABASE_URL=postgres://makerspace:makerspace@db:5432/makerspace_manager \
  -T backend pytest
```

`tests/backup` and `tests/tenant_migration` are **Docker-only in practice**: they need a PostgreSQL
client whose major equals the server's (16), which `postgres_client.client_binary` looks for under
`/usr/lib/postgresql/{major}/bin` or `/usr/pgsql-{major}/bin`. Neither path exists on Arch, so on the
host they all refuse with `PostgresClientUnavailable` — the environment, not a regression. The backend
image installs client 16 *and* 17 on purpose (`pg_dump` must be >= every supported source server;
`pg_restore` must be <= the target, because 17+ emits a `transaction_timeout` GUC that 16 rejects).

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
