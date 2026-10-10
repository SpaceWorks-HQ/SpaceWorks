# Research Wave 0: notifications and API clients

Worktree: `research/w0-notify`. All changes stay unstaged; the coordinator commits.

## Completed

- D9: the unread poll and both mark-read mutations share one TanStack Query key.
  Added an integration-style Vitest test for immediate badge refresh and tenant isolation.
- D10: removed unimplemented admin/report scopes from the supported vocabulary,
  grant catalog and browser allowlist; direct model issuance rejects them too.
  Existing stored grants remain inert (no automatic
  conversion to `legacy:v1` or other authority). The system check now rejects unused or
  unknown declared scopes as well as missing protected routes. Updated affected tests.

- D11: API-access resolution now uses the `api_access` notification matrix category
  (not a capability or module key), preserving email/Telegram defaults and gaining
  destinations, per-room quota, channel mutes, module gates and delivery logs. The staff
  master switch stops rooms/push while requester email retains its own matrix control.
  Private resolution notes stay in requester email.
- D12: every lifecycle adapter explicitly carries domain IDs. Webhooks retain existing
  fields/header semantics and add `structured` version 1 with a canonical event name,
  positive integer IDs, makerspace ID and stable event time. Template contact fields and
  credentials cannot enter the structured IDs. Updated protocol documentation, including
  the direct `reports.scheduled_report` sender.
- Read-only delegated review completed with no actionable findings. No review edits.

## Remaining

- Coordinator database tests, migration drift check, schema regeneration and external CLI
  review/QA gates. No remaining lane implementation work.

## Coordinator validation

- Database tests cannot run in this sandbox. No backend test has been run or passed here.
- Frontend checks executed: TypeScript `tsc -b --pretty false` exited 0; Vitest ran the new
  inbox test (2 cases, 0 failures) and existing API-client panel/picker tests (7 cases,
  0 failures). The initial inbox-test issues were fixed before these results.
- Python AST syntax checks completed for all 29 changed/new Python files. `git diff --check`
  is clean and every changed/new source or test file stays at or below 300 lines.
- Run `./scripts/dev.sh test tests/test_api_key_resolution_notifications_w0.py
  tests/test_apiclient_retired_scopes_w0.py tests/test_notification_payload_adapters_w0.py
  tests/test_webhook_payload_w0.py tests/test_webhook_channel.py
  tests/test_apiclient_scope_enforcement.py tests/test_apiclient_scope_grants.py
  tests/test_apiclient_validation.py tests/test_end_to_end_prd_gaps.py
  tests/tenant_migration/test_api_client_contract_d8.py tests/test_notification_fanout.py
  tests/test_notification_rules_api.py tests/test_notification_rules_perf.py
  tests/test_notification_channels_k1.py tests/test_notification_dispatch.py`.
- Also run the existing notifications tests in `tests/bookings`, `tests/events`,
  `tests/maintenance` and `tests/makerspaces/test_membership_notifications_j3.py`.
- Check `makemigrations --check --dry-run` in the coordinator's configured backend.
- Regenerate OpenAPI snapshot/types after the notification catalog migration.
- Codex CLI preflight failed (home/config resolution and provider network reachability);
  the coordinator must complete the external review gate.

## Decisions and exclusions

- No new inbound admin/report API access: the research reserves inbound write authority
  for an owner decision. Remove dead scopes instead of widening authorization.
- Preserve existing webhook fields and add a separately versioned structured object.
  Destination opt-in for an incompatible replacement envelope remains future product work.
- No git state changes, database test execution, or generated API file edits.

## Migration

- `backend/apps/integrations/migrations/0026_notificationfeature_api_access.py`
  depends only on `integrations.0025_webhook_channel` (the actual leaf inspected before
  writing it). Alters `feature` choices on NotificationPreference,
  NotificationDeliveryLog, NotificationRecipient and ChatTemplate. No new model or
  stored API-scope migration; historical retired grants remain inert and detectable.

## Tests added (all backend tests await coordinator execution)

- `frontend/src/features/staff/panels/NotificationInbox.test.tsx`:
  `refreshes immediately after Mark read`, `refreshes immediately after Mark all read`.
- `backend/tests/test_apiclient_retired_scopes_w0.py`:
  `test_retired_scopes_cannot_be_granted_or_advertised`,
  `test_historical_retired_grants_do_not_authorize_any_registered_route`,
  `test_direct_issuance_rejects_retired_scopes_before_creating_a_client`,
  `test_supported_scope_catalog_exactly_covers_route_scopes_and_legacy`,
  `test_system_check_rejects_scope_catalog_drift`.
- `backend/tests/test_api_key_resolution_notifications_w0.py`:
  `test_resolution_uses_matrix_destinations_and_quota_without_private_chat_content`,
  `test_resolution_channel_mutes_stop_both_email_and_telegram`,
  `test_resolution_obeys_module_and_quota_blocks`,
  `test_staff_master_mute_keeps_requester_email_but_stops_rooms`,
  `test_resolution_provider_failure_is_logged_and_does_not_escape`,
  `test_resolution_rollback_sends_nothing`,
  `test_api_access_catalog_preserves_defaults_and_can_be_muted_via_scoped_api`.
- `backend/tests/test_notification_payload_adapters_w0.py`:
  `test_hardware_adapter_identifies_request_and_charge`,
  `test_booking_adapter_identifies_booking_and_space`,
  `test_event_adapter_identifies_occurrence_series_and_registration`,
  `test_maintenance_adapter_identifies_machine_schedule_and_completion_log`,
  `test_membership_adapters_identify_request_and_membership`,
  `test_printing_adapter_identifies_kernel_request`,
  `test_structured_ids_refuse_contact_credentials_and_invalid_identifiers`.
- `backend/tests/test_webhook_payload_w0.py`:
  `test_every_catalog_event_has_a_versioned_unambiguous_name` (all matrix events plus reports),
  `test_legacy_queued_row_uses_delivery_creation_time_without_inventing_ids`,
  `test_payload_ids_scope_and_event_time_survive_fanout_queue_delay_and_retry`.
- Existing tests updated to use active scopes and the actual bare webhook event/header.
  Removed the obsolete browser/admin-write concurrency case: retired grants now reject
  at field validation before row locking. The valid-scope concurrency test remains.

## Owner decisions and unrelated findings

- No owner decision blocks these fixes. Inbound admin-write authority and incompatible
  webhook envelope replacement remain the research's deferred product decisions.
- Existing hardware-submitted and kernel-printing chat builders include email/phone in
  their staff text, despite the signed-webhook invariant's statement that no contact
  fields travel. This lane preserves existing text for compatibility and guarantees the
  new structured object carries only IDs/time; a separate privacy review should resolve
  that existing discrepancy.
- `docs/INVARIANTS.md` still mentions retired admin/report scopes as superadmin-only.
  The precise supported vocabulary is now documented in `docs/api-client-protocol.md`.
  The coordinator should reconcile the large invariant document (not edited here under
  the lane's 300-line ceiling).
