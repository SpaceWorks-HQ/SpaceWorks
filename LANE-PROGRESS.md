# w7-notify — WP3 items 14–20

## Completed

- Verified repository guidance, actual file paths, BUILD GAPS ordering/deferred list and cited research.
- Payment failure: verified Stripe/Razorpay attempt outcomes, existing receipt idempotency, payer-only notification after commit, pending debt preserved.
- Timing: opt-in local quiet windows and personal email-family daily digests, using F4 wall-time rules and F1 durable claims. Critical/exempt mail bypasses timing. Release rechecks opt-outs, suppression, matrix and account standing.
- Bounce/complaint: tenant-signed HMAC ingress, five-minute window, bounded payload, hashed suppression, complaint upgrades, audit without addresses/secrets.
- Broadcast: scoped plan/status/certification segments, MANAGE_MEMBERS composer, matrix email and personal inbox/feed, opt-out and revoked-account protection. Encrypted broadcast history classified for export.
- Bookings: owned reschedule with current cutoff/buffers/opening hours/certification; finite staff weekly occurrences with savepoints and explicit conflicts; per-occurrence ordinary charges.
- Booking ICS: hashed private account token, rotation/revocation, own reservations only, no contacts/notes, sequence updates, cancelled/rejected statuses, token/IP throttles and no-store headers.
- Added owner-only RBAC booking scope so account-only borrowers see their reservations; revoked membership is refused. Included the new authorization module in the authority source guard.
- Added classifications, User-FK decisions, literal tenant catalog/authority/projection entries, encryption/backfill and module-purge ownership for new models.
- Cash-book aggregation already exists in this tree; added registry and currency/method/decimal regressions.
- All changes remain unstaged. No state-changing git commands, generated API updates, event feed-service edits or new module keys.

## Validation and coordinator work remaining

- Frontend and TypeScript results below are superseded by the actual CLI runs recorded in Review pass. Dependencies were copied into this worktree from the main checkout without writing outside this worktree.
- TypeScript: the actual `npx.cmd tsc -b` run reports only the five owner-supplied exclusions (nine diagnostics); see Review pass.
- Python compilation, touched-file line limit and whitespace checks are recorded in Review pass. Database tests were NOT run: Django is absent and access to the Docker daemon is denied in this sandbox.
- Coordinator must run all backend test files listed below, plus booking/integration notification/F1 tests, API-client and origin-scope guards, data-export/tenant-migration and encryption/module-purge guards.
- Coordinator must apply/check migrations, run Django checks and makemigrations --check, recompute the merged CATALOG_SCHEMA_SHA256, regenerate OpenAPI JSON/types and run normal frontend build/tests in the integrated tree.
- The account-only feed test requires WP2's removal of bookings' membership dependency before integrated validation. This lane does not change that lane's registry.
- codex doctor failed configuration/provider reachability checks; nested CLI review was unavailable. No database-pass claim or merge/commit was made.

## Migrations (actual leaves checked before creation)

- integrations/0030_notification_timing_policy.py → integrations/0029_personal_delivery_controls + makerspaces/0085_space_pack_profile.
- notifications/0003_broadcasts_and_digests.py → notifications/0002_personal_inbox + makerspaces/0085_space_pack_profile + swappable AUTH_USER_MODEL.
- bookings/0011_calendar_feed.py → bookings/0010_booking_buffers_and_cancellation + makerspaces/0085_space_pack_profile + swappable AUTH_USER_MODEL.

## Boundaries, decisions and findings

- No owner decision needed for the implemented defaults. Quiet hours/digests/broadcasts/recurrence remain opt-in; empty quiet channels are inert.
- Kept flat per-booking charges and existing charge due dates on reschedule; no duration repricing or automatic refund. Recurrence produces independent finite bookings, not an infinite generator or cancel-all series controller.
- Did not implement deferred guest/no-account registration, member push, SMS/WhatsApp, automatic refunds, new loan/machine states or other deferred BUILD GAPS work. Maintenance ICS belongs to WP4.
- Bookings/events membership independence and the core loans switch belong to WP2; this lane preserves that integration boundary. Event feed-token code is imported, not edited.
- Item 20's audit description is stale: the current cash-book strategy/aggregator already cover currency and method. The review defects and fixes are recorded below.
- Protocol, source ownership and behavior details: docs/WP3-NOTIFICATIONS-BOOKINGS.md.

## Added tests (backend execution pending)
- `backend/tests/bookings/test_booking_feed.py`
  - `test_ics_contains_only_owner_bookings_and_rotation_and_revocation_invalidate_tokens`
  - `test_wrong_tenant_module_off_and_revoked_owner_are_refused`
  - `test_account_only_feed_needs_no_events_or_membership_module`
- `backend/tests/bookings/test_member_reschedule.py`
  - `test_member_moves_same_reservation_and_charge_and_calendar_identity`
  - `test_reschedule_respects_buffers_and_failure_keeps_old_window`
  - `test_cutoff_ownership_and_module_off_are_enforced`
  - `test_account_only_owner_can_reschedule_but_revoked_membership_denies_own_access`
- `backend/tests/bookings/test_recurring_bookings.py`
  - `test_occurrence_conflicts_are_explicit_and_only_successful_rows_are_audited`
  - `test_weekly_recurrence_preserves_local_hour_across_dst`
  - `test_bounds_and_disabled_feature_refuse_before_creating_any_occurrence`
  - `test_recurring_route_resolves_its_space_for_custom_domain_authority`
- `backend/tests/notifications/test_broadcasts.py`
  - `test_scoped_broadcast_respects_email_and_inbox_opt_out_and_feed_is_personal`
  - `test_plan_status_segment_uses_current_scoped_term_and_foreign_plan_is_invalid`
  - `test_manage_members_gate_disabled_feature_and_module_off`
  - `test_revoked_and_globally_restricted_members_never_match`
  - `test_certification_segment_uses_live_grant_not_an_expired_or_foreign_grant`
- `backend/tests/notifications/test_wp3_portability.py`
  - `test_history_is_classified_and_live_disclosure_controls_are_dropped`
  - `test_export_and_field_catalog_guards_cover_wp3_schema`
- `backend/tests/operations/test_org_report_registry_coverage.py`
  - `test_registry_has_a_strategy_or_explicit_exclusion_for_every_report`
  - `test_cash_book_totals_preserve_currency_method_and_decimal_precision`
- `backend/tests/payments/test_payment_failed_notification.py`
  - `test_failure_notifies_payer_after_commit_once_and_does_not_cancel_debt`
  - `test_rollback_discards_failure_receipt_and_notification`
  - `test_foreign_provider_handles_and_terminal_failures_do_not_notify`
- `backend/tests/test_bounce_ingestion.py`
  - `test_signed_hard_bounce_is_idempotent_private_and_honoured_at_dispatch`
  - `test_forgery_expired_timestamp_and_signature_from_another_tenant_are_refused`
  - `test_complaint_upgrades_bounce_without_duplicate_audit_and_soft_bounce_is_invalid`
- `backend/tests/test_quiet_hours_digests.py`
  - `test_overnight_local_quiet_window_and_boundary`
  - `test_quiet_end_in_dst_gap_moves_to_real_wall_time`
  - `test_critical_events_bypass_quiet_hours_and_digest`
  - `test_quiet_mail_is_durable_and_f1_releases_it_at_most_once`
  - `test_daily_digest_groups_only_one_users_opted_in_family_and_rechecks_opt_out`
  - `test_revocation_before_digest_release_suppresses_queued_content`
  - `test_timing_policy_requires_scoped_manager_and_never_returns_signing_secret`
- `frontend/src/features/bookings/BookingReschedule.test.tsx`
  - Keeps the editor open on conflict and refreshes booking/availability caches on success.
- `frontend/src/features/notifications/PreferenceCentre.digest.test.tsx`
  - Digest opt-in keeps the email topic enabled.
- `frontend/src/features/staff/BroadcastComposer.test.tsx`
  - Submits named segment choices and renders the eligible-recipient receipt.
- `frontend/src/features/staff/StaffBookingForm.recurring.test.tsx`
  - Submits a finite recurrence and displays every occurrence conflict.

## Review pass

Read the complete working diff (including new files), repository/global instructions, the original BUILD GAPS section and its ordering/deferred decisions, cited research, and the implementation handoff. Git was used read-only throughout; nothing was staged, committed, merged or pushed.

### Defects fixed

1. A stale F1 claim could release a newly rescheduled notification. Deferred releases now match the exact persisted due marker. A regression changes the marker and proves the old claim cannot deliver it.
2. Suppressing an entire 200-row digest batch stranded the remaining rows. Tail scheduling now runs even when no summary is produced; a 201-row regression exercises that boundary.
3. Digest summaries lost their family/address policy identity and did not recheck all policy at queued SMTP delivery. Summaries now group by family/address/audience, retain the feature for unsubscribe headers, and recheck account standing, opt-outs, suppression, domain module and notification matrix at actual delivery. Tests cover each late policy change.
4. Late delivery tasks could resend originals already marked skipped/included in a digest. Both email and chat delivery return for terminal skipped rows.
5. Quiet-hour deferral could destroy a synchronous invitation/receipt body intentionally omitted from persistence. Redacted-body sends remain synchronous and bypass timing; a transport-level regression verifies one send, blank persisted bodies and no reminder.
6. Bounce ingestion was absent from the anonymous tenant-writer inventory and its implementation lived outside the guard's view-file discovery. Moved the HTTP implementation to views_bounce.py behind the original compatibility barrel and declared its verified-HMAC tenant writer. The complete AST source-gate guard now passes.
7. Several policy locks, payment webhook lookups and booking-purge queries bypassed the requested RBAC scope helper. They now use explicit tenant-scoped RBAC queries. Stripe additionally restricts matches to Stripe-owned rows; a regression refuses a stale Stripe handle on a Razorpay payment. Added signed Razorpay failure normalization coverage as well.
8. New booking routes and throttle hooks were missing from the exhaustive claim-session/pre-auth policies. Added declarations, feed route fixture arguments and a complete route-matrix regression. Feed settings refuse durable credential creation from claim credentials; member rescheduling is explicitly audited.
9. Feed settings could mint/rotate a token for a revoked owner because checking an unevaluated empty booking queryset did not enforce owner eligibility. Settings now explicitly check standing and hidden-tenant authority, recheck the locked owner before mutations, and return issued bearer URLs with private/no-store and no-referrer headers. Tests cover all settings methods and hidden tenants.
10. Private booking bearer URLs leaked through reverse-proxy/WSGI access logging and early Django 4xx logs. Extended calendar redaction to booking paths, suppressed matching nginx access logs and redacted formatted request messages/request extras before logging. Tests exercise real middleware, a Django LogRecord and the proxy configuration.
11. Booking cache/local editor/calendar-token state could survive an account switch. Query keys now include the personal recipient, and owner-keyed components reset local state. A real account-switch render regression verifies the previous owner's reservation/editor disappears.
12. A hidden, previously selected recurrence could still be submitted after its feature was disabled. Payload construction now checks the live feature flag. Added the feature-toggle regression and replaced the broken result separator with the intended em dash.
13. SOURCE-MAP and environment-reference omitted the new ownership/settings/throttle information. Updated both, clarified digest/timing contracts, and normalized every touched text file to UTF-8 LF.

Additional behavioral coverage verifies calendar issue/revoke controls, cancellation ICS sequence/status, and rescheduling against actual opening-hours exceptions while preserving the original pending reservation on refusal. Added a schema-generation regression for requests, successful responses and error schemas on the new surfaces.

### Validation

- `npx.cmd vitest run src/features/bookings src/features/notifications src/features/staff/BroadcastComposer.test.tsx src/features/staff/StaffBookingForm.recurring.test.tsx src/features/staff/StaffBookingForm.test.tsx src/features/staff/BookingsPanel.test.tsx`: **28 tests passed across 11 files**.
- `npx.cmd tsc -b`: **nine diagnostics, all in the five explicitly excluded pre-existing files; zero lane diagnostics**. Used npx.cmd because PowerShell blocks npx.ps1 under its current execution policy.
- `python -m py_compile` on every changed/new backend Python file: **96 files passed**.
- Direct check of the actual logging filter/formatter with event and booking URLs: passed (loaded without the unavailable Celery package bootstrap; Django request integration remains in the pending backend test).
- Full pure-AST `validate_source_gate_coverage()`: passed; tasks 41, webhooks 5, HTTP participants 35, lifecycle participants 6, object writers 115, fan-outs 14.
- LF/UTF-8, 300-line ceiling on touched production app/frontend files, identical AGENTS.md/CLAUDE.md and `git diff --check`: **passed**.
- Django/Postgres tests, migrations and generated schema execution remain **unverified** locally: Django is not installed and the Docker daemon is inaccessible. `codex doctor` also failed configuration/provider reachability, so nested CLI review was unavailable. No backend-runtime pass is claimed.

### Coordinator backend validation

Run through the isolated runner after merging the coordinated WP2 registry changes, regenerating API snapshots/types and recomputing the merged catalog checksum. All paths below are relative to backend/ as expected by scripts/dev.sh test:

```bash
./scripts/dev.sh test tests/bookings tests/notifications tests/payments/test_payment_failed_notification.py tests/payments/test_razorpay_provider.py tests/test_quiet_hours_digests.py tests/test_bounce_ingestion.py tests/operations/test_org_report_registry_coverage.py tests/accounts tests/test_log_setup.py tests/events/test_event_calendar_feeds.py tests/operations/test_reminder_sweeper.py tests/operations/test_reminder_services.py tests/operations/test_reminder_source_registry.py tests/test_notification_dispatch.py tests/test_notification_families_f3.py tests/test_notification_review_f3.py tests/tenant_migration tests/data_export tests/encryption tests/makerspaces/test_module_purge.py tests/makerspaces/test_origin_scope_p2b.py tests/makerspaces/test_tenant_servability_guard.py tests/test_apiclient_scope_registry.py tests/test_apiclient_scope_enforcement.py tests/test_apiclient_scope_grants.py
```

Also run Django checks, migration application and `makemigrations --check`, then the normal integrated frontend build. Database tests that assert the catalog checksum need the coordinator's merged checksum pin; this lane intentionally does not bless a checksum before all schema lanes land.

## Complete changed-file inventory (after review)

- Created: `LANE-PROGRESS.md`
- Modified: `backend/apps/accounts/claim_pre_auth_guard.py`
- Modified: `backend/apps/accounts/claim_routes_public.py`
- Modified: `backend/apps/accounts/rbac.py`
- Created: `backend/apps/accounts/rbac_bookings.py`
- Modified: `backend/apps/apiclients/scope_registry_routes.py`
- Created: `backend/apps/bookings/migrations/0011_calendar_feed.py`
- Modified: `backend/apps/bookings/models.py`
- Created: `backend/apps/bookings/models_booking.py`
- Created: `backend/apps/bookings/models_feed.py`
- Created: `backend/apps/bookings/models_spaces.py`
- Created: `backend/apps/bookings/serializers_reschedule.py`
- Modified: `backend/apps/bookings/services_bookings.py`
- Created: `backend/apps/bookings/services_recurrence.py`
- Created: `backend/apps/bookings/services_reschedule.py`
- Modified: `backend/apps/bookings/services_transitions.py`
- Created: `backend/apps/bookings/throttles_feed.py`
- Modified: `backend/apps/bookings/urls_admin.py`
- Modified: `backend/apps/bookings/urls_public.py`
- Created: `backend/apps/bookings/views_feed.py`
- Modified: `backend/apps/bookings/views_member.py`
- Created: `backend/apps/bookings/views_recurrence.py`
- Modified: `backend/apps/data_export/classification.py`
- Created: `backend/apps/data_export/classification_wp3.py`
- Created: `backend/apps/data_export/credentials_wp3.py`
- Modified: `backend/apps/data_export/datasets.py`
- Created: `backend/apps/data_export/datasets_wp3.py`
- Modified: `backend/apps/data_export/guards_credentials.py`
- Modified: `backend/apps/data_export/references_core.py`
- Modified: `backend/apps/encryption/management/commands/backfill_scoped_pii.py`
- Modified: `backend/apps/encryption/management/commands/decrypt_scoped_pii.py`
- Modified: `backend/apps/encryption/registry.py`
- Modified: `backend/apps/events/middleware.py`
- Created: `backend/apps/integrations/bounce_webhooks.py`
- Created: `backend/apps/integrations/digests.py`
- Modified: `backend/apps/integrations/dispatch_channels.py`
- Created: `backend/apps/integrations/dispatch_channels_delivery.py`
- Modified: `backend/apps/integrations/dispatch_delivery.py`
- Modified: `backend/apps/integrations/dispatch_outbox.py`
- Modified: `backend/apps/integrations/dispatch_policy.py`
- Modified: `backend/apps/integrations/email_templates_registry.py`
- Created: `backend/apps/integrations/email_templates_registry_wp3.py`
- Created: `backend/apps/integrations/migrations/0030_notification_timing_policy.py`
- Modified: `backend/apps/integrations/models.py`
- Created: `backend/apps/integrations/models_timing.py`
- Modified: `backend/apps/integrations/notification_catalog.py`
- Created: `backend/apps/integrations/quiet_hours.py`
- Created: `backend/apps/integrations/reminders_deferred.py`
- Created: `backend/apps/integrations/serializers_timing.py`
- Created: `backend/apps/integrations/timing_dispatch.py`
- Modified: `backend/apps/integrations/urls.py`
- Created: `backend/apps/integrations/views_bounce.py`
- Created: `backend/apps/integrations/views_timing.py`
- Modified: `backend/apps/makerspaces/capability_definitions.py`
- Created: `backend/apps/makerspaces/capability_definitions_wp3.py`
- Modified: `backend/apps/makerspaces/module_purge_collectors.py`
- Modified: `backend/apps/makerspaces/module_purge_collectors_single_model.py`
- Modified: `backend/apps/makerspaces/module_purge_plans.py`
- Modified: `backend/apps/makerspaces/origin_scope_model_lookups.py`
- Created: `backend/apps/notifications/broadcasts.py`
- Created: `backend/apps/notifications/migrations/0003_broadcasts_and_digests.py`
- Modified: `backend/apps/notifications/models.py`
- Created: `backend/apps/notifications/models_broadcasts.py`
- Modified: `backend/apps/notifications/models_inbox.py`
- Modified: `backend/apps/notifications/preferences.py`
- Created: `backend/apps/notifications/serializers_broadcasts.py`
- Modified: `backend/apps/notifications/serializers_inbox.py`
- Modified: `backend/apps/notifications/urls.py`
- Created: `backend/apps/notifications/views_broadcasts.py`
- Modified: `backend/apps/notifications/views_preferences.py`
- Modified: `backend/apps/operations/reminder_registry.py`
- Created: `backend/apps/payments/failure_notifications.py`
- Modified: `backend/apps/payments/providers/base.py`
- Modified: `backend/apps/payments/providers/razorpay.py`
- Modified: `backend/apps/payments/services_webhooks.py`
- Modified: `backend/apps/tenant_migration/audit_references_meta.py`
- Created: `backend/apps/tenant_migration/audit_references_wp3.py`
- Modified: `backend/apps/tenant_migration/authority_guards.py`
- Created: `backend/apps/tenant_migration/catalog_wp3.py`
- Modified: `backend/apps/tenant_migration/gate_policy_http.py`
- Modified: `backend/apps/tenant_migration/target_projection_fields.py`
- Created: `backend/apps/tenant_migration/target_projection_wp3.py`
- Modified: `backend/apps/tenant_migration/tenant_dump_authority.py`
- Modified: `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- Modified: `backend/apps/tenant_migration/tenant_dump_model_catalog.py`
- Modified: `backend/config/log_setup.py`
- Modified: `backend/tests/accounts/test_claim_session_contract_p7.py`
- Created: `backend/tests/bookings/test_booking_feed.py`
- Created: `backend/tests/bookings/test_member_reschedule.py`
- Created: `backend/tests/bookings/test_recurring_bookings.py`
- Created: `backend/tests/notifications/test_broadcasts.py`
- Created: `backend/tests/notifications/test_wp3_portability.py`
- Created: `backend/tests/notifications/test_wp3_route_guards.py`
- Created: `backend/tests/operations/test_org_report_registry_coverage.py`
- Created: `backend/tests/payments/test_payment_failed_notification.py`
- Created: `backend/tests/test_bounce_ingestion.py`
- Created: `backend/tests/test_quiet_hours_digests.py`
- Modified: `docs/SOURCE-MAP.md`
- Created: `docs/WP3-NOTIFICATIONS-BOOKINGS.md`
- Modified: `docs/environment-reference.md`
- Modified: `frontend/nginx.conf`
- Created: `frontend/src/features/bookings/BookingCalendar.test.tsx`
- Created: `frontend/src/features/bookings/BookingCalendar.tsx`
- Created: `frontend/src/features/bookings/BookingReschedule.test.tsx`
- Created: `frontend/src/features/bookings/BookingReschedule.tsx`
- Modified: `frontend/src/features/bookings/MyBookings.test.tsx`
- Modified: `frontend/src/features/bookings/MyBookings.tsx`
- Created: `frontend/src/features/notifications/AnnouncementFeed.tsx`
- Modified: `frontend/src/features/notifications/MemberNotifications.tsx`
- Created: `frontend/src/features/notifications/PreferenceCentre.digest.test.tsx`
- Modified: `frontend/src/features/notifications/PreferenceCentre.tsx`
- Modified: `frontend/src/features/staff/BookingDrawer.tsx`
- Modified: `frontend/src/features/staff/BookingsPanel.tsx`
- Created: `frontend/src/features/staff/BroadcastComposer.test.tsx`
- Created: `frontend/src/features/staff/BroadcastComposer.tsx`
- Modified: `frontend/src/features/staff/MakerspaceSettingsPanel.tsx`
- Created: `frontend/src/features/staff/NotificationTimingSettings.tsx`
- Created: `frontend/src/features/staff/StaffBookingForm.recurring.test.tsx`
- Modified: `frontend/src/features/staff/StaffBookingForm.tsx`
- Modified: `frontend/src/features/staff/StaffTabContent.tsx`
- Modified: `frontend/src/features/staff/panels/NotificationInbox.tsx`
- Modified: `frontend/src/features/staff/staffBookingApi.ts`
- Modified: `frontend/src/lib/features.ts`
