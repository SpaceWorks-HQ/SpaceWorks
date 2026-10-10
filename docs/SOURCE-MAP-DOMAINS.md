# SpaceWorks domain and frontend source map

Continued from [SOURCE-MAP.md](SOURCE-MAP.md); paths are relative to the repository root.

- `backend/apps/hardware_requests/` — Hardware Request Workflow: `HardwareRequest`/`HardwareRequestItem`,
  `HardwareRequestItemAsset` through-model, immutable `ReturnEvent`/`RequesterAccountability`,
  `PublicToolLoan`, `PublicProblemReport`. `workflow.py` is the **single source of truth** for state
  transitions (atomic + row-locked + audited; also `assign_box`/`issue_request`/`return_items`);
  `permissions.py`, `exceptions.py` (workflow→HTTP map + `ErrorSerializer._EXCEPTION_MAP`),
  `notifications.py` (Telegram seam), public submit/verify/status views, `send_return_reminders` command.
  `self_checkout_workflow.py` re-exports the issue and return services from `self_checkout_issue.py`
  and `self_checkout_returns.py`, with shared evidence checks in `self_checkout_evidence.py`.
  All return paths use `return_helpers.finalize_return_status`, which schedules the post-commit
  loan charge seam in `loan_payments.py` only when the request closes.
  Phase 9c replay: `models_replay.py` owns omitted command coordination; `replay_authorization.py`
  reloads the human lease and live policy; `replay_serializers.py`/`replay_payload_serializers.py` and
  `replay_fingerprint.py` normalize the protocol; `replay_prepare.py` establishes evidence/ownership;
  `replay_claims.py` fences claims; `replay_execute.py`/`replay_dispatch.py` wrap the shared online
  dispatcher and workflow transaction. `replay_views.py` is mounted by makerspaces/station_urls.py;
  `replay_cleanup.py`/`tasks_replay.py` implement bounded daily cleanup, with settings checks in checks.py.
  `evidence/finalization_completed.py` supplies database-only finalized reuse under domain locks.
  `frontend/src/features/kiosk/kioskReplayApi.ts` hand-writes typed prepare/execute calls using only
  Station cookie + human lease; `kioskReplayClient.ts` now owns encrypted foreground/SW replay.
  The staff recovery screen remains phase 9e.
- `backend/apps/payments/` — immutable multi-subject Payment authority, per-space raw credentials + managed
  Stripe Connect resolution, checkout/webhook settlement, reconciliation, native PaymentSheet intents.
  `services_webhooks.py` re-exports Connect handling from `services_connect_webhooks.py`;
  `notifications.py` supplies bounded payment snapshots to the feature/channel matrix.
- `backend/apps/printing/` — **TOMBSTONED** (Project B): only an `AppConfig` and an empty `models.py`, kept
  in `INSTALLED_APPS` so its historical migrations remain installed. 3D printing is now a `MachineType`
  inside `apps/machines/` — look there, not here.
- `backend/apps/roadmap/` — **TOMBSTONED**: `RoadmapItem` retained for migration history only. No URLs,
  serializers, admin surface or frontend; `tests/roadmap/test_removed_surfaces.py` asserts they stay removed.
- `backend/apps/machines/` — machine registry and service workflows. Machine-role authorization keeps a
  thin `role_scope.py` import surface over `role_scope_resolution.py` (including the identity-sensitive
  `EXEMPT`/`NOTHING` sentinels), `role_scope_grants.py`, and `role_scope_queries.py`; scope mutations remain
  in `role_scope_services.py`.
- `backend/apps/events/` — the separable events module. `models.py` is the stable explicit re-export barrel
  over `models_event.py`, `models_registration.py`, `models_attendance.py`, `models_feedback.py`,
  `models_station.py`, `models_certificates.py`, `models_series.py`, `models_calendar.py`, `models_collaborators.py` and
  `organizer_models.py`; those focused files are the schema sources for events/occurrences, approval and
  waitlist registrations, immutable check-in history and the event-owned `EventStationBinding`, feedback,
  certificate artifacts,
  recurring series, member feed credentials, makerspace collaboration and organization attribution.
  `services.py` remains the audited transactional boundary for one-off event and registration mutations,
  delegating lifecycle and registration-state transitions to `services_lifecycle.py`,
  `services_registration.py` and `services_registration_state.py`. The other `services_*` modules own the
  corresponding series/recurrence/collaboration, calendar/feed, badge, check-in/offline-sync and the event
  policy adapter over the makerspaces Station core,
  feedback/certificate, image and organizer workflows; `urls_admin.py`, `urls_member.py`, `urls_public.py`
  and `urls_station.py` divide the staff, authenticated-member, public and anonymous-station surfaces.
- `backend/apps/warranty/`, `apps/maintenance/`, `apps/events/`, `apps/bookings/`, `apps/forms_schema/`,
  `apps/encryption/`, `apps/procurement/`, `apps/notifications/`, `apps/operations/report_registry.py` — the
  remaining FabLab + governance modules.
- `backend/tests/` — pytest behavior tests (external behavior, not implementation).
- `frontend/src/features/inventory/` — public catalog/detail/self-checkout + `ProductCard`/
  `AvailabilityBadge`. `frontend/src/features/staff/` — staff console panels; grouped nav via
  `staffAccess.ts` `TAB_GROUPS`, which does sidebar grouping AND permission derivation (**not**
  `StaffApp.tsx`; module gating and routing are the separate `staffTabs.ts`); capabilities from
  action-based `staffAccess.ts`; payment reconciliation and platform credential panels.
  `MakerspaceProfileSettings.tsx` loads/saves the location and hours profile;
  `MakerspaceHoursEditor.tsx` and `makerspaceProfileForm.ts` own the weekly/exception
  draft. Profile and payment editors refresh each other's shared currency query.
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

Tenant branding lives in `frontend/src/lib/brandColours.ts` (WCAG checks and
light/dark palette derivation) and `useTenantBranding.ts` (page-scoped variables).
See [SOURCE-MAP-FRONTEND.md](SOURCE-MAP-FRONTEND.md) for the theme settings preview,
shared component styles, browser theme preference and tenant support links.

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
