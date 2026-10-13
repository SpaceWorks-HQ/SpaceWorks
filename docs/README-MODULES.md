## Modules

A makerspace only carries the parts it uses. Space Works ships **32 modules**; **6 are core** and
always on (the public catalogue, request workflow, staff admin, evidence uploads, QR management and
the scanner). The rest are **opt-in**.

Core is not negotiable because the hardware-handover rules depend on it: issuing a tool requires a box
QR scan *and* a photo, so a machines-only workshop still carries the request/QR/evidence spine.

Per-module detail — what each key is and what you lose without it — is in
[**docs/MODULES.md**](MODULES.md).

You do not have to think in 32 switches. They are grouped into **twelve areas**, which is what the
console shows you:

| Area | Covers |
|---|---|
| **Inventory** *(always on)* | The catalogue, request workflow, QR/evidence spine, asset units, containers, transfers, QR print batches, front-desk handover and purchasing |
| **Stocktake** | Scan-first stock counts and variance reporting |
| **Machines** | Machine registry, the service/print queue, maintenance and warranty |
| **Events** | Event scheduling and registrations — recurring series, approval and waitlists, QR check-in at the door, post-event feedback and attendance certificates, member calendar feeds, printable attendee badges, and cross-makerspace collaborative events |
| **Bookings** | Resource booking and public self-booking |
| **Membership** | Join requests, waivers, referrals, member activity, maker profiles, presence — and the member-facing identity ecosystem |
| **Notifications** | The in-app inbox and every outbound channel |
| **Reports** | Analytics, the report registry and CSV/XLSX exports |
| **Payments** | Taking money online, through Stripe or Razorpay |
| **Mobile apps** | Attested device sessions, native push and the in-app payment sheet |

**Pick modules at install time** — `setup.sh` reads the live registry and opens a tick list. Its initial
recommended state corresponds to this profile table; management commands can also pass `--profile`:

| Profile | Modules | For |
|---|---|---|
| `minimal` | 6 | Core only; nothing published publicly |
| `workshop` | 14 | A machine shop: machines, service queue, maintenance |
| `lending` | 17 | A tool library: the full lending lifecycle, no machines |
| `recommended` | 20 | Core plus the inventory lifecycle, reports and machines |
| `cloud` | 25 | A managed box: everything a hosted deployment runs |
| `everything` / `full` | 34 | All modules |

**Change it later.** Uninstalling clears the capability and hides the surfaces; **your data is always
retained** and reinstalling brings it back:

```bash
docker compose run --rm --no-deps backend --role management python manage.py list_modules
docker compose run --rm --no-deps backend --role management python manage.py install_module bookings
docker compose run --rm --no-deps backend --role management python manage.py uninstall_module bookings
```

Core modules cannot be uninstalled, nor can one another installed module depends on.

### Deleting a module's data

Uninstalling only hides. If you also want a module's rows *gone*, that is a separate, deliberate
second step — so that no single command can both hide and destroy:

```bash
docker compose run --rm --no-deps backend --role management python manage.py purge_module_data bookings --list
docker compose run --rm --no-deps backend --role management python manage.py purge_module_data bookings --makerspace my-space
```

- **The module must already be uninstalled.** Purging an installed module is refused.
- **Superadmin only**, and it asks you to type the makerspace slug back before proceeding.
- **It cannot be undone.** Uninstall is reversible; this is not.
- **Payment records are kept.** Switching a module off and deleting its rows is not a reason to
  destroy the record of money that really changed hands, so receipts stay visible and a pending
  charge stays payable and can still be marked paid or waived. Each charge keeps the description it
  was raised under, so it still reads sensibly once the booking or event behind it is gone. Deleting
  a whole makerspace is the exception — there, its payments go with it.
- Uploaded files are removed after the database work commits, and your storage quota is credited
  back only for objects the bucket confirmed it deleted — a failed delete credits nothing, so the
  counter can never drift below what you are actually storing.

A module absent from the list either owns no data of its own or cannot be purged separately, and
the command tells you which. `machines` is the notable second case: machine rows host warranty
records, consumables and service history, so purge `machine_service` first.

### Every module, by area

The full list, so you can see exactly what a profile is turning on. **Core** is always present and
cannot be removed. **Default** means it is on when you install without choosing a profile.

| Area | Module | Core | Default | What it adds |
|---|---|:--:|:--:|---|
| **Inventory** | [`public_inventory`](MODULES.md#public_inventory) | ● | ● | The public catalogue |
| | [`request_workflow`](MODULES.md#request_workflow) | ● | ● | Borrow requests and the state machine |
| | [`staff_admin`](MODULES.md#staff_admin) | ● | ● | The staff console |
| | [`evidence_uploads`](MODULES.md#evidence_uploads) | ● | ● | Issue/return photos |
| | [`qr_management`](MODULES.md#qr_management) | ● | ● | QR codes for boxes, tools and assets |
| | [`scanner`](MODULES.md#scanner) | ● | ● | The camera scanner |
| | [`asset_units`](MODULES.md#asset_units) | | | Individually tracked units of a product |
| | [`containers`](MODULES.md#containers) | | | Boxes and storage containers |
| | [`bulk_import`](MODULES.md#bulk_import) | | | Spreadsheet import |
| | [`stock_transfers`](MODULES.md#stock_transfers) | | | Moving stock, including between makerspaces |
| | [`qr_print_batches`](MODULES.md#qr_print_batches) | | | Printable QR sheets and ZIP export |
| | [`guest_handover`](MODULES.md#guest_handover) | | | Front-desk direct handouts |
| | [`procurement`](MODULES.md#procurement) | | | The "to buy" list |
| **Stocktake** | [`stocktake`](MODULES.md#stocktake) | | | Scan-first stock counts and variance |
| **Machines** | [`machines`](MODULES.md#machines) | | | The machine registry |
| | [`machine_service`](MODULES.md#machine_service) | | | The service/job queue |
| | [`printing`](MODULES.md#printing) | | | 3D printing on top of `machine_service` |
| | [`maintenance`](MODULES.md#maintenance) | | | Scheduled and reactive maintenance |
| **Events** | [`events`](MODULES.md#events) | | | Scheduling, recurring series, registrations and waitlists, QR check-in, feedback and certificates, collaborative events |
| **Bookings** | [`bookings`](MODULES.md#bookings) | | | Resource booking and public self-booking |
| **Membership** | [`membership`](MODULES.md#membership) | | | Join requests, waivers, referrals, maker profiles |
| | [`member_accounts`](MODULES.md#member_accounts) | | | Member sign-up and member sign-in |
| **Notifications** | [`notifications`](MODULES.md#notifications) | | | The in-app inbox |
| | [`email`](MODULES.md#email) | | | Outbound email |
| | [`telegram`](MODULES.md#telegram) | | | Telegram group alerts (outbound only) |
| | [`slack`](MODULES.md#slack) | | | Slack alerts |
| | [`mattermost`](MODULES.md#mattermost) | | | Mattermost alerts |
| | [`discord`](MODULES.md#discord) | | | Discord alerts |
| | [`webhook`](MODULES.md#webhook) | | | Signed JSON webhooks to your own systems |
| **Reports** | [`reports`](MODULES.md#reports) | | | Analytics, the ledger and CSV/XLSX export |
| **Payments** | [`payments`](MODULES.md#payments) | | ● | Taking money online (Stripe or Razorpay) |
| **Mobile apps** | [`mobile`](MODULES.md#mobile) | | | Attested device sessions, native push, payment sheet |

`mobile` requires `member_accounts`; `printing` requires `machine_service`; `maintenance` requires
`machines`. Bookings accepts active accounts and does not require `membership`. Installing one pulls in
what it needs. `membership` deliberately does **not** require `member_accounts` — identity can come
from an external identity provider or a staff-created walk-in record instead.

**Every module has a page.** [**docs/MODULES.md**](MODULES.md) covers each of the 34 keys in turn:
what it is, what it puts on screen, **what happens if you do not install it**, and what becomes of its
data if you later purge it.

### Features: the second level

Some capabilities are narrower than a whole module, so they are **features** inside one. A feature
is only effective when its parent module is on, and unlike modules these are editable by a **Space
Manager** in the console rather than a superadmin.

| Feature | Inside | Default | What it does |
|---|---|:--:|---|
| `loans.enabled` | `staff_admin` | On | Per-space loan catalogue, borrowing and loan consoles; core and data stay installed |
| `payments.enabled` | `payments` | ● | Master switch for all online payments |
| `payments.machines` | `machines` | | Charge for machine jobs |
| `payments.bookings` | `bookings` | | Charge for bookings |
| `payments.events` | `events` | | Charge for event registration |
| `payments.membership` | `membership` | | Charge membership dues |
| `payments.loans` | `payments` | | Raise a deposit when a loan is issued and a capped late fee when it comes back late |
| `mobile.push` | `mobile` | ● | Native push notifications |
| `events.offline_checkin` | `events` | | Expiring on-device roster and event-scoped PIN check-in stations |
| `machines.certifications` | `machines` | | Members need an unexpired certification per machine type to book a linked space or request work; overrides need machine-type authority and are audited |
| `notifications.delegated_recipients` | `notifications` | | Machine-scoped maintainers manage maintenance recipients for their own machines (also needs `maintenance` and `machines`) |
| `inventory.self_checkout` | — | ● | Member self-checkout and staff direct handouts |
| `presence.geofence` | — | ● | Advisory location check at check-in (never blocks) |

The four `payments.<area>` switches are **off by default and stay inert until you add credentials** —
turning one on cannot start charging anyone by itself. `inventory.self_checkout` and
`presence.geofence` belong to no module: they are standalone capabilities that apply whenever you
enable them.

### What you get if you choose nothing

Installing without a profile gives you **7 modules**: the six core ones plus `backup`.
Member accounts and mobile apps are opt-in; mobile pulls in `member_accounts` when installed.

Everything money-related is still dormant: `payments` being installed means the *surfaces* exist,
and no charge can be created until a Space Manager enables a `payments.<area>` feature **and** valid
Stripe or Razorpay credentials resolve. The same is true of push (needs FCM/APNs), every chat channel
(needs a webhook) and every sign-in method beyond username/password.

### Notification channels are modules

`email`, `telegram`, `slack`, `mattermost`, `discord` and `webhook` are each a module, so a space that lives in
Discord ships no Slack surface at all. Turning a channel's module on never makes it start sending on
its own — you still add the webhook or token, and you still enable the events you want in the
per-feature × per-channel matrix. Turning it off stops delivery but **keeps the stored credential**,
so re-enabling needs no re-entry.

Chat channels are configured **per makerspace** (the space owns the channel and pays for it). Sign-in
providers are the opposite — they resolve before a makerspace is chosen, so they are configured once
for the whole deployment.

### Running without member accounts

Turning **Member accounts** off removes the member-account *ecosystem*: nobody signs themselves up, and the
member area, phone sign-in and the built-in Google/Apple buttons all go with it. It does **not** remove
identity, and it never touches staff sign-in — a deployment that could switch off its own staff logins
could not be administered.

People still get named, two ways:

- **Your own identity provider.** A configured OIDC provider (Keycloak, Authentik, Azure AD, Okta,
  Google Workspace) keeps working, because it is your institution's directory rather than an account
  ecosystem this deployment runs.
- **Walk-ins.** Front-desk staff add someone at the counter from the handout screen. That creates a
  person record — a name, optionally an email and phone — with **no password and no way to sign in**.
  It is enough to issue them a tool, register them for an event or run a machine job for them, and it
  keeps every handover attributable to a real person, which the hardware rules require.

#### Who may ask to borrow something

Borrow requests are only ever a *proposal* — staff still accept them, and staff acceptance is what
reserves stock — so who may submit one is a separate switch from who may sign in. There are three
states, and you never set them both:

| Member accounts | Account-less requests | Who may submit |
| --- | --- | --- |
| on | off | **Members** — an active member of that makerspace |
| off | off | **Account holders** — anyone signed in (the default without the module) |
| off | **on** | **Anyone** — no account at all |

The last row is opt-in per makerspace, and turning **Member accounts** on turns it back off: enabling
membership means asking for membership, so a stranger must not still walk past it. Account-less
submissions ask for a name, email and phone, require an `Idempotency-Key`, and are rate-limited per IP
and per email address; every one of them is recorded against a single shared requester principal, which
is deliberately excluded from every per-person ranking so a hundred strangers never add up to one
fictional "top borrower". `setup.sh` asks this question during first-run setup, and it can be changed
later with `manage.py set_request_access`.

### Choosing which ways in you offer

**`/control/` → Platform login methods** switches the four credential kinds independently: password,
identity provider, phone code, and self sign-up. All four are on by default and switching one off
never deletes anything, so turning it back on needs no re-entry.

Each switch covers **every** way in of that kind, not just the obvious one. Turning passwords off
also refuses a mobile app's device login, which would otherwise mint a long-lived session from the
same password. Turning self sign-up off also stops an identity provider from creating a brand-new
account — signing in on an already-linked account, and linking a provider to an account you already
have, both keep working, because neither is a registration.

Existing sessions are deliberately **not** revoked: a login-method switch is a policy change, not a
revocation. Use the restrict/suspend flow to end someone's access.

Two changes are refused rather than performed, because they cannot be undone from inside the app:
switching off a method that is somebody's *only* credential (they have no password to reset, so
forgot-password cannot rescue them), and switching off passwords while no superadmin has a linked
provider — this page would then be unreachable.

### Rooms: sending different alerts to different places

A chat channel can have more than one **room** — a Slack channel, a Discord channel, a Telegram group.
Add them under **Settings → Notification channels → Rooms**. A room with nothing selected receives
everything; narrow one to a machine, a machine type or an inventory category and it receives only
those alerts. "All the 3D printers, plus the laser" needs no extra concept — the selections are a
union.

Two things worth knowing before you set this up:

- **Webhook URLs are write-only.** They are stored encrypted and never shown again, so an edit that
  only renames a room can leave the field blank.
- **Telegram rooms share the makerspace's bot** — add the same bot to each group and paste each
  group's chat ID. Delivery is outbound only: chat is not a decision surface, so no alert carries
  accept/reject buttons and decisions are made in the staff console or `/control/`.

A makerspace that has added no rooms keeps using the single webhook under **Chat webhooks**, exactly
as before. Nothing changes until you add your first room.

### Choosing who hears about what

By default every alert goes to everyone whose role covers it — a booking alert reaches whoever can
manage bookings. Under **Settings → Notification channels → Who gets notified** you can override that
per event, for events, bookings, maintenance and members. A recipient can be:

| Recipient | Means |
|---|---|
| A role | Everyone currently holding that role |
| A named member | One person, who must be a member of this makerspace |
| All members | The whole membership |
| The person it is about | The requester, booker or registrant |

**Leaving an event empty is the default, not silence** — remove every recipient and it goes back to
notifying by role. A member who has switched their own notifications off is never mailed, even when
somebody selects them.

Recipients can be narrowed by machine or category the same way rooms are, and the narrowing can only
ever *reduce* who is notified: a person is never alerted about a machine their role cannot see.

### Editing the wording

**Settings → Email templates** covers hardware, printing, events, bookings, maintenance and
membership, for both the member-facing and staff-facing message. Each template lists the variables it
can use and previews against sample data, and a saved template can be reset to the built-in wording at
any time. Chat messages have one editable body per event, shared by all four chat channels — so you
edit the wording once rather than four times.

Chat rooms only ever receive the **staff** wording. Member-facing text ("your booking is confirmed")
goes to email and to the member's phone, never into a shared room where everyone with channel access
would see that member's name.

### Removing a module from the build entirely

Uninstalling is per makerspace. A deployment that will *never* use an area can drop its code surfaces
too — no routes, no admin, no OpenAPI paths — while keeping every row and migration:

```bash
docker compose run --rm --no-deps backend --role management python manage.py suggest_tombstones   # prints the line to paste
```

Add the result to `.env` as `TOMBSTONED_APPS=`. It is deliberately conservative: an app is only
suggested when **no** makerspace on the deployment uses any of its modules.

