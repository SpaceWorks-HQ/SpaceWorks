# Console and frontend source map

Continuation of [SOURCE-MAP.md](SOURCE-MAP.md).

- `frontend/src/features/inventory/` — public catalog/detail/self-checkout + `ProductCard`/
  `AvailabilityBadge`. `frontend/src/features/staff/` — staff console panels; grouped nav via
  `staffAccess.ts` `TAB_GROUPS`, which does sidebar grouping AND permission derivation (**not**
  `StaffApp.tsx`; module gating and routing are the separate `staffTabs.ts`); capabilities from
  action-based `staffAccess.ts`; payment reconciliation and platform credential panels.
  `frontend/src/features/auth/` + `members/MemberAuthPanel.tsx` — provider-config-driven social/member auth.
  `frontend/src/features/printing|bookings|forms|...` — feature slices. `frontend/src/lib/`,
  `components/ui/`, `types/`, `generated/api.ts`.
- `frontend/src/features/events/` — the standalone anonymous PIN-station route. Its
  `EventCheckInStationPage.tsx` exchanges the event-scoped PIN, then reuses the offline roster/sync API,
  IndexedDB state and operator UI owned by `features/staff/eventCheckInOfflineApi.ts`,
  `eventCheckInOfflineStore.ts` and `OfflineCheckInOperator.tsx`.
- `frontend/src/features/kiosk/` — Station shell, selected offline handover and queue status.
  `offlineQueueStore.ts`/`offlineQueueDb.ts` own atomic encrypted work/commands/evidence,
  cross-context locks, caps and expiry; `offlineEvidence.ts` owns pixel normalization.
  `replayPolicy.ts` owns scheduling/backoff and typed authority/domain distinctions.
  `frontend/src/lib/encryptedIndexedDb.ts` supplies storage/crypto mechanics shared
  with the legacy event adapter, whose database/wire format remains unchanged.
  `frontend/src/sw.ts` owns kiosk app-shell fetch policy and opportunistic encrypted
  Background Sync. `frontend/scripts/kiosk-pwa.ts` bundles it through Vite and injects
  final asset revisions; `verify-pwa-build.mjs` checks emitted artifacts. Static
  `public/sw.js` is removed. The offline rules live in `docs/KIOSK-OFFLINE.md`.
  Failed handover recovery lives in `hardware_requests/replay_recovery_*` and
  `features/kiosk/KioskReplay*`; its review, correction and retention contract is
  documented in `docs/KIOSK-RECOVERY.md`. `operations/e2e_kiosk_seed.py` supplies
  isolated real-workflow fixtures; `dev.sh e2e` runs Playwright against a production preview.
- `frontend/src/features/organizations/` — public organization presentation and invitation redemption:
  `PublicOrganizationPage.tsx` renders the public profile and paginated cross-makerspace event catalogue,
  `OrganizationInvitationRedeemPage.tsx` binds a single-use invitation after member sign-in, and
  `publicOrganizationsApi.ts` owns their TanStack Query keys and public API calls. Staff profile,
  membership, invitation and event-organizer controls remain under `frontend/src/features/staff/`.

Tenant branding lives in `frontend/src/lib/brandColours.ts` (AA checks) and
`useTenantBranding.ts` (page-scoped variables). `lib/theme.ts` owns the browser theme preference;
`components/SupportContact.tsx` renders safe tenant support links.

## Connected device monitoring (phase 7d lane)

`apps/devices/services_offline.py` owns the per-tenant offline/retention scan and the locked
activity/recovery hook. `tasks.py` exposes its one-minute scheduled entry; `notifications.py`
builds immutable edge-time snapshots for the existing staff notification fan-out.
`integrations/email_templates_registry_devices*.py` owns the staff-only devices stream.
`tenant_migration/gate_policy.py` re-exports HTTP, task and object catalogs from the corresponding
`gate_policy_http.py`, `gate_policy_tasks.py` and `gate_policy_objects.py` siblings.

Frontend `StaffTabLoaders.tsx` holds lazy imports; `StaffPlatformTabContent.tsx` composes platform/admin
panels. `panels/DevicesPanel.tsx`, `DeviceIdentitySection.tsx` and `DeviceEnrollmentModal.tsx` render
7a identity/status/enrollment controls through `devicesApi.ts` and `deviceQueryKeys.ts`.
Printer adapter and label-command controls require the sibling 7b/7c lanes and are not present here.

`frontend/src/lib/useUrlListState.ts` owns staff filter/sort/page navigation. `StaffListContext.tsx`,
`ListViewControls.tsx` and `SavedViewsMenu.tsx` expose server-stored per-user preferences and manager
sharing; `CommandPalette.tsx` supplies keyboard navigation and scoped entity discovery.
Palette hits use an optional scoped list ID filter for inventory, members and requests;
the list controls clear it, while event, machine and booking hits open their drawers.
