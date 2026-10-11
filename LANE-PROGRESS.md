# w2-members lane handoff

Implementation complete; all edits are unstaged in this worktree. No add/commit/merge/push was run.

Completed: optional local-calendar renewal opening, durable same-charge checkout retries,
one successor after settlement/free renewal, promised grace, borrowing-only lapse, F1
reminder discovery and F3 owner-only lifecycle mail. Four feature keys default off.
Added profile editing, owned browser/native session revoke (stable JWT session lineage),
audited cancel/leave with shared cleanup, and queued subject ZIP/JSON exports reusing the
existing field classification, tenant scope, storage accounting and retention.
Added staff renewal fields and member account controls, including query cleanup on identity
changes and slug changes. Added explicit route schemas, claim policies, Celery task imports,
source-gate registrations, scheduler parity, export/import field policies and user docs.

Review fixes: real provider failures are now observable after charge commit; initial attempt
state survives worker death; existing tenant boundaries are reused; promised grace survives
policy changes; paid predecessors with staff successors and fully scheduled histories cannot
starve new work. Account caches/drafts cannot carry the previous sign-in identity.

Validation performed: TypeScript `tsc -b` passed. Five focused Vitest files passed, 23 tests.
Python AST parse and the <=300-line touched-file check passed. Source-gate fanout AST guard
passed (13 participants); claim policy catalog contains 111 route names. `git diff --check`
had no whitespace errors. Database tests were NOT run; Django/Docker/Postgres are unavailable
in this sandbox. No backend test or migration execution is claimed. Codex CLI review gates
could not run because `codex doctor` failed config/network access; independent source reviews
were completed and their findings fixed.

Coordinator remains responsible for isolated database tests, makemigrations --check,
OpenAPI/schema regeneration, catalog schema SHA repin (base was already RECOMPUTE), full
review/QA, verification and committing. Suggested database run includes all new test files
below plus tests/accounts/test_refresh_rotation.py, test_oidc_browser_collisions_p7.py,
test_claim_routes.py, test_device_auth.py, test_mfa_workflows.py, tests/makerspaces/
test_membership_plans.py, tests/data_export, tests/tenant_migration/test_source_gate_guards.py,
tests/test_notification_families_f3.py, tests/test_notification_family_edges_f3.py,
tests/test_scheduled_tasks.py and tests/test_capabilities.py.

Migration: backend/apps/makerspaces/migrations/0081_membership_renewal_automation.py;
dependency: (makerspaces,0080_membership_admission), verified actual leaf before writing.
No new model, module key, accounts.User FK, generated schema or AGENTS/CLAUDE edit.

Skips/defaults: no erasure, pause, proration, stored-card autopay, verified email/login-phone
change or self-service plan changes; those are outside the specified scope/defaults. Plan
changes stay staff initiated. Lapse never auto-revokes a membership/User. Legacy pre-upgrade
access tokens lack session lineage and expire at their original short lifetime after their
refresh is revoked; first refresh adopts the new marker and the UI explains the limit.
Exports omit credential fields, other identities, unproven anonymous records, tenant
configuration and object bytes. No owner product decision remains necessary for this lane.

Outside-task defect noticed and repaired: Wave1 admission routes were missing claim-policy
entries and the reachable-route pin still omitted admission/security routes. Added those
policies and updated the pin to 111. No other confirmed outside-task defect is left open.

## Files created or modified

- `LANE-PROGRESS.md`
- `backend/apps/accounts/authentication.py`
- `backend/apps/accounts/claim_routes_member.py`
- `backend/apps/accounts/claim_routes_public.py`
- `backend/apps/accounts/serializers_refresh.py`
- `backend/apps/accounts/serializers_self_service.py`
- `backend/apps/accounts/services_device_tokens.py`
- `backend/apps/accounts/tokens.py`
- `backend/apps/accounts/views_profile.py`
- `backend/apps/accounts/views_self_service.py`
- `backend/apps/accounts/web_sessions.py`
- `backend/apps/admin_api/serializers_membership_plans.py`
- `backend/apps/audit/presentation_catalog.py`
- `backend/apps/audit/presentation_catalog_dynamic.py`
- `backend/apps/audit/presentation_catalog_member_account.py`
- `backend/apps/data_export/apps.py`
- `backend/apps/data_export/classification_domain.py`
- `backend/apps/data_export/services.py`
- `backend/apps/data_export/storage.py`
- `backend/apps/data_export/subject_archive.py`
- `backend/apps/data_export/subject_boundary.py`
- `backend/apps/data_export/subject_selectors.py`
- `backend/apps/data_export/subject_services.py`
- `backend/apps/data_export/subject_tasks.py`
- `backend/apps/data_export/subject_views.py`
- `backend/apps/data_export/tasks.py`
- `backend/apps/data_export/urls_subject.py`
- `backend/apps/data_export/views.py`
- `backend/apps/integrations/email_templates_registry_research.py`
- `backend/apps/integrations/notification_catalog.py`
- `backend/apps/makerspaces/capabilities.py`
- `backend/apps/makerspaces/member_dashboard_service.py`
- `backend/apps/makerspaces/membership_plan_services.py`
- `backend/apps/makerspaces/membership_renewal_charges.py`
- `backend/apps/makerspaces/membership_renewal_notifications.py`
- `backend/apps/makerspaces/membership_renewal_reminders.py`
- `backend/apps/makerspaces/membership_renewals.py`
- `backend/apps/makerspaces/membership_revocation.py`
- `backend/apps/makerspaces/membership_self_service.py`
- `backend/apps/makerspaces/migrations/0081_membership_renewal_automation.py`
- `backend/apps/makerspaces/models_membership_plans.py`
- `backend/apps/makerspaces/models_memberships.py`
- `backend/apps/makerspaces/request_access.py`
- `backend/apps/makerspaces/self_service_access.py`
- `backend/apps/makerspaces/urls.py`
- `backend/apps/makerspaces/views_self_service.py`
- `backend/apps/operations/management/commands/run_scheduled_tasks.py`
- `backend/apps/operations/reminder_registry.py`
- `backend/apps/tenant_migration/audit_references_meta_membership.py`
- `backend/apps/tenant_migration/gate_policy_tasks.py`
- `backend/apps/tenant_migration/target_projection_fields.py`
- `backend/apps/tenant_migration/tenant_dump_authority_supplement.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `backend/tests/accounts/test_account_self_service.py`
- `backend/tests/accounts/test_claim_routes.py`
- `backend/tests/accounts/test_oidc_browser_collisions_p7.py`
- `backend/tests/accounts/test_refresh_rotation.py`
- `backend/tests/data_export/test_subject_access.py`
- `backend/tests/makerspaces/test_membership_renewal_automation.py`
- `backend/tests/makerspaces/test_membership_renewal_mail.py`
- `backend/tests/makerspaces/test_membership_self_service.py`
- `docs/member-account-renewals.md`
- `frontend/src/AppRoutes.tsx`
- `frontend/src/features/members/MemberAccount.test.tsx`
- `frontend/src/features/members/MemberAccountExports.tsx`
- `frontend/src/features/members/MemberAccountMembership.tsx`
- `frontend/src/features/members/MemberAccountPage.tsx`
- `frontend/src/features/members/MemberAccountProfile.tsx`
- `frontend/src/features/members/MemberAccountSessions.tsx`
- `frontend/src/features/members/MemberArea.tsx`
- `frontend/src/features/members/memberAccountApi.ts`
- `frontend/src/features/staff/MembershipPlansSection.test.tsx`
- `frontend/src/features/staff/MembershipPlansSection.tsx`
- `frontend/src/features/staff/MembershipRenewalFields.test.tsx`
- `frontend/src/features/staff/MembershipRenewalFields.tsx`
- `frontend/src/features/staff/membershipPlansApi.ts`
- `frontend/src/lib/features.ts`

## Backend tests added

- `backend/tests/accounts/test_account_self_service.py`
  - `test_member_edits_contact_fields_and_audits_names_only`
  - `test_profile_refuses_identity_and_authority_fields`
  - `test_profile_rejects_non_object_payload`
  - `test_session_list_is_paginated_owned_and_marks_current`
  - `test_rotation_preserves_session_and_revoke_invalidates_access_and_refresh`
  - `test_cannot_revoke_another_users_web_session`
  - `test_legacy_refresh_is_listed_revoked_or_adopted_on_next_refresh`
  - `test_device_revoke_is_owned_and_preserves_other_grants`
  - `test_account_routes_answer_400_with_module_off`
  - `test_account_feature_off_and_cross_tenant`
  - `test_mfa_session_marker_does_not_bypass_credential_version`
- `backend/tests/data_export/test_subject_access.py`
  - `test_archive_contains_only_own_tenant_rows_and_no_other_identity`
  - `test_staff_authoring_other_persons_request_is_not_subject_ownership`
  - `test_export_request_queue_poll_download_and_audits`
  - `test_other_member_other_tenant_and_staff_cannot_download_subject_job`
  - `test_throttle_survives_cache_reset_and_request_cannot_choose_subject`
  - `test_module_and_feature_off_return_400_and_create_nothing`
  - `test_leaving_while_job_is_queued_fails_without_storage_disclosure`
  - `test_expired_job_cannot_get_signed_download`
  - `test_subject_export_decrypts_owners_scoped_pii`
  - `test_pending_export_is_recovered_when_broker_enqueue_fails`
- `backend/tests/makerspaces/test_membership_renewal_automation.py`
  - `test_renewal_window_uses_makerspace_local_day`
  - `test_offline_settlement_auto_opens_exactly_one_next_term`
  - `test_free_or_no_charge_tracking_renewal_extends_without_a_rail`
  - `test_grace_protects_borrowing_until_boundary_without_revoking`
  - `test_prepaid_future_term_is_not_current_before_its_start`
  - `test_failed_charge_retries_are_bounded_and_do_not_duplicate_debt`
  - `test_checkout_failure_keeps_recorded_charge_and_retries_same_payment`
  - `test_cancellation_prevents_charging_and_opening`
  - `test_membership_module_off_makes_automation_inert`
  - `test_local_reminders_are_deduplicated_and_stop_after_cancellation`
  - `test_new_term_month_end_preserves_local_time_across_dst`
  - `test_plan_serializer_rejects_unbounded_timing_and_bad_reminders`
  - `test_promised_grace_survives_automation_disable`
  - `test_completed_staff_successor_does_not_starve_a_due_member`
  - `test_f1_boundary_is_reused_without_a_second_gate`
  - `test_discovery_skips_fully_scheduled_history_with_a_small_budget`
  - `test_worker_loss_recovers_initial_checkout_and_duplicate_callbacks_are_inert`
- `backend/tests/makerspaces/test_membership_renewal_mail.py`
  - `test_lifecycle_mail_only_reaches_the_terms_owner`
  - `test_lifecycle_feature_off_schedules_nothing`
- `backend/tests/makerspaces/test_membership_self_service.py`
  - `test_cancel_is_audited_idempotent_and_keeps_current_term`
  - `test_cancel_requires_reason`
  - `test_leave_preserves_account_and_history_and_does_not_flag_vouchers`
  - `test_sole_manager_cannot_leave_and_another_manager_allows_it`
  - `test_cancel_cannot_mutate_foreign_tenant`
  - `test_membership_off_answers_400`

Existing backend tests updated: test_current_all_active_tree_has_a_complete_claim_matrix
(test_claim_routes.py); test_concurrent_refresh_rotation_mints_one_usable_descendant
(test_refresh_rotation.py); test_oidc_transition_revokes_claim_session_and_every_refresh
(test_oidc_browser_collisions_p7.py), distinguishing markers from refresh credentials.

## Frontend tests added or updated

- `frontend/src/features/members/MemberAccount.test.tsx`
  - edits member profile fields and refreshes the query
  - revokes the selected current session and reports sign-out
  - requires a reason and confirmation before leaving
  - requests an export and shows a short-lived download link
  - makes no account requests when the feature and membership module are off
  - shows profile failures without submitting fabricated profile values
  - replaces a stale profile draft when fresh server data arrives
  - clears the previous identity's cached account before completing sign-in
  - resets the leave notice when navigating to another makerspace
- `frontend/src/features/staff/MembershipPlansSection.test.tsx`
  - lists plans with their interval and price and creates a new one
  - edits an existing plan through PATCH and toggles activity
  - validates like the serializer
  - shows the member's terms, starts a new one on the chosen plan and cancels the active one
- `frontend/src/features/staff/MembershipRenewalFields.test.tsx`
  - keeps opt-in off and normalizes configured local-day reminders
  - bounds retries, grace and each reminder offset

Existing MemberArea and MemberAreaAdmission tests were also run unchanged.

## Review pass

Reviewed the brief, repository/global instructions, the original handoff, tracked
diff and new files. All changes remain unstaged; git operations were read-only.

Defects fixed:

- Renewal/export worker reads and reminder/audit ownership lookups bypassed the
  RBAC scope helpers. They now use scheduled-work or actor tenant scopes,
  including locked reads and correlated successor queries. Shared export
  claim/finalize/failure helpers now accept and retain the personal worker's
  scoped queryset without changing portable tenant-migration caller semantics;
  a regression test rejects a foreign job claim before any state/audit write.
- The personal-export object writer lacked a source-gate declaration. Added
  `run_subject_export` to the object-writer policy and checked gate totality.
- The new one-to-one `MembershipTerm.renewed_from` lacked a deployment-global
  uniqueness disposition and dump authority entry. Added relationship remapping
  and field preservation, with a negative drift-guard regression test.
- Export claims, grace promises and checkout-attempt claims changed durable
  state without their own audit rows. Added transactional audit entries and
  presentation labels; tests check lifecycle and idempotence.
- A full export throttle could hide module/feature-off behind HTTP 429. Export
  creation now checks its tenant feature/module gates before throttling, so the
  required HTTP 400 survives a previous successful request.
- Account OpenAPI errors did not describe DRF field errors/auth failures, and
  the export creation body could disappear from the schema. Added shared error
  schemas, an explicit empty-object request and route/schema regression tests.
- Renewal cancellation survived departure and a later fresh admission. The
  existing audited activation transaction now clears that previous lifecycle's
  cancellation; cancellation within the current lifecycle still stops renewal.
- A storage quota rejection became `internal_error`. Personal exports now
  recognize the quota seam's DRF validation error, report `quota_exceeded`, and
  tests check that cleanup runs and no archive is published.
- Completed predecessors with staff/automatic successors could occupy the
  bounded renewal queue throughout grace and starve another due member. The
  queue now revisits them when expiry work is due; regression tests use a
  one-row budget for active and expired predecessors.
- Source-map, feature/module and environment documentation omitted new paths
  or reused export settings; invariants still said settlement never opens a
  successor. Updated the documentation and added the account/renewal guide.
- Removed CRLF from touched files. UTF-8/LF, mojibake, file ceilings and the
  AGENTS.md/CLAUDE.md byte-identical guard were checked.

Verification:

- `python -m py_compile`: all 66 touched backend Python files passed.
- Source-gate static coverage passed: 41 tasks, 4 webhooks, 33 HTTP writers,
  6 lifecycle writers, 115 object writers and 13 fan-outs.
- `npx.cmd tsc -b`: passed.
- `npx.cmd vitest run`: MemberAccount, MemberArea, MemberAreaAdmission,
  MembershipPlansSection and MembershipRenewalFields passed (23 tests / 5 files).
- `git diff --check`: passed; the index is empty; all 88 touched files checked
  as UTF-8 with LF, and touched production code stays within 300 lines.
- Backend runtime tests, migration checks, OpenAPI regeneration and catalog
  digest repinning could not run here: Django is not installed and Docker's
  daemon is unavailable. `codex doctor` also failed config-home/provider
  reachability checks, so the external Codex gate could not run.

Coordinator backend tests (isolated Postgres 16 runner, no concurrent review):

```bash
./scripts/dev.sh test tests/accounts tests/makerspaces tests/data_export tests/tenant_migration tests/payments/test_billing_due_p5.py tests/test_capabilities.py tests/test_scheduled_tasks.py tests/test_notification_families_f3.py tests/test_notification_family_edges_f3.py tests/test_notification_review_f3.py tests/test_audit_presentation.py
```

The new focused paths are `tests/accounts/test_account_self_service.py`,
`tests/accounts/test_account_self_service_schema.py`,
`tests/data_export/test_subject_access.py`,
`tests/makerspaces/test_membership_renewal_automation.py`,
`tests/makerspaces/test_membership_renewal_mail.py`,
`tests/makerspaces/test_membership_self_service.py`, and
`tests/tenant_migration/test_membership_renewal_projection.py`.

Before integration, run `makemigrations --check`, regenerate the OpenAPI JSON
snapshot/generated TypeScript with `spectacular --format openapi-json`, repin
the catalog digest, and complete the repository's review/QA gates. The migration
is chained to the actual `0080` leaf. No new models or accounts.User FK fields
were introduced by this lane; existing export classifications/FK declarations
are reused.
