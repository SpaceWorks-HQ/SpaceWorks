# w1-security handoff

Implementation complete; all changes are unstaged. Coordinator validation remains.

## Completed

- Encrypted TOTP enrollment, QR/manual provisioning, +/-1 step verification, replay protection, ten hashed recovery codes, password reauthentication, audit and credential invalidation.
- Password, Google/Apple, OIDC, phone, native and Django control logins enforce the second factor before issuing authority. IdP MFA claims are not already parsed, so social/OIDC always require the factor.
- Mandatory superadmin enrollment; per-space `security.staff_mfa_required` for local and organization-derived staff; optional member MFA.
- Scoped staff invitation creation/list/resend/revoke/accept with hashed single-use expiring tokens, encrypted address, current role/inviter authority, generic accept responses, throttles and safe email-off copyable links.
- Frontend enrollment, recovery management, two-step login, settings switch, staff invitation panel and accept page; declarations, schemas, classification and tenant catalogs updated.
- Split auth serializers/session views, environment documentation and three existing test files to respect the file ceiling.

## Validation completed

- `npx.cmd tsc -b`: passed.
- `npm.cmd test -- --run`: passed, 120 files / 477 tests (including seven new frontend tests).
- `npm.cmd run build`: passed, including the production/PWA build.
- `python -m py_compile` on all 85 touched backend Python files: passed.
- Django-independent `validate_source_gate_coverage()`: passed (tasks 36, webhooks 4, HTTP 33, lifecycle 6, objects 114, fanouts 10).
- Environment declaration/documentation coverage: all 276 registered variables covered across the two reference documents.
- `git diff --check`, empty index, untouched generated schema/client and byte-identical AGENTS.md/CLAUDE.md: verified.
- All touched files remain at or below 300 lines except `backend/config/settings.py`, the explicitly accepted repository exception.

## Coordinator work / skipped checks

- Run the seven new backend security test modules listed below, the updated control/auth/source-gate tests, drift guards, and the required isolated full backend suite. NO database test or Django runtime check was run in this lane: Docker/Postgres are inaccessible and host Python has no Django.
- Apply migrations and regenerate `frontend/openapi-schema.json` / `frontend/src/generated/api.ts` (intentionally left untouched per lane instructions).
- Run the mandatory separate review and browser QA. `codex doctor` failed CODEX_HOME/config resolution and provider network reachability; no separate CLI or agent review is claimed.
- No implementation item or owner product decision remains. No state-changing git command was used. Coordinator owns staging/commits; owner owns merging/pushing.

## Migrations

- `backend/apps/accounts/migrations/0026_mfa_staff_invitations.py`: dependencies accounts.0025_user_is_tenant_dump_stub and makerspaces.0076_station_operator_leases; creates UserMFA, MFAChallenge and StaffInvitation.
- `backend/apps/makerspaces/migrations/0077_staff_invitations_feature.py`: dependency makerspaces.0076_station_operator_leases; backfills staff.invitations enabled. No module key added.

## Outside-task defect

- `backend/apps/makerspaces/limits_usage.py` shared `_staff` quota counts every active-user membership, including community members. Left unchanged; invitation promotion of an existing membership does not add another quota unit.

## New backend tests (not run)

### backend/tests/accounts/test_mfa_concurrency.py

- `test_concurrent_challenges_cannot_consume_the_same_totp_step`
- `test_token_minting_waits_for_enrollment_and_cannot_adopt_an_unproven_version`

### backend/tests/accounts/test_mfa_crypto.py

- `test_rfc6238_sha1_vectors_truncated_to_six_digits`
- `test_accepts_one_adjacent_step`
- `test_refuses_outside_one_step`
- `test_refuses_replay_and_older_steps_after_future_window_was_used`
- `test_rejects_malformed_codes`
- `test_uri_encodes_identity_and_explicit_algorithm`

### backend/tests/accounts/test_mfa_enforcement.py

- `test_superadmin_cannot_mint_tokens_without_enrollment_even_on_member_surface`
- `test_space_policy_invalidates_prior_access_and_refresh_but_not_member_sessions`
- `test_staff_policy_covers_organization_authority`
- `test_required_staff_cannot_disable_mfa`
- `test_staff_authority_is_rechecked_at_challenge_completion`
- `test_control_password_session_cannot_reach_admin_until_mfa_and_recovers_safely`
- `test_control_challenge_cannot_be_consumed_on_api`
- `test_global_mfa_enrollment_remains_available_when_staff_tenant_is_frozen`

### backend/tests/accounts/test_mfa_login_protocols.py

- `test_google_sign_in_requires_second_factor_even_with_unparsed_idp_amr`
- `test_oidc_browser_callback_requires_local_second_factor`
- `test_phone_first_factor_is_not_enough_for_an_enrolled_account`
- `test_native_login_waits_for_mfa_then_preserves_device_delivery`
- `test_browser_challenge_is_bound_to_first_factor_origin`

### backend/tests/accounts/test_mfa_workflows.py

- `test_password_success_with_mfa_has_no_tokens_until_second_factor`
- `test_totp_replay_refused_across_distinct_challenges_and_failure_commits`
- `test_recovery_code_single_use_and_hashed_storage`
- `test_superadmin_enrollment_encrypts_secret_and_shows_ten_codes_once`
- `test_challenge_invalidated_before_token_issuance`
- `test_regenerate_and_disable_require_password_and_invalidate_old_sessions`
- `test_failed_attempts_commit_and_exhaust_challenge`
- `test_spent_mfa_challenges_join_cleanup_but_live_ones_remain`

### backend/tests/accounts/test_security_throttles.py

- `test_mfa_verification_throttles_ip_challenge_and_account`
- `test_challenge_cache_key_never_contains_bearer`
- `test_invitation_accept_throttle_does_not_require_a_real_account`
- `test_mfa_management_and_invite_routes_declare_separate_budgets`
- `test_non_mapping_json_body_is_a_validation_error`

### backend/tests/accounts/test_staff_invitations.py

- `test_email_off_yields_copyable_link_and_new_account_membership`
- `test_existing_account_is_linked_without_password_change_or_duplicate`
- `test_delivery_failure_keeps_invitation_and_link_without_logging_provider_secrets`
- `test_unavailable_invitation_has_one_generic_response`
- `test_resend_rotates_bearer_and_revoke_prevents_acceptance`
- `test_scoped_lists_and_cross_tenant_role_cannot_grant_authority`
- `test_feature_off_answers_400_and_never_sends`
- `test_custom_handover_role_can_be_invited_and_mfa_enforcement_applies`
- `test_revoke_does_not_require_permission_to_regrant_a_changed_role`
- `test_resend_revalidates_against_current_sender`
- `test_accept_failure_does_not_enumerate_account_and_commits_attempts`
- `test_existing_enrolled_account_must_prove_second_factor`
- `test_frozen_tenant_cannot_accept_an_invitation_or_create_an_account`
- `test_accept_rechecks_current_authority_and_never_reactivates_revoked_users`

## Frontend tests (passed)

- `frontend/src/features/auth/MfaFlow.test.tsx`: does not finish sign-in after a rejected second factor; shows QR and manual key, then waits for recovery-code acknowledgement; accepts a recovery code without exposing enrollment controls.
- `frontend/src/features/auth/StaffInvitationAcceptPage.test.tsx`: submits bearer from the fragment and clears it after acceptance; renders the same generic refusal without suggesting whether an account exists.
- `frontend/src/features/staff/panels/StaffInvitations.test.tsx`: creates a scoped invitation, offers the copyable link, and refreshes the list; revokes and resends through the selected makerspace.

## Existing tests moved / adjusted

- Existing image admin cases moved into `backend/tests/test_admin_images.py`; hidden audit cases into `backend/tests/test_admin_hidden_audit_scope.py`; payment-control cases into `backend/tests/payments/test_platform_payment_control.py`.
- Existing control tests use an explicit verified-MFA session helper; existing tenant source-gate global-auth test enrolls the superadmin; environment drift test reads both reference documents.

## Modified files

- `backend/apps/accounts/authentication.py`
- `backend/apps/accounts/claim_pre_auth_guard.py`
- `backend/apps/accounts/claim_routes_auth.py`
- `backend/apps/accounts/models.py`
- `backend/apps/accounts/schemas_auth.py`
- `backend/apps/accounts/serializers.py`
- `backend/apps/accounts/services_challenge_purge.py`
- `backend/apps/accounts/services_device_tokens.py`
- `backend/apps/accounts/tokens.py`
- `backend/apps/accounts/urls.py`
- `backend/apps/accounts/views_device.py`
- `backend/apps/accounts/views_oidc_browser.py`
- `backend/apps/accounts/views_phone.py`
- `backend/apps/accounts/views_session.py`
- `backend/apps/accounts/views_social_login.py`
- `backend/apps/admin_api/urls.py`
- `backend/apps/backup/management/commands/recover_superadmin.py`
- `backend/apps/backup/settings_policy.py`
- `backend/apps/data_export/classification_platform.py`
- `backend/apps/data_export/references_core.py`
- `backend/apps/makerspaces/capabilities.py`
- `backend/apps/tenant_migration/authority_guards.py`
- `backend/apps/tenant_migration/gate_policy_http.py`
- `backend/apps/tenant_migration/tenant_dump_catalog.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `backend/config/admin_access.py`
- `backend/config/settings.py`
- `backend/config/urls.py`
- `backend/tests/accounts/test_password_reset_invalidation.py`
- `backend/tests/accounts/test_walk_in_transition_p7.py`
- `backend/tests/makerspaces/test_archive_request_admin.py`
- `backend/tests/makerspaces/test_control_makerspace_admin.py`
- `backend/tests/payments/test_platform_payment_settings_validation.py`
- `backend/tests/tenant_migration/test_source_gate.py`
- `backend/tests/test_admin_access.py`
- `backend/tests/test_admin_custom_views.py`
- `backend/tests/test_admin_hidden_scope.py`
- `backend/tests/test_admin_monitoring.py`
- `backend/tests/test_admin_parity_actions.py`
- `backend/tests/test_apiclients.py`
- `backend/tests/test_control_integration_audit.py`
- `backend/tests/test_environment_reference_drift.py`
- `backend/tests/test_hardware_admin_actions.py`
- `backend/tests/test_makerspace_archive_impact.py`
- `backend/tests/test_notification_requeue_action.py`
- `backend/tests/test_operations_admin_actions.py`
- `backend/tests/test_password_change.py`
- `backend/tests/test_scheduler_control_visibility.py`
- `docs/PROJECT-STATUS.md`
- `docs/environment-reference.md`
- `frontend/src/AppRoutes.tsx`
- `frontend/src/features/auth/SocialSignInButtons.tsx`
- `frontend/src/features/auth/socialSdk.ts`
- `frontend/src/features/members/MemberArea.tsx`
- `frontend/src/features/members/MemberAuthPanel.tsx`
- `frontend/src/features/staff/LoginPanel.tsx`
- `frontend/src/features/staff/MakerspaceSettingsPanel.tsx`
- `frontend/src/features/staff/StaffApp.tsx`
- `frontend/src/features/staff/panels/Users.tsx`
- `frontend/src/features/staff/useStaffSession.ts`
- `frontend/src/lib/features.ts`

## Created files

- `LANE-PROGRESS.md`
- `backend/apps/accounts/control_mfa.py`
- `backend/apps/accounts/mfa_challenges.py`
- `backend/apps/accounts/mfa_crypto.py`
- `backend/apps/accounts/mfa_policy.py`
- `backend/apps/accounts/mfa_recovery.py`
- `backend/apps/accounts/mfa_sessions.py`
- `backend/apps/accounts/migrations/0026_mfa_staff_invitations.py`
- `backend/apps/accounts/models_mfa.py`
- `backend/apps/accounts/models_staff_invitations.py`
- `backend/apps/accounts/serializers_login.py`
- `backend/apps/accounts/serializers_mfa.py`
- `backend/apps/accounts/serializers_payload.py`
- `backend/apps/accounts/serializers_refresh.py`
- `backend/apps/accounts/serializers_staff_invitations.py`
- `backend/apps/accounts/services_mfa.py`
- `backend/apps/accounts/services_staff_invitations.py`
- `backend/apps/accounts/staff_invitation_acceptance.py`
- `backend/apps/accounts/staff_invitation_delivery.py`
- `backend/apps/accounts/templates/accounts/control_mfa.html`
- `backend/apps/accounts/throttles_mfa.py`
- `backend/apps/accounts/urls_security.py`
- `backend/apps/accounts/views_login.py`
- `backend/apps/accounts/views_mfa.py`
- `backend/apps/accounts/views_profile.py`
- `backend/apps/accounts/views_refresh.py`
- `backend/apps/accounts/views_staff_invitations.py`
- `backend/apps/makerspaces/migrations/0077_staff_invitations_feature.py`
- `backend/tests/accounts/mfa_helpers.py`
- `backend/tests/accounts/test_mfa_concurrency.py`
- `backend/tests/accounts/test_mfa_crypto.py`
- `backend/tests/accounts/test_mfa_enforcement.py`
- `backend/tests/accounts/test_mfa_login_protocols.py`
- `backend/tests/accounts/test_mfa_workflows.py`
- `backend/tests/accounts/test_security_throttles.py`
- `backend/tests/accounts/test_staff_invitations.py`
- `backend/tests/payments/test_platform_payment_control.py`
- `backend/tests/test_admin_hidden_audit_scope.py`
- `backend/tests/test_admin_images.py`
- `docs/environment-operations.md`
- `frontend/src/features/auth/MfaAccountPage.tsx`
- `frontend/src/features/auth/MfaFlow.test.tsx`
- `frontend/src/features/auth/MfaFlow.tsx`
- `frontend/src/features/auth/StaffInvitationAcceptPage.test.tsx`
- `frontend/src/features/auth/StaffInvitationAcceptPage.tsx`
- `frontend/src/features/auth/mfaApi.ts`
- `frontend/src/features/staff/panels/StaffInvitations.test.tsx`
- `frontend/src/features/staff/panels/StaffInvitations.tsx`
