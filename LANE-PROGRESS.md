# w2-machines handoff

Implementation and review fixes complete; every change remains unstaged. No state-changing
Git command was run. The coordinator owns database validation, schema generation and commits.
The current review findings, validations, full file inventory and coordinator test paths
are in [w2-machines-PROGRESS.md](w2-machines-PROGRESS.md).

## Completed

- Machine-type training types and validity UI; scoped member picker; grant, append-only
  renewal and revoke flows with User actors and audit entries. Original trainer notes
  and expired grant evidence remain intact. Member and temporary-claim-session views
  expose only the account's own tenant-scoped history and expiry.
- Existing certification gate continues to enforce expiry at the stored instant for
  linked bookings and machine service submission. Booking forms expose the machine-type
  link; the three public submission serializers forward bounded override reasons to
  the existing authorization gate, which still refuses ordinary-member bypasses.
- Opt-in certification reminders through F1 and F3: member advance/expired notices,
  daily per-type expiring-soon staff count digest, current machine scope on recipients,
  local-calendar timing, stale-grant revalidation and terminal-marker batching.
- Opt-in maintenance advance/overdue reminders through F1 and F3; occurrence identity
  includes next_due so completion rearms reminders. Both machines and maintenance
  must be installed, and inactive machines/schedules cannot dispatch.
- Completion-date anchor remains default. Fixed-calendar anchor advances whole
  intervals from the previous due date past completion. Completion uses makerspace
  time and audits the anchor and old/new due dates atomically.
- Tenant/type numeric policy (manager identity only): default certification lead14,
  maintenance lead7, grace0; nullable fields retain defaults, zero disables advance
  notices. Data export, User-edge declaration, tenant projection/catalog/snapshot,
  purge and audit-reference classifications include the new model/fields.
- Handwritten frontend APIs, loading/error states and TanStack Query invalidation;
  backend route schemas; claim-route and custom-domain tenant-resolution entries.
- Documentation explains defaults, delivery limits, overlapping grants and portable
  migration replay. No new module keys or machine-service states.

## Original implementation validation (superseded by review results below)

- `npx.cmd tsc -b --pretty false`: completed with exit0.
- Python AST parsing: all55 changed/new Python files parsed.
- `git diff --check`: exit0. No staged files.
- No touched production Python/TypeScript file exceeds300 physical lines.
- AGENTS.md and CLAUDE.md are byte-identical and untouched.
- Database and frontend tests were NOT run; no test result is claimed. This lane
  cannot access Docker/Postgres, and its Python environment lacks Django/DRF.

## Migrations

- `backend/apps/machines/migrations/0025_machine_type_policy.py` depends on actual
  leaf `machines.0024_certifications`; creates MakerspaceMachineTypePolicy.
- `backend/apps/maintenance/migrations/0002_schedule_anchor.py` depends on actual
  leaf `maintenance.0001_initial`; adds completion/calendar anchor and check constraint.

## Coordinator remaining work

- Run the isolated database test runner for the tests below plus affected machine,
  maintenance, booking, operations reminder, integration destination, export and
  tenant-migration drift/portability coverage. Do not share a DB between pytest processes.
- Run the three new frontend test files and existing booking/maintenance/member UI tests.
- Run migration-state/check/schema validation; regenerate frontend/openapi-schema.json
  and frontend/src/generated/api.ts centrally (both intentionally untouched here).
- Recompute the merged tenant catalog digest: the branch already uses RECOMPUTE from
  Wave1. Complete coordinator review/QA gates and commit; no merge/push in this lane.

## Skips and owner decisions

- Escalation to a Space Manager is not implemented: research names escalate_after_days
  but gives no interval default. Owner must choose timing before escalation is built.
- Automatic lockout, work orders, training prerequisites/induction and new service
  request states are beyond top10 items1-2 / Wave2 and remain unchanged.
- No other owner decision blocks this lane's stated defaults.

## Other findings

- Existing certification detail/grant/revoke routes lacked custom-domain tenant lookup;
  fixed alongside new picker/renew routes to avoid mis-scoping these surfaces.
- Existing OpenAPI error helper lacked423; added its description for blocked writes.
- docs/SOURCE-MAP-FRONTEND.md had a pre-existing profile-settings change; that content
  is preserved. Machine UI ownership entries live in docs/SOURCE-MAP.md.
- No further outside-task defect was identified. Catalog RECOMPUTE is inherited
  integration work, not a new lane regression.

## Exact backend tests for coordinator

- `backend/tests/machines/test_certification_reminders.py` (new tests):
  - `test_member_and_staff_digest_are_once_per_grant_and_local_day`
  - `test_expiry_reminder_uses_local_wall_time_across_dst`
  - `test_revocation_renewal_and_foreign_tenant_suppress_stale_notices`
  - `test_module_off_prevents_discovery_and_dispatch`
  - `test_small_batches_progress_past_disabled_policy_and_completed_subjects`
  - `test_short_renewal_does_not_announce_expiry_while_an_older_grant_covers_use`
  - `test_expired_grant_notice_catches_up_after_downtime_once`
  - `test_reminder_feature_off_keeps_existing_training_records_silent`
- `backend/tests/machines/test_certification_ui_api.py` (new tests):
  - `test_member_history_only_contains_own_tenant_grants_and_no_staff_notes`
  - `test_member_picker_and_renewal_are_machine_type_scoped`
  - `test_grant_rejects_foreign_inactive_members_and_past_expiry`
  - `test_revoke_preserves_original_training_notes`
  - `test_exact_expiry_blocks_booking_and_service_gate_like_a_missing_grant`
  - `test_policy_is_tenant_local_and_requires_space_manager_identity`
  - `test_override_reason_reaches_boundary_serializers_but_cannot_authorize_member`
- `backend/tests/machines/test_reminder_scope_and_catalog.py` (new tests):
  - `test_machine_reminders_refuse_unlinked_and_other_type_roles`
  - `test_policy_has_explicit_export_snapshot_and_type_remapping_without_user_edges`
- `backend/tests/maintenance/test_completion_recurrence.py` (existing tests updated):
  - `test_completion_starts_fresh_interval_and_audits_due_dates`
  - `test_backdated_completion_uses_recorded_local_date`
- `backend/tests/maintenance/test_reminder_anchors.py` (new tests):
  - `test_fixed_calendar_preserves_phase_and_skips_missed_intervals`
  - `test_completion_anchor_uses_makerspace_zone_not_worker_timezone`
  - `test_invalid_anchor_is_rejected_at_service_and_http_boundary`
  - `test_due_soon_and_overdue_are_once_per_occurrence_and_completion_rearms`
  - `test_grace_period_deactivation_and_foreign_subject_revalidation`
  - `test_module_off_leaves_sweeper_inert`
  - `test_small_batch_is_not_starved_by_a_disabled_advance_notice`

## Exact frontend tests for coordinator

- `frontend/src/features/staff/panels/machine/CertificationsPanel.test.tsx`:
  - shows this type's training roster and renews through the audited endpoint
  - shows a failed list as an error without claiming there are no types
- `frontend/src/features/members/MemberCertifications.test.tsx`:
  - renders expiry and renewal guidance using server validity
  - keeps an unavailable history distinct from no records
- `frontend/src/features/staff/BookableSpaceMachineType.test.tsx`:
  - selects a scoped type by name and submits its authoritative id
  - retains a configured link when type discovery is unavailable

## Complete lane file inventory

A = created, M = modified. The pre-existing frontend source-map change is excluded.

- A `LANE-PROGRESS.md`
- M `backend/apps/accounts/claim_routes_member.py`
- M `backend/apps/admin_api/serializers_certifications.py`
- M `backend/apps/admin_api/urls_certifications.py`
- M `backend/apps/admin_api/views_certification_grants.py`
- A `backend/apps/admin_api/views_certification_members.py`
- M `backend/apps/admin_api/views_certifications.py`
- A `backend/apps/admin_api/views_machine_type_policy.py`
- M `backend/apps/bookings/serializers_public.py`
- M `backend/apps/data_export/classification_domain.py`
- M `backend/apps/data_export/datasets.py`
- M `backend/apps/data_export/references_core.py`
- A `backend/apps/integrations/notifications_machine_scope.py`
- M `backend/apps/integrations/notifications_research.py`
- M `backend/apps/integrations/staff_notifications.py`
- A `backend/apps/machines/certification_grants.py`
- A `backend/apps/machines/migrations/0025_machine_type_policy.py`
- M `backend/apps/machines/models.py`
- A `backend/apps/machines/models_policy.py`
- M `backend/apps/machines/notifications_certifications.py`
- M `backend/apps/machines/public_printer_service.py`
- M `backend/apps/machines/public_printer_service_serializers.py`
- M `backend/apps/machines/public_service_serializers.py`
- A `backend/apps/machines/reminder_policy.py`
- A `backend/apps/machines/reminders_certification_digest.py`
- A `backend/apps/machines/reminders_certifications.py`
- M `backend/apps/machines/urls.py`
- A `backend/apps/machines/views_member_certifications.py`
- M `backend/apps/machines/views_public_service.py`
- A `backend/apps/maintenance/migrations/0002_schedule_anchor.py`
- M `backend/apps/maintenance/models.py`
- A `backend/apps/maintenance/recurrence.py`
- A `backend/apps/maintenance/reminders.py`
- M `backend/apps/maintenance/serializers.py`
- M `backend/apps/maintenance/services_shared.py`
- M `backend/apps/maintenance/services_workflows.py`
- M `backend/apps/maintenance/views_schedules.py`
- M `backend/apps/maintenance/views_shared.py`
- M `backend/apps/makerspaces/capabilities.py`
- M `backend/apps/makerspaces/lifecycle_purge.py`
- M `backend/apps/makerspaces/origin_scope_model_lookups.py`
- M `backend/apps/openapi_errors.py`
- A `backend/apps/operations/reminder_consumer_queries.py`
- A `backend/apps/operations/reminder_machine_sources.py`
- M `backend/apps/operations/reminder_registry.py`
- M `backend/apps/operations/reminder_sweeper.py`
- M `backend/apps/tenant_migration/audit_references_meta_phase5.py`
- M `backend/apps/tenant_migration/target_projection_references.py`
- M `backend/apps/tenant_migration/target_projection_rows.py`
- M `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- M `backend/apps/tenant_migration/tenant_dump_model_catalog.py`
- A `backend/tests/machines/test_certification_reminders.py`
- A `backend/tests/machines/test_certification_ui_api.py`
- A `backend/tests/machines/test_reminder_scope_and_catalog.py`
- M `backend/tests/maintenance/test_completion_recurrence.py`
- A `backend/tests/maintenance/test_reminder_anchors.py`
- M `docs/SOURCE-MAP.md`
- A `docs/machine-training-maintenance.md`
- M `docs/reminder-schedules.md`
- M `frontend/src/features/members/MemberArea.tsx`
- A `frontend/src/features/members/MemberCertifications.test.tsx`
- A `frontend/src/features/members/MemberCertifications.tsx`
- M `frontend/src/features/members/MemberClaimSession.tsx`
- M `frontend/src/features/staff/BookableSpaceForm.tsx`
- A `frontend/src/features/staff/BookableSpaceMachineType.test.tsx`
- A `frontend/src/features/staff/BookableSpaceMachineType.tsx`
- M `frontend/src/features/staff/BookingDrawer.tsx`
- M `frontend/src/features/staff/BookingsPanel.tsx`
- M `frontend/src/features/staff/bookingsApi.ts`
- A `frontend/src/features/staff/certificationsApi.ts`
- M `frontend/src/features/staff/panels/MachinesPanel.tsx`
- A `frontend/src/features/staff/panels/machine/CertificationGrants.tsx`
- A `frontend/src/features/staff/panels/machine/CertificationTypeForm.tsx`
- A `frontend/src/features/staff/panels/machine/CertificationsPanel.test.tsx`
- A `frontend/src/features/staff/panels/machine/CertificationsPanel.tsx`
- A `frontend/src/features/staff/panels/machine/MachineReminderPolicy.tsx`
- M `frontend/src/features/staff/panels/machine/MachineTypePage.tsx`
- M `frontend/src/features/staff/panels/machine/MaintenanceSchedules.tsx`
- M `frontend/src/features/staff/panels/machine/maintenanceApi.ts`
- M `frontend/src/lib/features.ts`

## Review pass

- Fixed duplicate-name database errors, validity bounds, inactive-type validity labels,
  unbounded trainer rosters, overdue/expired discovery priority, unchanged booking-link
  resubmission, maintenance service and timer query RBAC boundaries, schema errors and
  recurrence descriptions, explicit portable authority dispositions, and CRLF files.
- New review coverage: `backend/tests/machines/test_certification_review.py`,
  `backend/tests/maintenance/test_review_regressions.py`,
  `frontend/src/features/staff/BookableSpaceForm.test.tsx`; extended scope/catalog and
  certification-panel tests; updated existing certification API pagination expectations.
- `python -m py_compile`: all 64 changed backend Python files compiled (exit 0).
- `npx.cmd tsc -b --pretty false`: exit 0 after correcting the new test helper's typing.
- `npx.cmd vitest run` for machine, booking-editor and member touched areas:
  15 files / 57 tests passed. No database test was run or claimed to pass.
- `git diff --check`: exit 0; no staged paths; all changed files LF-only and <=300 lines.
- Original migration dependencies remain verified; no migration added by review.
- Coordinator: use the precise test paths and inventory in `w2-machines-PROGRESS.md`.
  Regenerate OpenAPI artifacts and resolve the inherited catalog RECOMPUTE centrally.
- `codex doctor` was rechecked and failed in this sandbox: home/config unavailable and
  inference endpoint unreachable. An independent CLI review/DB QA remains coordinator work.
- Outside-task defect: Git tracks both SOURCE-MAP-FRONTEND.md and SOURCE-MAP-frontend.md,
  which alias on Windows. Incoming content is preserved; the coordinator must resolve
  the duplicate tracked paths. No Git state change or filename removal was attempted.
