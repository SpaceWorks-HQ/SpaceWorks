# SpaceWorks frontend source map

Frontend companion to [SOURCE-MAP.md](SOURCE-MAP.md).

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

Tenant branding lives in `frontend/src/lib/brandColours.ts` (WCAG maths, both-mode
foreground/interaction/ink/tint derivation) and `useTenantBranding.ts` (page-scoped
variables). `features/staff/MakerspaceThemeSettings.tsx` owns the live contrast preview
and audited settings PATCH. `src/styles/components.css` owns the shared component
layer and opaque secondary tint utilities; `src/index.css` owns product tokens, fonts
and base styles. `lib/theme.ts` owns browser theme preference;
`components/SupportContact.tsx` renders safe tenant support links.

