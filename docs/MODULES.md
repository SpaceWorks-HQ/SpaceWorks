# SpaceWorks modules — what each one is, and what happens without it

Space Works ships **32 modules**: 6 **core** ones that cannot be switched off, 2 that are **on by
default**, and the rest opt-in. This page is the per-module reference the README links into — one entry
per key, saying what it is, what it puts on screen, what disappears if you do not install it, and what
happens to its data.

> **Derived from `backend/apps/makerspaces/module_registry.py`**, which is the single source of truth for
> module keys, defaults and dependencies. If you add or change a module there, update the matching entry
> here in the same commit. The rules modules must obey (install/uninstall/purge semantics, the `email`
> gate, two-level capabilities) are in `docs/INVARIANTS.md`, not here.

## The three levels

| Level | Who changes it | What it means |
|---|---|---|
| **Core module** | nobody | Always on. The Hard Rules make the loan spine *the system*: issuing hardware needs a box QR scan **and** an issue photo, so catalogue + requests + staff console + evidence + QR + scanner ship with every install. |
| **Module** | superadmin (console or CLI) | A whole capability. Installing adds its surfaces; uninstalling hides them and **keeps every row**. |
| **Feature** | Space Manager (in the console) | A switch *inside* a module, for something narrower than a whole capability. Inert while its parent module is off. |

## What "without it" actually means

Uninstalling a module does two things and nothing else:

- **The API refuses its endpoints.** Every gated view calls `require_module(makerspace, "<key>")`, which
  returns `400 {"module": "<key> is disabled for this makerspace."}`.
- **The frontend never renders the surface.** Bootstrap only publishes the workflows of installed
  modules, so the nav entry, page and buttons are simply not there.

**Your data is retained.** Uninstalling never deletes rows; reinstalling brings the surface back with its
history intact. Deleting rows is a separate, deliberate second command — see [Deleting a module's
data](#deleting-a-modules-data).

```bash
docker compose run --rm --no-deps backend --role management python manage.py list_modules
docker compose run --rm --no-deps backend --role management python manage.py install_module bookings
docker compose run --rm --no-deps backend --role management python manage.py uninstall_module bookings
```

A module another installed module depends on cannot be uninstalled until the dependant goes first, and
core modules cannot be uninstalled at all.

## Index

**Inventory** (always on): [public_inventory](#public_inventory) · [request_workflow](#request_workflow) ·
[staff_admin](#staff_admin) · [evidence_uploads](#evidence_uploads) · [qr_management](#qr_management) ·
[scanner](#scanner) · [asset_units](#asset_units) · [containers](#containers) ·
[bulk_import](#bulk_import) · [stock_transfers](#stock_transfers) ·
[qr_print_batches](#qr_print_batches) · [guest_handover](#guest_handover) · [procurement](#procurement)
**Stocktake**: [stocktake](#stocktake) — **Machines**: [machines](#machines) ·
[machine_service](#machine_service) · [printing](#printing) · [maintenance](#maintenance) —
**Events**: [events](#events) — **Bookings**: [bookings](#bookings) —
**Membership**: [membership](#membership)
**Notifications**: [notifications](#notifications) · [email](#email) · [telegram](#telegram) ·
[slack](#slack) · [mattermost](#mattermost) · [discord](#discord) — **Reports**: [reports](#reports) —
**Payments**: [payments](#payments) — **Accounts**: [member_accounts](#member_accounts) —
**Mobile apps**: [mobile](#mobile) — **Updates**: [updates](#updates)

---

## Inventory

The permanent heading. It absorbs all six core keys, so this area has no master switch — but nine of the
thirteen modules under it are optional.

### public_inventory

**Core — cannot be uninstalled.**

- **What it is** — the public browse catalogue and item detail pages at `/m/<slug>`.
- **What it adds** — the `catalog` workflow: the public product list and detail view.
- **Without it** — not an option. It is the surface the whole system exists to publish. What you *can*
  control is per item: `is_public` removes a product from the public list entirely, and
  `public_availability_mode` (`exact_count` / `status_only` / `hidden`) decides how much of its stock
  level a visitor sees. A space that wants no public catalogue publishes nothing.
- **Data** — core; not separately purgeable.

### request_workflow

**Core — cannot be uninstalled.**

- **What it is** — member hardware requests and the state machine behind them
  (`draft → pending_approval → accepted → issued → returned`).
- **What it adds** — the `request_submit` and `request_status` workflows: submitting a borrow request
  and following it, plus the staff review queue.
- **Without it** — not an option. Every handover in the system — staff issue, front-desk handout, member
  self-checkout — records itself through this workflow, and it is the only place a request's status is
  allowed to change.
- **Who may submit is set by `membership`, not by this module.** Being core, this module is present in every
  makerspace and therefore must work with `membership` uninstalled: members only when `membership` is on,
  any signed-in account when it is off, and account-less strangers only when an operator has explicitly
  opted in (`manage.py set_request_access --mode anyone`, which is refused while `membership` is installed).
  See the `membership` module below, and **Who may submit a borrow request** in `docs/INVARIANTS.md`.
- **Accept and reject are one request at a time.** There is no bulk accept or bulk reject anywhere —
  `/control/` serves a per-request review page, and Telegram alerts carry no buttons.
- **Data** — core; not separately purgeable.

### staff_admin

**Core — cannot be uninstalled.**

- **What it is** — the staff console's inventory and request administration API.
- **What it adds** — the `staff_inventory` and `staff_requests` workflows: products, categories, assets,
  the needs-fixing queue, exports and the request review screens.
- **Without it** — not an option; a space with no staff console cannot be run. Who sees what inside it is
  a **roles** question, not a module one — see the role/action matrix.
- **Data** — core; not separately purgeable.

### evidence_uploads

**Core — cannot be uninstalled.**

- **What it is** — immutable issue and return evidence photos in a private bucket.
- **What it adds** — the `evidence_uploads` workflow: presigned upload, and the photo attached to every
  issue and return.
- **Without it** — not an option: hardware cannot be issued without an issue photo, nor returned without
  a return photo and a remark. That is the accountability rule the product is built around.
- **Data** — core; not separately purgeable. Evidence rows are immutable and only ever removed when the
  whole makerspace is purged. The *object bytes* are a separate question: an optional per-makerspace
  retention policy deletes the stored image once its window passes, keeping the immutable row, the
  remarks, the QR scans and the audit trail. An expired photo then reads as a truthful expired state
  (410) rather than a broken link, so the accountability record survives the picture.

### qr_management

**Core — cannot be uninstalled.**

- **What it is** — generating, revoking and printing the QR codes for boxes, tools and asset units.
- **What it adds** — the `qr_generate`, `qr_revoke` and `qr_print` workflows, plus QR rebinding.
- **Without it** — not an option: issuing reviewed-request hardware requires a box QR scan, so a space
  with no QR codes could not complete a handover.
- **Data** — core; not separately purgeable. Scan records are immutable.

### scanner

**Core — cannot be uninstalled.**

- **What it is** — the camera scanner and the container lookup it feeds.
- **What it adds** — the `qr_scan` and `container_lookup` workflows.
- **Without it** — not an option, for the same reason as `qr_management`: no scan, no handover.
- **Data** — core; not separately purgeable.

### asset_units

- **What it is** — individually QR-tracked units of a product, so "drill #3" is a thing rather than "one
  of four drills".
- **What it adds** — per-unit QR generation and asset-level status tracking; asset units become
  selectable at issue time.
- **Without it** — products are tracked by **quantity only**. Availability maths, requests and handovers
  all still work; you simply cannot say *which* physical unit went out, and per-unit QR labels are
  unavailable.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately.

### containers

- **What it is** — the physical container hierarchy (boxes inside shelves inside rooms) and moves
  between them.
- **What it adds** — creating and listing containers, the parent/child hierarchy and container moves; a
  direct handout can resolve a scanned container into the loan.
- **Without it** — you cannot create, list or re-parent containers in the console, and a direct handout
  will not accept one. Storage location stops being modelled as a hierarchy. Scanning a box QR still
  resolves — that is [`scanner`](#scanner) — and containers that already exist keep their codes, so the
  box-scan-at-issue rule is unaffected.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately.

### bulk_import

- **What it is** — spreadsheet import of inventory rows.
- **What it adds** — the `bulk_import` workflow: upload a sheet, map columns, preview, commit.
- **Without it** — inventory is created one product at a time in the console (or through the API). The
  most common reason to install it is the first week of migrating from a spreadsheet.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately.

### stock_transfers

- **What it is** — moving stock between locations, including true movement **between makerspaces**.
- **What it adds** — the `stock_transfer` workflow: raise a transfer, its lines, and the receiving side.
- **Without it** — stock stays where it was booked in. A multi-space operator loses the only supported
  way to move quantity across a tenant boundary without editing counts by hand.
- **Data** — purgeable: transfers and their lines.

### qr_print_batches

- **What it is** — batched QR label generation as a downloadable ZIP.
- **What it adds** — the `qr_print_batch` workflow: select items or asset units, generate a sheet, keep
  the batch as a record.
- **Without it** — QR codes still exist and still print one at a time from `qr_management`; what you
  lose is generating and re-downloading a whole sheet at once.
- **Data** — purgeable: print batches and their items.

### guest_handover

- **What it is** — the narrow front-desk console: hand out an accepted request, take it back, without
  seeing the rest of the admin.
- **What it adds** — the `guest_issue` and `guest_return` workflows, and direct handouts at the counter.
- **Without it** — handovers happen in the full staff console instead. Front-desk volunteers then need a
  role with wider access than they should have, which is the reason this module exists. The handover
  **role** is a separate concept: a custom role holding the handout actions, editable per space.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately; the requests
  and evidence it produced belong to the core loan spine.

### procurement

- **What it is** — the "to buy" list and the receipts attached to it.
- **What it adds** — the `procurement` workflow: raise a to-buy item, track it, attach a receipt, and
  move a purchased item into stock.
- **Without it** — restocking is tracked outside the system. Low-stock signals still show in inventory;
  there is just nowhere in-app to record what was ordered.
- **Data** — purgeable: to-buy items and their receipts (including the uploaded receipt files).

---

## Stocktake

### stocktake

- **What it is** — scan-first stock counts and the variance they produce.
- **What it adds** — the `stocktake` workflow: open a session, scan through the shelves, review variance,
  commit the adjustment as a ledger entry.
- **Without it** — counts are corrected by editing quantities directly, with no session, no variance
  report and no audit of the count as an event.
- **Data** — purgeable: stocktake sessions, lines and ledger entries.

---

## Machines

### machines

- **What it is** — the machine registry: machines, their operators, usage and documents. Warranty
  records and consumable pools hang off it.
- **What it adds** — the Machines console, machine detail, per-machine documents and images, consumables
  and usage. `MANAGE_MACHINES` is scoped per role, so a maintainer can be narrowed to specific machines.
  A consumable pool is scoped to **either** one machine or one machine type, never both, so a filament
  colour can be shared across every printer of a type instead of being re-entered per machine. Each pool
  also carries a hex swatch for the staff console and its own public/private flag. A public pool appears
  in the public printing form as material and colour name only — never the hex value, the lot code or
  the remaining grams — and only while it is active with stock left.
- **Without it** — the whole machine side of the product disappears: no registry, no service queue
  (which needs machines to point at), no maintenance schedules, no per-machine consumables. A pure tool
  library runs exactly like this — see the `lending` profile.
- **Data** — **not separately purgeable**, and the command says why: machine rows host warranty records,
  inventory-backed consumables and service history, so deleting them piecemeal would orphan other
  modules. Purge `machine_service` first, then archive and purge the makerspace.

### machine_service

Required by `printing`.

- **What it is** — the service/job queue: a member asks for work on a machine, staff run it.
- **What it adds** — the `machine_service_requests` workflow: request intake, the staff queue, file
  uploads, consumption ledgers and the usage entries a finished job produces.
- **Without it** — machines are a registry you look at, not a queue you work. Jobs are arranged in person
  or by message; nothing records who ran what, on which machine, using how much material. `printing`
  cannot be installed while this is off.
- **Data** — purgeable: service requests, queues, uploads, consumption ledgers and the usage entries they
  produced. Consumable pools stay — they belong to `machines`.

### printing

**Requires `machine_service`** (installing `printing` pulls it in).

- **What it is** — 3D printing as a machine type on top of the service queue.
- **What it adds** — the `printing_requests` workflow: print-specific intake, print files, and the
  printer-facing view of the queue.
- **Without it** — 3D printers can still be registered as machines and their jobs run through the
  ordinary service queue; what you lose is the print-specific handling around them.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately; print jobs are
  service requests and go with `machine_service`.

### maintenance

- **What it is** — scheduled and reactive maintenance: schedules, work orders and their logs.
- **What it adds** — the `maintenance` workflow, the maintenance section of the dashboard, and log
  documents.
- **Without it** — machines have no maintenance history and nothing schedules preventive work; a broken
  machine is handled as a service request or out of band.
- **Data** — purgeable: maintenance schedules, logs and log documents (including uploaded files).

---

## Events

### events

- **What it is** — event scheduling and registration: one-off events or recurring series, registration
  with optional approval and waitlists, QR check-in at the door, post-event feedback and attendance
  certificates, and cross-makerspace collaborative events.
- **What it adds** — the events console, the public event list, member and staff-side registration,
  registration approval and waitlist promotion, QR check-in, printable attendee badges, post-event
  feedback surveys with the attendance certificates they issue, per-member calendar feeds,
  organization-hosted events, collaborators and host waivers, and attended events on the maker profile.
- **Without it** — the space runs no events in-app: no public listing, no registrations, no check-in, no
  feedback or certificates, no calendar feeds, and no attended-event history on member profiles.
  `payments.events` and `events.offline_checkin` become inert.
- **Data** — purgeable: events and series, registrations (they hold PII and are handled as such),
  check-in history, station credentials, feedback surveys and responses, attendance certificates and the
  stored PDFs they name, calendar feeds, and collaboration records. Payment routing on a registration is
  deliberately left intact, so a receipt stays readable and a charge raised later stays payable.

---

## Bookings

### bookings

- **What it is** — bookable resources and the bookings against them, including public self-booking.
- **What it adds** — bookable spaces, booking rules, the admin booking screens, the public booking page,
  and bookings in member activity.
- **Without it** — nothing in the system reserves a resource for a time slot; `payments.bookings`
  becomes inert.
- **Data** — purgeable: bookable spaces and their bookings (bookings hold PII).

---

## Membership

### membership

- **What it is** — the community layer: join requests, waivers, referrals, verification, maker profiles,
  the member directory and member activity.
- **What it adds** — the join-request queue, member capabilities and memberships in the console, the
  opt-in maker profile and directory, and per-member activity history.
- **Without it** — people can still exist as members and still borrow: staff create walk-in member
  records, and identity can come from `member_accounts` or an external OIDC provider. What goes is the
  *enrolment and community* layer — no join requests to approve, no waivers, no referrals, no profiles,
  no directory. `payments.membership` becomes inert.
- **Deliberately does not require `member_accounts`.** Identity can come from external OIDC or a staff-created
  person record, so the two are independent switches.
- **It decides who may submit a borrow request, and installing it closes account-less requests.** With this
  module on, submitting requires an active member of the makerspace. With it off, any signed-in account may
  submit — a request is only a proposal that staff must accept, and waiver acceptance cannot be recorded
  without a membership row anyway. Turning it ON therefore forces `anonymous_requests_enabled` OFF (audited,
  never silent): the account-less path bypasses the membership check entirely, so leaving both on would let
  a stranger walk past the requirement you just switched on. Turning it back off does **not** re-open
  account-less requests — that is an explicit choice, made with
  `manage.py set_request_access --mode anyone`.
- **Data** — purgeable: join requests and member profiles with their projects and imagery. Memberships,
  waivers and acceptance evidence **stay** — they are core RBAC and liability state.

---

### member_accounts

Required by `mobile`.

- **What it is** — the member-facing identity ecosystem: self sign-up, and the built-in password, social
  and phone sign-in.
- **What it adds** — member registration, the member area, Google/Apple buttons, phone + SMS login.
- **Without it** — nobody signs themselves up and the member-facing login methods go away. **Staff sign-in
  is never gated** — a space that could switch off its own staff logins could not be administered — and
  external identity (generic OIDC) plus the member-domain APIs keep working. Members are then created by
  staff as walk-in records. `mobile` cannot be installed while this is off.
- **Deployment-level reading.** Sign-up and social/phone sign-in resolve *before* a makerspace is chosen,
  so this key is read as "does any live makerspace run it", and it fails **open** on a box with no
  makerspaces yet — otherwise a fresh install could not bootstrap its first space.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately; user accounts
  are platform state.

---


## Notifications

Each channel is its own module, so a space that lives in Discord ships no Slack surface at all. Turning a
channel on never makes it start sending: you still add the webhook or token, and you still enable the
events you want in the per-feature × per-channel matrix. Turning it off stops delivery but **keeps the
stored credential**, so re-enabling needs no re-entry.

### notifications

- **What it is** — the in-app notification inbox and the emitters that feed it.
- **What it adds** — the inbox, unread state, and the emit path every other module notifies through.
- **Without it** — no in-app notifications at all; outbound channels that are installed still deliver,
  because they are gated separately.
- **Data** — purgeable: in-app notification rows.

### email

- **What it is** — outbound email **for this makerspace**.
- **What it adds** — tenant email delivery using the space's own SMTP credentials.
- **Without it** — the space sends no tenant email. **Account recovery and email verification still
  send**: those are platform mail (`makerspace=None`) and are deliberately exempt, or switching a module
  off could lock people out of their own accounts.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately.

### telegram

- **What it is** — per-makerspace Telegram group alerts. Outbound only.
- **What it adds** — the `telegram_alerts` workflow and test alerts. **No accept/reject buttons**: chat is
  a notification channel, not a decision surface, so an alert names the request and points staff at the
  console. The webhook route survives but acknowledges and discards every callback, which stops Telegram
  retrying against a deployment that already ran `setWebhook`.
- **Without it** — no Telegram alerts. Request decisions are unaffected; they are made in the staff console
  or `/control/` either way.
- **Data** — purgeable: Telegram destinations and their chat ids. Delivery logs survive — the record that
  a message was attempted is history; the credential is the secret.

### slack

- **What it is** — per-makerspace Slack alerts through an incoming webhook.
- **What it adds** — Slack as a destination in the notification matrix.
- **Without it** — no Slack surface ships at all for this space.
- **Data** — purgeable: Slack destinations and their stored webhooks (delivery logs survive).

### mattermost

- **What it is** — per-makerspace Mattermost alerts through an incoming webhook.
- **What it adds** — Mattermost as a destination in the notification matrix.
- **Without it** — no Mattermost surface ships at all for this space.
- **Data** — purgeable: Mattermost destinations and their stored webhooks (delivery logs survive).

### discord

- **What it is** — per-makerspace Discord alerts through an incoming webhook.
- **What it adds** — Discord as a destination in the notification matrix.
- **Without it** — no Discord surface ships at all for this space.
- **Data** — purgeable: Discord destinations and their stored webhooks (delivery logs survive).

---

## Reports

### reports

- **What it is** — analytics, the report registry and CSV/XLSX exports.
- **What it adds** — the `analytics` and `report_export` workflows: a server-provided report catalog,
  dashboards, accessible charts with table fallbacks, the ledger, problem reports and every registered
  report. The catalog covers every module either with a substantive report or an explicitly gated row in
  a composite operational-health report.
- **Without it** — no analytics screens and no exports from the console. It is a **standalone area
  rather than part of Inventory** on purpose: switching Inventory off would otherwise take the machine
  and event reports with it.
- **Data** — closed historical buckets are stored as append-only, non-PII metric rollups; corrections add
  a revision rather than rewriting history. Automatic evidence retention must finalize its rollup fence
  first, so it cannot change historical figures. Whole-tenant purge removes the rollups through tenant
  ownership, and an explicit source-module purge removes that module's derived rollups too.

---

## Payments

### payments

**On by default.**

- **What it is** — taking money online, through Stripe or Razorpay behind one provider seam.
- **What it adds** — the payment surfaces, charges, receipts, reconciliation and (with `mobile`) the
  in-app payment sheet.
- **Without it** — no online payment surfaces exist. Money is handled outside the system.
- **Installed ≠ charging.** The module being on means the *surfaces* exist. No charge can be created
  until a Space Manager turns on a `payments.<area>` feature **and** valid credentials resolve.
- **Data** — **payments are never purged by a module purge.** A charge is the record of money that really
  changed hands, so receipts stay readable and a pending charge stays payable, waivable and markable
  paid, keeping the description it was raised under. Only purging the whole makerspace removes them.

---

## Mobile apps

### mobile

Requires `member_accounts`.

- **What it is** — the native-app substrate: attested device sessions, native push and the in-app
  payment sheet.
- **What it adds** — device registration and revocation, push delivery (feature `mobile.push`), and
  PaymentSheet when `payments` is also on.
- **Without it** — native apps cannot hold a session for this space; the web app is unaffected.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately.

---

## Updates

### updates

**On by default.**

- **What it is** — in-app release control: check for a new version, and apply it from the console.
- **What it adds** — the superadmin update surface and `UpdateState` (current / available / target
  version).
- **Without it** — the box is updated by whatever tooling you already use (`git pull` + `docker compose
  up -d --build`, Ansible, your own pipeline). This is a **deployment-level** key like
  `member_accounts`, read
  as "does any live makerspace run it", because the update console is a single-box superadmin surface
  with no tenant to scope by.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately.

---

## Features: the level below a module

A feature is narrower than a whole module, and unlike modules these are editable by a **Space Manager**
in the console rather than a superadmin. A feature is inert while its parent module is off.

| Feature | Inside | Default | What it does | Without it |
|---|---|:--:|---|---|
| `payments.enabled` | `payments` | ● | Master switch for all online payments | Every `payments.<area>` switch below is inert |
| `payments.machines` | `machines` | | Charge for machine jobs | Machine jobs are free in-app |
| `payments.bookings` | `bookings` | | Charge for bookings | Bookings are free in-app |
| `payments.events` | `events` | | Charge for event registration | Registration is free in-app |
| `payments.membership` | `membership` | | Charge membership dues | Dues are collected out of band |
| `mobile.push` | `mobile` | ● | Native push notifications | Apps rely on in-app/inbox notifications |
| `events.offline_checkin` | `events` | | Expiring on-device roster plus event-scoped PIN check-in stations | Check-in needs a live connection and an authenticated staff actor |
| `notifications.delegated_recipients` | `notifications` | | Machine-scoped maintainers manage maintenance alert recipients for their own machines. Needs `maintenance` and `machines` too | Only makerspace-level staff manage recipients |
| `inventory.self_checkout` | — | ● | Member self-checkout and staff direct handouts | Every handover goes through a staff-issued request |
| `presence.geofence` | — | ● | Advisory location check at check-in | Check-in records no location. It is advisory either way — it never blocks |

The four `payments.<area>` switches are **off by default and stay inert until credentials resolve** —
turning one on cannot start charging anyone by itself. `inventory.self_checkout` and `presence.geofence`
belong to no module: they are standalone capabilities that apply whenever you enable them.

## Install profiles

`setup.sh` asks, or pass `--profile`. Every profile is dependency-closed and always includes the six core
modules.

| Profile | Modules | For |
|---|---|---|
| `minimal` | 6 | Core only; nothing published publicly |
| `workshop` | 14 | A machine shop: machines, service queue, maintenance — deliberately without `member_accounts` |
| `lending` | 17 | A tool library: the full lending lifecycle, no machines |
| `recommended` | 20 | Core plus the inventory lifecycle, reports and machines (the default) |
| `cloud` | 24 | A managed box: everything that runs on a single Django process, no worker or beat |
| `everything` / `full` | 32 | All modules |

**Installing without a profile** gives you **8 modules**: the six core ones plus `payments` and
`updates`. Member accounts and mobile apps are opt-in; installing `mobile` also installs its
`member_accounts` dependency.

## Deleting a module's data

Uninstalling only hides. If you also want a module's rows *gone*, that is a separate, deliberate second
step — so that no single command can both hide and destroy:

```bash
docker compose run --rm --no-deps backend --role management python manage.py purge_module_data bookings --list
docker compose run --rm --no-deps backend --role management python manage.py purge_module_data bookings --makerspace my-space
```

- **The module must already be uninstalled.** Purging an installed module is refused.
- **Superadmin only**, and it asks you to type the makerspace slug back before proceeding.
- **It cannot be undone.** Uninstall is reversible; this is not.
- **Payment records are kept** — see [`payments`](#payments).
- Uploaded files are removed after the database work commits, and your storage quota is credited back
  only for objects the bucket confirmed it deleted, so the counter can never drift below what you are
  actually storing.

A module absent from `--list` either owns no data of its own or cannot be purged separately, and the
command tells you which. [`machines`](#machines) is the notable second case.

## Removing a module from the build entirely

Uninstalling switches a module off for one makerspace; the code still ships. A deployment that will never
use an area can drop the app itself with `TOMBSTONED_APPS`, and `suggest_tombstones` reads the installed
modules and names the apps that are safe to remove. The separable apps are `warranty`, `presence`,
`payments`, `updates`, `events`, `bookings`, `maintenance` and `procurement`. That is a different axis
from modules — see **Separability and tombstoning** in `docs/INVARIANTS.md`.
