# w2-notify progress

## Review pass

Review-and-fix completed; changes remain unstaged. Read AGENTS.md, the original
brief, main-checkout research plans, the inherited LANE-PROGRESS.md and full diff.
The specifically named w2-notify-PROGRESS.md was absent; this is that handoff.
No git state-changing commands or backend database tests were run.

Defects found and fixed:

- Requester inbox fan-out ignored explicit recipient selection and the membership receives_notifications switch. Both now apply to inbox rows.
- Booking requester switches were ignored without email. Explicit inbox delivery now uses the same tenant/per-space effective switch as email.
- Printing and API-access owners without email received no inbox row. Added bounded identity-based summaries; explicit inbox text overrides token-bearing email text.
- Matrix hardware/printing inbox defaults diverged from the proposal. Restored OFF, preserving legacy direct staff alerts and avoiding duplicate matrix-owned edges.
- Legacy on_commit writes used stale module/gate state; optional mirror failures
  could roll back the shared alert. Recheck under tenant_write; isolate mirror savepoint.
- Retry service trusted a spoofable instance tenant and relied on view-level gates.
  Lock the authorized tenant row; enforce active actor, module and source gates inside
  the service. Control requeue uses generation snapshots and truthful partial counts.
- Personal access allowed revoked memberships through delegated grants. Deny those memberships before the independent staff branch.
- Stored opt-outs stopped applying after runtime tombstoning. Retained policy rows still govern delivery. Family module availability is checked before enabling prefs.
- New internal adapter/policy/purge queries lacked an explicit RBAC boundary. Added
  exact-tenant policy scope in rbac; custody hygiene remains effective for hidden tenants.
- Browser URL normalization could turn local-looking links into external navigation.
  Reject backslashes/control characters in backend and frontend; added render tests.
- Backup object guard mistook UUID event_key for storage. Added a non-object exemption.
- Retention missed platform logs and accepted invalid limits. Apply the same bounded
  terminal windows and reject invalid limits; preserve unread/in-flight/recent failures.
- Platform bounce/complaint suppression was missing. Added separate nullable-platform
  keyed hashes, DB uniqueness, superadmin-only manual control and audited add/delete.
- Suppressed platform recovery dispatch bypassed PII minimization. Redact address,
  subject and body in that skipped-log branch too.
- Write-route OpenAPI omitted freeze/recovery errors. Added 423/503 declarations.
- Existing env documentation did not explain unsubscribe proxy/HTTPS or retention
  batching. Updated environment-reference, SOURCE-MAP and protocol/inbox docs.
- 38 inherited changed files had CRLF. Normalized all changed text to LF; repaired
  handoff placeholders. AGENTS.md and CLAUDE.md remain byte-identical and unedited.

Verification completed locally:

- npx.cmd tsc -b: exit 0.
- Relevant Vitest: eight files, 68 tests passed, exit 0.
- python -m py_compile: all changed backend Python files (81 files, passed).
- Source-gate AST validation passed: 38 tasks, 4 webhooks, 34 HTTP participants,
  6 lifecycle declarations, 114 object declarations, 12 fan-outs.
- git diff --check clean; index empty; touched files <=300 lines; LF-only.
- No backend test pass is claimed. Django/DB migration/schema checks need coordinator.

## Migrations and dependencies

- backend/apps/notifications/migrations/0002_personal_inbox.py:
  notifications.0001_initial + swappable AUTH_USER_MODEL.
- backend/apps/integrations/migrations/0029_personal_delivery_controls.py:
  integrations.0028_research_notification_families + swappable AUTH_USER_MODEL.
  Review updated this unshipped migration for nullable platform suppression and its
  partial uniqueness constraint; no additional migration was created.
The actual leaf directories were checked. New models/fields have export/User-FK,
projection/catalog/authority, encryption and module-purge declarations; the backup
object exemption is also covered. No new module key or environment variable.

## Coordinator remaining work / skips / decisions

Run the new backend files listed below via ./scripts/dev.sh test, plus existing
notification/emails/workers/F3, encryption, F1/operations, module purge/separability,
backup object-field coverage and tenant-migration guards. Include
tests/test_notification_requeue_action.py and tests/backup/test_object_field_coverage.py.
Run makemigrations --check --dry-run, system/OpenAPI validation and regenerate
frontend/openapi-schema.json plus frontend/src/generated/api.ts in integration.
These generated files were deliberately not edited.
Codex doctor cannot resolve managed configuration/connectivity here; external CLI
review was unavailable. The authorized review was performed directly.
Automatic provider bounce webhooks skipped: SMTP is the only existing transport;
manual tenant and platform controls implement the stated fallback. Retention defaults
are 90 days for read/sent/skipped and 365 for failed; longer overrides, digests,
quiet hours, provider transports and member push delivery are outside this lane.
No owner product decision blocks this scope. Optional future retention overrides need
an owner-approved policy. No merge/push/staging/commit performed.

## Outside-task defects

Wave-1 recipients_selection.FEATURE_MODULES binds the payments notification family
to the optional online rail. This can suppress core-ledger debt notices when the rail
is off. Left unchanged because it predates and spans the F3/ledger lane; coordinator
should assign that correction with ledger-specific regression coverage.
The inherited Telegram destination form promised retired accept/reject buttons;
that lane change now correctly describes outbound alerts and staff-console decisions.

## New backend test files and tests (coordinator must run)

### backend/tests/test_delivery_controls_f2.py

- `test_delivery_list_unifies_channels_filters_and_is_tenant_scoped`
- `test_retry_generation_prevents_repeated_clicks_even_if_enqueue_fails_again`
- `test_retry_refuses_skips_and_cannot_reach_foreign_logs`
- `test_send_test_only_addresses_actor_or_an_explicit_scoped_destination`
- `test_email_retry_uses_same_generation_and_delivery_rechecks_suppression`
- `test_retry_channel_off_returns_400_without_enqueue_or_audit`
- `test_retry_of_a_row_already_removed_by_retention_is_a_typed_not_found`

### backend/tests/test_email_preferences_f2.py

- `test_signed_one_click_needs_no_login_and_only_mutes_its_bound_family`
- `test_unsubscribe_refuses_forged_expired_wrong_salt_and_missing_form_value`
- `test_headers_are_https_one_click_and_omitted_for_mandatory_mail`
- `test_suppression_blocks_new_and_queued_mail_including_transactional`
- `test_personal_email_opt_out_is_rechecked_before_delivery_and_safety_cannot_be_muted`
- `test_manual_suppression_api_is_scoped_audited_and_does_not_echo_address`
- `test_signed_unsubscribe_cannot_mutate_a_frozen_tenant`

### backend/tests/test_notification_hygiene_f2.py

- `test_new_models_fields_user_edges_projection_and_source_gate_catalogues_are_complete`

### backend/tests/test_notification_retention_f2.py

- `test_retention_keeps_unread_inflight_recent_failures_and_other_tenants`
- `test_f1_runs_retention_without_reminder_sources_and_batches_are_bounded`
- `test_retention_respects_tenant_freeze`
- `test_platform_email_retention_is_bounded_and_keeps_inflight_and_recent_failures`
- `test_retention_rejects_invalid_batch_sizes_before_deleting_rows`

### backend/tests/test_notification_review_f2.py

- `test_matrix_requester_selection_and_blanket_opt_out_apply_to_personal_inbox`
- `test_booking_requester_switch_applies_without_an_email_address`
- `test_event_adapter_respects_requester_selection_for_an_actual_registration`
- `test_printing_inbox_is_email_independent_and_omits_public_tokens`
- `test_api_access_owner_without_email_still_receives_an_inbox_row`
- `test_legacy_direct_alerts_survive_the_planned_matrix_default`
- `test_legacy_on_commit_emitter_rechecks_the_tenant_before_writing`
- `test_personal_mirror_failure_keeps_the_original_legacy_alert`
- `test_service_retry_cannot_follow_a_spoofed_cross_tenant_instance`
- `test_service_retry_checks_module_and_source_gate_before_any_mutation`
- `test_saved_opt_out_survives_notifications_runtime_tombstone`
- `test_preferences_cannot_enable_a_family_whose_domain_module_is_off`
- `test_revoked_personal_membership_is_not_restored_by_delegated_staff_actions`
- `test_suppression_still_applies_to_hidden_tenant_custody_mail`
- `test_inbox_link_rejects_browser_normalization_bypasses`

### backend/tests/test_personal_inbox_f2.py

- `test_personal_list_count_and_read_are_isolated_from_other_members_and_tenants`
- `test_read_all_changes_only_callers_rows_and_is_idempotent`
- `test_module_and_member_feature_off_return_400_and_restricted_user_is_refused`
- `test_staff_and_machine_only_users_read_their_own_rows_without_member_feature`
- `test_account_only_owner_can_read_explicit_rows_but_revoked_members_cannot`
- `test_matrix_writes_requester_wording_and_deduplicates_staff_owner`
- `test_preference_update_is_audited_and_cannot_enable_a_tenant_disabled_channel`
- `test_inbox_opt_out_is_independent_of_email_and_no_email_is_needed`
- `test_legacy_only_staff_alerts_have_personal_read_state_without_widening_old_visibility`

### backend/tests/test_platform_email_suppression_f2.py

- `test_platform_suppression_blocks_new_and_queued_recovery_mail_without_retaining_pii`
- `test_platform_and_tenant_suppression_do_not_cross_custody_boundaries`
- `test_platform_suppression_uniqueness_is_database_enforced`
- `test_platform_control_is_superadmin_only_hides_tenant_rows_and_audits_add_delete`

### backend/tests/test_webhook_schema_f2.py

- `test_v2_has_stable_names_and_identifiers_without_template_or_secret_fields`
- `test_existing_destinations_keep_the_legacy_envelope`
- `test_every_matrix_event_has_a_schema_and_catalogue_matches_the_documented_snapshot`
- `test_v2_refuses_bool_foreign_family_fields_and_uses_snapshot_time_on_retries`
- `test_destination_edit_without_new_field_preserves_opted_in_v2_and_create_defaults_v1`

## Extended tests and frontend tests

- backend/tests/encryption/test_leak_sweep.py: inbox title/summary encrypted DB coverage.
- backend/tests/test_notification_families_f3.py:
  test_catalog_extends_stable_families_with_external_channels_off_and_personal_inbox_on.
- frontend/src/features/notifications/PersonalInbox.review.test.tsx: member acknowledgement
  and unread refresh, plus five unsafe-link render regressions (6 cases).
- frontend/src/features/notifications/NotificationControls.test.tsx: preferences/disabled
  channel/error cache, generation retry and self delivery test.
- frontend/src/features/notifications/personalQueryKeys.test.ts: account cache isolation,
  stable refresh keys, signed-out/malformed sessions and no tokens in cache keys.
- frontend/src/features/staff/panels/NotificationInbox.test.tsx: read/read-all isolation.
- frontend/src/features/staff/StaffDock.test.tsx: personal unread endpoint.
- frontend/src/features/staff/staffTabs.test.ts: machine/handover personal inbox access.
- frontend/src/features/staff/staffTabs.moduleGates.test.ts: moved module gate coverage.
Review extended test_notification_retention_f2.py with bounded platform cleanup and
invalid-limit cases; test_notification_hygiene_f2.py with event-key exemption; and
corrected test_personal_inbox_f2.py to assert explicit-summary precedence.

## Every created or modified file (entire lane, including inherited changes)

- `LANE-PROGRESS.md`
- `backend/apps/accounts/rbac.py`
- `backend/apps/accounts/rbac_notifications.py`
- `backend/apps/admin_api/serializers_notification_destinations.py`
- `backend/apps/admin_api/views_notification_destinations.py`
- `backend/apps/apiclients/notifications.py`
- `backend/apps/backup/archive_objects.py`
- `backend/apps/bookings/notifications.py`
- `backend/apps/data_export/classification_domain.py`
- `backend/apps/data_export/classification_platform.py`
- `backend/apps/data_export/datasets.py`
- `backend/apps/data_export/references_core.py`
- `backend/apps/encryption/management/commands/backfill_scoped_pii.py`
- `backend/apps/encryption/management/commands/decrypt_scoped_pii.py`
- `backend/apps/encryption/registry.py`
- `backend/apps/events/notifications.py`
- `backend/apps/hardware_requests/notifications.py`
- `backend/apps/integrations/admin.py`
- `backend/apps/integrations/admin_notifications.py`
- `backend/apps/integrations/admin_suppression.py`
- `backend/apps/integrations/delivery_serializers.py`
- `backend/apps/integrations/delivery_services.py`
- `backend/apps/integrations/delivery_tests.py`
- `backend/apps/integrations/delivery_views.py`
- `backend/apps/integrations/dispatch.py`
- `backend/apps/integrations/dispatch_delivery.py`
- `backend/apps/integrations/dispatch_outbox.py`
- `backend/apps/integrations/dispatch_policy.py`
- `backend/apps/integrations/email.py`
- `backend/apps/integrations/email_preferences.py`
- `backend/apps/integrations/migrations/0029_personal_delivery_controls.py`
- `backend/apps/integrations/models.py`
- `backend/apps/integrations/models_destinations.py`
- `backend/apps/integrations/models_email.py`
- `backend/apps/integrations/models_notifications.py`
- `backend/apps/integrations/models_suppression.py`
- `backend/apps/integrations/notification_catalog.py`
- `backend/apps/integrations/notification_enums.py`
- `backend/apps/integrations/notifications_research.py`
- `backend/apps/integrations/notify.py`
- `backend/apps/integrations/push.py`
- `backend/apps/integrations/suppression_views.py`
- `backend/apps/integrations/tasks.py`
- `backend/apps/integrations/urls.py`
- `backend/apps/integrations/webhook_schema.py`
- `backend/apps/integrations/webhooks.py`
- `backend/apps/machines/service_printing_emails.py`
- `backend/apps/makerspaces/capabilities.py`
- `backend/apps/makerspaces/membership_notifications.py`
- `backend/apps/makerspaces/module_purge_collectors.py`
- `backend/apps/makerspaces/module_purge_plans.py`
- `backend/apps/notifications/access.py`
- `backend/apps/notifications/emit.py`
- `backend/apps/notifications/inbox.py`
- `backend/apps/notifications/legacy_inbox.py`
- `backend/apps/notifications/migrations/0002_personal_inbox.py`
- `backend/apps/notifications/models.py`
- `backend/apps/notifications/models_inbox.py`
- `backend/apps/notifications/preferences.py`
- `backend/apps/notifications/retention.py`
- `backend/apps/notifications/serializers_inbox.py`
- `backend/apps/notifications/urls.py`
- `backend/apps/notifications/views_inbox.py`
- `backend/apps/notifications/views_preferences.py`
- `backend/apps/operations/reminder_sweeper.py`
- `backend/apps/tenant_migration/authority_guards.py`
- `backend/apps/tenant_migration/gate_policy_http.py`
- `backend/apps/tenant_migration/gate_policy_tasks.py`
- `backend/apps/tenant_migration/target_projection_rows.py`
- `backend/apps/tenant_migration/tenant_dump_authority_supplement.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `backend/apps/tenant_migration/tenant_dump_model_catalog.py`
- `backend/tests/encryption/test_leak_sweep.py`
- `backend/tests/test_delivery_controls_f2.py`
- `backend/tests/test_email_preferences_f2.py`
- `backend/tests/test_notification_families_f3.py`
- `backend/tests/test_notification_hygiene_f2.py`
- `backend/tests/test_notification_retention_f2.py`
- `backend/tests/test_notification_review_f2.py`
- `backend/tests/test_personal_inbox_f2.py`
- `backend/tests/test_platform_email_suppression_f2.py`
- `backend/tests/test_webhook_schema_f2.py`
- `docs/SOURCE-MAP.md`
- `docs/api-client-protocol.md`
- `docs/environment-reference.md`
- `docs/notification-inbox.md`
- `docs/webhooks-v2.md`
- `docs/webhooks-v2.schema.json`
- `frontend/src/features/members/MemberArea.tsx`
- `frontend/src/features/notifications/DeliveryLogScreen.tsx`
- `frontend/src/features/notifications/MemberNotifications.tsx`
- `frontend/src/features/notifications/NotificationControls.test.tsx`
- `frontend/src/features/notifications/PersonalInbox.review.test.tsx`
- `frontend/src/features/notifications/PersonalInbox.tsx`
- `frontend/src/features/notifications/PreferenceCentre.tsx`
- `frontend/src/features/notifications/SuppressionAdmin.tsx`
- `frontend/src/features/notifications/personalQueryKeys.test.ts`
- `frontend/src/features/notifications/personalQueryKeys.ts`
- `frontend/src/features/staff/StaffDock.test.tsx`
- `frontend/src/features/staff/StaffTabLoaders.tsx`
- `frontend/src/features/staff/StaffWorkspace.tsx`
- `frontend/src/features/staff/notificationDestinationTypes.ts`
- `frontend/src/features/staff/notificationDestinations/DestinationForm.tsx`
- `frontend/src/features/staff/panels/DeliveryLogPanel.tsx`
- `frontend/src/features/staff/panels/NotificationInbox.test.tsx`
- `frontend/src/features/staff/panels/NotificationInbox.tsx`
- `frontend/src/features/staff/staffAccess.ts`
- `frontend/src/features/staff/staffTabs.moduleGates.test.ts`
- `frontend/src/features/staff/staffTabs.test.ts`
- `frontend/src/features/staff/useUnreadNotifications.ts`
- `frontend/src/lib/features.ts`
- `w2-notify-PROGRESS.md`
