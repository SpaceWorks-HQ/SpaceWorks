# SpaceWorks source map

> **This is the file-layout half of `CLAUDE.md` / `AGENTS.md`.** It was split out when that file crossed
> the harness's memory-file size limit; nothing was dropped in the move. It has no `AGENTS.md`-style twin —
> both names of that document point at this one path, so edit it in place.
>
> Paths drift. If this disagrees with the tree, the tree wins — fix this file in the same commit.

## Current source map (real paths)

WP1 event access and ticketing lives in `events/registration_access.py`, `invites.py`,
`ticketing.py` and `promos.py`; `participant_access.py` limits account ticket reads to
the owned registration. New model, serializer and route files are indexed in
[SOURCE-MAP-DOMAINS.md](SOURCE-MAP-DOMAINS.md). Public event detail and ticket controls
live in `frontend/src/features/inventory/PublicEventDetailPage.tsx` and
`frontend/src/features/events/`; staff ticketing uses `eventTicketingApi.ts` and the
`EventInvitesPanel`, `EventTicketsPanel` and `EventPromosPanel` components.

[Module families and public-site settings](SOURCE-MAP-MODULE-FAMILIES.md) maps the
WP2 loan/public-site gates, compatibility splits, family dashboards and routing.
WP5 staff UX: `components/ui/ListColumns.tsx` supplies shared table column/density
controls, stored in URL list state and `operations/serializers_saved_views.py`.
`features/staff/quickCreate.ts` owns permission-filtered palette creation intents.
`features/staff/handover/HandoverWizard.tsx` and `DirectHandoverWizard.tsx` guide
phone handovers through existing workflow endpoints; `HandoverBoxScan.tsx` and
`HandoverItems.tsx` handle scoped scans and return quantities. `CameraTorch.tsx`
adds optional lighting; `QrScanner.tsx` shows continuous-scan feedback and haptics.
`admin_api/serializers_creation_setup.py` validates nested creation profile/modules
and first staff; `makerspaces/creation_setup.py` applies setup atomically and schedules
invitation delivery after commit. The console creation steps live in
`features/staff/panels/usersModals/CreationWizardSteps.tsx`.
`organizations/views_console.py` and `services_console.py` own superadmin create/link
setup alongside `views_admin.py`; `features/staff/OrganizationSetup.tsx` renders it.
Organization-link audit IDs are inert source provenance in
`tenant_migration/audit_references_meta_ux.py`.
`features/members/memberCard/offlineLoans.ts` stores an explicit own-loan projection;
`OfflineLoansControl.tsx` owns device opt-in and `public/member-pwa/offline.js` renders
the stale snapshot. `components/ui/jobStore.ts` and `JobTray.tsx` observe async jobs
across panel navigation and fence late callbacks after account/session cleanup.

Member renewal automation lives in `makerspaces/membership_renewals.py`, with the
record-first charge seam in `membership_renewal_charges.py`, F1 reminder discovery
in `membership_renewal_reminders.py` and owner-only F3 mail in
`membership_renewal_notifications.py`. `membership_plan_services.py` keeps its
explicit compatibility exports. `membership_self_service.py` owns cancel/leave;
`self_service_access.py` applies owned-membership RBAC and module/feature checks.
Account profile/session routes use `accounts/views_self_service.py`, serializers
and schemas in the matching siblings, and `web_sessions.py` for stable browser
JWT lineage over the existing token ledger. Subject export routes/jobs live in
`data_export/subject_views.py`, `subject_services.py` and `subject_tasks.py`;
`subject_selectors.py` proves row ownership while `subject_archive.py` reuses the
existing field classification. `subject_boundary.py` reuses source-gate boundaries.
Frontend account controls live in `features/members/MemberAccount*.tsx` with
`memberAccountApi.ts`; staff plan controls use `MembershipRenewalFields.tsx`.
See [member-account-renewals.md](member-account-renewals.md) for policy and limits.
Public item deep links live in `frontend/src/features/inventory/PublicItemPage.tsx`;
they reuse `inventory/views.py`'s existing `PublicInventoryDetailView` and the
catalogue's `PublicProductSerializer`. Public search builds an allowlisted vector
from name/description in that view; the staff search vector remains unchanged.
`frontend/src/components/PageMetadata.tsx` owns routed client-side head tags.
`features/members/MemberPortalTabs.tsx` owns member tab URLs and keyboard navigation;
`MemberArea.tsx` reuses the member panels with membership-gated activity and independent
payment visibility. `features/discovery/` owns URL filters, calendar rendering and
tenant-zone date boundaries (`calendarDates.ts`); `features/bookings/SpaceDiscoveryCalendar.tsx`
reads published busy intervals through the existing availability API.

Wave 5 member PWA/offline-card entry points are indexed in
`docs/SOURCE-MAP-CLIENT.md`; toast/undo, setup progress and dashboard drill-down
entry points are indexed in `docs/SOURCE-MAP-CONSOLES.md`.

Cloud surfaces: `accounts/views_social.py` explicitly exports the nonce/login views in
`views_social_login.py` and identity management in `views_social_identities.py`, with shared
verification/error helpers in `views_social_helpers.py`. `integrations/health.py` explicitly exports
`health_status.py` rollups and `health_chat.py` destination/legacy delivery summaries. The
read-only scheduler control page lives in `operations/admin_scheduling.py`.
The shared reminder foundation is `operations/models_reminders.py`,
`reminder_types.py`, `reminder_registry.py`, `reminder_services.py`, `reminder_sweeper.py` and
`tasks_reminders.py`; `membership_payment_reminders.py` registers the admission
payment-deadline consumer for F3 membership notices. Loan borrower/staff sources
are registered explicitly alongside these payment consumers. The explicit `payments.due`
consumer in `payments/reminders.py` uses durable claims for owner-only email.
Receipt and credit-note snapshots live in `payments/models_documents.py`; `documents.py`
allocates the shared tenant sequence in the settlement/refund transaction. `document_pdf.py`
renders snapshots, `document_delivery.py` owns payer-only mail and signed grants, and
`views_documents.py` rechecks payment ownership or active VIEW_FINANCE authority at download.
The finance registry is `operations/report_definitions_finance.py`; `reports_finance_sources.py`
selects dated ledger rows, `reports_finance.py` builds local-period revenue/cash summaries,
and `reports_accounting.py` builds the balanced CSV journal. `report_date_ranges.py`
distinguishes calendar filters from rolling scheduler instants. Frontend document access is
`features/payments/PaymentDocuments.tsx`, policy editing is `staff/BillingDocumentsSettings.tsx`,
and report presentation is `staff/panels/OperationsReportsFinance.tsx`.
Core due dates and billing policy live in `payments/due_dates.py`, `models_billing.py`
and `views_billing.py`; manual receipt corrections/release reuse
`services_refunds_offline.py` and `views_refunds_offline.py`.
`operations/reports_cash_book.py` owns effective manual money-in/out totals.
`payments/schemas_billing.py` documents typed business errors and DRF field-validation
responses. The module guide links into `MODULES-INVENTORY.md`, `MODULES-WORKSHOPS.md`,
`MODULES-PLATFORM.md` and `MODULES-LIFECYCLE.md` to keep each reference below the file ceiling.
Explicit lazy machine/maintenance adapters live in
`reminder_machine_sources.py`. Certification expiry and staff digests live in
`machines/reminders_certifications.py` and `reminders_certification_digest.py`;
maintenance reminders and anchor maths live in `maintenance/reminders.py` and
`recurrence.py`. `machines/models_policy.py` owns tenant/type numeric settings.
`admin_api/views_certification_types.py` and `views_certification_grants.py` own
paginated trainer rosters; `serializers_certifications.py` validates type names and
maps concurrent unique-name collisions to field errors. The member history lives in
`machines/views_member_certifications.py`; `views_machine_type_policy.py` owns policy edits.
Frontend trainer controls live in `staff/panels/machine/CertificationsPanel.tsx`,
`CertificationGrants.tsx` and `MachineReminderPolicy.tsx`; `staff/certificationsApi.ts`
owns paging. `members/MemberCertifications.tsx` owns private history and
`staff/BookableSpaceForm.tsx` owns the optional booking training link.
Staff/member API and UI behavior is described in
[machine-training-maintenance.md](machine-training-maintenance.md).
Explicit event and booking consumers live in `events/reminders.py` and
`bookings/reminders.py`, sharing requester delivery and fair batch discovery in
`operations/reminder_members.py`. The booking editor uses the paginated
`staff/staffBookingApi.ts` choices under booking authority.
Queries use `accounts/rbac.py:scope_for_scheduled_work`; see
[reminder-schedules.md](reminder-schedules.md) for UTC, claims and migration rules.
Platform monitoring uses `admin_api/views_platform_monitoring.py` and its schema sibling;
`operations/platform_dashboard.py` scopes tenants, `platform_signals.py` reads deployment state,
`platform_checks.py` declares checks, and `platform_problems.py` isolates failures.
`platform_integration_health.py` reads channels without creating settings; `tasks_platform.py`
and `scheduler_telemetry.py` own scheduled checks and beat completion telemetry.
Tenant counters and allowances are read by `makerspaces/usage_snapshot.py`.

Membership admission is described in [membership-admission.md](membership-admission.md).
`makerspaces/models_admission.py` owns the settings and immutable vouch models.
`membership_services.py` remains the explicit compatibility barrel over
`membership_helpers.py`, `membership_legacy.py` and `membership_admission.py`.
Admission settings/forms/vouches/charges live in `membership_admission_settings.py`,
`membership_admission_forms.py`, `membership_vouching.py` and
`membership_admission_payments.py`; all grants use `membership_activation.py`.
`membership_admission_direct.py` applies gates to walk-in and core creation paths.
`views_admission.py` serves the public policy and owned applicant/voucher routes;
`admin_api/views_membership_admission.py` serves manager settings. Existing staff
review serializers include answer snapshots and named vouches. Committed payment
callbacks live in `payments/admission_settlement.py`, with narrow rejoin debt access
in `payments/admission_access.py`. `operations/tasks_admissions.py` drives expiry
and settlement recovery in both schedulers. Application-export audit writes and
settlement activation take explicit tenant write boundaries; reviewer debt summaries
use the existing finance-scoped payment context.

Loan policy lives in `makerspaces/models_loan_policy.py` and `loan_policy.py`;
`admin_api/views_loan_policy.py` / `serializers_loan_policy.py` extend the existing
return-policy route. `hardware_requests/workflow.py` exports `renewal_workflow.py`
for policy-bound extensions; `renewal_views.py` serves member/staff actions.
`loan_reminders.py` and `loan_reminder_notifications.py` adapt F1 claims to borrower
mail and F3 escalation. `inventory/availability_loan_limits.py` owns borrower quantity
ceilings; `accounts/rbac_borrowers.py` scopes owned rows even without membership.
`makerspaces/member_loans.py` includes reviewed and direct loans in member activity.
See [loan-policy.md](loan-policy.md) for defaults, inheritance, gates and routes.
`tenant_migration/tenant_dump_authority_loans.py` declares portable loan terms and
renewal history; the fan-out gate registry names the legacy reminder helper that
actually holds the boundary.
Frontend loan controls are `staff/MakerspaceLoanPolicySettings.tsx`,
`staff/StaffLoanRenew.tsx` and `members/MemberLoanRenew.tsx` under features/.

The backend, frontend and domain lookup continues in [SOURCE-MAP-APPS.md](SOURCE-MAP-APPS.md).

Space packs live in `makerspaces/space_pack_*`, with their literal configuration
projection in `data_export/space_pack_configuration.py`. The profile model is
`makerspaces/models_space_packs.py`; HTTP contracts are in
`admin_api/serializers_space_packs.py` and `views_space_packs.py`.
`capabilities.py` re-exports the catalog from `capability_definitions.py` and
validation from `capability_validation.py`;
`loan_policy_settings.py` is the settings editor and pack shared policy writer.
See [SPACE-PACKS.md](SPACE-PACKS.md) for the protocol and authority boundaries.
Frontend `staff/SpacePacksPanel.tsx` owns export/preview/apply, with handwritten
`spacePacksApi.ts` calls and `SpacePackProfilePicker.tsx` for creation profiles.
Platform profile admin scoping is declared in `config/admin_scope_registry.py`;
the profile route is platform-exempt in `tenant_migration/gate_policy_http.py`,
while pack application explicitly asserts the target source gate before writes.
- `backend/config/` — Django project (`settings.py`, `urls.py`, wsgi/asgi). All API routes under `/api/`.
  `config/admin_access.py` holds the `/control/` gating, CSP middleware, and the hidden-scope drift-guard
  registries (`NESTED_MAKERSPACE_LOOKUPS`, `GLOBAL_ADMIN_MODELS`).
- `backend/apps/accounts/` — custom `User` model (`AUTH_USER_MODEL`), browser JWT auth, attested device
  grants/rotating refresh families, Google/Apple social identities + nonce/JWKS verification, and the
  Auth & RBAC module: thin `rbac.py` import surface/coordinator over `rbac_actions.py`,
  `rbac_memberships.py`, `rbac_organizations.py`, and `rbac_superadmin.py` (`can(...)`, action-based
  `actions_for_membership`/`makerspaces_for_action`/`scope_by_action`, makerspace scoping, superadmin
  hide/archive exclusion).
- `backend/apps/makerspaces/` — `Makerspace` model (tenant root; unique `slug`; `frontend_domain`, module
  flags, `resource_limit_overrides`, `archived_at`, `superadmin_access_enabled`), bootstrap views, dynamic
  CORS, module guards, `module_registry.py` (canonical module registry — all module lists derive from
  it; the `ModuleDefinition` tuple itself lives in `module_registry_catalog.py`, the import-time checks in
  `module_registry_validation.py`, so add a module to the catalogue), `platform.py` (origin helpers), `limits.py` (fair-use quotas), `lifecycle.py` (archive/purge barrel
  over `lifecycle_archive.py`, `lifecycle_purge.py` and `lifecycle_storage.py`),
  `models_makerspace_validation.py` owns model clean checks; `theme_validation.py` validates
  the closed theme JSON for control forms and API writes; `theme_contrast.py` owns
  the shared WCAG contract. `theme_validation.public_theme_config` sanitizes bootstrap
  colours while retaining independently valid logo and mode values.
  `profile_validation.py` validates IANA timezone, ISO country and opening-hours JSON;
  `opening_hours_schema.py` documents the shared hours schema. `local_time.py` owns
  `local_now`, `to_local`, `local_day_bounds`, `is_open` and `next_open_interval`
  (aware inputs, UTC half-open bounds; fold/gap policy in its docstring).
  `admin_api/views_makerspace_profile.py` serves audited, MANAGE_MAKERSPACE-scoped
  `/admin/makerspace/<id>/profile`; currency uses `MakerspacePaymentSettings.default_currency`.
  `origin_scope.py` (browser origin→tenant guard), `provisioning.py`/`hosting.py`, `secrets.py`.
  `models_stations.py` owns shared inert `Station` metadata plus the complete live
  `StationCredential` envelope; `station_credentials.py`, `station_sessions.py`, `station_security.py` and
  `station_throttles.py` own reusable rotation/reveal/disable, signing, PIN/origin and throttle mechanics
  without importing event policy.
  `role_services.py` re-exports `role_authority.py` (locked grant validation),
  `role_crud.py` (audited role mutations), and `role_assignments.py` (staff and community
  role assignment). The RBAC vocabulary remains in `accounts/rbac_actions.py`.
  The tenant-migration authority guard scans the split role-authority/assignment modules.
  Phase 9b kiosk Stations: `models_station_leases.py` (`StationOperatorLease`, `StationSessionRevocation`),
  `kiosk_station_services.py` (scanner/handover lifecycle + PIN session), `station_operator_leases.py`
  (lease issue/resolve/narrow/revoke), `station_views_admin.py`/`station_views_public.py`/`station_urls.py`
  (routes), `station_lease_cleanup.py` + `tasks_station.py` (daily cleanup), `checks_station.py` (timing).
  The handover side owns `hardware_requests/kiosk_command_policy.py` (the literal operation table),
  `kiosk_online_commands.py` (work package + dispatch into existing workflows) and `kiosk_views.py`;
  `evidence/services_upload.py` is the shared row+staging-presign service.
- `backend/apps/organizations/` — `Organization` (platform entity, creatable before any makerspace, NOT a
  module_registry key), its opt-in public profile and cross-makerspace event catalogue,
  `OrganizationMakerspace` (the many-to-many link, at most one `owner` per space),
  `OrganizationMembership` (org-level makerspace grants plus separate organization-governance actions),
  and digest-only single-use `OrganizationInvitation` grants. Organization profile/member governance
  lives in `governance.py` + `services_profiles.py`/`services_invitations.py`; makerspace authority is
  resolved through `accounts/rbac.py` with its organization layer in `accounts/rbac_organizations.py`,
  never mirrored into `MakerspaceMembership`; `accounts/org_payload.py` projects it into the auth payload.
  `models.py` is the schema source of truth; `governance.py` owns the fixed organization-only action
  vocabulary, `access.py` the visible/locked authorization queries, and the two `services_*` modules the
  transactional audited profile and invitation mutations. `public_catalog.py` is the canonical public
  organization-event queryset; `urls_public.py` withdraws that separable events route when `apps.events`
  is tombstoned, while `urls_admin.py` and the corresponding `views_*`/`serializers_*` expose governance.
- `backend/apps/apiclients/` — `ApiClient` (client_id + Fernet-encrypted HMAC secret), `ApiKeyRequest`, and
  `scope_registry.py`/`scope_registry_routes.py` — the single source of truth for which protected route each
  scope authorizes, keyed on the versioned `view_name`. `checks.py` is the deployment-time guard that a
  widened `HMAC_PROTECTED_PATH_PREFIXES` has no unregistered routes. Verification itself lives in
  `apps/inventory/middleware.py`. `origin_validation.py` is the shared exact-origin boundary, and
  `ApiClientImportApproval` plus the import-provenance/delivery fields are Lane D's append-only,
  artifact-bound API-client reset record.
- `backend/apps/audit/` — append-only `AuditLog` + `audit.record(...)` (Postgres-trigger immutable), with
  signing/batch models in `models_signing.py`, verification phases behind the `integrity.py` barrel, and
  object-store/HTTP collector protocols behind the `anchors.py` barrel (typed sink failures in
  `anchors_base.py`, the per-attempt read budget in `anchors_budget.py`, budgeted S3 reads in
  `anchors_object_io.py`). `presentation.py` is the ONE projector from a stored row to what staff may see
  (catalogue in `presentation_catalog*.py`, deny policy in `presentation_catalog_dynamic.py`, drift guard in
  `presentation_guards.py` + `presentation_discovery.py`), used by the audit list, the request timeline and
  the `audit-trail` CSV. Staff verification runs: models in `models_verification_runs.py`, admission in
  `verification_runs.py`, one attempt in `verification_execution.py` over `integrity_scope.py` (bounded
  genesis membership in `integrity_rows.py`, query-free fetched batch checks in `integrity_scope_anchors.py`), the task in
  `tasks_verification.py`, the API in `views_verification.py`/`serializers_verification.py`, read-only
  `/control/` views in `admin_verification.py`. The request timeline's audit/retention helper is
  `hardware_requests/timeline_service_audit.py`; the audit report is `operations/reports_audit.py`.
- `backend/apps/evidence/` — evidence photos (immutable once attached), S3 storage helpers, signed upload/view URLs gated by
  per-makerspace `UPLOAD_EVIDENCE` + active status.
  `retention_models.py` owns the optional per-makerspace `EvidenceRetentionPolicy` override and per-photo
  `EvidenceObjectRetentionState`, re-exported by
  `models.py`; both use normal primary keys plus unique one-to-ones so they can travel through tenant
  migration. `retention_policy.py` is the single source of truth for the effective window and candidate/
  preview query. `services_retention.py` owns the bounded idempotent sweep: it observes deployment recovery
  and each tenant source gate, removes both final and staging bytes, credits confirmed storage and audits a
  terminal expired state without mutating the `EvidencePhoto` row. `sweep_evidence_retention()` is the
  single sweep entry point, `tasks.py` is its Celery/scheduled-task adapter, and `views_retention.py` exposes
  the policy and preview API. Mechanism A (object expiry) always retains the row.
  Abandoned-upload cleanup is separate: `consumption.py` owns the only permitted photo UPDATE (the
  one-way `consumption_state` → `consumed` mark every consuming workflow makes inside its attachment
  transaction); `abandoned_upload_candidates.py` is the single predicate (`unconsumed`, strictly old,
  no inbound FK, no consumption audit, no live coordination claim) shared by preview, discovery and
  rechecks; `abandoned_upload_cleanup.py` is the gated fan-out sweep (report fence first) and
  `abandoned_upload_state.py` its claim/complete/release state machine, which deletes a proven
  never-consumed presign row under the exact-ID GUC and writes the permanent FK-free
  `EvidenceAbandonedUploadReceipt`; `abandoned_upload_reconciliation.py` re-deletes receipt keys forever
  as deployment coordination (360-minute success / 720-minute failure cadence).
- `backend/apps/boxes/` — `QrCode`/`Box` payloads, immutable `BoxScan`/`QrScanEvent`, `qr_render.py`
  (namespaced standalone SVG shared by QR-print + batch ZIP), QR rebind. Camera scanner at
  `frontend/src/components/ui/QrScanner.tsx` (native `BarcodeDetector` + `zxing-wasm` fallback).
- `backend/apps/admin_api/` — staff REST surface: makerspaces, inventory CRUD + per-makerspace category CRUD
  (`EDIT_INVENTORY`), bulk import, staff/membership + role management, user restrict/restore, API-client
  issuance (`api_client_views.py`) and access requests (`api_key_request_views.py`), audit reads, warranty,
  email-log, notification-recipient, FabLab report views.
  `views_certifications.py` explicitly re-exports type endpoints from
  `views_certification_types.py` and grant endpoints from `views_certification_grants.py`.
- `backend/apps/operations/` — open operations/reporting: health, stock transfers (intra + true
  cross-makerspace), stocktake, adjustments, ledger, `report_registry.py` + `report_scope.py` + `reports_*`
  builders, CSV/XLSX exports, container APIs, QR print batches (`qr_zip.py`), dashboard, accountability.
  `views.py`/`services.py` are thin re-export barrels over `views_*`/`services_*`.
- `backend/apps/integrations/` — Telegram/email/Slack/Mattermost/native-push delivery, encrypted FCM/APNs
  credentials + device registrations, `dispatch_email` choke point + `EmailLog` outbox + Celery task,
  webhook (auth via `X-Telegram-Bot-Api-Secret-Token` vs `TELEGRAM_WEBHOOK_SECRET`, fail-closed),
  `PlatformEmailSettings`, `DailyEmailCounter`, staff-notification recipient matrix.
  F3's bounded templates live in `email_templates_registry_research.py`; domain
  adapters use `notifications_research.py` for on-commit staff and owner email delivery.
- Update and backup internals: see [SOURCE-MAP-PLATFORM.md](SOURCE-MAP-PLATFORM.md).
- `backend/apps/devices/` — device identity (phase 7a, separable, module `devices`). `models_identity.py`
  (Device, DeviceEnrollment, DeviceRequestNonce) and `models_events.py` (append-only DeviceEvent, DB
  trigger in `0001`); `protocol.py` owns the v1 canonical bytes and published vectors;
  `authentication.py` (DeviceAuthentication -> `DevicePrincipal`, never a User) and
  `route_registry.py` + `checks.py` (the exact `/api/v1/device/` route/action registry and its system
  check); `services_locks.py` is the Makerspace -> Device -> Enrollment lock order every mutation takes;
  `services_enrollment.py` (PoP enroll/rotate/reactivate), `services_identity.py` (create/PATCH/revoke),
  `services_requests.py` (atomic nonce claim, heartbeat), `services_events.py` (DeviceEvent + typed
  `devices.*` audit).
  Phase 7b adds `models_commands.py` and `models_printers.py` for durable delivery, bindings
  and typed immutable reports. `services_commands.py` owns lease/ack/backoff; `printer_access.py`
  owns current adapter checks and scope; `services_printer_reports.py` claims measurements before
  `services_printer_apply.py` invokes the existing machine workflow in a separate transaction.
  Binding and creation services are separate siblings; `printer_state.py` derives advisory staff
  state. `urls_7b.py`/`route_registry_7b.py` extend the exact protocol and staff surfaces.
  Shared export, PII, purge, origin and tenant-migration registries compose `*_7b.py` siblings.
  Phase 7c adds `models_labels.py` (LabelPrintCommand and immutable LabelPrintResult),
  `services_label_*`, `label_access.py`, `serializers_labels.py` and `views_labels.py`.
  Labels reuse `services_commands.py` lease/ack/backoff and the operations ZIP renderer;
  `*_7c.py` siblings compose the shared catalogs. The first send freezes a QR batch.
  The full contract and invariants live in [device-label-commands.md](device-label-commands.md).
- `backend/apps/data_export/` — Space-Manager data export (Phase 4). Per-fidelity (`REDACTED`/`PORTABLE`)
  disposition registry over models, fields, datasets, traversals and the global-user reference closure, with
  **drift guards that refuse an unclassified model or field**. `classification.py` and `references.py`
  are thin barrels: the exported field lists live in `classification_domain.py`, the global/omitted
  model reasons in `classification_platform.py`, and the declared `accounts.User` edges in
  `references_core.py`; adapter extensions compose `classification_7b.py`/`references_7b.py`.
  Credential omission checks live in `guards_credentials.py` behind the original `guards.py` exports. Its `guards._equal(subject, declared,
  actual)` is called with the *scanned* set passed as `declared`, so `extra=` in a failure means **scanned
  but not registered** — read the signature before deciding which side to fix.
- `backend/apps/tenant_migration/` — per-makerspace migration, managed → self-host (Phase 5B), in
  `SEPARABLE_APPS`. `source_gate.py` + `gate_locks.py`/`gate_runtime.py`/`gate_policy.py`/`middleware.py`/
  `task_gate.py` (the write-drain lock protocol and its AST coverage guards in `source_gate_guards.py`);
  `archive_envelope.py` + `object_export.py` (streamed into `age`); `admission.py` (the source-superadmin
  closure approval); `materialization.py` + `raw_repository.py` + `row_planning.py`/`row_dispositions.py`
  (one-shot insertion); `target_projection.py` (barrel over `target_projection_{types,fields,rows,references}.py`)
  + `unique_values.py` (barrel: the rules dict is
  `unique_values_core.py`, the disposition/policy types `unique_values_policy.py`) + `closure_references.py`;
  `tenant_dump_model_catalog.py` + `tenant_dump_field_snapshot.py` +
  `tenant_dump_authority.py` (public barrel over literal `tenant_dump_authority_entries.py`
  and domain supplements)/`tenant_dump_catalog.py` (Lane D's deny-by-default source catalog), and
  `tenant_dump_source_projection.py` (single-makerspace raw rows plus decision-22 grant closure);
  `tenant_dump_builder.py` (Lane D's migrated scratch → verified custom-dump orchestrator), with
  `tenant_dump_database.py`, `tenant_dump_graph.py`, `tenant_dump_raw.py`, `tenant_dump_sql.py` and
  `tenant_dump_verification.py` owning run-scoped databases, actual-row FK ordering/nullable cycles,
  reviewed raw columns, fence/closure SQL and restored-candidate verification respectively;
  `tenant_dump_sequences.py` owns Lane D's exact empty/non-empty sequence state;
  `tenant_dump_machine_types.py` resolves only fingerprint-identical global built-ins, while
  `tenant_dump_objects.py` packages immutable staged object bytes without live-storage reads;
  `tenant_dump_capture.py` + `tenant_dump_capture_database.py` freeze the full exported-snapshot database
  and exact object bytes before `source_gate_release.py` performs the fenced `copy_capture` release;
  `tenant_dump_staging.py` + `tenant_dump_database_cleanup.py` own marker-guarded crash cleanup;
  `tenant_dump_cleanup.py` retries refused unpublished-object deletion from its durable capture-row key;
  `tenant_dump_derivation.py` derives and seals output only from that capture;
  `tenant_dump_pii.py` binds raw mapped-column mode findings and ciphertext AAD identities;
  `tenant_dump_key_inventory.py` freezes and exact-set checks source-broker key facts, while
  `tenant_dump_dek_protocol.py`/`tenant_dump_dek_helper.py`/`tenant_dump_deks.py` keep plaintext DEKs inside
  the bounded child operation and emit only the tenant-recipient ciphertext;
  `tenant_dump_recipients.py` keeps `outer_recipients` and `tenant_dek_recipients` distinct, and
  `tenant_dump_envelope.py` owns the declared key-member presence/absence ledger plus streaming outer seal;
  `tenant_dump_target.py` binds D5's pre-destructive identity proof to reconstruction, with
  `tenant_dump_target_identities.py` enforcing read-only mode-0600 tenant mounts,
  `tenant_dump_target_protocol.py`/`tenant_dump_target_helper.py`/`tenant_dump_target_deks.py` owning the
  key-free parent plus bounded target decrypt/rewrap child, and `tenant_dump_target_readiness.py` rebuilding
  target search derivations and authenticated readiness; `tenant_dump_target_custody.py` re-proves carried
  recipient public metadata and independently derives Part A versus Lane D custody and decision-19b routing;
  `tenant_dump_manifest.py` and `tenant_dump_lineage.py` bind D4 custody facts and parent/policy digests;
  `tenant_dump_publication.py` owns recipient revalidation, refusal cleanup and the atomic
  pending-to-published/download transition; `tenant_dump_audit_anchors.py` supplies the fail-closed
  external-anchor absence proof;
  `tenant_restore_orchestrator.py` is the D7 §5.4 ordered target-restore spine over H1;
  `tenant_restore_activation.py` owns crash-safe pointer/marker re-entry and writer restart, with
  `tenant_restore_preflight.py`, `tenant_restore_database*.py`, `tenant_restore_sibling.py`,
  `tenant_restore_pgpass.py`, `tenant_restore_pointer.py` and `tenant_restore_scheduler.py` owning
  topology/privilege/lifecycle/credential-minimization/CAS/callback refusal boundaries;
  `tenant_restore_target_state.py`, `tenant_restore_objects.py`, `tenant_restore_api_clients.py`,
  `tenant_restore_superadmin.py` and `host_credential_delivery.py` own target-import gating, pre-ledgered
  object effects, approved authority reset and durable one-time credential delivery;
  `verification.py` (pre-commit), audit-reference domains behind the `audit_references.py` barrel, and
  `target_cutover.py` (pre-activation + `IMPORTING → ACTIVE`);
  `receipts.py`/`receipt_crypto.py`/`cutover.py` (signed single-use handoff); `views_*.py` (superadmin REST).
- `backend/apps/inventory/` — `InventoryProduct`/`InventoryAsset`, `availability.py` (**the only place**
  available/reserved/issued/damaged/lost counts change: `reserve_for_request`, `issue_items`/`return_items`,
  `issue_available`/`return_to_available`, `consume_available`; row-locked, never-below-zero,
  `InsufficientStock`), `public_availability.py`, allowlist-only public serializers/views,
  `public_image_storage.py`, `seed_demo`.
## Domain and frontend map
See [SOURCE-MAP-DOMAINS.md](SOURCE-MAP-DOMAINS.md) for hardware loans, payments,
printing, events, the frontend directories and connected device monitoring.
See also [SOURCE-MAP-CLIENT.md](SOURCE-MAP-CLIENT.md) for the standalone
frontend directory and browser/kiosk flow map.
See [SOURCE-MAP-CONSOLES.md](SOURCE-MAP-CONSOLES.md) for staff lists, saved views,
command-palette discovery and the connected-device console map.
Staff list preferences live in `operations/models_saved_views.py`, `serializers_saved_views.py` and
`views_saved_views.py`; cross-entity discovery is `admin_api/search.py`. Shared pagination/ordering
and entity authority live in `admin_api/list_options.py` and `staff_list_scope.py`.
Saved-view audit targets travel as inert source provenance in
`tenant_migration/audit_references_targets.py`, including after a preference is deleted.
Booking/event `views_admin_spaces.py` / `views_admin_events.py` barrels re-export the corresponding `*_list/detail.py` handlers.
