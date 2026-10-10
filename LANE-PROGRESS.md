# Lane 9c - replay server

Branch lane/9c, based on lane/9b. All repository edits remain unstaged. No commits,
merges, checkouts, index changes or database tests were performed.

## Completed

- Compared phase 9c, the phase-9 overview, stage1-p9 and HANDOVER-CODEX section 7
  against the actual 9a/9b tree and migration leaves. Review copy:
  docs/plans/2026-09-03-forward-plan/reviews/stage1-p9c.md (gitignored).
- Added ReplayCommand, immutable ownership, stream/predecessor constraints, canonical
  envelope validation and fingerprints; no persisted payload, QR or PII.
- Added Station-cookie + signed-human-lease replay authentication without normal
  login; live account/RBAC/module/feature/session/version checks at both boundaries.
- Added atomic prepare/evidence identity, direct staging presigns, short claims,
  stale recovery, token fencing, shared workflow dispatch, stable result references,
  transactional success/audit and safe typed failures. Storage/unknown faults retry.
  Each committed claim also writes kiosk.replay_claimed without its fencing token, so
  a transient execution has an audit trail even when no domain effect is committed.
- Added database-only finalized evidence reuse inside domain transactions, avoiding
  the existing completed finalizer's S3 delete while request/evidence locks are held.
  The adapter does not take attachment locks early; existing workflows retain their
  request/loan-before-evidence order and authoritative retention lock checks.
  Replay does not hold extra makerspace/credential locks across dispatch: that would
  invert existing quota lock order. Authority is reloaded immediately before dispatch.
  Concurrent prepares serialize through the owner unique constraint and locked retry.
- Added bounded expiry/terminal-leaf cleanup, daily beat/beat-less scheduling, timing
  checks, independent throttles and whole-tenant purge ordering.
- Registered omitted coordination, actor edge, all-DROP authority, exact field graph,
  source-gate participants, token origin ownership and every replay audit ID path.
- Re-blessed schema digest to 28e593005a2cc5df32e4a4a61aac2735c21e473e75222ebdd72b6c3c81e44d17.
  Static graph reconstruction reproduced the previous digest exactly before adding
  the reviewed 31-field model. Live Django catalog validation remains for coordinator.
- Added drf-spectacular request/result/error/auth schemas and handwritten frontend
  prepare/execute helpers; updated INVARIANTS and SOURCE-MAP.

## Migration

backend/apps/hardware_requests/migrations/0025_kiosk_replay.py depends on:
- hardware_requests/0024_anonymous_request_submission
- makerspaces/0074_station_operator_leases (plan's 0073 reference was stale)
- evidence/0006_evidence_retention
- swappable accounts.User dependency

## Coordinator work remaining

- Copy stage1-p9c.md from this worktree to the main checkout's requested review path;
  the main path is outside this lane's writable root.
- Run Django checks and makemigrations --check --dry-run, apply migrations, run the
  tests listed below against the isolated PostgreSQL/Redis/MinIO harness, plus the
  existing kiosk/station, evidence, catalog/source-gate, backup and tenant suites.
- Run frontend typechecking and kioskReplayApi.test.ts (dependencies absent here).
- Regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts, as the
  lane instructions reserve generated artifacts for the coordinator.
- Perform coordinator review/QA and staging/commit. No passing DB/frontend tests claimed.

## Checks actually completed

- Python AST parsing of all 53 changed/new Python files: no syntax errors.
- validate_http_coverage, validate_task_coverage, validate_object_mutation_coverage,
  validate_fanout_gate_coverage: all returned OK using the repo's static AST guards.
- git diff --check: no whitespace errors. Touched production Python files are below
  300 lines except the accepted config/settings.py exception.
- Final read-only index check is empty; AGENTS.md and CLAUDE.md remain byte-identical.
- System Python has no Django; pip dependency download was denied by sandbox network
  access. An ignored .venv was created for that attempt. No DB suite was invoked.

## Skips, decisions and defects outside this slice

- No browser queue/service worker, recovery UI, standalone offline QR lookup or new
  module/feature key; those are outside phase 9c.
- Chained direct return resolves the new loan. Newly-created item lines still require
  server item IDs in resolutions, as the existing staff contract dictates. Container-only
  chained returns work. Before advertising fully offline issue-then-return of item
  lines, choose a client-product-to-server-item resolution contract; no silent return-all.
- Existing direct_loan_returns._return_scan_qr accepts a matching expected QR without
  checking ACTIVE status. This slice preserves the workflow's behavior; the plan's
  claim that every existing return re-checks QR revocation is too strong.
- Existing evidence finalization stale promotion recovery does not fence S3 copy by
  its claim token; replay fences database commits, but does not redesign that storage
  protocol. Coordinator should review simultaneous slow stale promotions separately.
- 9b's frontend KioskWorkPackage kind union omits the server's prospective direct_handout
  kind; unchanged here because the direct-handout kiosk UI is later work.

## File inventory
- backend/apps/backup/settings_policy.py
- backend/apps/data_export/classification_platform.py
- backend/apps/data_export/references_core.py
- backend/apps/evidence/finalization_completed.py
- backend/apps/evidence/storage.py
- backend/apps/hardware_requests/apps.py
- backend/apps/hardware_requests/checks.py
- backend/apps/hardware_requests/kiosk_online_commands.py
- backend/apps/hardware_requests/migrations/0025_kiosk_replay.py
- backend/apps/hardware_requests/models.py
- backend/apps/hardware_requests/models_replay.py
- backend/apps/hardware_requests/replay_authorization.py
- backend/apps/hardware_requests/replay_claims.py
- backend/apps/hardware_requests/replay_cleanup.py
- backend/apps/hardware_requests/replay_dispatch.py
- backend/apps/hardware_requests/replay_execute.py
- backend/apps/hardware_requests/replay_failures.py
- backend/apps/hardware_requests/replay_fingerprint.py
- backend/apps/hardware_requests/replay_payload_serializers.py
- backend/apps/hardware_requests/replay_prepare.py
- backend/apps/hardware_requests/replay_records.py
- backend/apps/hardware_requests/replay_serializers.py
- backend/apps/hardware_requests/replay_throttles.py
- backend/apps/hardware_requests/replay_views.py
- backend/apps/hardware_requests/tasks.py
- backend/apps/hardware_requests/tasks_replay.py
- backend/apps/makerspaces/lifecycle_purge.py
- backend/apps/makerspaces/origin_scope_routes.py
- backend/apps/makerspaces/station_urls.py
- backend/apps/operations/management/commands/run_scheduled_tasks.py
- backend/apps/tenant_migration/audit_references_meta_kiosk.py
- backend/apps/tenant_migration/gate_policy.py
- backend/apps/tenant_migration/gate_policy_objects.py
- backend/apps/tenant_migration/gate_policy_replay.py
- backend/apps/tenant_migration/tenant_dump_authority_supplement.py
- backend/apps/tenant_migration/tenant_dump_catalog.py
- backend/apps/tenant_migration/tenant_dump_field_snapshot.py
- backend/config/settings.py
- backend/tests/data_export/test_portable_audit_references.py
- backend/tests/data_export/test_registry_guards.py
- backend/tests/evidence/test_kiosk_replay_evidence.py
- backend/tests/hardware_requests/replay_helpers.py
- backend/tests/hardware_requests/test_kiosk_replay.py
- backend/tests/hardware_requests/test_kiosk_replay_checks.py
- backend/tests/hardware_requests/test_kiosk_replay_cleanup.py
- backend/tests/hardware_requests/test_kiosk_replay_concurrency.py
- backend/tests/hardware_requests/test_kiosk_replay_crashes.py
- backend/tests/makerspaces/test_tenant_lifecycle.py
- backend/tests/tenant_migration/test_authority_dispositions_d8.py
- backend/tests/tenant_migration/test_authority_guard.py
- backend/tests/tenant_migration/test_reference_registry.py
- backend/tests/tenant_migration/test_tenant_dump_catalog_d1.py
- backend/tests/test_scheduled_tasks.py
- docs/INVARIANTS.md
- docs/SOURCE-MAP.md
- frontend/src/features/kiosk/kioskReplayApi.test.ts
- frontend/src/features/kiosk/kioskReplayApi.ts
- LANE-PROGRESS.md
- docs/plans/2026-09-03-forward-plan/reviews/stage1-p9c.md (gitignored review)

## Added tests (all need coordinator execution)

backend/tests/data_export/test_portable_audit_references.py
- test_replay_audit_keeps_station_binding_and_namespaces_source_coordination_ids

backend/tests/data_export/test_registry_guards.py
- test_replay_coordination_is_omitted_and_actor_never_expands_user_closure

backend/tests/evidence/test_kiosk_replay_evidence.py
- test_failed_qr_photo_is_readable_and_cleanup_keeps_it
- test_finalized_reuse_inside_domain_transaction_has_no_storage_io
- test_invalid_or_absent_upload_is_terminal_and_retains_photo
- test_prepare_presigns_same_staging_photo_on_retry_and_rejects_metadata_conflict
- test_staging_promotion_happens_once_and_later_staging_bytes_cannot_replace_final
- test_storage_failure_rolls_back_prepare_and_leaves_execute_retryable
- test_unconsumed_failure_reads_staging_and_expired_state_never_reads_storage

backend/tests/hardware_requests/test_kiosk_replay.py
- test_a_different_lease_cannot_take_over_an_owned_command
- test_canonical_objects_ignore_key_order_and_lists_preserve_order
- test_chained_direct_return_resolves_created_container_loan
- test_changed_payload_and_stream_position_conflict_without_mutating_original
- test_command_age_is_enforced_at_prepare
- test_current_box_mismatch_is_a_terminal_return_failure
- test_current_presence_and_inventory_refusals_are_typed
- test_issue_deposit_and_box_scan_failures_are_typed_and_terminal
- test_live_revocation_prevents_domain_effect
- test_module_off_and_missing_cookie_origin_csrf_or_lease_fail_closed
- test_permission_is_checked_again_after_s3_and_before_domain_commit
- test_predecessor_pending_failed_and_cross_aggregate_refusals
- test_prepare_and_execute_duplicate_apply_exactly_one_box_scan_without_login
- test_reviewed_issue_and_return_commit_with_replay_results
- test_source_gate_refuses_prepare_and_execute_without_mutation
- test_tenant_reference_and_model_identity_guards
- test_unknown_protocol_and_untrusted_tenant_are_refused

backend/tests/hardware_requests/test_kiosk_replay_checks.py
- test_default_replay_timing_is_valid
- test_replay_age_cannot_outlive_tombstones_and_claim_timeout_is_shorter
- test_replay_timing_rejects_nonpositive_and_noninteger_values

backend/tests/hardware_requests/test_kiosk_replay_cleanup.py
- test_cleanup_does_not_touch_a_fresh_claim
- test_closed_source_gate_skips_cleanup
- test_expiry_is_bounded_and_never_deletes_evidence
- test_retained_descendant_protects_predecessor_and_old_envelope_cannot_reopen

backend/tests/hardware_requests/test_kiosk_replay_concurrency.py
- test_a_slow_stale_executor_cannot_commit_after_a_new_claim_succeeds
- test_concurrent_prepare_creates_one_owner_and_one_evidence
- test_fresh_claim_collision_executes_one_issue

backend/tests/hardware_requests/test_kiosk_replay_crashes.py
- test_an_old_executor_cannot_release_a_reclaimed_token
- test_stale_claim_recovers_each_crash_without_double_issue
- test_unknown_exception_rolls_back_domain_and_preserves_retryability

backend/tests/makerspaces/test_tenant_lifecycle.py
- test_whole_tenant_purge_removes_protected_replay_chain_before_domain_and_evidence

backend/tests/tenant_migration/test_authority_guard.py
- test_every_replay_field_has_an_explicit_drop_override

backend/tests/tenant_migration/test_reference_registry.py
- test_replay_audit_paths_have_exact_portable_or_source_local_dispositions

backend/tests/tenant_migration/test_tenant_dump_catalog_d1.py
- test_replay_catalog_is_exactly_the_live_field_universe_and_all_drop

backend/tests/test_scheduled_tasks.py
- test_replay_cleanup_is_daily_in_both_schedulers

backend/tests/tenant_migration/test_authority_dispositions_d8.py: 31 ReplayCommand
field cases added to the existing exact disposition matrix tests.

frontend/src/features/kiosk/kioskReplayApi.test.ts: bearer-only transport/same-envelope
and typed conflict preservation/no login refresh.
