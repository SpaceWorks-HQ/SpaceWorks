# WP3 notifications and bookings

Payment failure callbacks record an attempt outcome, not a terminal ledger state.
Verified Stripe intent/async-session failures and Razorpay `payment.failed` events
claim the existing provider receipt and notify only the payer after commit. Replays
do not send again; delayed failures of settled charges do not notify.

## Delivery timing

`notifications.quiet_hours` and `notifications.digests` default off. Managers with
`MANAGE_MAKERSPACE` configure local times and affected channels under notification
timing settings. Empty channels and equal start/end times disable the quiet window.
The default clock values are 22:00–08:00 and an 08:00 daily digest. F4 resolves DST
gaps/folds; F1 owns durable delayed claims, with no second scheduling framework.

Members opt each email family into the daily digest through their preferences.
Digest release rechecks channel policy, personal opt-outs, address suppression and
account/membership standing. Each digest contains only one recipient's messages.
Batches contain at most 200 messages; additional messages receive a separate F1
claim even when the first batch is entirely suppressed. Summaries are grouped by
family and destination address so delayed SMTP delivery can recheck opt-outs,
matrix switches and account standing and emit family-specific unsubscribe headers.
Original outbox rows become skipped with `included_in_daily_digest` when the
summary is durably queued. Existing F1 handling never automatically reclaims an
uncertain delivery. In-app inbox updates remain immediate.

Never deferred: `return_reminder`, `closed_with_issue`, `series_generation_failed`,
all `ALWAYS_ON` events and every existing email-module exemption. Bounce/complaint
suppression still blocks an undeliverable address, including safety mail.
Sync-only emails whose bodies are deliberately omitted from storage also bypass
timing: delaying a private invitation or receipt grant would lose its live token.

## Signed bounce/complaint ingress

The API is `POST /api/v1/integrations/makerspace/{id}/bounce-webhook`.
A provider adapter translates its hard bounce/complaint event into:

```json
{"event_id":"provider-event-id","address":"member@example.test","reason":"bounce"}
```

`reason` accepts `bounce` or `complaint`; soft bounces are rejected. Configure a
write-only signing secret of at least 32 characters through timing settings.
Send an ASCII Unix-seconds `X-SpaceWorks-Timestamp` and a lowercase hexadecimal
`X-SpaceWorks-Signature`, computed as:

```text
HMAC-SHA256(secret, timestamp + "." + exact_raw_JSON_body)
```

The timestamp must be within five minutes. Bodies larger than 16 KiB are rejected.
Suppression is idempotent by tenant/address hash; a complaint upgrades a bounce.
Audit entries contain the suppression reason, never the address or signing secret.
Ingress remains available for configured, servable tenants when channels are off,
so an in-flight provider complaint cannot be lost after disabling notifications.
No provider-specific SDK or automatic provider webhook registration is introduced.

## Broadcasts

`membership.broadcasts` defaults off and requires membership plus notifications.
The Notifications console composer requires `MANAGE_MEMBERS`. Conditions combine
with AND: current plan, current/lapsed term and live certification. Lapsed terms
must have ended; future-only terms do not count as lapsed. A plan/lapsed campaign
can match the expired plan. Membership must remain active, notifications accepted
and the account unrestricted. One submission is capped at 2,000 recipients.

Mail uses the existing matrix and editable membership/broadcast template; chat
fan-out is disabled. Each member's own inbox stores the announcement. The member
announcement feed is paginated over that personal inbox, never a tenant-wide
notification row, and requires `notifications.member_inbox`. Live hints and polling
refresh the feed. Broadcast text participates in scoped PII encryption and exports.

## Booking changes

Member rescheduling preserves the booking ID, public token, approval state and
existing flat charge. It locks the same bookable-space row as creation, validates
opening hours and occupied buffers, checks certification and applies the current
cancellation cutoff to both the old and proposed start. It increments ICS sequence
and emits `booking.rescheduled`; confirmation/creation wording uses existing mail
templates. Automatic refunds and duration-based repricing remain deferred.

`bookings.recurring` defaults off. Staff create 2–52 finite weekly occurrences,
spaced 1–12 weeks apart with the final occurrence within 52 weeks. Local start time
is preserved across DST, with explicit conflicts for nonexistent wall times. Every
occurrence uses ordinary creation, approval, evidence-independent booking charging
and individual cancellation. Savepoints roll back a conflicted occurrence's debt
and audit, while successful occurrences survive. The response reports every slot;
there is no infinite generator or automatic conflict retry.

The private booking calendar link belongs to an authenticated account. It stores
only a SHA-256 token digest, can be rotated/revoked and rechecks active standing on
every read. Revoked memberships cannot use it. It exposes only that account's room
names/times/status, never contact fields, notes or attendees. Cancelled/rejected
reservations emit `CANCELLED`; updates increment `SEQUENCE`. Responses use
`private, no-store` and token/IP throttles. At most 1,000 events are returned, with
upcoming reservations first and recent history filling the remaining slots.

Calendar capability rows and timing/signing policy are dropped from portable tenant
artifacts. Broadcast history travels without replay; target calendar sequences reset.
The owner-only booking scope in `accounts/rbac_bookings.py` includes account-only
borrowers and refuses revoked memberships, without granting any staff authority.
WP2 owns removal of bookings' membership-module dependency. This lane adds no module
keys and does not change the event feed-token implementation.

The current tree already aggregates `payment-cash-book` by currency and settlement
method. WP3 adds registry and decimal-total regressions without replacing that code.
