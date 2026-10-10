# Personal notifications and delivery controls

The legacy `notifications.Notification` remains a makerspace-wide feed with its existing
shared read state. Personal inboxes use `NotificationInboxRow`, keyed by makerspace,
User and lifecycle event UUID. Reading one inbox never acknowledges another person's
message or a legacy row. The member dashboard's existing derived notices remain intact.

## Gates and recipients

Install the existing `notifications` module for staff inboxes. The matrix has an `in_app`
channel, on by default except hardware/printing, whose existing direct staff alerts are
mirrored while their matrix channel remains opt-in. Member delivery additionally requires
`notifications.member_inbox`; its default is off. The preference editor requires
`notifications.member_preferences`, also off by default. No new module is introduced.

Staff recipients use the existing action, explicit recipient selection and machine scope
resolver. Member recipients come from explicit authenticated domain-owner User IDs,
never submitted email/phone fields. Active account-only borrowers can read rows addressed
to them. Revoked memberships, restricted/inactive accounts and unavailable tenants cannot.
When an owner is also staff, their own summary wins and one event produces one row.
Requester selections, blanket member opt-outs and booking requester switches apply to
inbox delivery too. Explicit inbox summaries take precedence over email fallbacks, so
mail-only status tokens need not become inbox content. Printing and API-access inboxes
also work without an email address. Links reject controls, backslashes and external origins.
Member summaries are built independently of staff chat text; no email address is needed
for inbox delivery. Legacy-only staff alerts are mirrored for the old feed's eligible
staff audience; matrix-backed request/printing alerts are not mirrored a second time.

Titles and summaries use the existing scoped PII encryption boundary. Links are local
application paths. A private User SSE hint carries no text; clients refetch through the
scoped API. Personal TanStack query keys include recipient ID as well as makerspace
and surface, preventing cached inbox/preferences from crossing account switches. Inbox rows are snapshots; later staff-role changes do not rewrite history.

## API

Paths below are relative to `/api/v1`; lists use `{count,next,previous,results}` and 24 rows.
All personal authenticated routes constrain rows to the current User and makerspace.
Module/feature-off responses are 400, denied access is 403, foreign row IDs are 404.
Writes emit audit entries with a User actor.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/notifications/inbox/{makerspace_id}` | Personal inbox; `unread`, `feature`, `page` filters |
| GET | `/notifications/inbox/{makerspace_id}/unread-count` | Own unread count |
| POST | `/notifications/inbox/{makerspace_id}/{id}/read` | Idempotent acknowledgement |
| POST | `/notifications/inbox/{makerspace_id}/read-all` | Own unread rows only |
| GET/PATCH | `/notifications/preferences/{makerspace_id}` | Family/channel cells; PATCH `{feature,channel,enabled}` |
| POST | `/notifications/unsubscribe/{token}` | Signed, login-free one-click email opt-out |
| GET | `/integrations/makerspace/{makerspace_id}/delivery-logs` | Staff unified email/channel history |
| POST | `/integrations/makerspace/{makerspace_id}/delivery-logs/{kind}/{id}/retry` | Failed row retry; `{generation}` |
| POST | `/integrations/makerspace/{makerspace_id}/delivery-test` | Email to current User; optional `{destination_id}` tests an explicitly selected room |
| GET/POST | `/integrations/makerspace/{makerspace_id}/email-suppressions` | List hashes or add `{address,reason}` |
| DELETE | `/integrations/makerspace/{makerspace_id}/email-suppressions/{id}` | Remove a scoped suppression |

Delivery controls require `MANAGE_MAKERSPACE`, including delegated custom roles.
Log filters: `channel`, `status`, `feature`, `event`, `destination`, `page`. Responses
exclude rendered bodies, addresses, credentials and destination URLs. Retry locks the
row, checks the submitted generation, advances it once and enqueues after commit. A
repeated request with the old generation cannot enqueue again even if enqueue failed.
Workers still provide at-least-once transport: a crash after provider acceptance and
before SENT commits can resend. Send-test cannot name an arbitrary email recipient.

## Preferences and deliverability

Personal opt-outs are checked both when mail is queued and immediately before send.
They cannot turn on a channel the makerspace disabled. Existing staff receives-notification
and recipient rules remain authoritative. Turning off the editor does not discard saved
opt-outs, including after a deployment tombstones notifications. Email, inbox and existing staff device push preferences are independent;
this lane does not add member push delivery.

Account recovery, verification, overdue return reminders, custody alarms and loan
closure-with-issue emails bypass personal opt-outs. Suppression still blocks known bad
addresses, including transactional mail. Suppression stores a tenant-keyed HMAC of the
normalized address, a reason (`bounce` or `complaint`) and the staff User who recorded it.
It is checked for every tenant email, independently of the inbox feature switch.

SMTP is the only current mail transport, so suppression is manual in Delivery logs.
Superadmins can suppress platform mail separately in `/control/` under Email
suppressions. Tenant hashes affect that tenant's mail; platform hashes affect
platform mail only. Both controls audit changes and retain no plaintext address.
There is no provider webhook to authenticate. API email providers and automatic bounce
callbacks are deferred. Suppression is intrinsic delivery hygiene rather than an opt-in
switch that could resend to a known complaining address.

Optional family emails addressed to a known User include `List-Unsubscribe` and
`List-Unsubscribe-Post: List-Unsubscribe=One-Click` when the preference editor is enabled
and `PUBLIC_APP_BASE_URL` is HTTPS. The token binds tenant, User and family, uses Django's
salted timestamp signature and expires after 365 days. POST accepts URL-encoded form or
JSON with `List-Unsubscribe=One-Click`; GET has no effect. Forged/expired tokens return
400. The late tenant write gate refuses frozen tenants with 423. No login, cookies or
CSRF session are required. Configure the SMTP provider to DKIM-sign both unsubscribe
headers as required by RFC 8058; the application cannot enforce provider signing.

## Retention and data hygiene

The F1 reminder sweeper runs bounded cleanup even with no reminder sources registered.
Platform email logs use the same bounded terminal-delivery cleanup.
Each tenant holds its migration boundary, skips frozen/not-restored tenants and isolates
failures. Row locks with skip-locked protect cleanup against concurrent retry claims.

| Rows | Default cutoff |
| --- | --- |
| Read inbox | 90 days after `read_at` |
| Sent email/channel delivery | 90 days after `sent_at` |
| Failed delivery | 365 days after last `updated_at` |
| Skipped delivery | 90 days after last `updated_at` |
| Unread inbox, pending/sending delivery | Kept |

These are the research proposal's fixed defaults. Per-space retention overrides and
longer retention need a separate owner decision. Suppression and preference rows are
not delivery telemetry and are retained until removed or the tenant/module is purged.
Notification-module purge deletes legacy rows, personal rows and personal preferences.

Export/model/User-edge and tenant field catalogues declare all new models. Inbox text
and deployment-keyed suppressions are omitted from portable artifacts. Preferences
are included in manager datasets but dropped at target import, following the existing
target-owned notification policy; target Users must re-establish them before optional
communications are enabled. Tenant backups preserve source data normally. The target
catalogue schema digest remains the Wave 1 `RECOMPUTE` marker for coordinator pinning.

## Structured webhooks

Signed destinations keep `payload_version=1` by default, including old clients editing
an existing destination. Choosing 2 emits the contract in
[webhooks-v2.md](webhooks-v2.md) and [the JSON Schema catalogue](webhooks-v2.schema.json).
Editable templates cannot alter v2 field names or inject contact/credential fields.
