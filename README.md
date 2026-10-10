<div align="center">

  <img src="docs/banner.svg" alt="Space Works — Open Source Makerspace Manager" width="860">

  <h1>Space Works — Open Source Makerspace Manager</h1>

<p>
  Self-hostable, multi-tenant <strong>management platform for makerspaces</strong> — run your
  inventory, tool &amp; equipment lending, and 3D printing in one place. Browse, borrow, track, and
  stay accountable, without spreadsheets.
</p>

<p>
  <a href="LICENSE"><img alt="License: AGPL-3.0-or-later" src="https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg"></a>
  <a href="https://github.com/SpaceWorks-HQ/SpaceWorks/actions/workflows/release.yml"><img alt="Release" src="https://github.com/SpaceWorks-HQ/SpaceWorks/actions/workflows/release.yml/badge.svg?branch=main"></a>
  <img alt="Stack" src="https://img.shields.io/badge/stack-Django%206%20%C2%B7%20React%2019-0b7285.svg">
  <a href=".github/CONTRIBUTING.md"><img alt="PRs welcome" src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg"></a>
</p>

</div>

---

Space Works started inside the **TinkerSpace Kochi** community, from a simple need: make it easy for a
makerspace to know **what tools and equipment exist, who borrowed what, what's available, and how
every loan and print job moves from request to done** — with enough traceability that accountability
for shared gear is never a guessing game. It's built by makers, for makers: run it at your space, fork it, remix it, or use it as
a starting point. If your community works differently, make it your own.

One deployment can host **many makerspaces** (tenants). Each owns its inventory, public URL, staff,
Telegram group, QR namespace, and audit scope — fully isolated from the others.

## Features

- **Public catalog** — browse by makerspace and category, request to borrow, and (when enabled)
  **QR self-checkout/return** for present members with photo evidence.
- **Full hardware lifecycle** — request → accept → issue (box QR scan + photo) → return (photo +
  remark) → accountability, all audited. Direct staff handouts too.
- **3D-printing manager** — public print requests, printer/spool management, filament tracking,
  slicer estimates, and an optional (staff-private) cash charge at collection.
- **Events & bookings** — one-off events or recurring series, registration with optional approval and
  waitlists, QR check-in at the door (plus an expiring offline roster and event-scoped PIN stations for
  a desk with no signal), post-event feedback, attendance certificates, printable badges, member
  calendar feeds, and bookable spaces.
- **Organizations across makerspaces** — a network, university or chain registered as an organization
  linked to any number of spaces, with a public profile and a cross-makerspace event catalogue. An
  organization grant confers **actions, never identity**.
- **QR everywhere** — boxes, tools, and individual assets; immutable scan history.
- **Live staff console and one search box** — queues, loans and check-ins update the moment a change
  commits (Server-Sent Events over the deployment's Redis; falls back to polling without it), and every
  inventory, machine and event list answers `?q=` with full-text search that tolerates typos.
- **Editions and a single box** — an events-only or bookings-only installation hides the loan spine it
  does not use (`SPACEWORKS_EDITION`), and the whole application can run as one container beside
  Postgres and MinIO when a makerspace has one small server and nobody to operate a stack.
- **Operable in production** — every request carries an `X-Request-ID` through JSON logs and Celery,
  a token-protected Prometheus endpoint reports queue depth, delivery failures and storage, and CI runs
  the whole suite before an image is published.
- **Action-based staff console** — editable per-makerspace roles over a fixed action set, four seeded
  defaults, and a superadmin-only Django control plane.
- **Reports & ledger** — what's out, who has it, overdue tracking, CSV/XLSX export, plus accessible
  charts with table fallbacks and append-only metric rollups where a correction adds a revision rather
  than rewriting history. Every module is covered either by a substantive report or an explicitly
  gated row.
- **Notifications** — per-makerspace **Telegram, Slack, Mattermost and Discord** alerts plus async
  (Celery) email, with a per-feature × per-channel matrix. Each channel is its own module.
- **Modular by install** — turn whole modules on and off per makerspace; uninstalling hides surfaces
  and always keeps the data. See [Modules](#modules).
- **Sign-in options** — username/password, Google, Apple, any OIDC provider (Keycloak, Authentik,
  Azure AD, Okta), and **phone + SMS code** for members. Each is switchable, and a space can run with
  **no member accounts at all**, on your own identity provider plus staff-created walk-in records.
- **Maker profiles** — an opt-in per-makerspace profile with projects, interests, education and an
  optional GitHub contribution count, plus a member directory that lists only the people who chose to
  be listed.
- **Traceable by design** — append-only audit log; immutable evidence photo records and scan history.
  Photo *bytes* can expire under a per-makerspace retention policy, while the photo metadata, remarks,
  scans and audit trail are kept — so the accountability record outlives the image itself, and an
  expired photo reads as a truthful expired state rather than a missing one.

> **What works out of the box:** username/password. Google, Apple and OIDC need credentials you
> create with that provider, and phone sign-in needs an SMS account — none of them can ship
> preconfigured, because they are issued against *your* domain. `setup.sh` walks you through Google
> and you can skip it; password login is unaffected either way. The GitHub contribution count on
> maker profiles is the same shape: set `GITHUB_API_TOKEN` in `.env` to enable it, and leave it unset
> for the section to simply never appear.

## Quick start

Space Works runs entirely through Docker Compose — it brings up **PostgreSQL, Redis, MinIO storage, the
Celery worker/beat, and database migrations** and wires them to the app for you (the images don't bake
in any addresses; the compose file passes them in). Pick one path:

**Path 1 — Guided pinned install (easiest; no Git clone or local build).** One script checks the host,
downloads the newest tagged release, generates all secrets, pulls its published images, and creates your
first admin + makerspace:

```bash
curl -fsSL https://raw.githubusercontent.com/SpaceWorks-HQ/SpaceWorks/main/install.sh | bash
```

It installs to `/opt/spaceworks`; set `SPACEWORKS_DIR` on the `bash` side of the pipe to override that
(on Windows Git Bash, use `SPACEWORKS_DIR="$HOME/SpaceWorks"`). It detects x86_64/aarch64 and the host
distribution, checks dependencies, Docker, release availability, ports, disk space and existing state
**before changing anything**, then installs missing Linux dependencies through apt, dnf/yum, pacman or
zypper. The downloaded source and backend/frontend images are pinned to the tagged release.

It prints your URL and login when it finishes and offers to install seven-day, backup-first production
update checks. Super Admins can control automatic or manual installation from **Platform settings →
Software updates**. `setup.sh` pulls published images by default; developers with a full source checkout
can explicitly opt into a local Django/Vite build with `bash setup.sh --build`.

Run the same curl command later and an existing install offers **update**, **change modules**, **both**, or
**cancel**. It never silently reinstalls or reruns first-instance setup.

**Path 2 — Manual prebuilt-image setup.** Pull the two published images and start the stack —
after `cp .env.example .env` (fill in the few values it asks for):

```bash
export MAKERSPACE_IMAGE_TAG=latest        # or pin a release, e.g. 0.5.1-main.42.a1b2c3d4e5f6
bash scripts/init-host-orchestration.sh   # one-time root-owned pointer/key/config state
scripts/spaceworks-compose.sh bundled up -d
```

This pulls **`ghcr.io/spaceworks-hq/spaceworks-backend`** + **`ghcr.io/spaceworks-hq/spaceworks-frontend`** and brings up the
full stack automatically.

### Upgrades and module changes

An interactive update reviews the live module ticks after the new release is healthy. The useful explicit
forms are:

```bash
bash scripts/update.sh --force --modules                    # update, then review modules
bash scripts/update.sh --force --no-module-changes          # update images only
bash scripts/update.sh --modules-only --makerspace my-space # modules only; no release check
bash scripts/update.sh --all-modules --without=printing,payments \
  --makerspace my-space --confirm-removals
bash scripts/update.sh --all-modules --all-makerspaces      # explicit cross-tenant target
```

Modules belong to a makerspace through `Makerspace.enabled_modules`, not to the deployment as a whole.
When more than one makerspace exists, select one with `--makerspace <slug>` or deliberately target all
with `--all-makerspaces`; non-interactive updates refuse to guess. `--modules` requests the interactive
tick list, while `--modules-only`, `--all-modules`, `--without=a,b`, `--confirm-removals` and
`--no-module-changes` support explicit operator and automation flows.

Unticking a module hides its surfaces and calls `uninstall_module`; it does **not** delete rows.
`purge_module_data` is a separate destructive command and is never called by setup or update.

### Windows support boundary

- **Tier 1 — native:** install, run and upgrade with Docker Desktop plus Git Bash (or run the bash scripts
  inside WSL). Because native Git Bash normally has no `flock`, the updater falls back to a PID/timestamp
  directory lock, automatically clears a dead owner's lock, and provides `--override-lock` for a verified
  wedged or unreadable owner.
- **Tier 2 — WSL2 required:** in-place restore, backup import and compound host orchestration. Those
  supervisors depend on Linux AF_UNIX sockets and root-owned-file trust semantics with no native Windows
  equivalent; this tier does not have native parity.

## Modules

See the [module setup guide](docs/README-MODULES.md) for profiles, per-space switches,
notification channels, sign-in options and build removal. The [module reference](docs/MODULES.md)
explains each module and its retained data.

## Documentation

| I want… | Go to |
|---|---|
| What a **module** is and what happens without it | **[docs/MODULES.md](docs/MODULES.md)** |
| A **plain-language, non-technical** walkthrough | **[docs/setup-for-makerspaces.md](docs/setup-for-makerspaces.md)** |
| **Production** reference (env vars, TLS, upgrades, releases) | **[docs/self-hosting.md](docs/self-hosting.md)** |
| **Advanced** config (Telegram, HMAC, Supabase, cron) | **[.github/ADVANCED.md](.github/ADVANCED.md)** |
| **Develop / contribute** (run from source, tests, releases) | **[.github/DEVELOPMENT.md](.github/DEVELOPMENT.md)** |

## Roadmap

Space Works 0.5 is focused on reliable self-hosting and complete makerspace operations:

- automatic, backup-first updates from every successful `main` release;
- stable public, member, staff, and superadmin workflows across the full module set;
- continued accessibility, mobile, reporting, and operational resilience work.

### Planned modules

Not built yet. Listed here rather than in the module table because that table is generated from the
module registry, and the registry only carries modules with real enforcement behind them.

- **Hardware integration** — talking to the machines themselves rather than only recording them:
  reading job state off a printer or CNC controller, driving label printers directly, and door or
  access-control hardware for check-in. Today the machine service queue is operated by hand and
  geofenced check-in is deliberately advisory; this is the module that would change that. It needs a
  device-identity and trust story of its own, because a network device reporting job completion is
  an unauthenticated actor asserting a state transition.
- **Invitation requests** — letting a prospective member *ask* for an invitation, rather than only
  being invited or applying to join.

Current work and shipped changes are tracked in
[GitHub issues](https://github.com/SpaceWorks-HQ/SpaceWorks/issues),
[pull requests](https://github.com/SpaceWorks-HQ/SpaceWorks/pulls), and the release notes. The running
product intentionally does not expose a separate roadmap page.

## Roles & access

See [roles and access](docs/README-HOSTING.md#roles--access) for custom roles, action grants,
and makerspace scoping.

## Hosting

See the [hosting guide](docs/README-HOSTING.md#hosting) for first-run generated credentials,
Docker and split deployments, and moving a makerspace onto its own server.

## Tech stack

Django 6 + DRF · React 19 + Vite 8 + Tailwind CSS 4 + TypeScript (TanStack Query v5) · PostgreSQL 16 ·
Celery + Redis · MinIO (S3-compatible) · django-unfold admin · drf-spectacular / OpenAPI. Delivered as
two Docker images (`spaceworks-backend`, `spaceworks-frontend`); everything else is official upstream images.

## Contributing

Space Works is a collaborative project for the makerspace community, and **contributors are very welcome** —
code, docs, translations, or just running it at your space and reporting what's rough. See
**[.github/CONTRIBUTING.md](.github/CONTRIBUTING.md)**. **No CLA is required** — by opening a pull
request you agree your contribution is offered under the project's AGPL-3.0-or-later license
(inbound = outbound); merged contributors are credited in
[.github/CONTRIBUTORS.md](.github/CONTRIBUTORS.md).

## License

Space Works is **free and open source software**, licensed under the
**[GNU Affero General Public License v3](LICENSE)** (`AGPL-3.0-or-later`).

You are free to use, study, share, and modify Space Works — for **any** purpose, commercial or
noncommercial — subject to the AGPL. Because the AGPL is a **network copyleft** license: if you run
a modified version and let users interact with it over a network, you must offer those users the
corresponding source code of your modified version under the same license.

## Contributors

Thanks to **everyone** who has contributed to Space Works — code, docs, bug reports, or running it at their
space. The wall below is pulled live from this repository's
[GitHub contributor graph](https://github.com/SpaceWorks-HQ/SpaceWorks/graphs/contributors) and
shows **all** contributors — bots and automation included, no filtering:

[![Contributors](https://contrib.rocks/image?repo=SpaceWorks-HQ/SpaceWorks&max=100)](https://github.com/SpaceWorks-HQ/SpaceWorks/graphs/contributors)

<sub>Contributor image by [contrib.rocks](https://contrib.rocks).</sub>
