# Member accounts and renewal automation

The existing `membership` module owns these features. No new module is required.
`membership.auto_renew`, `membership.lifecycle_mail`, `membership.self_service`
and `membership.self_export` all start off. Account and export routes also require
`member_accounts`; disabled modules/features return HTTP 400.

## Renewal policy

Staff edit renewal settings on each membership plan: automatic renewal, opening
days (0–365), grace days (0–365), retries (0–3), and up to ten reminder offsets
before and after expiry (1–365 days). The defaults are seven opening days, zero
grace/retries, and reminders 14, 7 and 1 days before expiry.

F1 opens the renewal charge on the makerspace's local calendar day. The existing
charge seam records debt independently of the online payments module. A settled
or waived renewal opens exactly one successor starting at the previous expiry;
free plans and disabled charge tracking extend without a payment rail. A future
prepaid term supplies coverage only once its start arrives. No stored card is
automatically charged. Existing manual plans retain their seven-day charge seam.

Checkout creation runs after the debt transaction commits. Provider outages keep
that debt and use daily bounded retries on the same Payment. The initial attempt
and retry date are durable so the next sweep can recover a worker interruption.
The promise of grace is saved on the term and survives later plan changes/import.
Expiry at the grace boundary changes the term, never membership or account status.
The existing `lapsed_members_cannot_borrow` switch controls borrowing restrictions.

F1 deduplicates reminder identities; F3 renders `MEMBERS`/membership lifecycle
emails for the owning account address. Delivery additionally needs the notification
email cell and email module enabled, and honors recipient selection/preferences.
There are no staff chat deliveries for these renewal notices.

## Own account

The member area links to `/m/<slug>/member/account` (or `/member/account` on a tenant
domain). Members may edit display name, first/last name and contact phone. This
does not alter verified login email/phone. Profile values stay out of audit metadata.

Sessions include browser sessions and native device grants. New browser tokens
share a stable session marker through refresh rotation; revoking that marker
immediately refuses its access and refresh tokens. Pre-upgrade tokens acquire a
marker on their next refresh. Revoking a legacy refresh credential leaves its
already-issued access token usable until its original short expiry; the UI says so.
MFA and authentication-generation checks continue to apply.

Cancel renewal records the reason, stops further renewal and cancels pending
renewal debt while retaining the current term. Leaving records a separate audited
departure and reuses existing membership revocation cleanup, preserving the global
account/history. A sole makerspace manager must appoint another manager first.
Plan changes remain staff initiated. Pause, proration and erasure are outside this lane.
Cancellation stays in force for the current membership lifecycle, including imported
history. A fresh admission after departure clears it in the audited activation transaction.

## Subject access

An authenticated member requests a personal ZIP containing JSON datasets and a
manifest. Row selectors prove ownership and intersect the selected tenant through
RBAC. Columns come from the existing reviewed export classification. Credentials,
other account identities, anonymous records without proven ownership, tenant
configuration and photo/file bytes are omitted. The owner's encrypted contact data
is read through its normal decrypted getters. Exports cannot use staff tenant-wide
download/runner routes.

Requests are limited to one per account per day in cache and one per tenant/account
per day under the database tenant lock. The worker uses existing export deadlines,
storage accounting and retention. Pending jobs survive broker enqueue failure and
are recovered hourly by `sweep_subject_exports_task`; the beat-less scheduled runner
also invokes it. Celery autodiscovery imports the tasks from `data_export.tasks`.
Downloads require renewed ownership checks and return a short-lived private storage
URL with no-store headers; links never enter audit metadata. Leaving while queued
fails the job without producing an archive.
