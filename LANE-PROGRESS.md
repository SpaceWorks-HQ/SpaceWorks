# w2-events lane handoff

Implementation complete; all changes are unstaged. Database validation and coordinator review remain.

## Review pass (2026-10-11)

- Read the root instructions, main-checkout research plans, complete tracked diff and untracked implementation/tests. There was no `w2-events-PROGRESS.md` at review start; this file was the prior handoff. The requested review handoff now exists under that name.
- Fixed unbounded opening-calendar traversal: duration and advance limits now reject invalid windows before opening-hours iteration. This protects the space row lock from maliciously large date ranges.
- Fixed B17 for booking-only staff: the editor now uses a paginated, minimal ID/name picker under `MANAGE_BOOKINGS`, including organization grants. It does not depend on Machines-console authority. Added the route's origin target and explicit OpenAPI request/response/error schemas.
- Fixed reminder result handling: synchronous failed mail marks the schedule FAILED; matrix/recipient suppression counts as skipped. Existing staff sources retain their dispatch-attempt semantics. No failed/uncertain schedule is automatically resent.
- Fixed multi-offset discovery starvation: after an early step completes, a future later step no longer occupies the discovery batch ahead of other members whose early step is due. Added an events/bookings regression with two offsets and a one-subject batch.
- Fixed public booking JSON lists/scalars causing `AttributeError`; return a field-keyed 400 while preserving the authenticated honeypot noop.
- Added pagination parameters and 423/503 migration-gate errors to changed route schemas.
- Normalized 17 lane files with CRLF/mixed endings to LF. All changed files are UTF-8 without detected mojibake and within 300 lines. AGENTS.md and CLAUDE.md remain byte-identical and untouched.
- Confirmed actual migration leaves, classification/snapshot/portable authority entries for every new scalar policy field. No new model/User FK, module key, feature key, environment variable, task entry point or object writer. E3/B10 use F1's existing declared fan-out gate. The existing reminder environment variable is documented in `docs/environment-reference.md`.
- Updated `docs/SOURCE-MAP.md` and `docs/reminder-schedules.md`.
- Static validation: `python -m py_compile` succeeded for all 71 changed backend Python files; `npx tsc -b` exited 0; focused `npx vitest run` passed 6 files / 27 tests; `git diff --check` exited 0. Database tests were not run and have no pass claim. Index remains empty.
- Broader frontend validation: `npx vitest run src/features/bookings src/features/members src/features/staff --maxWorkers=2` passed 100 files / 408 tests. Static fan-out coverage validated all 11 declared participants. Recompiled all 71 backend Python files after the final multi-offset fix.
- Added `tests/bookings/test_booking_review_regressions.py` (bounds before calendar traversal; malformed JSON; honeypot contract), `tests/bookings/test_booking_machine_type_choices.py` (booking-only authority, tenant/member refusal, organization/custom-domain authority, module-off, pagination/OpenAPI), and `tests/operations/test_attendance_reminder_results.py` (real SMTP failure, no automatic resend, matrix suppression).
- Extended `frontend/src/features/staff/StaffBookingForm.test.tsx` with paginated machine-type selection that preserves the selected type.
- Coordinator must run the new tests plus the full existing lane test inventory below, tenant source-gate/catalog/projection guards, API scope/claim and origin-scope guards, member activity and tombstone coverage. Regenerate OpenAPI artifacts and the merged catalog digest centrally.
- No new owner decision was invented: pending charges are voided, settled refunds remain a staff decision; paid re-registration remains refused; offer/claim windows, rescheduling and per-space hours overrides retain the prior documented deferrals. The inherited provider-I/O-under-lock and stale long-form presence documentation findings remain coordinator follow-ups.

Full lane paths, review-added test names and final checks are in `w2-events-PROGRESS.md`.

## Completed

- E1 member cutoff enforcement inside the event lock; existing FIFO capacity promotion/pending-charge cancellation retained. Paid cancelled registrations refuse revival, even if the current event is now free. Free revival keeps its existing row and resets FIFO position. Staff cancellation still overrides the member deadline.
- Nullable event/series cancellation policy (null = until start), occurrence inheritance, member deadline display and staff controls; bounded to 8760 hours to prevent datetime overflow.
- E3/B10 reminders consume F1 schedules and F3 notification matrix. Only the owning member's current account address is emailed, using makerspace local time. Current membership, preferences, requester toggles, modules, servability and source gates apply. Default leads [24]; empty disables. Member event ICS includes alarms.
- Reminder consumers are lazy and tombstone-safe. Completed markers cannot starve later members or rescheduled occurrences; UTC start identity allows one fresh reminder when a start changes.
- B1 public booking needs active membership/current waiver, with no presence requirement. Staff B3 creation uses the same service, audit, charging and certification override authority; member choices are paginated and tenant-scoped.
- B17 machine type editor uses existing machine visibility authority. Ordinary editor no longer promises to change approval mode, which belongs to the Space Manager rules endpoint.
- B4/B5 service enforces F4 local opening intervals, dated exceptions and cleanup buffers under the space lock on create and approve. Exact adjacent occupied boundaries are allowed. Buffer edits cannot introduce overlap among existing live confirmed bookings. Public availability publishes occupied/open intervals and timezone while keeping buffer settings and private contacts hidden.
- B2 member booking history is paginated, upcoming/past, scoped to User ownership. Pending and confirmed self-cancel checks the current cutoff under lock, voids pending charges through the existing seam and refreshes member/payment/public availability caches.
- Export field classification, literal tenant field snapshots and explicit portable authority policies updated. No new model/User FK or module/feature key was introduced.
- Oversized/near-ceiling booking lifecycle and staff views were split behind explicit compatibility exports. AGENTS.md/CLAUDE.md remain byte-identical.

## Validation performed

- Frontend focused Vitest: 6 files, 26 tests passed (MyBookings, StaffBookingForm, Track3Payments, MakerspaceReminderSettings, MemberEventCancel, EventFormFields).
- TypeScript: node.exe node_modules/typescript/bin/tsc -b exited 0.
- All changed Python files parsed with ast.parse; touched implementation/test files <=300 lines.
- git diff --check exited 0 (only checkout line-ending advisory warnings). Index remains empty.
- No database tests ran. Host Python has no Django installed; Docker/Postgres are unavailable as specified. No backend pass claim is made.

## Migrations

- bookings/0010_booking_buffers_and_cancellation.py -> bookings.0009_certifications.
- events/0024_event_cancellation_policy.py -> events.0023_event_station_binding.
- makerspaces/0080_event_booking_reminder_policy.py -> makerspaces.0079_staff_invitations_feature.

## Coordinator work remaining

- Regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts; both deliberately untouched.
- Recompute the merged tenant catalog digest; CATALOG_SCHEMA_SHA256 was already RECOMPUTE at lane start and remains so.
- Run ./scripts/dev.sh test tests/bookings tests/events tests/operations tests/makerspaces/test_reminder_policy_api.py tests/test_notification_templates.py tests/test_notification_template_registry.py, followed by affected member-activity, API-client scope/claim, data_export/tenant_migration catalog/projection and tombstone guards. Use the isolated runner, never the shared dev DB.
- Perform coordinator code review and owner QA of member cancellation, staff book-on-behalf, policy editing and reminder delivery. No git state-changing command was run in this lane.
- The existing long-form presence invariant still lists public booking as requiring presence. The task explicitly supersedes that policy; presence guard documentation has been corrected. Coordinator should update the long-form invariant alongside the merged programme docs.

## Deferred / owner decisions

- No automatic settled-refund policy is stated. Settled payments remain intact and staff decide refunds; pending payments are voided through existing services.
- Fresh identities for paid re-registration are undecided; implemented the requested fallback refusal. No paid revival is silently free.
- Retained the stated zero-offer-window/default instant FIFO promotion with charging only at REGISTERED. Offer/claim windows are E2, outside this lane; future offer charging should follow the plan's recommendation of charging at claim.
- Per-makerspace event cutoff numeric default, rescheduling, maintenance blocks, guest booking and per-space opening-hours overrides lack a specified build contract here; no guessed model/state or authorization path was added. F4 makerspace hours and dated exceptions are enforced.
- No owner decision blocks the delivered default behavior. The above optional extensions require their product contracts.

## Existing defect noticed outside scope

- payments.reconciliation.cancel_pending expires provider checkout/native handles while the event/booking cancellation transaction holds domain row locks. Event-wide cancellation already defers its provider work until commit; individual cancellation keeps the existing seam. Coordinator should address provider I/O under lock separately.
- Ordinary booking editor's silently ignored approval_mode was noticed and corrected in this lane.

## Test inventory

- `backend/tests/bookings/test_member_submission_m6.py` updated existing regression/contract expectations.
- `backend/tests/bookings/test_public_api.py` updated existing regression/contract expectations.
- `backend/tests/bookings/test_public_booking_leaks.py` updated existing regression/contract expectations.
- `backend/tests/test_notification_templates.py` updated existing regression/contract expectations.
- `backend/tests/bookings/test_booking_schedule_policy.py` (new): `test_buffers_refuse_overlap_and_allow_exact_half_open_boundary`, `test_buffer_edit_cannot_introduce_overlap_between_existing_bookings`, `test_dated_closed_day_refuses_create_and_approval`, `test_opening_interval_boundaries_include_cleanup_and_lunch_gaps`, `test_empty_hours_allow_overnight_booking`, `test_dst_interval_uses_makerspace_local_wall_clock`, `test_buffer_overlap_serializes_concurrent_reservations`, `test_public_busy_windows_include_buffers_without_exposing_private_policy`, `test_rule_updates_validate_policy_bounds_and_audit`.
- `backend/tests/bookings/test_member_booking_api.py` (new): `test_own_upcoming_and_past_history_never_matches_shared_contact_fields`, `test_member_cancel_pending_or_confirmed_is_audited_and_does_not_need_presence_or_new_waiver`, `test_cutoff_is_enforced_on_current_locked_policy`, `test_service_refuses_another_actor_and_http_refuses_cross_tenant_and_unowned_rows`, `test_module_off_is_400_for_list_and_cancel_and_body_refuses_extra_fields`, `test_cancellation_voids_pending_charge_once_and_keeps_settled_money`, `test_my_bookings_is_paginated_and_documents_all_routes`.
- `backend/tests/bookings/test_staff_booking_access.py` (new): `test_staff_books_without_presence_and_snapshots_member_with_actor_audit`, `test_staff_booking_refuses_other_tenant_space_and_member`, `test_staff_booking_refuses_inactive_membership`, `test_staff_booking_refuses_restricted_account`, `test_staff_booking_requires_current_waiver`, `test_staff_booking_override_needs_machine_type_authority_and_is_audited`, `test_member_cannot_use_staff_booking_and_module_off_returns_400`, `test_staff_member_picker_is_scoped_paginated_and_excludes_inactive_accounts`, `test_staff_booking_input_cannot_invent_status_or_override_flags`, `test_staff_booking_requires_explicit_timezone_offset`, `test_staff_booking_routes_have_schema_and_machine_editor_rejects_other_tenant_type`.
- `backend/tests/events/test_member_cancellation_policy.py` (new): `test_member_cancellation_deadline_is_strict_and_preserves_capacity`, `test_member_service_enforces_owner_and_deadline_but_staff_can_override`, `test_member_cannot_cancel_registration_for_terminal_event`, `test_cancelled_paid_registration_cannot_revive_or_reuse_terminal_charge`, `test_free_cancelled_registration_revives_with_a_new_fifo_position`, `test_member_activity_uses_same_cutoff_for_collaborative_history`, `test_staff_can_write_cutoff_and_series_occurrences_inherit_with_override`, `test_negative_or_overflowing_cancellation_hours_rejected_at_api_boundary`, `test_cancellation_throttle_is_per_member_and_does_not_spend_create_budget`.
- `backend/tests/makerspaces/test_reminder_policy_api.py` (new): `test_staff_updates_reminder_policy_and_records_field_names_only`, `test_settings_reject_invalid_reminder_lead_hours`, `test_reminder_policy_settings_are_scoped_to_the_staff_makerspace`, `test_reminder_settings_have_explicit_openapi_array_schemas`.
- `backend/tests/operations/test_attendance_reminders.py` (new): `test_reminders_email_only_the_owning_member_once`, `test_batch_discovery_does_not_starve_the_next_member`, `test_completed_old_start_does_not_block_one_reminder_for_rescheduled_start`, `test_domain_module_off_skips_discovery`, `test_unconfirmed_or_rejected_attendance_never_receives_a_reminder`, `test_booking_requester_email_override_can_suppress_reminders`, `test_cancelled_and_rescheduled_subjects_are_suppressed`, `test_module_off_never_sends_attendance_mail`, `test_current_member_and_matrix_preferences_suppress_delivery`, `test_foreign_schedule_subject_is_refused`, `test_due_instants_and_rendering_use_makerspace_zone_across_dst`, `test_removed_offsets_and_empty_policy_suppress_pending_steps`, `test_member_calendar_alarms_apply_only_to_confirmed_live_registrations`, `test_invalid_lead_policy_is_refused`.
- `backend/tests/operations/test_reminder_source_registry.py` (new): `test_core_registry_import_does_not_load_tombstoned_consumers`, `test_explicit_empty_override_does_not_load_any_production_consumer`.
- `backend/tests/test_notification_template_registry.py` (extracted registry coverage): `test_the_registry_covers_twenty_six_events_in_both_audiences`, `test_every_entry_renders_against_its_own_sample_context`, `test_every_registry_entry_anywhere_still_renders`, `test_defaults_are_not_blank`, `test_new_streams_are_selectable_on_the_model_and_in_the_registry`, `test_the_members_feature_maps_to_the_membership_stream`.
- `frontend/src/features/members/MemberEventCancel.test.tsx` extended/updated frontend coverage; included in the focused 26-test run.
- `frontend/src/features/staff/EventFormFields.test.tsx` extended/updated frontend coverage; included in the focused 26-test run.
- `frontend/src/features/staff/Track3Payments.test.tsx` extended/updated frontend coverage; included in the focused 26-test run.
- `frontend/src/features/bookings/MyBookings.test.tsx` new frontend coverage; included in the focused 26-test run.
- `frontend/src/features/staff/MakerspaceReminderSettings.test.tsx` new frontend coverage; included in the focused 26-test run.
- `frontend/src/features/staff/StaffBookingForm.test.tsx` new frontend coverage; included in the focused 26-test run.

## Created files

- `LANE-PROGRESS.md`
- `backend/apps/bookings/migrations/0010_booking_buffers_and_cancellation.py`
- `backend/apps/bookings/reminders.py`
- `backend/apps/bookings/serializers_member.py`
- `backend/apps/bookings/serializers_staff_booking.py`
- `backend/apps/bookings/services_schedule.py`
- `backend/apps/bookings/services_transitions.py`
- `backend/apps/bookings/views_admin_booking_actions.py`
- `backend/apps/bookings/views_admin_booking_create.py`
- `backend/apps/bookings/views_admin_booking_list.py`
- `backend/apps/bookings/views_member.py`
- `backend/apps/events/calendar_alarms.py`
- `backend/apps/events/cancellation_policy.py`
- `backend/apps/events/migrations/0024_event_cancellation_policy.py`
- `backend/apps/events/reminders.py`
- `backend/apps/makerspaces/migrations/0080_event_booking_reminder_policy.py`
- `backend/apps/makerspaces/reminder_policy.py`
- `backend/apps/operations/reminder_members.py`
- `backend/apps/operations/reminder_types.py`
- `backend/tests/bookings/test_booking_schedule_policy.py`
- `backend/tests/bookings/test_member_booking_api.py`
- `backend/tests/bookings/test_staff_booking_access.py`
- `backend/tests/events/test_member_cancellation_policy.py`
- `backend/tests/makerspaces/test_reminder_policy_api.py`
- `backend/tests/operations/test_attendance_reminders.py`
- `backend/tests/operations/test_reminder_source_registry.py`
- `backend/tests/test_notification_template_registry.py`
- `frontend/src/features/bookings/MyBookings.test.tsx`
- `frontend/src/features/bookings/MyBookings.tsx`
- `frontend/src/features/staff/MakerspaceReminderSettings.test.tsx`
- `frontend/src/features/staff/MakerspaceReminderSettings.tsx`
- `frontend/src/features/staff/StaffBookingForm.test.tsx`
- `frontend/src/features/staff/StaffBookingForm.tsx`
- `frontend/src/features/staff/staffBookingApi.ts`

## Modified files

- `backend/apps/accounts/claim_routes_public.py`
- `backend/apps/admin_api/serializers_makerspaces.py`
- `backend/apps/apiclients/scope_registry_routes.py`
- `backend/apps/bookings/models.py`
- `backend/apps/bookings/serializers_admin.py`
- `backend/apps/bookings/serializers_public.py`
- `backend/apps/bookings/services_bookings.py`
- `backend/apps/bookings/services_rules.py`
- `backend/apps/bookings/urls_admin.py`
- `backend/apps/bookings/urls_public.py`
- `backend/apps/bookings/views_admin_bookings.py`
- `backend/apps/bookings/views_public.py`
- `backend/apps/data_export/classification_domain.py`
- `backend/apps/events/models_event.py`
- `backend/apps/events/models_series.py`
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
- `backend/apps/makerspaces/models_makerspace.py`
- `backend/apps/makerspaces/origin_scope_model_lookups.py`
- `backend/apps/operations/reminder_registry.py`
- `backend/apps/operations/reminder_sweeper.py`
- `backend/apps/presence/guard.py`
- `backend/apps/tenant_migration/tenant_dump_authority_supplement.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `backend/tests/bookings/test_member_submission_m6.py`
- `backend/tests/bookings/test_public_api.py`
- `backend/tests/bookings/test_public_booking_leaks.py`
- `backend/tests/test_notification_templates.py`
- `docs/SOURCE-MAP.md`
- `docs/reminder-schedules.md`
- `frontend/src/features/bookings/AvailabilityCalendar.tsx`
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
- `frontend/src/features/staff/MakerspaceSettingsPanel.tsx`
- `frontend/src/features/staff/Track3Payments.test.tsx`
- `frontend/src/features/staff/bookingsApi.ts`
- `frontend/src/features/staff/eventSeriesApi.ts`
- `frontend/src/features/staff/eventsApiTypes.ts`
- `frontend/src/features/staff/panels/shared.tsx`
