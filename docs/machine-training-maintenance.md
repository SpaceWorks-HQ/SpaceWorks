# Machine training and maintenance reminders

Training types remain per makerspace and machine type. The Machines type page lets
authorized trainers define validity, grant training, renew by appending a new grant,
and revoke a grant. Original grant notes and expiry remain historical evidence;
revocation reasons are recorded in the audit log. Type deactivation preserves grants.
Members see only their own paginated history, expiry and renewal guidance, including
in a tenant-bound temporary claim session. Trainer notes never enter that response.
Staff type and grant lists also use 24-row paginated responses. The type UI fetches
every page before filtering by machine type; grant history has its own page controls.
Duplicate type names and out-of-range validity values return typed field errors.

The existing `machines.certifications` feature continues to gate service submission
and booking a linked space. Expiry is enforced at the instant stored on the grant,
with no grace period. An audited override requires authority over the entire machine
type and a stated reason. Booking forms now expose the machine-type link; public
booking, generic service and printer submission serializers pass override reasons to
the existing gate. A plain member's reason cannot authorize a bypass.
Unchanged booking training links are omitted from edit payloads, so disabling
Machines does not block unrelated booking-space edits. Clearing a link sends null.

Two new features default off:

- `machines.certification_reminders` requires Machines and Notifications. Members get
  an advance expiry notice (14 local calendar days by default) and an expired notice.
  Staff get one expiring-soon count digest per machine type per local day. Staff
  messages carry no member names or training notes.
- `maintenance.reminders` requires Maintenance, Machines and Notifications. Staff get
  a due-soon notice (7 local calendar days by default) and an overdue notice beginning
  the day after the due date plus any configured grace period.

The F3 CERTIFICATIONS and MAINTENANCE channel matrices stay off by default. Enable
channels separately. Recipient selections and member opt-outs still apply. Scheduled
staff emails and push recipients must currently manage the named machine/type;
unlinked roles cannot receive these safety reminders. Chat destinations retain their
existing explicit machine/type scope.

Space-manager identity alone may edit `MakerspaceMachineTypePolicy` on each type page:
`cert_reminder_days`, `reminder_lead_days` and `grace_days`. Blank retains 14, 7 and 0
respectively after reminder opt-in; zero disables advance notices. Settings accept
0–365 days. The policy belongs to the tenant, not a global built-in type's structural
capability configuration. It is exported, projected and purged with tenant data and
has no User foreign keys.

Maintenance schedules now have two recurrence anchors:

- `completion` (the existing default): recorded completion's makerspace-local date
  plus the interval.
- `calendar`: advance the previous due date by whole intervals until the result is
  after completion, skipping missed occurrences. Early completion advances one
  interval. For example, due January 1 every 30 days, completed April 10, next due May 1.

Completion, next due date and anchor are recorded together in the same audited
transaction. Machine status remains controlled by the existing workflow; reminders
do not introduce automatic lockout or machine-service request states.

All three consumers register with the existing F1 sweeper. Its single five-minute
task already runs through Celery beat and `SCHEDULED_TASKS`, with tombstone/module
filtering. A source may provide a domain dispatch callback after live revalidation;
sources without one continue to emit staff inbox notices as before. Reminder identity
includes the due-date occurrence for maintenance and the local day for digests.
Terminal rows are excluded before batching, so disabled policies and completed
subjects cannot starve eligible work. Renewals with overlapping grants notify only
the longest remaining valid window, matching the gate's “any live grant” semantics.
Expired and overdue notices take priority over advance notices within a small batch.

F1 provides at-most-once dispatch attempts, not guaranteed external delivery. Expired
and overdue work missed during downtime is discovered on the next sweep; no arbitrary
catch-up cutoff is imposed. Coordination rows do not travel in portable tenant dumps,
so enabling reminders on a target can send historical expired/overdue notices again.

Escalation timing, automatic maintenance lockout, work orders, prerequisites and new
machine-service request states remain outside this lane. No escalation interval was
stated, so no value is invented here. The coordinator regenerates OpenAPI artifacts,
recomputes the merged catalog digest and runs database/UI tests before integration.
