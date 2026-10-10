# Editions and module lifecycle

[Module guide and feature switches](MODULES.md)

## Editions

A deployment has one **edition**, set by `SPACEWORKS_EDITION` (setup asks; default `makerspace`). It answers
"what is this box for" one level above modules: the six core modules are the hardware loan spine and cannot
be uninstalled, so an events-only or bookings-only installation would otherwise still show a catalogue, a
borrow flow and a scanner it never uses. The edition **hides** those surfaces and makes their public routes
answer 404; it does not delete tables, endpoints or data, and every staff endpoint keeps answering so data
stays recoverable. Frontend bootstrap payloads carry `edition`, and edition-hidden module keys are already
removed from the `modules` list they return, so the console's tabs and the public site's routes need no
separate switch.

| Edition | Hidden module keys | Public home |
|---|---|---|
| `makerspace` (default) | none | the catalogue |
| `events` | `public_inventory request_workflow scanner asset_units containers bulk_import stock_transfers qr_print_batches guest_handover procurement stocktake machines machine_service printing maintenance bookings` | the events page |
| `bookings` | the same set with `bookings` visible and `events` hidden | the bookings page |
| `organization` | none — a labelling edition: one makerspace row is presented as "the organization" (`branding.display_name`) | the catalogue |

`Event.makerspace` stays the tenancy anchor in every edition (locked 2026-08-19); an organization-first
install is one `Makerspace` row with an organization label, never a re-anchoring. Turning an edition into a
genuinely smaller schema (removing the loan apps) is the separate `TOMBSTONED_APPS` axis and a future
"Option A"; see `docs/INVARIANTS.md` → Editions.

## Install profiles

`setup.sh` asks, or pass `--profile`. Every profile is dependency-closed and always includes the six core
modules.

| Profile | Modules | For |
|---|---|---|
| `minimal` | 6 | Core only; nothing published publicly |
| `workshop` | 15 | A machine shop: machines, service queue, maintenance — deliberately without `member_accounts` |
| `lending` | 18 | A tool library: the full lending lifecycle, no machines |
| `recommended` | 21 | Core plus the inventory lifecycle, reports and machines (the default) |
| `cloud` | 25 | A managed box: everything that runs on a single Django process, no worker or beat |
| `everything` / `full` | 35 | All modules |
| `events` | 13 | An events programme: events, notifications, email, member accounts, membership, payments, reports (core is present but hidden by the `events` edition) |
| `bookings` | 13 | Bookable rooms and resources: bookings, notifications, email, member accounts, membership, payments, reports (core hidden by the `bookings` edition) |

**Installing without a profile** gives you **8 modules**: the six core ones plus `updates` and
`backup`. Member accounts and mobile apps are opt-in; installing `mobile` also installs its
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
- **Payment records are kept** — see [`payments`](MODULES.md#payments).
- Uploaded files are removed after the database work commits, and your storage quota is credited back
  only for objects the bucket confirmed it deleted, so the counter can never drift below what you are
  actually storing.

A module absent from `--list` either owns no data of its own or cannot be purged separately, and the
command tells you which. [`machines`](MODULES.md#machines) is the notable second case.

## Removing a module from the build entirely

Uninstalling switches a module off for one makerspace; the code still ships. A deployment that will never
use an area can drop the app itself with `TOMBSTONED_APPS`, and `suggest_tombstones` reads the installed
modules and names the apps that are safe to remove. The separable apps are `warranty`, `presence`,
`payments`, `updates`, `events`, `bookings`, `maintenance`, `procurement`, `notifications`,
`tenant_migration` and `devices`. That is a different axis
from modules — see **Separability and tombstoning** in `docs/INVARIANTS.md`.
