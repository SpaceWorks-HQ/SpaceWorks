# Core billing: due dates, reminders and manual refunds

These surfaces remain available without the `payments` online module or credentials.
No new module key is introduced. Charge tracking still controls whether a debt is raised;
switching it off does not erase, settle or refund existing money.

New charges snapshot `due_at`. The default is the raise instant, or the makerspace's
`payment_terms_days` local calendar days later. Booking/event seams pass their start;
dues pass an existing active term's start, and renewal charges pass the current term's
end (the next term's start). Historic charges
keep a null due date. Due dates are immutable, including SQL updates. `due_state` is
derived only for pending charges: `upcoming`, `due_today` or `overdue`, using the owning
makerspace's local day. The server also returns `due_date`, so the browser never shifts
the date into its own timezone. Staff and member lists sort dated rows before nulls.

Managers configure `GET/PATCH admin/makerspace/<id>/billing-settings` (core, audited).
Defaults follow the research policy: due on raise, 3 days before, on the due day,
7 days after, and a cap of 2 steps. Increase the cap to 3 to include the default
overdue step, or configure a longer ladder. `billing.reminders` defaults OFF. Delivery additionally
requires `notifications`, `email` and the PAYMENTS/email matrix cell ON. Reminder
offsets are distinct positive local-calendar-day counts; the cap retains the earliest
configured steps, including the due-day step when it fits. Zero disables all steps.

The F1 sweeper owns claims and idempotency in `ReminderSchedule`; a duplicate payment
reminder log would introduce a second source of truth. The explicit `payments.due`
consumer revalidates pending status, tenant, due date and policy before dispatch.
Completed/uncertain claims are never retried. After downtime, only the latest eligible
step dispatches; earlier steps become skipped claims.
Advance and due-day notices expire after their scheduled local day, so downtime never
sends a stale "due today" message. Reminders send only to the charge
owner's current account address, respecting membership revocation and notification
opt-out. They never send staff email, chat, webhook or push and never alter debt.

PAYMENTS events already run on charge raised, money received and refund issued. They
now belong to the core ledger rather than the removable rail. Only the payer's receipt
email defaults ON; an explicit PAYMENTS/email OFF suppresses it. Other matrix defaults
remain OFF. Financial amounts stay out of staff chat.

`refund-offline` records money actually returned on any `paid_offline` charge kind and
requires `record_payment`. It is immediately succeeded and requires method, returned
date and an optional financial reference. Pending and succeeded refunds share the
original collected amount as their upper bound. `release-deposit` adds a closed-loan
check (`returned` or `closed_with_issue`). The return workflow itself never invents a
cash transfer: staff record the money handed back through the dialog after closing it.
Rail refunds remain on their existing provider-only route.

`payments/<payment>/refunds/<refund>/amend` appends corrected method/reference/date
metadata. The amount and currency are fixed. A receipt can be amended once; a later
correction amends its replacement. PostgreSQL guards cover raw/bulk bypasses as well as
model methods. No correction emits another refund event. Reconciliation and the
`payment-cash-book` report count only effective chain heads. The cash book groups by
method/currency and filters on actual receipt/refund dates, without mixing currencies
or inferring online settlement dates.

Portable dumps preserve due dates and refund correction chains, remapping identities.
They reset automatic-mail policy and drop F1 claims; the target must opt in afresh.
The money fingerprint includes due dates and every refund amendment. The coordinator
must recompute the merged catalog digest and regenerate the OpenAPI snapshot/client.
