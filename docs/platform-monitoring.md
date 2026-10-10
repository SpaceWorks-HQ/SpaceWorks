# Platform monitoring and tenant usage

The central staff console has a **Platform dashboard** tab for active superadmins.
It is unavailable on a tenant's custom-domain origin. Hidden makerspaces never
enter the platform counts, usage rows, delivery counts or tenant checks, including
when the operator separately holds a membership in one. Lifecycle counts include
visible importing, aborted and archived tenants; detailed usage covers only
servable tenants. Global deployment backup/update state is deployment telemetry.

Space Managers (the `manage_makerspace` action) have a **Usage & limits** tab for
their own makerspace. It uses the existing quota counters and effective managed
limits, including overrides; `null` limits mean unlimited. No plan entity exists.
Daily delivery and monthly print counts retain their enforcement periods. On
self-hosts limits are inert and storage accounting is not maintained. Counters
belonging to tombstoned apps are shown as unavailable rather than queried.

## API

All routes are read-only GET/HEAD routes with explicit OpenAPI response/error
schemas. They introduce no module keys or new feature switches.

- `/api/v1/admin/platform/dashboard`: active superadmin; safe deployment summaries
  and visible-tenant usage. No provider error strings, credentials or recipient data.
- `/api/v1/admin/platform/problems`: active superadmin; executes the explicit
  `operations/platform_checks.py` registry on demand. Each result carries an
  `ok`, `warn` or `error` status, a human message and a local inspection/fix URL.
- `/api/v1/admin/makerspace/<id>/usage`: `manage_makerspace`, scoped through RBAC
  and servability. A visible non-manager gets 403, another/hidden tenant gets 404.
  Hidden-space managers retain their membership authority on this tenant route.

## Problem checks

- Backup: disabled is informational; missing successful automatic backup warns;
  age over 1.5 scheduled cadences warns (36 hours today), over 3 errors (72 hours);
  last failed run or settings failure errors. Reads do not create singleton settings.
- Offsite: no active destination or a nonverified latest result warns; any visible
  outstanding failed/abandoned copy errors, even after a newer successful copy.
  Re-verification/retention transport errors on verified copies also error. The
  latest deployment destination probe contributes its safe audited result.
  Upload snapshots for hidden tenants and their destination error rollups are excluded.
- Scheduler: no execution or age over 3 cadences warns; latest execution failure
  errors. Cadences come from the existing cron registry.
- Updates: pending/available warns; failed errors; disabled is informational.
- Email/Telegram: disabled modules are informational; missing configuration or
  unknown/stalled health warns; failed delivery errors. Existing destination and
  legacy-channel health are both considered. These checks perform no network probes.
  Inactive Telegram destinations suppress legacy delivery and warn. Monitoring
  reads only the required integration sections and never bootstraps settings rows.
- Storage: at least 90% warns, above the cap errors, unlimited is informational.
- Domain: pending verification warns, failed errors, verified/unset is informational.

Each failed signal read is isolated as a fixed warning. Provider exception text is
neither returned nor logged. There is no MFA enrollment field or certificate-expiry
record in this checkout, and domain verification has no expiry policy. MFA and TLS
expiry checks are intentionally omitted until an authoritative signal exists.

## Scheduling and client refresh

`apps.operations.tasks_platform.run_platform_problem_checks_task` runs every
15 minutes in both Celery beat and `run_scheduled_tasks`. Its source-gate exemption
explicitly declares read-only monitoring and disposable deployment cache writes.
The cache retains only a timestamp and aggregate status; APIs always recompute
tenant-scoped results so hiding a tenant takes effect immediately. No new model or
migration is needed. This task does not send alerts or change tenant state.

Celery terminal task signals now write the same `PeriodicTaskRun` journal as cron.
Re-exported tasks resolve by registered Celery name. Telemetry failure does not
fail the worker, and task exception text is not stored. Each task import is
isolated so an unavailable task cannot blind other completions. Cron still records claims
before work; these timestamps prove scheduler activity rather than business success.
Pending beat tasks with no completion are stale once their last completion ages out.

React queries refresh every minute and on explicit refresh. Tenant usage keys
include the makerspace ID; the platform page uses separate platform query keys.

Coordinator verification: `tests/test_platform_monitoring_api.py`,
`tests/test_platform_problem_checks.py`, `tests/test_platform_scheduler.py`,
the existing scheduler/source-gate/origin-scope guards, and
`frontend/src/features/staff/platformMonitoring.test.tsx`. Regenerate the OpenAPI
snapshot/client after integration; this lane leaves both generated files untouched.
Review regressions: `tests/test_platform_monitoring_regressions.py` and
`frontend/src/features/staff/StaffApp.platform.test.tsx`.
