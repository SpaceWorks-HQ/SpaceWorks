# w5-ux progress

Implementation complete; coordinator validation and commit remain. Every edit is inside this worktree and unstaged. No state-changing git command or database test was run.

## Completed
- Separate member scopes (`/member`, `/m/<slug>/member`) and kiosk scopes (`/kiosk/`, `/m/<slug>/kiosk/`). Retires the historical root registration without deleting queued kiosk data. Existing active root-controlled tabs may need one reload during upgrade.
- Worker-served member manifests, generated 192/512 PNG icons, install prompt/browser instructions, revisioned dedicated offline HTML/CSS/JS. Only static member assets enter the member cache: no API responses, staff data, photos, loans or TanStack Query persistence.
- Explicit personal-device opt-in for a card-only snapshot and own active QR image. Every offline presentation says stale/last-known and requires staff online validation. Saving waits for the member worker; server refresh rotates cached QR; revocation, logout and account changes forget the applicable saved data.
- Shared accessible toast host and polite atomic announcer, including repeated messages and errors on older notifications. Inventory archive/unarchive undo uses an awaited real reverse PATCH and invalidates server state. Double undo is blocked; failures stay visible; expiry never calls a reversal.
- All 13 dashboard tiles link to allowed, module-enabled filtered lists using URL state. Added strict exact-zero inventory, bounded recent email and stocktake status filters; new machine-scoped paginated overdue maintenance read endpoint. Print type filtering now includes assigned-machine-only jobs, matching the counter and retaining global type identity.
- Setup checklist is a read-only tenant-scoped projection of profile/location, explicit opening hours, inventory, invitation rows and actual module changes in audit history. Dismissal is per user/makerspace/browser, module-inapplicable item steps are omitted, forbidden actions show an administrator hint.
- Kept near-ceiling inventory, request queue and stocktake entry points as explicit export barrels over domain components; extracted archive mutations, queue presentation and count editor. Existing imports remain valid.
- Schemas accompany new/changed read routes and filters; added origin-scope route entries. No model, migration, module key or feature key was added. AGENTS.md and CLAUDE.md were not edited and remain byte-identical.

## Validation recorded
- Ran `npm.cmd run test` for the final frontend suite (159 files / 655 tests, exit 0), as well as focused runs for offline-card readiness, announcer, URL-filter and component-split changes. Database tests below remain unrun.
- Ran `npm.cmd run build`: TypeScript/build and both service-worker scope guards exited 0. Guard exercises both member scopes, member manifest/icons, offline fallback, static-only cache boundaries, staff/API/kiosk exclusions, and preserved kiosk scanner WASM/revisioned shell.
- Parsed all 15 changed/new Python files with AST; no Django imports or database operations were performed. `git diff --check` produced no output. All touched files remain below 300 lines.
- `codex doctor` was rechecked: sandbox config/home and provider reachability unavailable. External CLI review gates remain coordinator-only.

## Tests added / extended
Frontend new files (47 cases total including parameterized scope/link cases):
- `frontend/src/components/ui/ToastHost.test.tsx`: 6 tests for expiry without reversal, awaited/double undo, reversal failure, repeated/focus-preserving announcements, older-toast failure announcement, accessible live region.
- `frontend/src/lib/pwaScopes.test.tsx`: 7 scope cases and 2 registrations/root-retirement cases.
- `frontend/src/features/members/memberCard/offlineCard.test.ts`: 4 tests for tenant isolation, staff-route exclusion, selective cleanup, same-owner refresh vs new owner.
- `frontend/src/features/members/memberCard/OfflineCardSave.test.tsx`: 4 tests for consent/forget, member-worker readiness, refreshed QR/check timestamp, revocation cleanup.
- `frontend/src/features/staff/SetupChecklist.test.tsx`: 4 tests for real-state/module derivation, permitted links, per-space dismissal, completed hiding.
- `frontend/src/features/staff/panels/dashboardLinks.test.ts`: 12 tile/path variants and the warranty cutoff test.
- `frontend/src/features/staff/panels/DashboardMachineQueue.test.tsx`: 4 tests for explicit URL queue whitelist, global type identity/status, paginated maintenance link, module-off requests.
- `frontend/src/features/staff/panels/QueuesDrilldown.test.tsx`: 2 cases for only pending/accepted queue fetching and rendering.
- `frontend/src/features/staff/panels/useInventoryArchive.test.tsx`: real archive/reverse PATCH and query invalidation.
Existing test files extended:
- `frontend/src/features/staff/panels/DashboardPanel.test.tsx`: router wrapper and permitted/module-enabled tile link test.
- `frontend/src/features/staff/panels/EmailLogPanel.test.tsx`: router wrapper and URL restoration of failed/recent/page filters.
Build verification extended: `frontend/scripts/verify-pwa-build.mjs`.

Backend new files (13 tests; coordinator MUST run):
- `backend/tests/makerspaces/test_ux_setup_and_own_card.py`:
  - test_setup_reads_real_state_without_modules_or_writing_rows
  - test_setup_progress_is_tenant_scoped_and_derived
  - test_inventory_manager_cannot_read_setup_state
  - test_feature_only_change_does_not_claim_modules_were_chosen
  - test_own_card_contains_only_own_qr_and_never_a_photo_key
  - test_own_card_refuses_module_off
- `backend/tests/maintenance/test_ux_overdue_list.py`:
  - test_overdue_drilldown_filters_active_and_strict_past_due_with_pagination
  - test_overdue_drilldown_has_no_fallback_for_an_empty_custom_machine_scope
  - test_overdue_drilldown_answers_400_when_maintenance_module_is_off
- `backend/tests/test_ux_drilldown_filters.py`:
  - test_print_type_drilldown_includes_assigned_machine_only_jobs_without_slug_collision
  - test_out_of_stock_drilldown_means_exactly_zero_and_includes_archived_when_requested
  - test_stocktake_status_filter_is_validated_and_tenant_scoped
  - test_dashboard_email_filter_excludes_old_failures_and_other_tenants

## Coordinator remaining work
- Run `./scripts/dev.sh test tests/makerspaces/test_ux_setup_and_own_card.py tests/maintenance/test_ux_overdue_list.py tests/test_ux_drilldown_filters.py` plus related original card, machine-service/scoping, maintenance, inventory, stocktake, origin-scope and schema guards.
- Regenerate `frontend/openapi-schema.json` and `frontend/src/generated/api.ts`; deliberately left untouched per lane instruction.
- Real-browser QA: install on secure single-tenant and central member routes, opt in to a card, airplane-mode launch, stale warning/QR, forget/logout/new-user isolation; upgrade a legacy root worker and verify kiosk scanning/queued replay still work. Build VM verification does not substitute for browser installation testing.
- Run external review gates; verify/commit all unstaged files. No merge or push is authorized here.

## Skips / owner decisions / unrelated defects
- No blocking owner decision. Member-only PWA default applied on single-tenant and central member routes; built-in icons are a reliable fallback, with tenant display name in the manifest.
- Loans, staff offline data, async-job tray and wider research-plan items are outside this assigned lane. Undo is limited to archive/unarchive; actions without an existing safe reversal retain their confirmation/workflow surfaces.
- Modules chosen is proven only by a changed module list in audit history. Keeping the preinstalled defaults unchanged does not record an explicit choice today; the checklist can be dismissed. A separate acknowledgement workflow would need an owner decision and is not fabricated here.
- Pre-existing unrelated defect: `backend/apps/operations/views_dashboard_counts.py` silently catches broad exceptions and leaves counters at zero, so storage/query failures can appear as empty queues. Left untouched outside these UX/filter changes.

## Created / modified file inventory
Root/docs:
- LANE-PROGRESS.md
- docs/SOURCE-MAP-CLIENT.md
- docs/SOURCE-MAP-CONSOLES.md
Backend apps:
- backend/apps/admin_api/inventory_filters.py
- backend/apps/admin_api/urls_makerspaces.py
- backend/apps/admin_api/views_email_logs.py
- backend/apps/admin_api/views_inventory_products.py
- backend/apps/admin_api/views_machine_service_requests.py
- backend/apps/admin_api/views_setup_state.py (new)
- backend/apps/maintenance/urls.py
- backend/apps/maintenance/views_overdue.py (new)
- backend/apps/makerspaces/member_card_own_serializer.py (new)
- backend/apps/makerspaces/member_card_views.py
- backend/apps/makerspaces/origin_scope_routes.py
- backend/apps/operations/views_stocktake.py
Backend tests: the three new files listed above.
Frontend build/public:
- frontend/nginx.conf
- frontend/vite.config.ts
- frontend/tsconfig.node.json
- frontend/scripts/kiosk-pwa.ts
- frontend/scripts/member-pwa.ts (new)
- frontend/scripts/verify-pwa-build.mjs
- frontend/public/member-sw.js (new)
- frontend/public/member-pwa/offline.html (new)
- frontend/public/member-pwa/offline.js (new)
- frontend/public/member-pwa/offline.css (new)
Frontend runtime:
- frontend/src/main.tsx
- frontend/src/components/PwaRegistration.tsx (new)
- frontend/src/components/ui/ToastHost.tsx (new)
- frontend/src/components/ui/toastStore.ts (new)
- frontend/src/lib/pwaScopes.ts (new)
- frontend/src/lib/api/client.ts
- frontend/src/features/members/MemberArea.tsx
- frontend/src/features/members/MemberCardPanel.tsx
- frontend/src/features/members/MemberInstall.tsx (new)
- frontend/src/features/members/memberCard/api.ts
- frontend/src/features/members/memberCard/offlineCard.ts (new)
- frontend/src/features/members/memberCard/OfflineCardSave.tsx (new)
- frontend/src/features/staff/StaffTabContent.tsx
- frontend/src/features/staff/StaffWorkspace.tsx
- frontend/src/features/staff/SetupChecklist.tsx (new)
- frontend/src/features/staff/setupChecklistState.ts (new)
- frontend/src/features/staff/panels/AccountabilityPanel.tsx
- frontend/src/features/staff/panels/DashboardPanel.tsx
- frontend/src/features/staff/panels/dashboardLinks.ts (new)
- frontend/src/features/staff/panels/DashboardMachineQueue.tsx (new)
- frontend/src/features/staff/panels/EmailLogPanel.tsx
- frontend/src/features/staff/panels/Inventory.tsx
- frontend/src/features/staff/panels/InventoryWorkspace.tsx (new)
- frontend/src/features/staff/panels/useInventoryArchive.ts (new)
- frontend/src/features/staff/panels/MachinesPanel.tsx
- frontend/src/features/staff/panels/Queues.tsx
- frontend/src/features/staff/panels/RequestQueues.tsx (new)
- frontend/src/features/staff/panels/QueuesDisplay.tsx (new)
- frontend/src/features/staff/panels/StocktakePanel.tsx
- frontend/src/features/staff/panels/StocktakeSessionPanel.tsx (new)
- frontend/src/features/staff/panels/StocktakeCountSection.tsx (new)
- frontend/src/features/staff/panels/WarrantyPanel.tsx
- frontend/src/features/staff/panels/machine/MachineDrawer.tsx
Frontend tests: all eleven new/extended files listed above.

## Review pass

2026-10-11: Reviewed the brief/research, AGENTS.md/global workflow, the handoff,
the full unstaged diff and new files, and the relevant accessibility, machine-scope
and tenancy rules. Git was used read-only throughout; nothing was staged or committed.

Defects found and fixed:
- Toast busy-state updates cancelled the pending aria-live announcement. Kept the
  announcement timer across unrelated row changes, with cleanup on unmount/sign-out.
- Older archive undo buttons could overwrite a newer change to the same item, and
  archive/restore could race an in-flight undo. Retire superseded compensations and
  refuse overlapping changes per product; every successful reversal still uses PATCH.
- Private staff notifications and undo closures survived account changes/logout.
  Clear the toast store on authentication changes, preserve it on same-owner token
  refresh, and suppress late mutation/undo results from the prior session.
- TanStack retained a previously valid card after a failed refetch, allowing its QR
  to appear current and be saved after access denial. Refuse retained card data after
  refresh errors and forget the saved copy on module-off/auth/access/not-found errors.
- Logout/account changes in another tab erased storage but left an open offline
  card's name/QR visible. The offline shell now clears its displayed copy on storage changes.
- Disabled dashboard work queues still rendered previously cached rows. Hide cached
  data on module-off and select dashboard queues before mounting the fleet workspace,
  avoiding unrelated machine/type/pool queries and redirects for queue URLs.
- Inventory export lost `archived=all` from the zero-stock dashboard view. Carry the
  actual archive filter into CSV/XLSX requests, scope the export queryset through RBAC,
  and document both archive modes and the new out-of-stock filter.
- Setup progress missed inventory/invitation live invalidations, and dismissal state
  could carry between users in a mounted workspace. Add derived-progress invalidation
  while preserving the unknown-event fallback; key the checklist by user plus space.
- Own-card lookup lacked an explicit RBAC queryset boundary. Add it while preserving
  the own-active-membership constraint and the private QR-only projection. Also scope
  the stocktake creation tenant lookup through RBAC before resolving the requested space.
- The archive compensation endpoint lacked the module-off guard and complete error
  documentation. Gate detail reads/PATCH through `staff_admin` and document partial
  writes, actual responses, validation/auth/scoping and migration-freeze errors.
- The source-map index did not point to this lane's split reference entries. Update
  `docs/SOURCE-MAP.md` and both client/console references with the final ownership.

Regression coverage now includes 17 touched frontend test files and 20 backend tests
across the four paths below. Added tests exercise announcement timing, superseded and
overlapping PATCH/undo calls, authentication changes and late callbacks, retained-card
access denial, cross-tab offline display cleanup, module-off cached queues, workspace
query suppression, setup live refresh, and dashboard export filters. Backend additions
cover real 24/25-row pagination, suspended actors, read-without-audit writes, revoked
QRs, audited archive/compensation, foreign-tenant refusal, module-off no-write behavior,
filtered export isolation and generated OpenAPI contracts.

Validation:
- `python -m py_compile` passed on all 17 lane backend Python files; the final run
  also compiled the concurrently changed existing payments migration (18 total).
- `npx tsc -b` passed; `npm run build` passed, including both service-worker scope/cache
  guards, member manifests/icons/offline fallback and kiosk scanner WASM preservation.
- `npx vitest run` on all 17 touched frontend test files passed: 101 tests, zero failures.
- `git diff --check`, UTF-8/LF checks, touched-code 300-line ceiling, and byte equality
  of AGENTS.md/CLAUDE.md passed. No models, DB fields, migrations, module keys, environment
  variables, tasks, fan-out seams or backend object writers were introduced, so their
  classification/catalog/projection/authority/env/gate-policy declarations do not change.

Coordinator MUST run (paths relative to backend):
```bash
./scripts/dev.sh test tests/makerspaces/test_ux_setup_and_own_card.py tests/makerspaces/test_ux_schema.py tests/maintenance/test_ux_overdue_list.py tests/test_ux_drilldown_filters.py
```
Also run the related existing `tests/test_member_cards.py`, `tests/test_inventory_export.py`,
`tests/test_ops_dashboard.py`, `tests/test_stocktake_integrity.py`, `tests/test_stocktake_scan.py`,
`tests/maintenance`, `tests/machines/test_machine_scope_surfaces.py`,
`tests/makerspaces/test_origin_scope_p2b.py` and source-gate/schema guards.

Database tests and schema snapshot/client regeneration remain unrun: host Python has
no Django, and Docker's engine pipe is denied in this sandbox. Regenerate
`frontend/openapi-schema.json` and `frontend/src/generated/api.ts` in the coordinator's
backend environment using spectacular `--format openapi-json`, then the frontend client
generator. New schema tests check the contracts directly from the view declarations.
`codex doctor` was rechecked; configuration/home and provider reachability still fail,
so external CLI review gates remain blocked here. Real-browser install/airplane-mode
and kiosk upgrade QA remain required as described above.

Concurrent change observed during final validation: someone else modified
`backend/apps/payments/migrations/0020_billing_due_refund_amendments.py` to pass
`params=None` on the two trigger-SQL executions. It was absent from the initial dirty
inventory, was inspected and compiled, and was preserved without editing it. This is
an existing migration's SQL-execution correction, not a model/field addition by this lane.
