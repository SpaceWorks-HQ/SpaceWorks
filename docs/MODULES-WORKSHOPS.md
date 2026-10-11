# Module reference

[Module guide and feature switches](MODULES.md)

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
  the remaining grams — and only while it is active with stock left. With the `machines.certifications`
  feature switched on, a makerspace defines certification types per machine type and issues grants to
  memberships; an uncertified member is refused when booking a linked space or requesting work, and an
  override needs machine-type authority plus a recorded, audited reason. The `certification-coverage`
  report shows trained members per type.
- **Booking limit** — machine time bookings are not available. The machine-type `requires_booking`
  flag is stored and validated but **not yet enforced**, including on the built-in laser/CNC types
  where it is true. It does not block service requests or job starts. Space bookings remain separate.
- **Without it** — the whole machine side of the product disappears: no registry, no service queue
  (which needs machines to point at), no maintenance schedules, no per-machine consumables. A pure tool
  library runs exactly like this — see the `lending` profile.
- **Data** — **not separately purgeable**, and the command says why: machine rows host warranty records,
  inventory-backed consumables and service history, so deleting them piecemeal would orphan other
  modules. Purge `machine_service` first, then archive and purge the makerspace. Certification grants
  are training evidence: a type is deactivated, never deleted, and a grant is revoked, never edited.

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

**Requires `machines`**: every schedule, log and document belongs to a machine.

- **What it is** — preventive maintenance schedules and immutable logs of completed maintenance,
  including reactive repairs. Work orders with status, assignee and priority are not available.
- **What it adds** — the `maintenance` workflow, the maintenance section of the dashboard, and log
  documents. Completing a schedule sets its next due date to the recorded completion date plus its
  interval; a late completion starts a fresh interval. Backdated logs use their recorded date.
- **Without it** — machines have no maintenance history and nothing schedules preventive work; a broken
  machine is handled as a service request or out of band.
- **Data** — purgeable: maintenance schedules, logs and log documents (including uploaded files).

---

## Events

### events

**Requires `membership`** (installing `events` pulls it in): registration needs an active member and
records the host waiver on the membership.

- **What it is** — event scheduling and registration: one-off events or recurring series, registration
  with optional approval and waitlists, QR check-in at the door, post-event feedback and attendance
  certificates, and cross-makerspace collaborative events.
- **What it adds** — the events console, the public event list, member and staff-side registration,
  registration approval and waitlist promotion, QR check-in, printable attendee badges, post-event
  feedback surveys with the attendance certificates they issue, per-member calendar feeds,
  organization-hosted events, collaborators and host waivers, and attended events on the maker profile.
- **Without it** — the space runs no events in-app: no public listing, no registrations, no check-in, no
  feedback or certificates, no calendar feeds, and no attended-event history on member profiles.
  `charges.events`, `payments.events` and `events.offline_checkin` become inert.
- **Combined with money** — a paid event (`payment_amount` > 0) records the debt when a registration
  becomes REGISTERED (at sign-up, on approval with room, or on waitlist promotion — never while pending
  or waitlisted), under `charges.events`; `payments.events` only adds the card rail. Cancelling the
  event cancels every still-pending registration charge; settled ones stay for a staff refund.
- **Data** — purgeable: events and series, registrations (they hold PII and are handled as such),
  check-in history, station credentials, feedback surveys and responses, attendance certificates and the
  stored PDFs they name, calendar feeds, and collaboration records. Payment routing on a registration is
  deliberately left intact, so a receipt stays readable and a charge raised later stays payable.

---

## Bookings

### bookings

**Requires `membership`** (installing `bookings` pulls it in): public self-booking needs an active
member with an open presence session.

- **What it is** — bookable resources and the bookings against them, including public self-booking.
- **What it adds** — bookable spaces, booking rules, the admin booking screens, the public booking page,
  and bookings in member activity.
- **Without it** — nothing in the system reserves a resource for a time slot; `charges.bookings` and
  `payments.bookings` become inert.
- **Combined with other modules** — a priced space records the debt only once a booking is CONFIRMED
  (instantly, or on approval); a space linked to a machine type is gated by `machines.certifications`
  while `machines` is installed, and books ungated once it is not.
- **Data** — purgeable: bookable spaces and their bookings (bookings hold PII).

---

## Membership

### membership

Required by `events` and `bookings`.

- **What it is** — the community layer: join requests, waivers, referrals, verification, maker profiles,
  the member directory and member activity.
- **What it adds** — the join-request queue, member capabilities and memberships in the console, the
  opt-in maker profile and directory, and per-member activity history.
  Plans and terms (monthly, yearly or custom-length, priced or free) can be attached to a membership;
  a beat-less sweep raises one renewal charge per term before it ends when `charges.membership` is on
  (and attaches an online checkout when `payments.membership` is), and an optional per-makerspace rule
  stops lapsed members from borrowing — by request, by self-checkout or by a staff handout; returning a
  tool is never refused. Prospective members can
  send an invitation request from the public site (throttled, honeypot-guarded, PII encrypted at rest);
  staff invite or decline it from the same queue as join requests.
- **Without it** — people can still exist as members and still borrow: staff create walk-in member
  records, and identity can come from `member_accounts` or an external OIDC provider. What goes is the
  *enrolment and community* layer — no join requests to approve, no referrals, no profiles, no
  directory, no member cards, no plans. Waivers stay (they are liability evidence, so publishing,
  accepting and witnessing one is core), and so do STAFF invitations, end to end: issue, claim,
  approve, decline. `payments.membership` and `charges.membership` become inert.
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
- **Member ID cards live here.** A card is a revocable QR credential over one membership (`MemberCard`),
  issued, reissued, revoked and printed by staff holding `manage_member_cards` (Space Managers by default)
  and resolvable at a scanner only by `scan_member_cards` — never through the inventory scanner, so an
  inventory-only role can never turn a QR into a person. The printed name is scoped PII, the photo is a
  private object stored only with the member's recorded consent, and revoking a card deletes the photo
  and blanks the name immediately while the redacted row, the revoked QR, the scans and the audit entries
  stay; a fresh card can then be issued. Revoking the membership revokes its card too. Cards print as one CR80 card or an A4/Letter sheet; nothing rendered is stored.
- **Data** — purgeable: join requests, member profiles with their projects and imagery, and member cards
  with their photos (their QR codes are revoked, never deleted). Memberships, waivers and acceptance
  evidence **stay** — they are core RBAC and liability state.

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


