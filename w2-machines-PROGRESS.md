# w2-machines review handoff

The requested w2-machines-PROGRESS.md did not exist in the worktree or the main
plans directory. LANE-PROGRESS.md was the original handoff; it has also been updated.
All edits are inside this worktree and unstaged. No state-changing Git command ran.

## Review pass

Completed: read the root instructions, original brief, research/defaults, machine-scoping
invariants, original handoff, full tracked diff and every new source/test file.

Defects and fixes:

- Duplicate certification names could raise IntegrityError (500), including renames.
  Scoped serializer preflight now returns a name error; a nested transaction maps a
  concurrent PostgreSQL unique collision to the same 400 without partial audit writes.
- Overriding the model integer serializer removed its upper bound. validity_days now
  accepts only 1 through the PostgreSQL PositiveIntegerField maximum, or null.
- The staff serializer called an inactive type's grants live while the member view
  called them inactive. Both now account for type activity and stored expiry/revocation.
- Trainer lists were unbounded arrays. Types and grants now use 24-row paginated
  responses and schemas; the UI fetches all type pages and pages grant history.
- The sweeper caps the whole source generator. Advance-first discovery could keep
  expired/overdue notices out of a busy small batch. Terminal safety notices drain first.
- Booking edits always resent their existing machine_type, so unrelated edits failed
  after Machines was uninstalled. Unchanged links are omitted; intentional clear sends null.
- Maintenance service lookups relied on a supplied model object instead of the RBAC
  queryset boundary. Machine locks and schedule/log/document lookups are now actor-scoped.
  Timer recipient and maintenance notification rebuild queries use scheduled-work RBAC.
  A disappeared membership cannot become an account-only certification reminder recipient.
  Interactive lifecycle recipient fallback remains unchanged, including unlinked roles.
- Affected maintenance schemas omitted 401/423 and described only completion anchors.
  They now document authentication/frozen-write errors and both anchors; all certification
  paginated APIs explicitly document the page query argument and response envelope.
- New policy/anchor fields had export/catalog/projection entries but lacked explicit
  authority/disclosure decisions. Both guard declarations and portable PRESERVE dispositions
  now record that timing/recurrence carries no actor grant; target opt-ins remain reset.
- 55 changed files contained CRLF. Normalized them to LF; no mojibake found.

Why these changes matter: DRF validates user-controlled values before ORM writes;
PostgreSQL remains the final uniqueness authority under races. Savepoints convert only
known collisions without hiding other integrity errors. RBAC query boundaries protect
service callers as well as views. TanStack Query page keys separate grant pages, while
prefix invalidation refreshes every cached page after an audited mutation.

## Validation actually performed

- python -m py_compile: all 64 changed backend Python files compiled, exit 0.
- npx.cmd tsc -b --pretty false: exit 0 (new test helper typing corrected before final run).
- npx.cmd vitest run: 15 affected frontend files, 57 tests passed. This includes all tests
  under staff/panels/machine, MachinesPanel, BookableSpaceForm, BookableSpaceMachineType,
  MemberCertifications, MemberArea, MemberAreaBranding, MemberAreaArchivedLink,
  and MemberClaimSession.
- git diff --check: exit 0; git diff --cached --name-only: empty.
- Every changed file is LF-only, UTF-8, and <=300 lines. Root AGENTS.md and CLAUDE.md
  remain byte-identical and untouched. Generated OpenAPI files are untouched.
- codex doctor: exit 1; sandbox home/config unavailable and inference endpoint unreachable.
  Independent CLI review remains coordinator work; no approval was requested.
- NO database tests, migration application, Django schema generation, or Docker checks ran.
  Python compilation is syntax verification, not runtime/database validation.

## Migrations and catalog/gate review

No migration was added by this review. The implementation created:

- backend/apps/machines/migrations/0025_machine_type_policy.py
  depends on machines.0024_certifications (verified prior leaf).
- backend/apps/maintenance/migrations/0002_schedule_anchor.py
  depends on maintenance.0001_initial (verified prior leaf).

The new policy has no accounts.User FK; references_core.py documents that explicitly.
Export fields/dataset, model and field catalog snapshots, FK type remapping, purge ordering,
normal data projection, authority dispositions and renewal audit meta edges were inspected.
Reminder callbacks reuse the already-declared F1 task and run_reminder_sweep fan-out boundary;
there is no new task, tenant fan-out boundary or object writer needing a new gate declaration.
No environment variable or module key was added. No environment-reference edit is needed.
The inherited RECOMPUTE catalog digest still requires central coordinator regeneration.

## Coordinator remaining work

Run the database paths below in the isolated runner. Also run affected machine/booking,
operations/reminder, notification-family/recipient, data-export and tenant-migration
portability/drift coverage. Do not share one test DB across pytest processes.
Regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts centrally;
apply/check migrations and run final review/QA before staging or committing.

Exact changed/new backend test paths:
- `backend/tests/machines/test_certification_reminders.py`
- `backend/tests/machines/test_certification_review.py`
- `backend/tests/machines/test_certification_ui_api.py`
- `backend/tests/machines/test_certifications_api.py`
- `backend/tests/machines/test_reminder_scope_and_catalog.py`
- `backend/tests/maintenance/test_completion_recurrence.py`
- `backend/tests/maintenance/test_reminder_anchors.py`
- `backend/tests/maintenance/test_review_regressions.py`

Additional coordinator guard/regression paths:

- backend/tests/maintenance/
- backend/tests/machines/
- backend/tests/bookings/
- backend/tests/operations/
- backend/tests/test_staff_notifications.py
- backend/tests/test_notification_family_edges_f3.py
- backend/tests/test_notification_families_f3.py
- backend/tests/test_notification_recipient_scope.py
- backend/tests/data_export/
- backend/tests/tenant_migration/test_authority_guard.py
- backend/tests/tenant_migration/test_source_gate_guards.py
- backend/tests/tenant_migration/test_tenant_dump_catalog_d1.py
- backend/tests/tenant_migration/test_projected_catalog_travel_guard.py
- backend/tests/tenant_migration/test_projection_behaviors_d8.py

## Review-added or extended tests

- `backend/tests/machines/test_certification_review.py`:
  - `test_duplicate_type_name_is_400_without_partial_audit`
  - `test_validity_range_refused_before_database_write`
  - `test_type_and_grant_lists_are_paginated_after_machine_scope_filtering`
  - `test_inactive_type_grants_are_not_presented_as_live`
  - `test_expired_notices_take_priority_in_small_discovery_batches`
  - `test_member_expiry_payload_has_only_owner_email_and_disables_staff_channels`
  - `test_member_expiry_does_not_send_after_membership_disappears`
- `backend/tests/maintenance/test_review_regressions.py`:
  - `test_overdue_notices_take_priority_in_small_discovery_batches`
  - `test_foreign_actor_cannot_complete_schedule_through_service`
  - `test_schedule_http_surfaces_refuse_machines_off_with_400`
- `backend/tests/machines/test_reminder_scope_and_catalog.py`:
  - `test_machine_reminders_refuse_unlinked_and_other_type_roles`
  - `test_timer_recipient_queries_refuse_a_hidden_tenant`
  - `test_policy_has_explicit_export_snapshot_and_type_remapping_without_user_edges`
  - `test_portable_projection_retains_numeric_policy_but_resets_reminder_opt_in`
- frontend/src/features/staff/BookableSpaceForm.test.tsx (new):
  - omits an unchanged link when Machines discovery is unavailable
  - sends an explicit null when the training link is cleared
- frontend/src/features/staff/panels/machine/CertificationsPanel.test.tsx (extended):
  - loads every type page and pages through grant history
- backend/tests/machines/test_certifications_api.py (existing expectations updated):
  - test_staff_api_creates_grants_and_revokes_with_audit
  - test_staff_api_hides_and_refuses_types_for_unlinked_machine_types

Original implementation-added tests are enumerated in LANE-PROGRESS.md; their exact paths
are included above. Existing timer scope/catalog tests also gained push and lifecycle
fallback assertions, declaration coverage, and a real raw portable-projection check.

## Skips, owner decisions and outside findings

- Database tests are prohibited in this sandbox; the coordinator must run them.
- Generated schema artifacts and inherited catalog digest regeneration are coordinator-owned.
- No escalation interval default is stated. Escalation remains skipped pending the owner's
  escalate_after_days decision; it does not block the stated reminder/anchor defaults.
- Work orders, automatic lockout, prerequisites, sessions and new machine-service request
  states remain outside Wave 2. No new product decision was guessed.
- Outside-task defect: Git tracks docs/SOURCE-MAP-FRONTEND.md and docs/SOURCE-MAP-frontend.md
  with different baseline content. They alias on Windows. The incoming profile-settings
  content is preserved, and lane ownership additions live in docs/SOURCE-MAP.md.
  Resolving the duplicate tracked paths requires coordinator Git state changes and was skipped.

## Complete current lane file inventory

A = new/untracked in this lane; M = modified tracked file, including inherited changes
and LF normalization. This is the entire unstaged lane, not only semantic review edits.

- A `LANE-PROGRESS.md`
- M `backend/apps/accounts/claim_routes_member.py`
- M `backend/apps/admin_api/serializers_certifications.py`
- M `backend/apps/admin_api/urls_certifications.py`
- M `backend/apps/admin_api/views_certification_grants.py`
- A `backend/apps/admin_api/views_certification_members.py`
- M `backend/apps/admin_api/views_certification_types.py`
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
- M `backend/apps/maintenance/notifications.py`
- A `backend/apps/maintenance/recurrence.py`
- A `backend/apps/maintenance/reminders.py`
- M `backend/apps/maintenance/serializers.py`
- M `backend/apps/maintenance/services_documents.py`
- M `backend/apps/maintenance/services_shared.py`
- M `backend/apps/maintenance/services_workflows.py`
- M `backend/apps/maintenance/views_logs.py`
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
- M `backend/apps/tenant_migration/authority_guards.py`
- M `backend/apps/tenant_migration/target_projection_references.py`
- M `backend/apps/tenant_migration/target_projection_rows.py`
- M `backend/apps/tenant_migration/tenant_dump_authority_supplement.py`
- M `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- M `backend/apps/tenant_migration/tenant_dump_model_catalog.py`
- A `backend/tests/machines/test_certification_reminders.py`
- A `backend/tests/machines/test_certification_review.py`
- A `backend/tests/machines/test_certification_ui_api.py`
- M `backend/tests/machines/test_certifications_api.py`
- A `backend/tests/machines/test_reminder_scope_and_catalog.py`
- M `backend/tests/maintenance/test_completion_recurrence.py`
- A `backend/tests/maintenance/test_reminder_anchors.py`
- A `backend/tests/maintenance/test_review_regressions.py`
- M `docs/SOURCE-MAP-FRONTEND.md`
- M `docs/SOURCE-MAP.md`
- A `docs/machine-training-maintenance.md`
- M `docs/reminder-schedules.md`
- M `frontend/src/features/members/MemberArea.tsx`
- A `frontend/src/features/members/MemberCertifications.test.tsx`
- A `frontend/src/features/members/MemberCertifications.tsx`
- M `frontend/src/features/members/MemberClaimSession.tsx`
- A `frontend/src/features/staff/BookableSpaceForm.test.tsx`
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
- A `w2-machines-PROGRESS.md`
