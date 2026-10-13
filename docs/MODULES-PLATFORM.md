# Module reference

[Module guide and feature switches](MODULES.md)

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

### webhook

- **What it is** — per-makerspace **signed JSON webhooks** to systems of your own (an ERP, a Slack bot you
  wrote, a spreadsheet bridge). Not a chat room, but it sits in the same matrix: a webhook destination
  receives exactly the notification a room would, as JSON, signed with a per-destination secret.
- **What it adds** — `webhook` as a destination channel in the notification matrix, with an HTTPS endpoint
  and a signing secret per destination; `X-SpaceWorks-Signature: t=<unix>,v1=<hex>` is HMAC-SHA256 over
  `"<t>.<body>"`, plus `X-SpaceWorks-Event` and `X-SpaceWorks-Delivery` headers. Retries and the durable
  delivery log are the ones every non-email channel already has; a superadmin can re-queue failed
  deliveries from `/control/`. Verification recipe: `docs/api-client-protocol.md` → "Outbound webhooks".
- **Without it** — no signed-webhook surface ships for this space. The inbound API-client protocol is
  unaffected; other systems poll instead of being told.
- **Data** — purgeable: webhook destinations with their endpoint URLs and signing secrets (delivery logs
  survive). Endpoint URLs are validated against private and loopback ranges when saved and re-resolved at
  send time, like every other webhook channel.

---

## Reports

### reports

- **What it is** — analytics, the report registry and CSV/XLSX exports.
- **What it adds** — the `analytics` and `report_export` workflows: a server-provided report catalog,
  dashboards, accessible charts with table fallbacks, the ledger, problem reports and every registered
  report. The catalog covers every module either with a substantive report or an explicitly gated row in
  a composite operational-health report. Every CSV/XLSX export carries provenance (who generated it,
  when, for which makerspace, which report version and filters) as the first CSV line or a `Provenance`
  sheet, and staff can schedule a report to be delivered daily, weekly or monthly to a notification
  destination or a list of email recipients as a short-lived signed download link.
  Counts-only membership cohorts and recurring-plan MRR/ARR use local months and require
  `membership`; MRR requires `VIEW_FINANCE`. Server report views save filters and columns,
  with manager-authorized sharing. Schedules can require non-empty rows or a metric
  threshold, and role/action recipients resolve current authority at send time.
- **Without it** — no analytics screens, no exports and no scheduled deliveries from the console. It is a **standalone area
  rather than part of Inventory** on purpose: switching Inventory off would otherwise take the machine
  and event reports with it.
- **Data** — closed historical buckets are stored as append-only, non-PII metric rollups; corrections add
  a revision rather than rewriting history. Automatic evidence retention must finalize its rollup fence
  first, so it cannot change historical figures. Whole-tenant purge removes the rollups through tenant
  ownership, and an explicit source-module purge removes that module's derived rollups too. Purging
  `reports` deletes saved report views, schedules and their delivered files (private objects);
  other staff-list preferences and the rollups stay.

---

## Payments

### payments

**Opt-in.** It was on by default until charge *tracking* moved out from under it: a space that takes
cash needs none of this module and still keeps a full ledger of what members owe.

- **What it is** — taking money **online**, through Stripe or Razorpay behind one provider seam.
- **What it adds** — the online rail: checkout, Connect, webhooks, refunds (full or partial, through
  the same provider seam, as ledger lines that never edit the charge) and (with `mobile`) the in-app
  payment sheet. With `payments.loans` on, a loan deposit and a capped late fee can be collected
  online too.
- **Without it** — money owed is still tracked, listed and reported: the `charges.*` features raise
  the charge, members see what they owe, and staff settle it in person and record how (cash, UPI,
  bank transfer, card machine, cheque) in the append-only manual-settlement ledger. What disappears
  is only the ability to pay by card online.
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

## Backup & custody

### backup

**On by default** (and backfilled onto every existing makerspace by `backup/0026`, because the key was
placed in front of surfaces every makerspace already had).

- **What it is** — the makerspace-facing half of backup: a Space Manager's own archives and the keys
  that decide who can open them.
- **What it adds** — requesting, listing and downloading makerspace archives; enrolling, verifying,
  revoking and reactivating archive-recipient `age` keys; and a read-only custody status (archive
  custody and tenant-exit custody) at `makerspace/<id>/backup-custody`.
- **Without it** — those routes answer **400** naming `backup`. What it does **not** switch off:
  **marking a recipient compromised** (security response never waits on a module), and everything
  deployment-level — the full deployment backup, its scheduled run (which still builds the per-tenant
  archive of a superadmin-off makerspace), restores, recovery and offsite destinations all cover this
  makerspace exactly as before.
- **Coupled to superadmin access** — recipients are the only custody path for a makerspace whose
  superadmin access is off, so `backup` **cannot be uninstalled while superadmin access is disabled**,
  and superadmin access **cannot be disabled while `backup` is uninstalled**.
- **Data** — `purge_module_data backup` deletes only the archives a Space Manager requested ad hoc
  (finished ones, never one a restore references) and their stored bytes. It keeps archive
  recipients and their reservations (sealed deployment slices are encrypted to them), custody state
  and alarm history, run-produced tenant archives and offsite copies — those are the deployment's
  backup of this makerspace. **Archives are outside the purge guarantee**: a copy someone already
  downloaded, a deployment archive and an offsite copy are not deleted by any purge.

## Connected devices

### devices

Opt-in, no dependencies; installed only by the `full`/`everything` profiles.

- **What it is** — device identity for printers and label printers on the space's own network. A
  device is **not** a staff account: it holds an Ed25519 key, proves possession of it once at
  enrollment, and then signs every request (protocol in `docs/device-protocol.md`).
- **What it adds** — staff device enrollment, rename, offline threshold, key rotation and revocation,
  plus signed heartbeats. With `machines` and `machine_service` installed, staff holding
  `MANAGE_DEVICES` and management scope for the selected machine can bind a printer and create a
  command for its explicitly assigned in-progress request. Bounded delivery leases become durable
  ownership after acknowledgement. Measurements pass through the existing completion/failure workflow.
  Automatic application defaults off; scoped staff approval supplies the approving User. Charges use
  current machine pricing, and failed jobs create no charge. Telemetry affects staff display only.
  Every mutation leaves typed device provenance and an audit row. The server wire contract is in
  [Printer protocol](device-printer-protocol.md).
- **Without it** — device routes answer 400 and cannot enroll, authenticate or mutate. Printer routes
  additionally require both machine modules and answer 400 when either is off. Tombstoning the devices
  app removes its routes with 404.
- **Data** — `purge_module_data devices` deletes printer consumption claims, jobs, commands and
  bindings, then replay nonces, enrollments, device events and identities. Machine workflows and the
  payment ledger survive. Purging a machine adapter nulls live printer links and retains history;
  missing targets cannot deliver or finish. Tenant moves retain applied reports and source snapshots,
  disable bindings and automatic application, cancel commands, clear delivery credentials and turn
  unprocessed work into inert review. Device keys, enrollments and nonces never travel.

- **Monitoring** - both scheduler topologies check offline state once a minute. Offline/recovery
  history appears in module operational health. Device alerts have their own notification feature;
  every channel is opt-in and initially off. The Devices console exposes identity/status/enrollment
  to device managers. Printer jobs and label delivery controls arrive with their adapter lanes.

---
