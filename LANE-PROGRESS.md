# Lane w1-events - F3 notification families

Status: implementation complete; all changes unstaged. No state-changing git commands used.

## Completed

- Added payments, stock/procurement and certifications matrix families; extended the existing
  `members` (email stream `membership`) and `maintenance` families rather than creating duplicates.
  Existing application-received key remains `members.request_pending`.
- Events: payments `charge_raised`, `payment_due_soon`, `payment_overdue`, `payment_received`,
  `refund_issued`, `payment_failed`; members adds `approved`, `declined`, `renewal_due`, `lapsed`,
  `renewal_failed`; maintenance adds `due_soon`, `overdue`; stock `low_stock`, `procurement_received`;
  certifications `granted`, `revoked`, `expiring`, `expired`.
- Every new matrix cell defaults OFF; all prior defaults and direct member welcome/verification/
  invitation mail behavior remain. Approved member mail already exists, so the new approved adapter
  adds staff alerts only; its requester template is declared without a duplicate welcome send.
- Staff email/chat templates declare bounded snapshot fields. Staff payment context has no amount,
  currency, contact details, provider handles or credentials. Only the owner's requester email
  receives the financial amount. Requester variants: payments, membership lifecycle and certification
  expiry. Stock and maintenance additions remain staff operational alerts.
- Delivery resolves the actual owner User email, not applicant/invite contact text or a space list;
  active status, revocation, receives_notifications opt-out and requester recipient flags are checked.
  Account-only payment owners remain supported.
- Wired existing charge creation, offline/online settlement (including real payment after waiver),
  successful online/manual refund, membership approval/decline, automatic restock creation,
  procurement received status and certification grant/revoke edges. Existing maintenance log edges
  remain; maintenance/member adapters now suppress delivery when the domain module is disabled.
- New snapshots fail safe, run through notify_lifecycle/on_commit and recheck module/servability
  gates after commit. Payment alerts currently follow the payments module gate; the core ledger
  continues recording/settling debt independently of that gate.
- Finance recipients use today's MANAGE_MAKERSPACE finance-list authority. Stock uses EDIT_INVENTORY
  or MANAGE_PRINTING; certifications use MANAGE_MACHINES. Type-only notification scopes now narrow
  role/fallback recipients using the existing machine scope resolver.
- Split certification endpoint modules and Connect webhooks before growing the near-ceiling files;
  explicit exports retain their existing import paths. No authorization source guards pin these files.
  Grant writes/audits and procurement status edges are atomic; received edges re-read under a row lock.
- Module-off template access returns 400 and OpenAPI errors cover the affected space/type routes.
  No new routes, module keys, capability keys or models: these are notification matrix features,
  not new feature-capability switches. No export/reference/catalog schema changes are required.
- Updated frontend recipient-picker labels; generated frontend API/schema artifacts were untouched.

## Migration

`backend/apps/integrations/migrations/0028_research_notification_families.py`
Depends on `integrations.0027_device_notifications` (actual leaf inspected before generation).
Choice-only AlterFields: ChatTemplate.feature, EmailTemplate.stream,
NotificationDeliveryLog.feature, NotificationPreference.feature, NotificationRecipient.feature.
Static choice snapshots were generated from the runtime enum declarations without importing Django;
Django is not installed in this sandbox. Coordinator must confirm makemigrations drift below.
The existing device parity test now checks the new integrations choice leaf.

## Remaining / coordinator verification

No database tests were run; no runtime test passes are claimed. Run the two F3 test files below,
plus devices/test_device_notifications.py, tests/payments, tests/maintenance/test_notifications.py,
tests/makerspaces/test_membership_notifications_j3.py, tests/machines/test_certifications_api.py,
tests/test_b7a_kernel_low_stock.py, tests/test_procurement.py,
tests/test_notification_templates.py, tests/test_machine_type_email_templates.py and the existing
notification recipient/scope tests in the isolated Docker/Postgres runner.

Example: `./scripts/dev.sh test tests/test_notification_families_f3.py tests/test_notification_family_edges_f3.py tests/devices/test_device_notifications.py`
Also run Django `makemigrations --check --dry-run` and regenerate the OpenAPI snapshot/client in the
coordinator tree. Existing F3 event families are ready for the F1 sweeper / wave-2 reminder consumers;
F2 owns member preferences/inbox work. w1-rbac must change the finance mapping/template authority and
its regression assertion to VIEW_FINANCE once that action exists.

Static verification: changed Python files parse with ast.parse and are <=300 lines;
`git diff --check` is clean. No Django/pytest execution was attempted.
`codex doctor` reported unavailable config/CODEX_HOME and provider HTTP reachability; independent
CLI plan/code review gates could not run here. Coordinator review remains required.

## Intentionally deferred / decisions / outside findings

- No scheduler added. Due-soon/overdue/renewal/lapse/expiry events are declared for F1.
- payment_failed and renewal_failed are declared, but today's domain has no recorded failure edge
  to wire; future domain consumers should call the existing adapters when they record that event.
- Existing member approval mail remains direct and unchanged; no duplicate requester approved mail.
- No unresolved owner product decision for this lane: OFF defaults follow the explicit lane brief.
- No additional outside-task code defect was found that requires an owner decision. Existing template
  module-off 404 behavior and unlocked procurement received edges were addressed on touched paths.

## Files created or modified

- `LANE-PROGRESS.md` (created)
- `backend/apps/admin_api/views_certification_grants.py` (created)
- `backend/apps/admin_api/views_certification_types.py` (created)
- `backend/apps/admin_api/views_certifications.py` (modified)
- `backend/apps/admin_api/views_email_templates_common.py` (modified)
- `backend/apps/admin_api/views_email_templates_space.py` (modified)
- `backend/apps/admin_api/views_email_templates_types.py` (modified)
- `backend/apps/integrations/email_templates_registry.py` (modified)
- `backend/apps/integrations/email_templates_registry_research.py` (created)
- `backend/apps/integrations/lifecycle_data.py` (modified)
- `backend/apps/integrations/migrations/0028_research_notification_families.py` (created)
- `backend/apps/integrations/models_email.py` (modified)
- `backend/apps/integrations/notification_catalog.py` (modified)
- `backend/apps/integrations/notification_enums.py` (modified)
- `backend/apps/integrations/notifications_research.py` (created)
- `backend/apps/integrations/recipients_resolution.py` (modified)
- `backend/apps/integrations/recipients_selection.py` (modified)
- `backend/apps/integrations/staff_notifications.py` (modified)
- `backend/apps/machines/low_stock.py` (modified)
- `backend/apps/machines/notifications_certifications.py` (created)
- `backend/apps/maintenance/notifications.py` (modified)
- `backend/apps/makerspaces/membership_activation.py` (modified)
- `backend/apps/makerspaces/membership_notifications.py` (modified)
- `backend/apps/makerspaces/membership_notifications_research.py` (created)
- `backend/apps/makerspaces/membership_revocation.py` (modified)
- `backend/apps/payments/notifications.py` (created)
- `backend/apps/payments/reconciliation.py` (modified)
- `backend/apps/payments/services.py` (modified)
- `backend/apps/payments/services_connect_webhooks.py` (created)
- `backend/apps/payments/services_refunds.py` (modified)
- `backend/apps/payments/services_refunds_offline.py` (modified)
- `backend/apps/payments/services_webhooks.py` (modified)
- `backend/apps/payments/terminal_settlement.py` (modified)
- `backend/apps/procurement/notifications.py` (created)
- `backend/apps/procurement/views_items.py` (modified)
- `backend/tests/devices/test_device_notifications.py` (modified)
- `backend/tests/test_notification_families_f3.py` (created)
- `backend/tests/test_notification_family_edges_f3.py` (created)
- `backend/tests/test_notification_review_f3.py` (created during review)
- `docs/SOURCE-MAP.md` (modified)
- `docs/SOURCE-MAP-DOMAINS.md` (created during review)
- `frontend/src/features/staff/NotificationRecipientPicker.tsx` (modified)
- `frontend/src/features/staff/NotificationRecipientPicker.test.tsx` (created during review)

## Added tests (coordinator must run)

### `backend/tests/test_notification_families_f3.py`

- `test_catalog_extends_stable_families_and_every_new_cell_is_default_off`
- `test_templates_validate_and_requester_coverage_is_explicit`
- `test_payment_is_on_commit_and_snapshot_has_no_provider_or_amount`
- `test_rollback_sends_nothing`
- `test_default_off_sends_nothing`
- `test_member_variant_uses_own_address_and_amount_never_reaches_chat`
- `test_member_opt_out_and_revocation_win`
- `test_account_only_payment_owner_can_receive_own_email`
- `test_selected_members_get_staff_body_and_requester_flag_controls_own_variant`
- `test_provider_failure_does_not_escape_on_commit`
- `test_disabled_before_commit_suppresses_even_enabled_matrix`
- `test_finance_fallback_matches_existing_finance_list_action`
- `test_choice_migration_matches_all_runtime_fields`
- `test_new_template_stream_module_off_is_400`

### `backend/tests/test_notification_family_edges_f3.py`

- `test_charge_creation_and_offline_settlement_emit_only_after_commit`
- `test_online_settlement_is_idempotent_at_payment_edge`
- `test_waiver_does_not_emit_payment_received`
- `test_successful_refund_emits_once_and_pending_or_failed_do_not`
- `test_offline_refund_emits_after_receipt_transaction`
- `test_membership_decisions_extend_existing_events_and_preserve_welcome`
- `test_low_stock_emits_once_per_existing_restock_edge`
- `test_certification_http_edges_emit_granted_and_revoked`
- `test_type_only_notification_scope_excludes_other_machine_types`
- `test_each_family_module_off_suppresses_delivery`
- `test_existing_maintenance_log_edge_and_module_gate`

### Existing test updated

- `backend/tests/devices/test_device_notifications.py::test_choice_migrations_match_runtime_fields` - integrations leaf advanced to 0028.

## Review pass

Review complete; changes remain unstaged. No database tests were executed. The review
read the root instructions, main-checkout research, handoff, tracked diff and untracked
implementation files. No state-changing git commands were used.

Defects found and fixed:

- Certification revoke was atomic but did not lock the grant: concurrent decisions could
  both write provenance, audit and alerts. The HTTP path now locks only the grant row,
  rechecks revoked_at, and scopes grant and membership queries through RBAC. An actual
  endpoint/SQL regression checks the lock, first-decision preservation and one alert.
- Certification type mutations could persist without their audit if recording failed.
  All three writes are now atomic. Charge creation has the same transaction boundary:
  direct service callers cannot leave an unaudited debt or emit an uncommitted charge.
- Split certification endpoints omitted auth/not-found/module-off errors from OpenAPI.
  They now declare 400/401/403/404, plus 423 on writes. Added a generated-schema test;
  no coordinator-owned schema/client artifacts were regenerated.
- The procurement lock reloaded a row outside RBAC and did not recheck its CURRENT
  machine type. A stale validated serializer could retag another team's item and mark
  it received. Queries now derive tenant scope from RBAC, retain organization-derived
  authority and the existing empty-list/403 contracts, and recheck visibility and the
  module after locking. Added a simulated concurrent-retag regression.
- Stock snapshots dropped known machine provenance, preventing machine-specific rooms
  from matching their own restock alert. Source/result pool and resulting-machine IDs
  now populate the existing NotificationScope alongside the type.
- The bounded snapshot helper treated numeric zero as absent. It now distinguishes
  None from zero. Owner email resolution also rejects an address empty after trimming.
- New migration/split files and the handoff contained CRLF or mixed endings. All
  touched files now use LF. Replaced the handoff's damaged question-mark separators.
- SOURCE-MAP.md exceeded this lane's 300-line ceiling. Moved its domain/frontend/device
  section intact into SOURCE-MAP-DOMAINS.md and linked it from the original entry point.
- Test gaps: added member decline/expiry addressing and privacy checks, commit-time
  owner restriction, charge/type audit rollback, route schema coverage, and late online
  settlement after waiver with distinct provider event IDs. Added a real recipient-picker
  rendering/navigation test for the new families.

Review verification:

- `python -m py_compile` passed for all 38 touched backend Python files.
- `npx.cmd tsc -b` passed, including the new frontend test.
- `npx.cmd vitest run src/features/staff/NotificationRecipientPicker.test.tsx
  src/features/staff/devicesNotificationMatrix.test.tsx`: 2 files / 2 tests passed.
  The .cmd entry point was used because PowerShell blocks npx.ps1.
- `git diff --check`, UTF-8/LF, mojibake and <=300-line checks passed for all touched
  files; AGENTS.md and CLAUDE.md remain byte-identical and unchanged.
- Re-listed integrations migrations: 0028 depends on actual prior leaf 0027. New changes
  add choices only: no new model, field, User FK, module key, capability or environment
  variable. Existing export classification and tenant catalog/projection/authority entries
  cover these rows/fields. Existing notify_lifecycle/dispatch/Celery paths are reused;
  no new scheduled task, deployment tenant fan-out or object-store writer requires a
  gate_policy declaration. Authorization-source files were not moved.

Additional tests for the coordinator (all unexecuted here):

- `backend/tests/test_notification_review_f3.py`:
  `test_charge_audit_failure_rolls_back_debt_and_notification`,
  `test_revoke_locks_only_grant_and_replay_preserves_first_actor`,
  `test_certification_type_audit_failure_rolls_back_creation`,
  `test_locked_procurement_rechecks_current_machine_type_before_retag`,
  `test_stock_scope_reaches_room_for_known_machine`,
  `test_membership_decline_uses_account_address_not_invite_contact`,
  `test_certification_expiry_only_emails_its_member`,
  `test_owner_restriction_before_commit_suppresses_own_payment_email`,
  `test_zero_amount_is_rendered_and_blank_owner_email_is_skipped`,
  `test_split_certification_routes_have_auth_request_response_and_errors`.
- `backend/tests/test_notification_family_edges_f3.py` additionally contains
  `test_late_online_receipt_emits_once_when_waiver_becomes_real_payment` (Stripe/Razorpay).
- `frontend/src/features/staff/NotificationRecipientPicker.test.tsx`: labels the three
  new families and verifies changing the area chooses that family's first event.

Coordinator should run the original verification paths above PLUS
`tests/test_notification_review_f3.py`, `tests/tenant_migration/test_source_gate_guards.py`
and `tests/tenant_migration/test_authority_guard.py` in the isolated runner; confirm
`makemigrations --check --dry-run` and regenerate OpenAPI/client artifacts centrally.
No unresolved owner decision or additional outside-task defect remains. The scheduler,
failure edges, F2 preferences/inbox and later VIEW_FINANCE mapping remain intentionally
deferred as described above. The independent Codex CLI gate still cannot run: doctor
reports missing CODEX_HOME/config and unreachable provider HTTP endpoints.
