# Lane w1-sweeper — research F1

## Completed

- Read root rules, global workflow, research index/consumer scheduler sections,
  relevant invariants and existing scheduler/gate/export surfaces.
- Added source-local ReminderSchedule model and migration off the actual operations
  leaf 0009_report_schedules; offsets, tenant/source identity, committed disjoint
  claims, fenced idempotent completion, UTC normalization and boundary validation.
- Added an explicit empty source registry, one fail-safe tenant sweep, optional F4
  timezone resolver, notification emit dispatch, five-minute beat/beat-less entries,
  task autodiscovery re-export and source-gate declarations.
- Added omitted export classification, no-User-FK decision, DROP projection, literal
  field snapshot and updated catalog digest. The static snapshot reconstruction
  reproduced the existing live pin before adding the model; live Django validation
  still belongs to the coordinator.
- Added test-only example and regression/concurrency/hygiene/cadence tests.
- Documented the batch knob and source contract. Split oversized source-map and
  environment-reference documents into linked siblings without dropping content;
  the environment drift guard now reads both reference files.
- Split near-ceiling tenant-migration target_projection.py into types, fields, rows
  and reference declarations behind an explicit compatible re-export barrel.
- Reminder primitives reuse the gate runtime's active tenant-boundary ContextVar
  instead of reacquiring the same advisory lock on another connection during a
  sweep; standalone writes still take tenant_write. Added regression coverage.
- Static Python syntax/compilation inspection and git diff whitespace inspection
  completed. These are not database, Django or pytest results.

## Remaining / coordinator validation

- No database tests run: this sandbox cannot reach Docker/Postgres and its Python
  has no Django installed. The coordinator must run the tests below and Django
  migration drift/system checks, including the live catalog digest guard.
- All changes remain unstaged. No state-changing git commands used.

## Tests for the coordinator

- backend/tests/operations/test_reminder_services.py: UTC/configured offsets,
  duplicate identities, due-date movement, claim/complete fencing and tenant scope,
  terminal claims/failures, invalid inputs, autocommit, two-worker disjoint claims,
  each step's due instant, standalone closed-tenant denial and skip_locked against
  a deliberately held row lock.
- backend/tests/operations/test_reminder_sweeper.py: two sweeps emit once, foreign
  subjects, module/feature gates, closed source gate counted, tenant failure isolation,
  terminal dispatch failure, default/custom/invalid timezone, empty registry and
  registration validation, cancellation revalidation, discovery batch fairness,
  dispatch after transaction commit and reuse of the held tenant boundary.
  backend/tests/operations/reminder_example.py
  is only a source fixture.
- backend/tests/operations/test_reminder_hygiene.py: export/catalog/projection DROP,
  exact field coverage, no User FK and both source-gate participants.
- backend/tests/test_scheduled_tasks.py: new equal five-minute cadence test plus all
  existing scheduler tests unchanged in behaviour.
- backend/tests/test_environment_reference_drift.py: existing full-reference
  assertions preserved over the two linked reference documents.
- Existing return-reminder tests (unchanged), data-export complete-registry guards,
  tenant-migration catalog/source-gate guards, environment-reference/surface guards.

## Scope decisions / limitations

- Existing loan reminder left intact: it resets its sent marker and retries failed
  channel delivery. Porting to the generic at-most-once emitter would change behaviour.
- No consumer, endpoint, feature/module key, frontend or generated API changes.
- Coordination rows do not travel (requested default). No owner decision needed.
- At-most-once permits missed notices after crash/failure; claims are never reclaimed.
  Dispatch counts are attempts because the existing emitter has no receipt.
- config/settings.py retains its explicitly accepted root-rule size exception;
  unrelated settings refactoring is outside this build lane.
- codex doctor could not load its local config and reported inference unreachable;
  this lane supplies code/tests for the coordinator's review/QA rather than running
  a nested Codex review or a database suite.

## Defect noticed outside this lane

- Existing operations/tasks_report_schedules.py appears absent from Celery worker
  autodiscovery: operations/tasks.py previously imported no sibling tasks, and
  config/celery.py uses default tasks autodiscovery with no explicit task imports.
  The beat-less runner imports dotted tasks itself, so that path is unaffected.
  Coordinator should verify scheduled-report task registration in a real worker;
  no out-of-scope fix made. The new reminder task is explicitly re-exported.
- Potential broader gate re-entry hazard: gate_runtime.tenant_write acquires an
  application-connection shared advisory lock even when a dispatch boundary holds
  the same tenant lock on its dedicated connection. A queued exclusive writer can
  create a wait cycle between those connections. F1 reuses the held boundary;
  other callers need a separate concurrency review. No global gate-runtime edit.

## Complete file inventory

- LANE-PROGRESS.md
- backend/apps/accounts/rbac.py
- backend/apps/backup/settings_policy.py
- backend/apps/data_export/classification_platform.py
- backend/apps/data_export/references_core.py
- backend/apps/operations/management/commands/run_scheduled_tasks.py
- backend/apps/operations/migrations/0010_reminder_schedule.py
- backend/apps/operations/models.py
- backend/apps/operations/models_reminders.py
- backend/apps/operations/reminder_registry.py
- backend/apps/operations/reminder_services.py
- backend/apps/operations/reminder_sweeper.py
- backend/apps/operations/tasks.py
- backend/apps/operations/tasks_reminders.py
- backend/apps/tenant_migration/authority_guards.py
- backend/apps/tenant_migration/gate_policy_tasks.py
- backend/apps/tenant_migration/target_projection.py
- backend/apps/tenant_migration/target_projection_fields.py
- backend/apps/tenant_migration/target_projection_references.py
- backend/apps/tenant_migration/target_projection_rows.py
- backend/apps/tenant_migration/target_projection_types.py
- backend/apps/tenant_migration/tenant_dump_catalog.py
- backend/apps/tenant_migration/tenant_dump_field_snapshot.py
- backend/apps/tenant_migration/tenant_dump_model_catalog.py
- backend/config/settings.py
- backend/tests/operations/reminder_example.py
- backend/tests/operations/test_reminder_hygiene.py
- backend/tests/operations/test_reminder_review.py
- backend/tests/operations/test_reminder_services.py
- backend/tests/operations/test_reminder_sweeper.py
- backend/tests/test_environment_reference_drift.py
- backend/tests/test_scheduled_tasks.py
- docs/SOURCE-MAP-frontend.md
- docs/SOURCE-MAP.md
- docs/environment-reference-delivery.md
- docs/environment-reference.md
- docs/reminder-schedules.md

## Exact new test names

### backend/tests/operations/test_reminder_hygiene.py

- test_reminder_coordination_does_not_travel_or_pull_users_into_export
- test_shared_sweeper_declares_both_source_gate_participants

### backend/tests/operations/test_reminder_services.py

- test_offsets_are_utc_and_duplicate_steps_are_idempotent
- test_changed_due_time_moves_only_pending_rows
- test_each_offset_waits_for_its_own_due_instant
- test_claim_and_complete_are_fenced_idempotent_and_tenant_scoped
- test_committed_claim_is_never_reclaimed_even_after_a_crash
- test_standalone_primitives_refuse_a_closed_tenant
- test_invalid_schedule_inputs_are_refused_without_rows
- test_claim_inside_an_outer_transaction_is_refused
- test_two_workers_claim_distinct_rows
- test_claim_skips_a_row_locked_by_another_worker

### backend/tests/operations/test_reminder_sweeper.py

- test_two_sweeps_emit_once_and_complete_the_schedule
- test_discovery_batches_do_not_starve_later_subjects
- test_emitter_runs_after_the_claim_transaction_commits
- test_sweep_reuses_its_tenant_boundary_without_reacquiring_on_another_connection
- test_tenant_isolation_revalidates_a_foreign_subject
- test_module_off_skips_discovery_and_leaves_pending_rows
- test_feature_off_skips_a_source
- test_gate_closed_tenant_is_skipped_and_counted_while_other_tenant_runs
- test_cancelled_subject_is_rechecked_before_dispatch
- test_invalid_timezone_for_one_tenant_does_not_stop_other_tenants
- test_one_failing_tenant_does_not_stop_the_sweep
- test_dispatch_failure_is_terminal_and_does_not_retry
- test_default_and_optional_timezone_resolvers_keep_utc_instants
- test_empty_production_registry_is_a_noop
- test_duplicate_and_unknown_registrations_are_refused

- backend/tests/test_scheduled_tasks.py: test_shared_reminder_sweep_has_equal_five_minute_cadence
- backend/tests/test_environment_reference_drift.py: existing tests updated for split documentation; no new test function.

## Review pass

Completed the full unstaged diff and new-file review against the brief, research
consumer scheduler requirements, root rules and relevant migration/notification
invariants. All changes remain unstaged; no state-changing git commands were used.

Defects fixed:

- Booking fixtures omitted required email/phone fields and failed before exercising
  the sweeper. Supplied valid contacts in the existing tests and new review tests.
- Reminder queries used direct tenant predicates instead of the required RBAC
  boundary; standalone primitives also admitted archived/inactive/hidden tenants.
  Added internal `rbac.scope_for_scheduled_work`, used it throughout discovery,
  coordination and dispatch, and refused direct writes to unavailable tenants.
  Not-restored/frozen tenants remain discoverable for gate skip accounting.
  Declared lifecycle_state in the authority guard because RBAC now reads it directly.
- Explicitly disabling connection autocommit bypassed the atomic-block check, allowing
  an uncommitted claim to escape. Claims and sweeps now require real autocommit too.
- Source module/feature checks used a stale makerspace snapshot through long scans.
  Reloaded gates after discovery and before dispatch; pre-claim skips retain pending
  rows. A claimed skip remains terminal, preserving the at-most-once contract.
- The new live RBAC predicate can change between selection and bulk claim update.
  Verify every selected row was persisted and roll back if visibility changed;
  never return a claim token that exists only in memory.
- Whitespace source keys and an empty feature key passed registration. Reject them.
  Falsy invalid timestamps silently selected the current time; UTC conversion could
  overflow without a validation error. Validate all supplied timestamps explicitly.
- The example did not reject unknown reminder kinds, and its comment incorrectly
  implied rediscovery could move a skipped claim. Revalidate kind and document that
  skipped claims are terminal; a new occurrence identity is needed for later notices.
- Eleven changed/new files contained CRLF or mixed endings. Normalized all lane files
  to LF and checked UTF-8, mojibake candidates and file sizes.

Review tests added (coordinator must run; none executed here):

- backend/tests/operations/test_reminder_services.py:
  `test_claim_with_manually_disabled_autocommit_is_refused`,
  `test_invalid_claim_and_completion_times_are_refused`,
  `test_visibility_change_during_claim_cannot_return_an_unpersisted_token`;
  extended invalid-input cases for whitespace source, excess steps and overflow.
- backend/tests/operations/test_reminder_review.py:
  `test_sweep_with_manually_disabled_autocommit_is_refused`,
  `test_background_scope_excludes_unavailable_tenants_and_direct_writes`,
  `test_not_restored_tenant_reaches_the_gate_and_is_counted`,
  `test_source_disabled_during_discovery_is_not_claimed`,
  `test_source_disabled_during_build_is_not_dispatched`,
  `test_wrong_kind_and_removed_offset_are_revalidated_before_dispatch`,
  `test_two_concurrent_sweeps_dispatch_the_same_subject_once`,
  `test_invalid_source_declarations_are_refused`.

Validation performed:

- `python -m py_compile` on all 31 changed/new backend Python files: passed.
- `frontend/ npx.cmd tsc -b`: passed. PowerShell blocks npx.ps1, so used npx.cmd.
- `frontend/ npx.cmd vitest run --changed --passWithNoTests`: exited 0, found no
  affected frontend test files; zero frontend tests executed (no frontend edits).
- `git diff --check`: passed. All touched files use LF; no mojibake candidates;
  all meet 300 lines except config/settings.py's existing documented exception.
  AGENTS.md/CLAUDE.md remain untouched and byte-identical.
- Static AST/text checks confirm all 269 environment names are documented and the
  projection split preserves the existing classes, functions and declaration maps.
  These are static checks, not the Django registry/catalog test suite.
- `codex doctor` was rechecked: config/home lookup and inference reachability fail.
  No nested CLI review or database test run is claimed.

Coordinator still needs the four reminder test files, test_scheduled_tasks.py,
test_environment_reference_drift.py, test_env_surface_drift.py,
test_return_reminders.py, test_return_reminder_task.py, test_cron_return_reminders.py,
data-export registry guards, tenant_migration/test_authority_guard.py,
tenant_migration/test_source_gate_guards.py and
tenant_migration/test_tenant_dump_catalog_d1.py, plus Django system checks and
makemigrations --check. Migration 0010 still depends on operations/0009_report_schedules;
no additional migration, endpoint, module/feature key or owner decision was introduced.
