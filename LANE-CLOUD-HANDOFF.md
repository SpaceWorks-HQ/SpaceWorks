# Cloud lane handoff (2026-10-10)

All edits are unstaged in `lane/cloud`. No database or frontend tests were executed in this continuation.
TypeScript build/type checking, Python AST/global-name inspection, Bash syntax inspection and
`git diff --check` completed without reported errors. Instruction twins remain byte-identical;
generated API artifacts were not changed. ENV_SURFACE and its reference match all 247 backend names.

## Files created or modified

- Modified: `.env.example`
- Modified: `.env.production.example`
- Created: `LANE-CLOUD-HANDOFF.md`
- Modified: `LANE-PROGRESS.md`
- Modified: `backend/.env.example`
- Modified: `backend/apps/accounts/oidc_browser_http.py`
- Modified: `backend/apps/accounts/social_apple.py`
- Modified: `backend/apps/accounts/social_jwt.py`
- Modified: `backend/apps/accounts/views_oidc_browser.py`
- Modified: `backend/apps/accounts/views_phone.py`
- Modified: `backend/apps/accounts/views_social.py`
- Created: `backend/apps/accounts/views_social_helpers.py`
- Created: `backend/apps/accounts/views_social_identities.py`
- Created: `backend/apps/accounts/views_social_login.py`
- Modified: `backend/apps/admin_api/views_integration_health.py`
- Modified: `backend/apps/admin_api/views_makerspaces.py`
- Modified: `backend/apps/integrations/dispatch.py`
- Modified: `backend/apps/integrations/health.py`
- Created: `backend/apps/integrations/health_chat.py`
- Created: `backend/apps/integrations/health_status.py`
- Modified: `backend/apps/integrations/push_apns.py`
- Modified: `backend/apps/integrations/push_fcm.py`
- Modified: `backend/apps/integrations/telegram.py`
- Modified: `backend/apps/integrations/views_push.py`
- Modified: `backend/apps/makerspaces/admin_subdomains.py`
- Modified: `backend/apps/makerspaces/config_views.py`
- Modified: `backend/apps/operations/management/commands/run_scheduled_tasks.py`
- Modified: `backend/apps/operations/views_health.py`
- Modified: `backend/apps/operations/views_live.py`
- Modified: `backend/apps/payments/admin.py`
- Modified: `backend/config/unfold.py`
- Created: `backend/tests/accounts/test_apple_token_conditions.py`
- Created: `backend/tests/accounts/test_identity_provider_cache_conditions.py`
- Created: `backend/tests/accounts/test_oidc_provider_failures.py`
- Created: `backend/tests/payments/test_connect_configuration_conditions.py`
- Modified: `backend/tests/payments/test_connect_webhook_signatures.py`
- Created: `backend/tests/payments/test_control_payment_settings_audit.py`
- Created: `backend/tests/test_cloud_domain_audit.py`
- Created: `backend/tests/test_cloud_integration_health_conditions.py`
- Created: `backend/tests/test_cloud_manifest_environment.py`
- Modified: `backend/tests/test_cloud_openapi_errors.py`
- Created: `backend/tests/test_cloud_platform_permissions.py`
- Created: `backend/tests/test_cloud_probe_conditions.py`
- Created: `backend/tests/test_cloud_settings_conditions.py`
- Modified: `backend/tests/test_env_surface_drift.py`
- Created: `backend/tests/test_ghcr_retention_failures.py`
- Created: `backend/tests/test_host_updater_behavior.py`
- Created: `backend/tests/test_hosting_cache_conditions.py`
- Modified: `backend/tests/test_integration_health.py`
- Created: `backend/tests/test_phone_provider_conditions.py`
- Created: `backend/tests/test_push_malformed_responses.py`
- Created: `backend/tests/test_push_registration_conditions.py`
- Created: `backend/tests/test_scheduler_concurrency.py`
- Modified: `backend/tests/test_scheduler_control_visibility.py`
- Created: `backend/tests/test_smtp_failure_conditions.py`
- Created: `backend/tests/test_telegram_failure_privacy.py`
- Modified: `docs/SOURCE-MAP.md`
- Created: `docs/cloud-completeness.md`
- Modified: `frontend/src/features/staff/IntegrationHealthPanel.test.tsx`
- Modified: `frontend/src/features/staff/IntegrationHealthPanel.tsx`
- Created: `frontend/src/features/staff/PlatformConfigurationStates.test.tsx`
- Modified: `frontend/src/features/staff/PlatformEmailPanel.tsx`
- Modified: `frontend/src/features/staff/PlatformSocialAuthPanel.tsx`
- Modified: `frontend/src/features/staff/PlatformStripeConnectPanel.tsx`
- Created: `frontend/src/features/staff/panels/EmailLogPanel.test.tsx`
- Modified: `frontend/src/features/staff/panels/EmailLogPanel.tsx`
- Modified: `scripts/update.sh`

## Tests added or expanded (coordinator must run)

Python names below are function IDs; parametrized cases must all be exercised.
Run these with `./scripts/dev.sh test` in isolated infrastructure, then the affected existing
identity, email, notification, hosting, update, scheduling and payments suites. Run the
frontend tests with Vitest, including the three new/expanded console test files.

- `backend/tests/accounts/test_apple_token_conditions.py`
  - `test_apple_accepts_literal_or_hashed_nonce`
  - `test_invalid_apple_claims_are_rejected_not_a_500`
- `backend/tests/accounts/test_identity_provider_cache_conditions.py`
  - `test_non_object_jwks_keys_are_unavailable_and_connection_closed`
  - `test_jwks_cache_outage_fetches_fresh_keys_and_closes_connection`
  - `test_key_rotation_refetches_when_the_cached_kid_is_absent`
  - `test_discovery_cache_outage_does_not_skip_issuer_validation`
- `backend/tests/accounts/test_oidc_provider_failures.py`
  - `test_unavailable_token_endpoint_is_sanitized_and_closed`
  - `test_mid_body_failure_is_unavailable`
  - `test_invalid_grant_or_token_is_rejected_and_closed`
  - `test_valid_token_is_returned_and_response_closed`
  - `test_body_read_is_part_of_the_elapsed_time_budget`
- `backend/tests/payments/test_connect_configuration_conditions.py`
  - `test_self_host_platform_settings_and_onboarding_return_404`
  - `test_unconfigured_managed_onboarding_returns_503_without_minting_state`
- `backend/tests/payments/test_connect_webhook_signatures.py`
  - `test_empty_secret_is_the_same_generic_error`
- `backend/tests/payments/test_control_payment_settings_audit.py`
  - `test_control_payment_settings_change_records_actor_scope_and_field_names`
  - `test_audit_failure_rolls_back_the_credential_update`
- `backend/tests/test_cloud_domain_audit.py`
  - `test_setting_and_clearing_domain_records_before_and_after`
  - `test_self_host_approval_reports_disabled_provisioning_not_existing_subdomain`
- `backend/tests/test_cloud_integration_health_conditions.py`
  - `test_platform_smtp_fallback_is_visible_and_unreadable_tenant_password_is_not`
  - `test_native_push_failure_is_scoped_and_contains_no_credentials`
  - `test_sms_unconfigured_and_health_errors_do_not_disclose_exception_text`
  - `test_unreadable_destination_credentials_are_reported_unconfigured`
  - `test_naive_worker_heartbeat_is_normalized_to_utc`
- `backend/tests/test_cloud_manifest_environment.py`
  - `test_effective_overlay_environment_keeps_the_complete_production_posture`
  - `test_env_examples_expose_observability_and_reference_the_complete_surface`
- `backend/tests/test_cloud_openapi_errors.py`
  - `test_cloud_route_documents_its_error_responses (expanded route/code matrix)`
- `backend/tests/test_cloud_platform_permissions.py`
  - `test_platform_routes_refuse_managers_members_and_anonymous`
  - `test_a_client_key_does_not_establish_a_superadmin_actor`
- `backend/tests/test_cloud_probe_conditions.py`
  - `test_invalid_bearer_on_a_probe_returns_401`
  - `test_metrics_bearer_survives_broker_outage`
  - `test_live_broker_fallback_and_eager_suppression`
  - `test_failed_subscription_closes_the_allocated_pubsub`
- `backend/tests/test_cloud_settings_conditions.py`
  - `test_negative_proxy_count_refuses_startup`
  - `test_axes_and_drf_must_agree_on_the_proxy_chain`
  - `test_redis_and_database_cache_selection`
  - `test_forwarded_proto_setting_changes_djangos_secure_request_detection`
  - `test_sentry_unset_never_imports_the_sdk`
  - `test_sentry_configured_has_both_integrations_and_no_default_pii`
- `backend/tests/test_env_surface_drift.py`
  - `test_on_box_defaults_are_overridden_by_production_manifests (expanded cloud/service matrix)`
  - `test_consumer_side_on_box_fallbacks_are_overridden_by_production_manifests (expanded cloud/service matrix)`
  - `test_manifests_do_not_set_variables_the_backend_never_reads (expanded cloud/service matrix)`
  - `test_the_proxy_posture_is_explicit_in_every_production_manifest (expanded cloud/service matrix)`
- `backend/tests/test_ghcr_retention_failures.py`
  - `test_failed_or_malformed_listing_vetoes_all_deletion`
  - `test_delete_failure_is_bounded_and_other_stale_versions_are_still_attempted`
- `backend/tests/test_host_updater_behavior.py`
  - `test_success_finishes_and_releases_both_locks`
  - `test_failed_deployment_rolls_back_and_resets_the_version_marker`
  - `test_failed_provider_check_or_pull_keeps_the_previous_release`
  - `test_noop_never_takes_a_backup_or_replaces_containers`
  - `test_single_box_uses_its_running_app_for_readiness_and_pulls_its_image`
  - `test_persisted_single_box_layer_is_respected`
  - `test_a_live_update_owner_is_refused_before_any_provider_call`
  - `test_a_dead_update_owner_is_recovered`
- `backend/tests/test_hosting_cache_conditions.py`
  - `test_managed_save_and_delete_invalidate_the_verified_domain_cache`
  - `test_bulk_update_does_not_emit_save_signal_and_expired_cache_refetches`
  - `test_managed_save_never_auto_verifies_a_pending_custom_domain`
  - `test_invalid_platform_suffix_is_refused_without_mutating_the_space`
- `backend/tests/test_integration_health.py`
  - `test_integration_health_subsection_failure_is_fail_safe`
- `backend/tests/test_phone_provider_conditions.py`
  - `test_daily_sms_cap_applies_on_self_host_and_managed`
  - `test_sms_counter_failure_keeps_auth_available`
  - `test_otp_resend_cooldown_survives_an_unsuccessful_provider`
  - `test_phone_request_throttle_returns_429`
- `backend/tests/test_push_malformed_responses.py`
  - `test_fcm_rejects_a_service_account_with_the_wrong_shape`
  - `test_fcm_malformed_oauth_does_not_reach_delivery`
  - `test_fcm_malformed_error_does_not_retire_a_device`
  - `test_apns_malformed_error_is_retryable`
  - `test_undecryptable_push_credentials_are_configuration_errors`
- `backend/tests/test_push_registration_conditions.py`
  - `test_missing_fingerprint_key_returns_503_and_creates_no_device`
  - `test_another_account_cannot_claim_the_same_token`
  - `test_push_registration_rate_limit_returns_429`
- `backend/tests/test_scheduler_concurrency.py`
  - `test_second_runner_skips_an_in_flight_claim`
  - `test_scheduler_failure_keeps_secrets_out_of_the_control_row_and_stderr`
- `backend/tests/test_scheduler_control_visibility.py`
  - `test_sidebar_has_every_platform_integration_and_the_scheduler`
- `backend/tests/test_smtp_failure_conditions.py`
  - `test_smtp_failure_notifies_staff_once_and_never_exposes_secret`
  - `test_broker_failure_records_failed_row_without_echoing_the_connection_url`
- `backend/tests/test_telegram_failure_privacy.py`
  - `test_direct_telegram_failure_logs_only_the_exception_class`
- `frontend/src/features/staff/IntegrationHealthPanel.test.tsx`
  - shows SMS configuration and a scoped native-push failure
- `frontend/src/features/staff/PlatformConfigurationStates.test.tsx`
  - shows an unconfigured SMTP host explicitly
  - shows both dormant social providers
  - does not label a partial Connect configuration as configured
- `frontend/src/features/staff/panels/EmailLogPanel.test.tsx`
  - filters skipped email, displays its reason and offers no retry

## Migrations, decisions and skipped work

- No migrations, models, module keys or feature keys were created. Dependencies: none.
- Existing mid-flight scheduler visibility, hosting-condition tests, Connect-signature tests,
  PROJECT-HISTORY entry and INVARIANTS block were verified. Scheduler sidebar was completed;
  Connect empty-secret coverage was added. Rerun those mid-flight tests as well.
- Owner decisions remain audit section 18: client-IP/proxy topology; cron exposure/audit policy;
  HSTS defaults; host-allowlist outage policy; probe access/content; rate limits and stream
  reauthorization; headers and Sentry tagging; update status/cadence/downgrade/publication policy;
  beat/cron coordination; Caddy live routing; startup proxy requirement; tombstone CI profiles;
  existing module-off contracts; identity switch/lockout gating; credential-key rotation;
  Apple developer operations; persisted platform test-send/check state.
- Push no-device false-SENT accounting remains the explicit owner decision from the plan.
- Paid/live-account validation and Apple client-secret generation/revocation were skipped.
  Local transport tests cannot validate deployed credentials, provider balances or quotas.
- Schema snapshot/type regeneration is deliberately left to the coordinator, as instructed.
- Independent Codex CLI review is unavailable: doctor could not resolve config or reach the
  provider. Coordinator review and database execution remain required.

## Merge risks and outside-task defects

- `backend/apps/payments/admin.py` is a payments-lane hotspot. The change only wraps the
  existing credential service and its new field-name-only audit row in one transaction.
- Splits cannot be committed separately here because lane instructions prohibit commits.
  The coordinator may separate the social/health splits when preparing commits.
- Existing `tests/test_host_orchestration_surface_h1a.py` uses a `/usr/bin/python3` stub that
  may not exist in the backend image. The prior session reported this failure; it was not
  rerun and that outside-task test was not edited.
