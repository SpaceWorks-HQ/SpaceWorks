# w2-events review handoff

## Review pass (2026-10-11)

The prior handoff is LANE-PROGRESS.md; this requested filename did not exist at review start.
All changes remain unstaged. No git state-changing command or database test suite was run.

Defects fixed:
- Calendar traversal preceded cheap booking limits. Duration/advance checks now bound that work.
- B17 used a Machines-only list, blocking booking-only staff. Added paginated type IDs/names under
  MANAGE_BOOKINGS, scoped to the tenant plus built-ins, with organization authority and origin mapping.
- Reminder callbacks discarded NotificationResult. Failed mail now records FAILED; suppression counts
  as skipped. F1 terminal claims remain closed and staff dispatch-attempt counting remains compatible.
- Future second offsets could keep partially completed subjects in every discovery batch and starve
  later members. Discovery now requires an unfinished step due NOW, while initially scheduling all steps.
- Public booking lists/scalars raised AttributeError before DRF validation. They now return 400;
  the authenticated honeypot still returns its existing noop response without requiring date fields.
- New paginated routes omitted page parameters; changed mutation schemas omitted migration 423/503.
  Added these explicit OpenAPI entries. Generated frontend artifacts remain coordinator-owned.
- Seventeen lane files had CRLF/mixed endings. Normalized LF. No detected UTF-8 mojibake or file >300 lines.

Completed checks:
- python -m py_compile: exit 0 for all 71 changed backend Python files.
- npx tsc -b: exit 0.
- npx vitest run (bookings, MemberEventCancel, StaffBookingForm, Track3Payments,
  MakerspaceReminderSettings, EventFormFields): 6 files, 27 tests passed.
- Broader npx vitest run src/features/bookings src/features/members src/features/staff --maxWorkers=2:
  100 files, 408 tests passed. All 71 backend Python files recompiled after the final reminder fix.
- validate_fanout_gate_coverage(): all 11 declared participants validated without Django/DB execution.
- git diff --check: exit 0; git diff --cached --stat: empty.
- Existing reminder env var is documented; no new env var, feature/module key, model, User FK,
  task/fan-out entry point or object writer. Existing F1 fan-out covers attendance consumers.

## Tests added in this review (backend NOT RUN)

backend/tests/bookings/test_booking_review_regressions.py:
- test_invalid_booking_range_is_rejected_before_calendar_traversal (duration, advance)
- test_public_booking_refuses_non_object_json (list, populated list, scalar)
- test_honeypot_keeps_its_noop_contract_without_dates

backend/tests/bookings/test_booking_machine_type_choices.py:
- test_booking_only_staff_can_choose_own_and_builtin_types_without_machine_access
- test_type_choices_refuse_members_and_foreign_tenants
- test_org_booking_authority_can_choose_types_from_its_verified_domain
- test_type_choices_module_off_returns_400 (bookings, machines)
- test_type_choices_are_paginated_and_have_openapi_errors

backend/tests/operations/test_attendance_reminder_results.py:
- test_failed_email_marks_schedule_failed_without_automatic_resend (events, bookings)
- test_matrix_suppression_counts_as_skipped_and_stays_terminal (events, bookings)
- test_future_second_step_cannot_starve_later_members_first_step (events, bookings)

frontend/src/features/staff/StaffBookingForm.test.tsx:
- Added pages-through-type-choices/preserves-selection test; updated picker wiring test.

## Coordinator work

Run ./scripts/dev.sh test tests/bookings tests/events tests/operations
  tests/makerspaces/test_reminder_policy_api.py tests/test_notification_templates.py
  tests/test_notification_template_registry.py
Also run affected member activity, organizations, origin-scope, API-client scope/claim,
export/catalog/projection/authority and tombstone guards. No backend pass claim is made.
Regenerate frontend/openapi-schema.json, frontend/src/generated/api.ts and the merged catalog digest.
The complete inherited test-function inventory is in LANE-PROGRESS.md.

## Migrations (inherited; no migration added by this review)

- bookings/0010_booking_buffers_and_cancellation.py -> bookings.0009_certifications
- events/0024_event_cancellation_policy.py -> events.0023_event_station_binding
- makerspaces/0080_event_booking_reminder_policy.py -> makerspaces.0079_staff_invitations_feature
Listed the actual leaves and checked all dependencies; classification, field snapshots and portable
scalar authority policies match the introduced fields. No new User-reference declaration is needed.

## Deferrals and outside-scope findings

No automatic settled-refund policy is stated, so pending debt is voided and paid receipts remain for
staff refund decisions. Paid re-registration is refused under the requested fallback; fresh identities
need an owner policy. Waitlist offer/claim windows, rescheduling, maintenance blocks, guest booking,
per-space opening overrides and a numeric makerspace event-cutoff default remain deferred as documented
in the prior handoff. No new owner decision blocks this review.
Existing individual cancellation does provider I/O while domain locks are held; event-wide cancellation
already defers it. The long-form presence invariant still names advance booking as presence-gated;
this brief supersedes it, and the coordinator should update that shared program documentation.

## Files changed by this review (including LF-only changes)

- `LANE-PROGRESS.md`
- `w2-events-PROGRESS.md`
- `backend/apps/bookings/services_bookings.py`
- `backend/apps/bookings/services_rules.py`
- `backend/apps/bookings/services_transitions.py`
- `backend/apps/bookings/urls_admin.py`
- `backend/apps/bookings/views_admin_booking_actions.py`
- `backend/apps/bookings/views_admin_booking_create.py`
- `backend/apps/bookings/views_admin_booking_list.py`
- `backend/apps/bookings/views_admin_bookings.py`
- `backend/apps/bookings/views_admin_machine_types.py`
- `backend/apps/bookings/views_member.py`
- `backend/apps/bookings/views_public.py`
- `backend/apps/data_export/classification_domain.py`
- `backend/apps/events/views_registration_cancel.py`
- `backend/apps/makerspaces/origin_scope_routes.py`
- `backend/apps/operations/reminder_members.py`
- `backend/apps/operations/reminder_registry.py`
- `backend/apps/operations/reminder_sweeper.py`
- `backend/apps/operations/reminder_types.py`
- `backend/apps/events/reminders.py`
- `backend/apps/bookings/reminders.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `backend/tests/bookings/test_booking_machine_type_choices.py`
- `backend/tests/bookings/test_booking_review_regressions.py`
- `backend/tests/operations/test_attendance_reminder_results.py`
- `backend/tests/test_notification_template_registry.py`
- `backend/tests/test_notification_templates.py`
- `docs/SOURCE-MAP.md`
- `docs/reminder-schedules.md`
- `frontend/src/features/staff/BookableSpaceForm.tsx`
- `frontend/src/features/staff/EventFormFields.tsx`
- `frontend/src/features/staff/EventSeriesForm.tsx`
- `frontend/src/features/staff/StaffBookingForm.test.tsx`
- `frontend/src/features/staff/staffBookingApi.ts`

## Full unstaged lane file inventory

- `LANE-PROGRESS.md`
- `backend/apps/accounts/claim_routes_public.py`
- `backend/apps/admin_api/serializers_makerspaces.py`
- `backend/apps/apiclients/scope_registry_routes.py`
- `backend/apps/bookings/migrations/0010_booking_buffers_and_cancellation.py`
- `backend/apps/bookings/models.py`
- `backend/apps/bookings/reminders.py`
- `backend/apps/bookings/serializers_admin.py`
- `backend/apps/bookings/serializers_member.py`
- `backend/apps/bookings/serializers_public.py`
- `backend/apps/bookings/serializers_staff_booking.py`
- `backend/apps/bookings/services_bookings.py`
- `backend/apps/bookings/services_rules.py`
- `backend/apps/bookings/services_schedule.py`
- `backend/apps/bookings/services_transitions.py`
- `backend/apps/bookings/urls_admin.py`
- `backend/apps/bookings/urls_public.py`
- `backend/apps/bookings/views_admin_booking_actions.py`
- `backend/apps/bookings/views_admin_booking_create.py`
- `backend/apps/bookings/views_admin_booking_list.py`
- `backend/apps/bookings/views_admin_bookings.py`
- `backend/apps/bookings/views_admin_machine_types.py`
- `backend/apps/bookings/views_member.py`
- `backend/apps/bookings/views_public.py`
- `backend/apps/data_export/classification_domain.py`
- `backend/apps/events/calendar_alarms.py`
- `backend/apps/events/cancellation_policy.py`
- `backend/apps/events/migrations/0024_event_cancellation_policy.py`
- `backend/apps/events/models_event.py`
- `backend/apps/events/models_series.py`
- `backend/apps/events/reminders.py`
- `backend/apps/events/serializers_admin.py`
- `backend/apps/events/serializers_series.py`
- `backend/apps/events/services.py`
- `backend/apps/events/services_calendar.py`
- `backend/apps/events/services_registration.py`
- `backend/apps/events/services_registration_state.py`
- `backend/apps/events/services_series.py`
- `backend/apps/events/views_public.py`
- `backend/apps/events/views_registration_cancel.py`
- `backend/apps/integrations/email_templates_registry_fablab.py`
- `backend/apps/integrations/email_templates_registry_fablab_defaults.py`
- `backend/apps/integrations/notification_catalog.py`
- `backend/apps/makerspaces/member_activity_serializers.py`
- `backend/apps/makerspaces/member_activity_service.py`
- `backend/apps/makerspaces/migrations/0080_event_booking_reminder_policy.py`
- `backend/apps/makerspaces/models_makerspace.py`
- `backend/apps/makerspaces/origin_scope_model_lookups.py`
- `backend/apps/makerspaces/origin_scope_routes.py`
- `backend/apps/makerspaces/reminder_policy.py`
- `backend/apps/operations/reminder_members.py`
- `backend/apps/operations/reminder_registry.py`
- `backend/apps/operations/reminder_sweeper.py`
- `backend/apps/operations/reminder_types.py`
- `backend/apps/presence/guard.py`
- `backend/apps/tenant_migration/tenant_dump_authority_supplement.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `backend/tests/bookings/test_booking_machine_type_choices.py`
- `backend/tests/bookings/test_booking_review_regressions.py`
- `backend/tests/bookings/test_booking_schedule_policy.py`
- `backend/tests/bookings/test_member_booking_api.py`
- `backend/tests/bookings/test_member_submission_m6.py`
- `backend/tests/bookings/test_public_api.py`
- `backend/tests/bookings/test_public_booking_leaks.py`
- `backend/tests/bookings/test_staff_booking_access.py`
- `backend/tests/events/test_member_cancellation_policy.py`
- `backend/tests/makerspaces/test_reminder_policy_api.py`
- `backend/tests/operations/test_attendance_reminder_results.py`
- `backend/tests/operations/test_attendance_reminders.py`
- `backend/tests/operations/test_reminder_source_registry.py`
- `backend/tests/test_notification_template_registry.py`
- `backend/tests/test_notification_templates.py`
- `docs/SOURCE-MAP.md`
- `docs/reminder-schedules.md`
- `frontend/src/features/bookings/AvailabilityCalendar.tsx`
- `frontend/src/features/bookings/MyBookings.test.tsx`
- `frontend/src/features/bookings/MyBookings.tsx`
- `frontend/src/features/bookings/PublicBookingsPage.tsx`
- `frontend/src/features/bookings/publicBookingsApi.ts`
- `frontend/src/features/members/MemberActivity.tsx`
- `frontend/src/features/members/MemberArea.tsx`
- `frontend/src/features/members/MemberEventCancel.test.tsx`
- `frontend/src/features/members/MemberEventCancel.tsx`
- `frontend/src/features/staff/BookableSpaceForm.tsx`
- `frontend/src/features/staff/BookingDrawer.tsx`
- `frontend/src/features/staff/BookingsPanel.tsx`
- `frontend/src/features/staff/EventFormFields.test.tsx`
- `frontend/src/features/staff/EventFormFields.tsx`
- `frontend/src/features/staff/EventSeriesForm.tsx`
- `frontend/src/features/staff/MakerspaceBookingRulesSettings.tsx`
- `frontend/src/features/staff/MakerspaceReminderSettings.test.tsx`
- `frontend/src/features/staff/MakerspaceReminderSettings.tsx`
- `frontend/src/features/staff/MakerspaceSettingsPanel.tsx`
- `frontend/src/features/staff/StaffBookingForm.test.tsx`
- `frontend/src/features/staff/StaffBookingForm.tsx`
- `frontend/src/features/staff/Track3Payments.test.tsx`
- `frontend/src/features/staff/bookingsApi.ts`
- `frontend/src/features/staff/eventSeriesApi.ts`
- `frontend/src/features/staff/eventsApiTypes.ts`
- `frontend/src/features/staff/panels/shared.tsx`
- `frontend/src/features/staff/staffBookingApi.ts`
- `w2-events-PROGRESS.md`
