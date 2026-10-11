# SpaceWorks source map

> **This is the file-layout half of `CLAUDE.md` / `AGENTS.md`.** It was split out when that file crossed
> the harness's memory-file size limit; nothing was dropped in the move. It has no `AGENTS.md`-style twin —
> both names of that document point at this one path, so edit it in place.
>
> Paths drift. If this disagrees with the tree, the tree wins — fix this file in the same commit.

## Current source map (real paths)

Cloud surfaces: `accounts/views_social.py` explicitly exports the nonce/login views in
`views_social_login.py` and identity management in `views_social_identities.py`, with shared
verification/error helpers in `views_social_helpers.py`. `integrations/health.py` explicitly exports
`health_status.py` rollups and `health_chat.py` destination/legacy delivery summaries. The
read-only scheduler control page lives in `operations/admin_scheduling.py`.
The shared reminder foundation is `operations/models_reminders.py`,
`reminder_types.py`, `reminder_registry.py`, `reminder_services.py`, `reminder_sweeper.py` and
`tasks_reminders.py`; `membership_payment_reminders.py` registers the admission
payment-deadline consumer for F3 membership notices. Loan borrower/staff sources
are registered explicitly alongside these payment consumers. The explicit `payments.due`
consumer in `payments/reminders.py` uses durable claims for owner-only email.
Core due dates and billing policy live in `payments/due_dates.py`, `models_billing.py`
and `views_billing.py`; manual receipt corrections/release reuse
`services_refunds_offline.py` and `views_refunds_offline.py`.
`operations/reports_cash_book.py` owns effective manual money-in/out totals.
`payments/schemas_billing.py` documents typed business errors and DRF field-validation
responses. The module guide links into `MODULES-INVENTORY.md`, `MODULES-WORKSHOPS.md`,
`MODULES-PLATFORM.md` and `MODULES-LIFECYCLE.md` to keep each reference below the file ceiling.
Explicit lazy machine/maintenance adapters live in
`reminder_machine_sources.py`. Certification expiry and staff digests live in
`machines/reminders_certifications.py` and `reminders_certification_digest.py`;
maintenance reminders and anchor maths live in `maintenance/reminders.py` and
`recurrence.py`. `machines/models_policy.py` owns tenant/type numeric settings.
`admin_api/views_certification_types.py` and `views_certification_grants.py` own
paginated trainer rosters; `serializers_certifications.py` validates type names and
maps concurrent unique-name collisions to field errors. The member history lives in
`machines/views_member_certifications.py`; `views_machine_type_policy.py` owns policy edits.
Frontend trainer controls live in `staff/panels/machine/CertificationsPanel.tsx`,
`CertificationGrants.tsx` and `MachineReminderPolicy.tsx`; `staff/certificationsApi.ts`
owns paging. `members/MemberCertifications.tsx` owns private history and
`staff/BookableSpaceMachineType.tsx` owns the optional booking training link.
Staff/member API and UI behavior is described in
[machine-training-maintenance.md](machine-training-maintenance.md).
Queries use `accounts/rbac.py:scope_for_scheduled_work`; see
[reminder-schedules.md](reminder-schedules.md) for UTC, claims and migration rules.
Platform monitoring uses `admin_api/views_platform_monitoring.py` and its schema sibling;
`operations/platform_dashboard.py` scopes tenants, `platform_signals.py` reads deployment state,
`platform_checks.py` declares checks, and `platform_problems.py` isolates failures.
`platform_integration_health.py` reads channels without creating settings; `tasks_platform.py`
and `scheduler_telemetry.py` own scheduled checks and beat completion telemetry.
Tenant counters and allowances are read by `makerspaces/usage_snapshot.py`.

Membership admission is described in [membership-admission.md](membership-admission.md).
`makerspaces/models_admission.py` owns the settings and immutable vouch models.
`membership_services.py` remains the explicit compatibility barrel over
`membership_helpers.py`, `membership_legacy.py` and `membership_admission.py`.
Admission settings/forms/vouches/charges live in `membership_admission_settings.py`,
`membership_admission_forms.py`, `membership_vouching.py` and
`membership_admission_payments.py`; all grants use `membership_activation.py`.
`membership_admission_direct.py` applies gates to walk-in and core creation paths.
`views_admission.py` serves the public policy and owned applicant/voucher routes;
`admin_api/views_membership_admission.py` serves manager settings. Existing staff
review serializers include answer snapshots and named vouches. Committed payment
callbacks live in `payments/admission_settlement.py`, with narrow rejoin debt access
in `payments/admission_access.py`. `operations/tasks_admissions.py` drives expiry
and settlement recovery in both schedulers. Application-export audit writes and
settlement activation take explicit tenant write boundaries; reviewer debt summaries
use the existing finance-scoped payment context.

Loan policy lives in `makerspaces/models_loan_policy.py` and `loan_policy.py`;
`admin_api/views_loan_policy.py` / `serializers_loan_policy.py` extend the existing
return-policy route. `hardware_requests/workflow.py` exports `renewal_workflow.py`
for policy-bound extensions; `renewal_views.py` serves member/staff actions.
`loan_reminders.py` and `loan_reminder_notifications.py` adapt F1 claims to borrower
mail and F3 escalation. `inventory/availability_loan_limits.py` owns borrower quantity
ceilings; `accounts/rbac_borrowers.py` scopes owned rows even without membership.
`makerspaces/member_loans.py` includes reviewed and direct loans in member activity.
See [loan-policy.md](loan-policy.md) for defaults, inheritance, gates and routes.
`tenant_migration/tenant_dump_authority_loans.py` declares portable loan terms and
renewal history; the fan-out gate registry names the legacy reminder helper that
actually holds the boundary.
Frontend loan controls are `staff/MakerspaceLoanPolicySettings.tsx`,
`staff/StaffLoanRenew.tsx` and `members/MemberLoanRenew.tsx` under features/.


The backend, frontend and domain lookup continues in [SOURCE-MAP-APPS.md](SOURCE-MAP-APPS.md).

Space packs live in `makerspaces/space_pack_*`, with their literal configuration
projection in `data_export/space_pack_configuration.py`. The profile model is
`makerspaces/models_space_packs.py`; HTTP contracts are in
`admin_api/serializers_space_packs.py` and `views_space_packs.py`.
`capabilities.py` now re-exports feature definitions from `capability_definitions.py`;
`loan_policy_settings.py` is the settings editor and pack shared policy writer.
See [SPACE-PACKS.md](SPACE-PACKS.md) for the protocol and authority boundaries.
Frontend `staff/SpacePacksPanel.tsx` owns export/preview/apply, with handwritten
`spacePacksApi.ts` calls and `SpacePackProfilePicker.tsx` for creation profiles.
Platform profile admin scoping is declared in `config/admin_scope_registry.py`;
the profile route is platform-exempt in `tenant_migration/gate_policy_http.py`,
while pack application explicitly asserts the target source gate before writes.
