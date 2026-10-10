# w6-platform handoff

Implementation and review-and-fix pass complete; all changes are unstaged. No git state-changing commands
were run. No models, migrations, dependencies, module keys or feature keys were added.

## Completed

- Superadmin dashboard API and central console page; hidden tenants excluded.
- Explicit read-only problem registry: backup, offsite, scheduler, updates, email,
  Telegram, storage and domain verification. Checks fail independently and expose
  no provider exception strings, secrets or recipient details.
- On-demand GET checks and 15-minute beat/cron task with an explicit gate exemption.
- Beat terminal executions share the cron PeriodicTaskRun journal; task re-exports
  resolve by Celery registered name. Failed telemetry cannot fail task execution.
- Scoped manager usage endpoint/page using existing counters and effective limits.
- Tombstoned counters display unavailable. Tenant query keys include makerspace ID.
- OpenAPI serializers/error declarations; generated files left for coordinator.
- API, check severity/scoping, scheduler and frontend regression tests written.

## Verification and remaining coordinator work

- `npx.cmd tsc -b` completed with exit code 0.
- `python -m py_compile` completed successfully for all 21 touched backend files.
- git diff --check is clean. All touched files are under 300 lines, except the
  repository-approved settings.py exception. AGENTS.md and CLAUDE.md remain byte-identical.
- Backend database tests and runtime/browser QA were not run in this lane.
  Backend tests below are authored, not claimed passing. Targeted frontend tests passed.
- Run the new test files and existing test_scheduled_tasks.py,
  test_integration_health.py and source-gate/origin-scope guards via the isolated runner.
- Regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts.
- Independent review gate and owner QA remain coordinator-owned. codex doctor
  reported missing configuration/home and unreachable provider in this sandbox.

## Skipped, decisions and limitations

- MFA check: no enrollment field exists in this checkout.
- TLS expiry check: no authoritative certificate expiry record exists.
- Domain verification has states but no expiry policy; checks report those states.
- No plan entity or plan/billing display was introduced. The task explicitly
  authorizes tenant counts against limits, resolving the research visibility question.
- No remaining owner product decisions for this scope.
- Scheduler timestamps record beat completions and cron attempts, not proof of
  individual business effects. Scheduled cache stores only timestamp/status; APIs
  recompute results so hidden-tenant changes take effect on reads.
- Outside-scope inherited defect noticed: platform update-settings endpoints return
  404 when the updates module is disabled (views_platform_updates.py), contrary to
  the lane requirement of 400 for module-off routes. Not modified here.

## File inventory

Created:

- `LANE-PROGRESS.md`
- `backend/apps/admin_api/serializers_platform_monitoring.py`
- `backend/apps/admin_api/views_platform_monitoring.py`
- `backend/apps/makerspaces/usage_snapshot.py`
- `backend/apps/operations/platform_checks.py`
- `backend/apps/operations/platform_dashboard.py`
- `backend/apps/operations/platform_integration_health.py`
- `backend/apps/operations/platform_problems.py`
- `backend/apps/operations/platform_signals.py`
- `backend/apps/operations/scheduler_telemetry.py`
- `backend/apps/operations/tasks_platform.py`
- `backend/tests/test_platform_monitoring_api.py`
- `backend/tests/test_platform_monitoring_regressions.py`
- `backend/tests/test_platform_problem_checks.py`
- `backend/tests/test_platform_scheduler.py`
- `docs/platform-monitoring.md`
- `docs/SOURCE-MAP-FRONTEND.md`
- `w6-platform-PROGRESS.md`
- `frontend/src/features/staff/PlatformDashboardPanel.tsx`
- `frontend/src/features/staff/StaffApp.platform.test.tsx`
- `frontend/src/features/staff/TenantUsagePanel.tsx`
- `frontend/src/features/staff/platformMonitoring.test.tsx`
- `frontend/src/features/staff/platformMonitoringApi.ts`

Modified:

- `backend/apps/admin_api/urls_platform.py`
- `backend/apps/makerspaces/origin_scope_routes.py`
- `backend/apps/operations/management/commands/run_scheduled_tasks.py`
- `backend/apps/operations/tasks.py`
- `backend/apps/tenant_migration/gate_policy_tasks.py`
- `backend/config/celery_signals.py`
- `backend/config/settings.py`
- `docs/PROJECT-STATUS.md`
- `docs/SOURCE-MAP.md`
- `frontend/src/features/staff/StaffApp.tsx`
- `frontend/src/features/staff/StaffPlatformTabContent.tsx`
- `frontend/src/features/staff/StaffTabContent.tsx`
- `frontend/src/features/staff/StaffTabLoaders.tsx`
- `frontend/src/features/staff/staffAccess.ts`
- `frontend/src/features/staff/staffTabs.ts`

## Exact added tests (coordinator must run)

`backend/tests/test_platform_monitoring_api.py`:

- `test_platform_endpoints_require_active_superadmin`
- `test_dashboard_excludes_hidden_and_counts_lifecycle_without_tenant_details`
- `test_problems_exclude_hidden_even_when_superadmin_is_a_manager_there`
- `test_usage_is_scoped_and_honors_managed_overrides`
- `test_usage_rejects_archived_hidden_and_foreign_origin`
- `test_self_host_usage_has_no_limits`
- `test_each_check_failure_is_isolated_and_provider_strings_are_not_returned`
- `test_scheduler_freshness_uses_three_cadences`
- `test_scheduler_missing_execution_is_warn`
- `test_usage_requires_authentication_and_refuses_initial_password`
- `test_offsite_tenant_uploads_exclude_hidden_snapshots`
- `test_dashboard_reads_do_not_create_singleton_settings`
- `test_usage_tombstoned_counters_are_unavailable`
- `test_offsite_older_visible_failure_is_not_masked_by_a_newer_success`

`backend/tests/test_platform_problem_checks.py`:

- `test_backup_age_is_relative_to_schedule`
- `test_backup_disabled_missing_and_failed`
- `test_offsite_states`
- `test_offsite_not_configured_is_warning`
- `test_scheduler_reports_freshness`
- `test_updates_states`
- `test_updates_disabled_is_ok`
- `test_email_health`
- `test_telegram_health_including_destinations`
- `test_channel_off_does_not_raise_false_alarm`
- `test_unknown_email_health_is_warning`
- `test_storage_boundaries`
- `test_domain_verification`
- `test_registry_is_explicit_and_unique`

`backend/tests/test_platform_scheduler.py`:

- `test_checker_is_registered_with_same_cadence_and_explicit_gate_policy`
- `test_scheduled_check_runs_and_caches_only_deployment_summary`
- `test_celery_completion_and_failure_update_cron_journal`
- `test_celery_signal_is_wired_and_does_not_store_exception_text`
- `test_reexported_celery_task_resolves_to_same_cron_name`
- `test_unknown_and_nonterminal_tasks_do_not_write_journal`
- `test_telemetry_database_failure_does_not_crash_worker`

`frontend/src/features/staff/platformMonitoring.test.tsx`:

- limits platform navigation to central superadmins and usage to managers
- renders operational signals, scheduler and actionable check links
- renders counts and byte limits using the selected makerspace route
- refetches usage for a new tenant rather than reusing another tenant's counts
- shows API failure with a refresh control

## Review pass (2026-10-11)

Reviewed AGENTS.md, the global/workflow rules, the original brief/research sections,
PROJECT-STATUS, relevant invariants and every tracked/untracked lane change.
The requested w6-platform-PROGRESS.md was absent from this worktree and the main
plans directory; created it with this updated handoff. Only this worktree was edited.

Defects fixed:

1. Problem-check GETs and scheduled checks used build_integration_health(), which
   can bootstrap platform email/SMS/push singleton rows. Added a read-only channel
   snapshot using existing section builders and noncreating SMTP reads. No audit
   is needed for these GETs because they now make no durable state changes.
2. Verified offsite copies with transport errors from re-verification or retention
   were excluded from failing copies. They now produce has_error and an error check.
3. Destination probes were ignored. The latest deployment-global audited probe
   outcome now contributes a boolean, without exposing provider details. A later
   successful probe clears that failure; outstanding copy errors still remain.
4. Inactive Telegram destinations suppressed legacy delivery but the checker
   incorrectly reported legacy credentials as healthy. It now warns.
5. StaffApp required a valid selected tenant for the global platform dashboard.
   The dashboard now opens with no tenant or a stale tenant selection; custom-domain
   and non-global route access checks remain in force.
6. A failed import of one scheduled task disabled completion telemetry for all.
   Resolution now isolates each import failure and logs only its type/task name.
7. SOURCE-MAP omitted monitoring ownership and already exceeded 300 lines. Moved
   frontend ownership into SOURCE-MAP-FRONTEND.md before adding monitoring entries.
8. PlatformDashboardPanel.tsx used CRLF; normalized it to LF. All changed files
   pass the LF/UTF-8/mojibake scan and the ceiling, except the documented settings.py
   exception. AGENTS.md and CLAUDE.md remain byte-identical.

Added backend regression tests (coordinator must run; NOT executed here):

`backend/tests/test_platform_monitoring_regressions.py`:
- test_monitoring_gets_and_scheduled_checks_never_create_integration_settings
- test_problem_email_snapshot_checks_credentials_without_writing (tenant/platform)
- test_verified_copy_transport_or_retention_failure_is_not_healthy (read/delete)
- test_latest_probe_failure_and_recovery_are_reported_without_provider_details
- test_hidden_copy_error_and_destination_rollup_do_not_leak
- test_usage_custom_origin_accepts_only_own_manager_and_space
- test_monitoring_still_works_when_updater_is_disabled
- test_platform_endpoints_refuse_ineligible_superadmin (both routes; initial-password,
  inactive and restricted actors; proves allowed before revocation)

`backend/tests/test_platform_problem_checks.py`:
- test_inactive_telegram_destinations_suppress_legacy_configuration

`backend/tests/test_platform_scheduler.py`:
- test_one_unimportable_task_does_not_disable_all_completion_telemetry

`frontend/src/features/staff/StaffApp.platform.test.tsx`:
- opens without a valid tenant selection (null/stale)
- keeps the tenant picker for inventory
- preserves custom-domain tenant access checks

Verification actually run:
- python -m py_compile: all 21 touched backend Python files passed.
- npx.cmd tsc -b: passed after the review fixes.
- npx.cmd vitest run src/features/staff/platformMonitoring.test.tsx
  src/features/staff/StaffApp.platform.test.tsx src/features/staff/staffTabs.test.ts:
  3 files, 52 tests passed. Used npx.cmd because PowerShell blocks npx.ps1.
- git diff --check, UTF-8/LF/line ceiling and instruction-mirror checks: passed.
- codex doctor: configuration/home and provider connectivity unavailable; a separate
  CLI review gate cannot run in this sandbox and remains coordinator-owned.

Coordinator backend run: tests/test_platform_monitoring_api.py,
tests/test_platform_monitoring_regressions.py, tests/test_platform_problem_checks.py,
tests/test_platform_scheduler.py, existing tests/test_scheduled_tasks.py,
tests/test_integration_health.py, tests/tenant_migration/test_source_gate_guards.py,
tests/makerspaces/test_tenant_servability_guard.py and
tests/makerspaces/test_origin_scope_p2b.py.
No model/field/migration, environment variable, module key or feature key was added.
Existing task exemption covers read-only fan-out and disposable deployment cache;
there are no tenant mutations or object-storage writers to declare. Existing export,
User-FK, catalog/projection and authority entries need no changes.
No owner product decision is outstanding. MFA/TLS expiry checks still need authoritative
signals and remain skipped as recorded above. Backend runtime, generated schema/client,
independent gate and owner QA remain coordinator work; no git state was changed.

Outside-scope inherited defect also noticed during review: makerspaces/limits_usage.py
contains mojibake in its storage/quota error messages. Left untouched in this lane.
