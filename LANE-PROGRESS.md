# Lane `makerspace` — progress

Branch `lane/makerspace`, based on `b7c2ee93`. Temporary file for the owner's checkpoint rule; drop it
when the lane is squashed.

## Done

- (1) Audit and plan: `docs/plans/2026-10-09-makerspace-completeness/00-audit.md` and `01-plan.md` in
  the main checkout (gitignored).
- A `a57fc3ab` module console + superadmin membership revoke honour hard hide / servability (G1, G6).
- B+D `bf37f64b` settings contract: cors read-only, lapsed flag exposed, audit field names,
  api-settings 404-before-403 + servable, return-policy servable, OpenAPI errors (G2, G3, G7, G8, G12).
- split `aa571ab0` `/control/` lifecycle actions moved to `admin_lifecycle_actions.py`.
- C `4decd5d7`+`ba32982b` `/control/` domain edits through `apply_domain_change`; domain-change and
  `/control/` create/edit audits (G4, G5).
- F `b59e6d46` `recompute_storage` counts member-card photos, event-series images, certificates;
  public directory exclusion tests; stale INVARIANTS paragraph fixed (G10, G13).
- E `eb769267` image routes document 403/404; envelope OpenAPI pin test (G9).
- G11 `4c87125a` managed `assets` quota test.

## In flight

- Implementation and test writing complete for the remaining no-decision cells.
- Coordinator: run the new/strengthened backend tests and the broad lane verification below;
  database execution is unavailable in this lane sandbox. Backend additions are UNRUN.

## Continuation (2026-10-10)

- Re-read the audit and plan from the main checkout. G1-G13 fixes and their tests are present;
  no remaining makerspace-envelope route, audit, module-off, or control-state build was identified.
- Closed the remaining BU test-writing gaps for `print`, `discord`, `native_push`, and `webhook`
  (audit section 6). Notification tests use actual encrypted credentials, dispatch and daily
  counters, stubbing only the outbound transport. The webhook tests set an explicit per-space
  override; they do not choose a default for the owner-decision limit-key cell.
- Fixed a print-quota defect discovered by those tests: `limits_usage._print_requests` now resolves
  the global built-in printer type instead of matching a bare slug. A tenant-local generic type
  called `3d_printer` no longer consumes the space's print allowance. This follows the existing
  global-printer-identity invariant; no migration or new module/feature key is needed.
- Strengthened the existing public print-status policy test (audit section 3): actually switch
  to `token_only`, GET the stored policy, switch back, reject an unknown value, and check the
  changing-field audit and actor. Previously the accepted PATCH sent the existing default.
- Added console tests for the already-built lapsed-member toggle: save, pending state, query
  refresh, refused save/retry, field availability, and loading state. No frontend production
  changes or generated schema/client changes.

### Files changed in this continuation

- `backend/apps/makerspaces/limits_usage.py`
- `backend/tests/makerspaces/test_makerspace_settings_contract.py`
- New `backend/tests/makerspaces/test_print_quota.py`
- New `backend/tests/makerspaces/test_notification_quotas.py`
- New `frontend/src/features/staff/MakerspaceMembershipSettings.test.tsx`
- `LANE-PROGRESS.md`

### Tests added / strengthened (coordinator backend run required)

`backend/tests/makerspaces/test_print_quota.py` (5 cases):

- `test_managed_print_cap_refuses_a_second_request_without_an_audit`
- `test_self_host_print_submissions_ignore_managed_caps`
- `test_tenant_type_slug_collision_does_not_spend_the_print_allowance`
- `test_print_usage_is_tenant_scoped_and_resets_at_the_utc_month_boundary`
- `test_missing_global_printer_type_leaves_no_print_usage`

`backend/tests/makerspaces/test_notification_quotas.py` (13 parameterized cases):

- `test_managed_notification_cap_blocks_transport_and_preserves_counter` (3 channels)
- `test_self_host_notification_delivery_does_not_consume_managed_quota` (3 channels)
- `test_notification_caps_reset_daily_and_are_separate_for_each_tenant` (3 channels)
- `test_fanout_charges_each_room_and_shares_the_cap_with_explicit_delivery` (2 channels)
- `test_explicit_delivery_reserves_quota_before_lifecycle_dispatch` (2 channels)

Strengthened `test_makerspace_settings_contract.py`:
`test_public_print_status_lookup_policy_round_trips_and_rejects_unknown_values`.

`frontend/src/features/staff/MakerspaceMembershipSettings.test.tsx` (4 cases):

- saves the API field, blocks repeat clicks while pending, and refreshes server state
- shows a refused save and keeps the last server value available for retry
- waits for the settings field before offering a policy change
- disables a loaded policy while the parent settings query is loading

### Verification in this continuation

- `npm.cmd test -- src/features/staff/MakerspaceMembershipSettings.test.tsx`: 4 passed.
- `node node_modules/typescript/bin/tsc -b --pretty false`: exit 0.
- Python AST parsing of all four touched/new Python files: syntax valid (no Django/DB execution).
- `git diff --check`: clean; AGENTS.md and CLAUDE.md remain byte-identical.
- No backend tests, Docker commands, migrations, staging, commits, or generated API regeneration.
- `codex doctor` was re-checked: nested CLI config/home resolution and provider reachability are
  unavailable in this sandbox. Coordinator owns the independent review and database gates.

Coordinator focused command:
`./scripts/dev.sh test tests/makerspaces/test_print_quota.py
tests/makerspaces/test_notification_quotas.py tests/makerspaces/test_makerspace_settings_contract.py
tests/machines/test_printer_type_global_identity.py`.
Then run the broader verification set in `01-plan.md` (including manage.py check and migration drift).

### Outside-task defect noticed

`apps/machines/views_public_printer_service.py` documents only success responses on the public
printer endpoints, although they can return module-off/validation/quota 400 and lookup/auth errors.
This is outside the makerspace-envelope OpenAPI table and the lane's owned routes; left for the
machines lane/coordinator. No other outside-task defect was pursued.

## Not built (owner decisions, `00-audit.md` §11)

Key rotation; ORG-only hide self-lockout; last-Space-Manager guard; tenant usage page; console
surface for account-less requests; limit-key vocabulary.

## Prior checkpoint verification (inherited; not re-run in this sandbox)

- A: new tests 22 passed; on base `b7c2ee93` the 6 new tests FAIL (regression proof).
- B+D: contract + notification_secrets, audit, apiclients, admin_api: 80 passed. On base the 9 new
  contract tests FAIL.
- C: 12 files, 155 passed, 0 failed.
- F: reconciler gaps 4 passed; directory + limits enforcement + events image + public inventory:
  63 passed before the fixture fix, reconciler file re-run 4 passed.
- E: OpenAPI pin + public images: 22 passed.
- G11: 2 passed.
- Frontend: `tsc -b` clean, `npm test` 64 files / 277 tests passed, `npm run build` ok.
- `manage.py check` (1 environmental AUDIT_MAC warning), `makemigrations --check` no changes,
  `diff CLAUDE.md AGENTS.md` empty, `git diff --check` clean.
