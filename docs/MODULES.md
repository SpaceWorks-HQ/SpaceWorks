# SpaceWorks modules — what each one is, and what happens without it

Space Works ships **35 modules**: 6 **core** ones that cannot be switched off, 2 that are **on by
default** (`updates` and `backup`), and the rest opt-in. This page is the per-module reference the README links into — one entry
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
[slack](#slack) · [mattermost](#mattermost) · [discord](#discord) · [webhook](#webhook) — **Reports**: [reports](#reports) —
**Payments**: [payments](#payments) — **Accounts**: [member_accounts](#member_accounts) —
**Mobile apps**: [mobile](#mobile) · **Backup & custody**: [backup](#backup) · **Connected devices**: [devices](#devices) ·
**Updates**: [updates](#updates)

---

## Inventory

### public_inventory

[Read the public_inventory module reference](MODULES-INVENTORY.md#public_inventory).

### request_workflow

[Read the request_workflow module reference](MODULES-INVENTORY.md#request_workflow).

### staff_admin

[Read the staff_admin module reference](MODULES-INVENTORY.md#staff_admin).

### evidence_uploads

[Read the evidence_uploads module reference](MODULES-INVENTORY.md#evidence_uploads).

### qr_management

[Read the qr_management module reference](MODULES-INVENTORY.md#qr_management).

### scanner

[Read the scanner module reference](MODULES-INVENTORY.md#scanner).

### asset_units

[Read the asset_units module reference](MODULES-INVENTORY.md#asset_units).

### containers

[Read the containers module reference](MODULES-INVENTORY.md#containers).

### bulk_import

[Read the bulk_import module reference](MODULES-INVENTORY.md#bulk_import).

### stock_transfers

[Read the stock_transfers module reference](MODULES-INVENTORY.md#stock_transfers).

### qr_print_batches

[Read the qr_print_batches module reference](MODULES-INVENTORY.md#qr_print_batches).

### guest_handover

[Read the guest_handover module reference](MODULES-INVENTORY.md#guest_handover).

### procurement

[Read the procurement module reference](MODULES-INVENTORY.md#procurement).

## Stocktake

### stocktake

[Read the stocktake module reference](MODULES-INVENTORY.md#stocktake).

## Machines

### machines

[Read the machines module reference](MODULES-WORKSHOPS.md#machines).

### machine_service

[Read the machine_service module reference](MODULES-WORKSHOPS.md#machine_service).

### printing

[Read the printing module reference](MODULES-WORKSHOPS.md#printing).

### maintenance

Requires `machines`: installing maintenance also installs its machine inventory.

[Read the maintenance module reference](MODULES-WORKSHOPS.md#maintenance).

## Events

### events

[Read the events module reference](MODULES-WORKSHOPS.md#events).

## Bookings

### bookings

Bookings accepts authenticated active accounts without installing `membership`. Existing
memberships retain their waiver requirement; booking in advance never requires presence.

[Read the bookings module reference](MODULES-WORKSHOPS.md#bookings).

## Membership

### membership

[Read the membership module reference](MODULES-WORKSHOPS.md#membership).

### member_accounts

[Read the member_accounts module reference](MODULES-WORKSHOPS.md#member_accounts).

## Notifications

### notifications

[Read the notifications module reference](MODULES-PLATFORM.md#notifications).

### email

[Read the email module reference](MODULES-PLATFORM.md#email).

### telegram

[Read the telegram module reference](MODULES-PLATFORM.md#telegram).

### slack

[Read the slack module reference](MODULES-PLATFORM.md#slack).

### mattermost

[Read the mattermost module reference](MODULES-PLATFORM.md#mattermost).

### discord

[Read the discord module reference](MODULES-PLATFORM.md#discord).

### webhook

[Read the webhook module reference](MODULES-PLATFORM.md#webhook).

## Reports

### reports

[Read the reports module reference](MODULES-PLATFORM.md#reports).

| Feature | Default | What it adds |
| --- | --- | --- |
| `reports.saved_views` | ON | Personal server-side report filters and columns, with optional manager-published makerspace sharing. Opening a view rechecks both reader and owner authority. |

Membership reports add counts-only join-month cohorts and retention at 3/6/12 months (or a chosen
anniversary), plus per-currency MRR/ARR from recurring terms. Reports require `membership`;
MRR also requires `VIEW_FINANCE`. Months follow the makerspace timezone. MRR is a plan projection,
uses current prices and waiver state, and excludes custom-day plans. It is separate from collected revenue.
Scheduled reports may require non-empty rows or a numeric metric threshold before generating a file.
Role slugs and action selectors resolve eligible staff at send time, including report authority and
notification opt-out. Currency thresholds must choose a currency when the report contains several.
Delivery remains a private, expiring download link. Purging reports deletes report saved views,
schedules and delivery files; other saved staff-list views remain. Portable imports reset saved-view
state/sharing and drop schedules, so neither restores source disclosure rules.

## Payments

### payments

[Read the payments module reference](MODULES-PLATFORM.md#payments).

## Mobile apps

### mobile

[Read the mobile module reference](MODULES-PLATFORM.md#mobile).

## Backup & custody

### backup

[Read the backup module reference](MODULES-PLATFORM.md#backup).

## Connected devices

### devices

[Read the devices module reference](MODULES-PLATFORM.md#devices).

## Updates

### updates

[Read the updates module reference](MODULES-PLATFORM.md#updates).

## Features: the level below a module

A feature is narrower than a whole module, and unlike modules these are editable by a **Space Manager**
in the console rather than a superadmin. A feature is inert while its parent module is off.

| Feature | Inside | Default | What it does | Without it |
|---|---|:--:|---|---|
| `billing.documents` | standalone core ledger (mail needs `email`) | ● | Issue numbered [receipt and credit-note PDFs](payment-documents.md), with issuer settings and accounting account mappings | New collections have no document; existing documents stay readable and documented charges still receive refund/correction documents |
| `billing.reminders` | `notifications` (needs `email`) | | Email the payer about due and overdue charges using [core billing policy](payment-billing.md), including cash-only charges | No automatic payment reminders; debt and receipts stay visible |
| `charges.enabled` | — | ● | Master switch for recording money owed | The space charges for nothing: no debt is recorded in any area |
| `charges.machines` | `machines` (needs `machine_service`) | ● | Record a charge when a priced machine job completes | Machine jobs are free |
| `charges.bookings` | `bookings` | ● | Record a charge when a paid booking is confirmed | Bookings are free |
| `charges.events` | `events` | ● | Record a charge when a registration for a paid event is confirmed | Registration is free |
| `charges.membership` | `membership` | ● | Record dues and renewal charges | Dues are not recorded |
| `membership.auto_renew` | `membership` | | Open the next term after renewal settlement, with plan timing/retries/grace | Manual renewal terms remain available |
| `membership.lifecycle_mail` | `membership` | | Send renewal lifecycle mail to the member | No automated lifecycle mail |
| `membership.self_service` | `membership` | | Edit own contact fields, revoke sessions and cancel/leave | Staff manage membership changes |
| `membership.self_export` | `membership` | | Request a private personal ZIP/JSON export | No member export surface |
| `charges.loans` | `request_workflow` | ● | Record loan deposits and late fees (amounts are set in payment settings) | Lateness is recorded but never charged |
| `loans.enabled` | `staff_admin` | On | Public loan catalogue, borrow submission and staff loan consoles; disabling preserves core and data | Loan surfaces are hidden and new public borrowing is refused |
| `payments.enabled` | `payments` | ● | Master switch for all online payments | Every `payments.<area>` switch below is inert |
| `payments.machines` | `machines` | | Card rail for machine-job charges | Charges are still recorded and settled offline |
| `payments.bookings` | `bookings` | | Card rail for booking charges | Charges are still recorded and settled offline |
| `payments.events` | `events` | | Card rail for event charges | Charges are still recorded and settled offline |
| `payments.membership` | `membership` | | Card rail for dues | Dues are still recorded and settled offline |
| `payments.loans` | `payments` | | Card rail for loan deposits and late fees | Loan charges are still recorded and settled offline |
| `mobile.push` | `mobile` | ● | Native push notifications | Apps rely on in-app/inbox notifications |
| `events.offline_checkin` | `events` | | Expiring on-device roster plus event-scoped PIN check-in stations | Check-in needs a live connection and an authenticated staff actor |
| `machines.certifications` | `machines` | | Members need an unexpired certification per machine type to book a linked space or request work; overrides need machine-type authority and are audited | Training is tracked out of band; nothing gates a request or booking |
| `notifications.delegated_recipients` | `notifications` | | Machine-scoped maintainers manage maintenance alert recipients for their own machines. Needs `maintenance` and `machines` too | Only makerspace-level staff manage recipients |
| `inventory.self_checkout` | — | ● | Member self-checkout and staff direct handouts | Every handover goes through a staff-issued request |
| `presence.geofence` | — | ● | Advisory location check at check-in | Check-in records no location. It is advisory either way — it never blocks |
| `inventory.kiosk` | — | | Scanner and handover Stations at `/m/<slug>/kiosk/<station>`: a Station PIN opens the channel, and a signed-in staff operator lease attributes every online handover to a real person | No Station sessions, operator leases, work packages or kiosk commands; the public desk at `/kiosk/<slug>` is unaffected |

The `payments.<area>` switches are **off by default and stay inert until credentials resolve** —
turning one on cannot start charging anyone by itself. They only put a card rail behind a debt the
matching `charges.<area>` switch records: with `charges.<area>` off, turning `payments.<area>` on records
nothing and offers nothing (the two are deliberately independent switches, the A6 rule). `inventory.self_checkout` and `presence.geofence`
belong to no module: they are standalone capabilities that apply whenever you enable them.

## Editions

[Read about editions](MODULES-LIFECYCLE.md#editions).

## Install profiles

[Read about install profiles](MODULES-LIFECYCLE.md#install-profiles).

## Deleting a module's data

[Read about deleting a module's data](MODULES-LIFECYCLE.md#deleting-a-modules-data).

## Removing a module from the build entirely

[Read about removing a module from the build entirely](MODULES-LIFECYCLE.md#removing-a-module-from-the-build-entirely).
