# w7-ux lane progress

BUILD GAPS WP5 27-33. All source changes are unstaged. No git state-changing commands, database tests, generated schema/client regeneration, migrations, new models, module keys or feature keys.

## Completed

- 27: shared DataTable column chooser and comfortable/compact density, integrated into inventory, bookings and payments. URL state and SavedView preserve presentation; presentation keys are excluded from API filtering. Retired columns safely fall back to current columns. Server accepts bounded, inert identifiers only.
- 28: permission- and enabled-tab-filtered palette commands for new request/direct handout, item, event and booking. Destinations consume the create intent once; booking asks the user to select the space before using its existing staff booking form.
- 29: guided reviewed-request issue/return and direct handout. Reviewed issue requires resolved box QR, borrower confirmation, required individual-asset scans, kit counts and uploaded photo. Return requires resolved container, valid outcomes, uploaded photo and a nonblank remark. Direct handout requires an eligible borrower, scanned/selected tools and uploaded photo. Uses existing workflow endpoints exclusively; receipts appear only after a successful workflow response. Assignment/issue partial failures retain an honest retry state. Camera torch is optional; supported scans use best-effort haptics. Sticky modal actions have phone-size targets.
- 30: makerspace creation wizard covers identity, profile/hours, saved pack, explicit module family overrides, first staff invitation and review. DRF nested serializers reuse existing validators; service setup and pack application share the creation transaction. Only edited profile fields override a pack. Existing invitation service owns encrypted address/token creation and fail-safe delivery after commit. Private fallback links are returned with no-store.
- 31: superadmin organization create and link/update/unlink in the existing console tab. Existing models only; OpenAPI annotations, action-scoped servable makerspaces, explicit hard-hidden exclusion, tenant-freeze lock before the tenant root lock, owner uniqueness and audits. UI warns that all three relationship labels can confer existing organization grants. Confirmation precedes link changes.
- 32: explicit device opt-in for a minimal own-loan offline projection. No QueryClient/API/evidence/payment cache. Stale timestamps are visible; account switch/logout and authoritative access refusal erase the snapshot; network failures preserve it. Separate card/loan opt-ins, bounded records and safe text rendering. Session-memory job tray follows imports, data exports and tenant/deployment backups after source-panel navigation, polls status, announces progress and supports retry/dismissal. Jobs clear on account change/logout.
- 33 script mode: verified scripts/update.sh already has git mode 100755 in this worktree; added an explicit host-only regression guard. No index update needed.

## Incomplete / prerequisites

- 33 compound-snapshot rollback is NOT implemented. The audit named real files, but scripts/restore.sh explicitly refuses compound-coordinator-ready and apps/updates/rollback.py refuses these manifests. The compound coordinator and database/target/pointer primitives exist; there is no complete production artifact/writer/object/capability adapter assembly or host command wiring. apps/backup/import_preflight.py still reports the host restore gate as "not configured". A safe host producer/consumer assembly, deployment topology and candidate readiness/recovery acknowledgement wiring must precede this rollback path. Passing a compound envelope to the legacy in-place restore would restore projected SQL while skipping required object/authority restoration. No refusal was weakened; no fake bridge/test claiming support was added.
- Coordinator must run backend tests, regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts, and perform real phone/camera QA. Neither generated file was edited here.
- Codex CLI review gate unavailable: codex doctor could not resolve config/home or reach the inference endpoint. No separate CLI review performed.
- Deferred audit items remain deferred, including guest registration, self-serve organization creation and other listed owner decisions. Events/bookings membership dependency removal and the loans master switch belong to WP2; no cross-lane files were edited for them.
- No new owner product decisions requested for implemented scope. Compound restore is an engineering prerequisite, not product sign-off.

## Verification actually performed

- 22 selected frontend suites: 94 tests passed. Includes the new/extended tests below plus existing DataTable, card, MemberArea variants, backup, payments and PWA scope regression suites.
- TypeScript noEmit completed with errors ONLY in the five pre-existing files named by the user: generated/api.ts, features/members/MemberPayments.test.tsx, features/staff/MembersPanel.tsx, features/staff/PaymentBilling.test.tsx, features/staff/panels/OrganizedEventsPanel.test.tsx. None were edited.
- Python AST syntax parsed for every changed Python file. git diff --check clean. All touched files are under 300 lines.
- NO backend/DB tests run; no backend pass claim. No Docker/build/live browser run.
- Tests reused the main checkout's already-installed frontend dependencies through an ignored lane-local node_modules junction. A temporary lane-only Vitest runner config kept cache writes in this worktree; it was removed afterward. Coordinator can use the normal frontend test configuration.

## Added / extended tests for coordinator

Backend (not run):
- backend/tests/operations/test_saved_views.py: test_columns_and_density_survive_saved_view_round_trip; test_invalid_presentation_state_is_refused (4 cases).
- backend/tests/makerspaces/test_creation_wizard.py: test_creation_profile_modules_and_first_staff_are_audited_and_delivery_follows_commit; test_invalid_setup_never_creates_a_makerspace_or_invitation (4 cases); test_pack_and_explicit_setup_share_one_transaction; test_creation_setup_cannot_be_replayed_on_settings_patch.
- backend/tests/organizations/test_admin_create_link.py: test_create_is_superadmin_only_and_audited; test_link_update_unlink_scope_and_audit; test_hidden_space_refused_and_not_listed_without_changing_links; test_second_owner_is_conflict_and_preserves_both_organizations; test_frozen_space_blocks_link_update_and_unlink_and_writes_no_audit.
- backend/tests/test_privileged_script_modes.py: test_update_operator_entry_point_is_executable. Host-only; Docker skips this guard when git/worktree metadata are unavailable.

Frontend (all run):
- components/ui/ListColumns.test.tsx: chooser/density/SavedView restore and retired-column fallback, including axe checks.
- components/ui/CameraTorch.test.tsx: unsupported/refusing capability reads; torch constraints toggle and failure fallback.
- components/ui/JobTray.test.tsx: progress survives panel navigation/polls/announces; tenant/session isolation; transient status-read retry and collection completion.
- features/staff/quickCreate.test.ts: action/enabled-tab filtering and superadmin commands.
- features/staff/CommandPalette.test.tsx: new permitted quick-create keyboard navigation with forbidden/disabled destinations omitted.
- features/staff/handover/HandoverWizard.test.tsx: box/photo issue gate and ordered workflow; photo/remark return gate; partial assignment failure with retry and no premature receipt, including axe.
- features/staff/handover/DirectHandoverWizard.test.tsx: borrower/integer quantity/photo gating and receipt; revoked/foreign card refusal; box QR cannot substitute for a tool, including axe.
- features/staff/panels/usersModals/CreateMakerspaceWizard.test.tsx: complete step/payload flow and partial profile override; invalid identity refusal, including axe.
- features/members/memberCard/offlineLoans.test.ts: minimal projection; tenant/member-route scope; same-owner refresh/account switch/logout; malformed/wrong-owner refusal; separate opt-ins/access-refusal clear; unavailable storage refusal.
- features/members/memberCard/offlineShell.test.ts: added own-loan text-only rendering with stale timestamp and cross-tab logout erasure; existing card fixture updated for loans section.
- lib/useUrlListState.test.tsx: added presentation/page preservation and exclusion from API query.

Coordinator backend targets: tests/operations/test_saved_views.py tests/makerspaces/test_creation_wizard.py tests/organizations/test_admin_create_link.py. Also run relevant scoping/servability/source-gate/OpenAPI guards and the host script-mode guard. Compound rollback tests need the production host bridge first.

## Migrations / outside defects

- No migrations; dependencies: not applicable. Existing model/registry classifications remain unchanged.
- Outside-task defects: the five known TypeScript errors above remain. No additional outside-task regression identified. The compound restore host assembly gap is documented under item 33.

## Complete persistent file manifest

Created:
- `LANE-PROGRESS.md`
- `backend/apps/admin_api/serializers_creation_setup.py`
- `backend/apps/makerspaces/creation_setup.py`
- `backend/apps/organizations/services_console.py`
- `backend/apps/organizations/views_console.py`
- `backend/tests/makerspaces/test_creation_wizard.py`
- `backend/tests/organizations/test_admin_create_link.py`
- `frontend/src/components/ui/CameraTorch.test.tsx`
- `frontend/src/components/ui/CameraTorch.tsx`
- `frontend/src/components/ui/JobTray.test.tsx`
- `frontend/src/components/ui/JobTray.tsx`
- `frontend/src/components/ui/ListColumns.test.tsx`
- `frontend/src/components/ui/ListColumns.tsx`
- `frontend/src/components/ui/jobStore.ts`
- `frontend/src/features/members/memberCard/OfflineLoansControl.tsx`
- `frontend/src/features/members/memberCard/offlineLoans.test.ts`
- `frontend/src/features/members/memberCard/offlineLoans.ts`
- `frontend/src/features/staff/OrganizationSetup.tsx`
- `frontend/src/features/staff/handover/DirectHandoverWizard.test.tsx`
- `frontend/src/features/staff/handover/DirectHandoverWizard.tsx`
- `frontend/src/features/staff/handover/HandoverBoxScan.tsx`
- `frontend/src/features/staff/handover/HandoverItems.tsx`
- `frontend/src/features/staff/handover/HandoverWizard.test.tsx`
- `frontend/src/features/staff/handover/HandoverWizard.tsx`
- `frontend/src/features/staff/panels/usersModals/CreateMakerspaceWizard.test.tsx`
- `frontend/src/features/staff/panels/usersModals/CreationWizardSteps.tsx`
- `frontend/src/features/staff/quickCreate.test.ts`
- `frontend/src/features/staff/quickCreate.ts`

Modified:
- `backend/apps/admin_api/serializers_makerspace_mutations.py`
- `backend/apps/admin_api/serializers_makerspaces.py`
- `backend/apps/admin_api/views_makerspaces.py`
- `backend/apps/operations/serializers_saved_views.py`
- `backend/apps/organizations/urls_admin.py`
- `backend/apps/organizations/views_admin.py`
- `backend/tests/operations/test_saved_views.py`
- `backend/tests/test_privileged_script_modes.py`
- `frontend/public/member-pwa/offline.html`
- `frontend/public/member-pwa/offline.js`
- `frontend/public/member-sw.js`
- `frontend/src/components/ui/CameraCapture.tsx`
- `frontend/src/components/ui/DataTable.tsx`
- `frontend/src/components/ui/QrScanner.tsx`
- `frontend/src/features/members/MemberActivity.tsx`
- `frontend/src/features/members/MemberArea.tsx`
- `frontend/src/features/members/memberCard/offlineCard.ts`
- `frontend/src/features/members/memberCard/offlineShell.test.ts`
- `frontend/src/features/staff/BackupRestorePanel.tsx`
- `frontend/src/features/staff/BookingsPanel.tsx`
- `frontend/src/features/staff/CommandPalette.test.tsx`
- `frontend/src/features/staff/CommandPalette.tsx`
- `frontend/src/features/staff/DataExportsPanel.tsx`
- `frontend/src/features/staff/DirectLoans.tsx`
- `frontend/src/features/staff/EventsPanel.tsx`
- `frontend/src/features/staff/PaymentsPanel.tsx`
- `frontend/src/features/staff/StaffListContext.tsx`
- `frontend/src/features/staff/StaffTabContent.tsx`
- `frontend/src/features/staff/StaffWorkspace.tsx`
- `frontend/src/features/staff/organizationsApi.ts`
- `frontend/src/features/staff/panels/BulkImport.tsx`
- `frontend/src/features/staff/panels/InventoryWorkspace.tsx`
- `frontend/src/features/staff/panels/OrganizationsPanel.tsx`
- `frontend/src/features/staff/panels/RequestQueues.tsx`
- `frontend/src/features/staff/panels/Users.tsx`
- `frontend/src/features/staff/panels/users/forms.ts`
- `frontend/src/features/staff/panels/usersModals/CreateMakerspaceModal.tsx`
- `frontend/src/features/staff/panels/usersModals/types.ts`
- `frontend/src/lib/api/client.ts`
- `frontend/src/lib/useUrlListState.test.tsx`
- `frontend/src/lib/useUrlListState.ts`


## Review pass (2026-10-11)

Review fixes remain unstaged. Read-only git only. The lane is NOT complete: WP5 item 33's production compound host restore assembly remains absent.

Defects found and fixed:

1. Valid nested creation profiles could raise AttributeError because the inherited validator read standalone initial_data. CreationProfileSerializer now validates supplied nested input, preserves field validators, rejects unknown profile fields and accepts omitted overrides. Added a direct nested regression and invalid-field HTTP coverage.
2. PATCH creation_setup was rejected only inside update(), after settings_audit.snapshot tried to read it as a model field and could raise AttributeError. MakerspaceSerializer now rejects it during field validation, before the view's audit snapshot. The HTTP regression checks no module change and no update audit.
3. Organization-link audit organization_id metadata lacked tenant-migration declarations. Added audit_references_meta_ux.py and unioned it into the existing catalogue. All three actions keep source-local organization provenance; imported audit metadata grants no target organization authority. Added remap/guard tests.
4. Guided scans accepted other authorized tenants' QR results, unavailable direct-handout tools and over-available manual quantities as ready. Box/assets/tools now check the selected makerspace, asset availability and the server's direct_handout action; manual quantities must stay within available stock. Backend workflow checks remain authoritative. Added foreign/unavailable/quantity regressions.
5. Continuous-scan progress and refusals were hidden behind the camera overlay. QrScanner accepts live feedback; handover flows show counts and errors inside the active camera UI. Added a camera-open progress/refusal regression.
6. Comfortable density changed every existing DataTable's padding, including tables without controls, and hidden-column loading skeletons kept the old column count. Preserved original py-2 spacing; compact remains py-1; skeletons use visible columns. Added legacy-spacing coverage.
7. Clearing the job tray on logout did not fence outstanding create/status responses, and query keys could reuse a previous session's job result. Jobs now carry a session generation; every producer captures it in onMutate, late callbacks are ignored, and status query keys include it. Added late creation/progress callback coverage.
8. Membership-list 400/403/404 refusals retained offline private projections, and a mounted loan control could transfer the previous member's opt-in to the next account. Authoritative refusals erase card/loan data; transient failures preserve it. Opt-in is bound to the account that chose it. Added refusal/network and mounted-account-switch regressions.
9. New organization endpoints declared error statuses without response bodies, and the new conflict exception omitted its stable code. Added error-object OpenAPI schemas and structured organization_conflict responses. Added scoped schema contracts and conflict-code assertions; inactive-organization refusal also has regression coverage.
10. SOURCE-MAP lacked all new lane modules, and LANE-PROGRESS.md used CRLF. Added the lane entry points to docs/SOURCE-MAP.md and normalized this handoff to UTF-8/LF.

Verification:

- Frontend: 22 suites, 94 tests passed in the final selected-area run. Includes DataTable/ListColumns, CameraTorch, JobTray, palette, both guided handovers, creation wizard, OfflineLoansControl/card/loans/shell, MemberArea variants, URL state, backups, exports and payments.
- Requested npx tsc -b attempted via npx.cmd (PowerShell disallows npx.ps1). Its normal node output path points through the existing node_modules junction outside the writable lane and returned EPERM. An equivalent temporary project-build config with lane-local output ran afterward and reported ONLY the five known excluded TypeScript files. No lane TypeScript diagnostics. Temporary configs/cache removed afterward.
- python -m py_compile passed for every touched backend Python file. git diff --check passed. Touched production code stays <=300 lines; touched text is UTF-8/LF and no mojibake was found. CLAUDE.md/AGENTS.md were not edited.
- No backend runtime/DB test pass claim: host Python lacks Django. Coordinator must use the isolated Docker runner. OpenAPI annotations/tests were updated; generated schema/client regeneration remains coordinator work in the configured backend.
- Rechecked codex doctor: CLI config/home resolution and inference reachability fail. No independent CLI review gate was available.
- No new persisted models/fields, migrations, module/feature keys, environment variables, tasks, fan-outs or object writers. Existing classifications, User-FK policies and gate declarations therefore remain applicable; the new audit metadata declaration is explicit.

Coordinator backend targets (from backend/):

- tests/operations/test_saved_views.py
- tests/makerspaces/test_creation_wizard.py
- tests/makerspaces/test_creation_console_schema.py
- tests/organizations/test_admin_create_link.py
- tests/organizations/test_org_console_access.py
- tests/organizations/test_org_authority.py
- tests/tenant_migration/test_organization_link_audit_references.py
- tests/tenant_migration/test_staff_invitation_audit_references.py
- tests/tenant_migration/test_source_gate_guards.py
- tests/tenant_migration/test_source_gate.py
- tests/makerspaces/test_tenant_servability_guard.py
- tests/makerspaces/test_space_pack_openapi.py
- tests/accounts/test_staff_invitation_schema.py
- tests/test_privileged_script_modes.py (host-only mode checks skip in Docker without git metadata)

Additional persistent files from this review: backend/apps/tenant_migration/audit_references_meta_ux.py; backend/tests/tenant_migration/test_organization_link_audit_references.py; backend/tests/makerspaces/test_creation_console_schema.py; frontend/src/features/members/memberCard/OfflineLoansControl.test.tsx. Also modified the audit metadata barrel, docs/SOURCE-MAP.md and MemberArea.test.tsx beyond the previous manifest.

Remaining engineering gap: item 33 still needs concrete production artifact/object/writer/capability adapters, host command wiring, pointer/topology admission, and candidate readiness/recovery acknowledgements. import_preflight.host_restore_gate_status() still returns "not configured"; restore.sh still refuses compound-coordinator-ready; updates/rollback.py still refuses compound manifests. These refusals were preserved. Coordinator must keep item 33 open, regenerate OpenAPI/client artifacts after the configured backend checks, and perform phone/camera QA before treating this lane as ready.
