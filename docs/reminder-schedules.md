# Shared reminder schedules (research F1)

`operations/reminder_sweeper.py` runs every five minutes in both Celery beat and
`run_scheduled_tasks --due-only`. No production sources are registered by F1, so
upgrading does not change notification behaviour. The existing hourly loan return
reminder and membership renewal tasks keep their current schedules and semantics.

## Registering a source

Add a `ReminderSource` explicitly to `operations/reminder_registry.py:REMINDER_SOURCES`.
Its module and optional feature must already exist in their canonical registries.
The sweeper checks both plus the `notifications` module before discovery or claims;
deployment tombstones are handled by `module_enabled` at the same boundary.
Gates are read again after discovery and before dispatch, so disabling a source
during a long scan suppresses its notices instead of using a stale settings object.

`discover(makerspace, now, limit, local_tz)` yields `ReminderSubject` values with an
opaque subject identity, kind, aware due timestamp, and configurable signed integer
offsets in **seconds**. For example, `[-259200, -86400, 0, 86400, 604800]` represents
three days before, one day before, due time, one day after, and seven days after.
An empty offset list disables reminders. Lists are limited to 100 steps and
duplicate offsets are collapsed. Consumer policy rows own these lists; F1 adds no
feature keys or tenant settings surface.

Use `accounts.rbac.scope_for_scheduled_work(queryset, makerspace_id=makerspace.pk,
field="makerspace_id")` for every source/domain query (adjust `field` for indirect
ownership). It excludes archived, inactive and hard-hidden tenants; not-restored
and frozen tenants still reach the write gate and are counted. This internal helper
does not authorize HTTP users or replace the tenant write gate. Primitives also
refuse direct writes to unavailable tenants. Discovery must scope every domain query
to the supplied makerspace. Ask far enough
ahead to cover negative offsets, include due items missed during downtime, and
paginate fairly so completed subjects cannot crowd out new ones. The shared batch
size bounds discovery subjects and claims separately, per source and tenant.
The source owns its query plan, cursor/fairness and future discovery horizon.

`build(makerspace, reminder, now, local_tz)` must re-read the subject within that
tenant and check current domain eligibility, policy offsets and due timestamp.
Return `None` for a cancelled/returned/ineligible subject, disabled offset or stale
due timestamp. Otherwise return a `ReminderMessage`. The sweeper sends it through
`notifications.emit.emit_notification`, preserving the staff inbox module gate and
fail-safe behaviour. This foundation adds no member delivery, matrix event families,
dues, certifications, booking/event reminders or state transitions. Later consumer
lanes own their notification matrix/recipient integration (research F2/F3).

The runnable **test-only** example is
`backend/tests/operations/reminder_example.py`; it must never be added to the
production registry. It illustrates scoped discovery, live revalidation and local
time formatting using existing booking rows without implementing booking mail.

## Claims and delivery limits

`ReminderSchedule` has a database unique constraint on makerspace, source, subject,
kind and offset. For recurring subjects include the occurrence/term in the subject
identity. Repeated discovery reuses the row. A changed due timestamp moves pending
rows; it never resets claimed, completed or failed rows.

`claim_reminders` locks pending due rows with `select_for_update(skip_locked=True)`
and commits their UUID claim tokens before dispatch. Concurrent workers claim
distinct rows without waiting on each other's row locks. Call claims/sweeps in
autocommit: an outer application transaction could roll back after a message escapes.
Both explicit atomic blocks and manually disabled autocommit are refused.
Primitives reuse the sweeper's validated tenant boundary; standalone calls acquire
their own write gate. This avoids acquiring the same advisory lock on two connections
while an exclusive migration writer waits, without weakening direct-call protection.
`complete_reminder` only updates a matching tenant, row and claim token, and repeated
completion leaves its original completion timestamp intact.
Returning `None` from `build` completes the claimed step without dispatch, permanently.
This includes removed offsets and stale subjects. Rediscovery can move only pending
steps; a consumer that needs a notice after rescheduling a claimed/skipped step must
use a new occurrence identity. Completion never makes an uncertain claim retryable.

**At most once is a dispatch guarantee within one source deployment**, not a
guarantee of successful delivery. A crashed worker can leave a permanent claimed row;
an emitter failure can lose a notice. There is deliberately no lease expiry or
automatic retry because a message may already have escaped. The existing emitter
returns no delivery receipt and catches storage errors, so `dispatched` counts attempts.
`skipped` counts closed/not-restored tenant boundaries, source gates and ineligible
messages; `failed` counts tenant/source/dispatch failures. One tenant failure does
not interrupt the next tenant. Coordination tombstones have no automatic retention
deletion, since deleting them would permit duplicate dispatch.

## UTC and source-local data

Due timestamps must be aware. Stored timestamps and comparisons are normalized to
UTC; offsets are elapsed seconds, including across daylight-saving changes.
`run_reminder_sweep(tz_resolver=...)` accepts a makerspace-to-timezone-name or tzinfo
hook for source policy overrides; without it, `makerspaces.local_time.to_local`
supplies the makerspace profile's timezone. The timezone only
affects source policy/rendering, never the persisted instant.

Reminder rows contain no payload, address or User FK and contribute no accounts to
the export identity closure. They are omitted from data export and explicitly DROP
in the tenant-migration catalog/projection, then rebuilt from imported domain rows.
Because sent markers do not travel, the target may dispatch a historical offset again:
consumer lanes must choose their target eligibility/catch-up window accordingly.
Full deployment backup/restore retains the database coordination rows as usual.

`REMINDER_SWEEP_BATCH_SIZE` defaults to 200 and must be positive. Cadence is fixed at
five minutes in both scheduler surfaces, with a parity test. No new endpoint or
generated frontend/OpenAPI artifact is needed for this internal foundation.
