# Research Wave 0: machines and maintenance

Lane: `research/w0-machines`. All changes remain unstaged for coordinator review.

## Completed

- D4: schedule completion starts the next interval from the local date of the
  validated `performed_at`, preserving the transaction and old/new due-date audit.
  Backdated maintenance intentionally uses the actual recorded service date.
- D5: Django control-plane help, staff machine-type controls and built-in summaries,
  module docs and landing-page limits disclose that the booking flag is not yet
  enforced. No unsupported booking prerequisite blocks existing laser/CNC jobs.
- D13: replace claims of reactive work orders with completed-maintenance logs;
  explicitly disclose that work orders do not exist.
- Regression tests added for D4 and D5; existing recurrence expectation corrected.
- Maintenance log endpoint's existing OpenAPI annotation describes the new
  recurrence behavior; request, response and error schemas remain unchanged.
- Diff reviewed, `git diff --check` clean, six changed/new Python files parsed
  successfully with `ast.parse`. Touched source files are 29–262 lines.
- `AGENTS.md` and `CLAUDE.md` verified byte-identical, neither edited.

## Remaining

- Coordinator review and execution of tests below, followed by schema regeneration
  to capture the updated endpoint description. Implementation is complete.
- No backend tests were run (Docker/Postgres unavailable, as instructed).
- Frontend tests were not run (`frontend/node_modules` is absent in this worktree).

## Tests added or updated for coordinator

- New `backend/tests/maintenance/test_completion_recurrence.py`:
  - `test_completion_starts_fresh_interval_and_audits_due_dates` (five cases: late
    by multiple intervals, one interval, on time and early; checks overdue + audit).
  - `test_backdated_completion_uses_recorded_local_date` (UTC and Asia/Kolkata).
  - `test_completion_audit_failure_rolls_back_log_and_rescheduled_date` (failure
    after log and schedule writes; both rows and audit must roll back).
- Updated `backend/tests/maintenance/test_services.py`:
  `test_logging_and_completion_are_audited_and_atomic` expects completion anchoring.
- New `backend/tests/machines/test_booking_flag_disclosure.py`:
  - `test_control_plane_capability_field_discloses_booking_flag_is_not_enforced`.
  - `test_booking_metadata_remains_valid_for_custom_types` (true and false).
- Updated `frontend/src/features/staff/panels/MachineTypesPanel.test.tsx`:
  - `discloses the booking limit on custom create and edit controls`.
  - `keeps the booking disclosure visible to read-only staff`.
  - `labels built-in laser and CNC booking flags as not yet enforced`.

Coordinator commands:

```bash
./scripts/dev.sh test tests/maintenance tests/machines/test_booking_flag_disclosure.py tests/machines/test_machine_type_capability_presets.py
cd frontend
npm test -- src/features/staff/panels/MachineTypesPanel.test.tsx
```

## Validation and constraints

- No migrations, models, module/feature keys or API shape changes are needed.
- Generated OpenAPI files are untouched.
- `codex doctor` was attempted: CLI configuration could not load and provider
  connectivity failed. Separate CLI review gates are blocked in this sandbox.
- No owner product decisions are needed for these corrections. Booking design
  and work-order implementation remain future work outside this lane.
- Existing long documentation files are edited in place as explicitly requested;
  all touched source files remain below the 300-line ceiling.

## Outside-lane defect observed

`docs/LANDING-PAGE-FEATURES.md` still claims Telegram decisions/buttons/actions
(lines 22, 181–182 and 369–370), contrary to the outbound-only invariant. This is
the inventory-loans portion of D13 and is left for its coordinator/owning lane.
