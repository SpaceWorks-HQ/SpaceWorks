# SpaceWorks app and domain source map

Continuation of [SOURCE-MAP.md](SOURCE-MAP.md).

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
- `backend/apps/notifications/` - legacy shared feed plus `models_inbox.py` personal rows;
  `inbox.py` matrix fan-out, `legacy_inbox.py` legacy-only staff snapshots,
  `preferences.py` opt-out policy, `views_inbox.py`/`views_preferences.py` personal APIs,
  `retention.py` F1 bounded cleanup. See `docs/notification-inbox.md`.
  `accounts/rbac_notifications.py` owns personal history scope and trusted tenant policy reads;
  `backup/archive_objects.py` declares the inbox event UUID as a non-object key.
  Membership analytics use `operations/reports_retention.py` and
  `reports_membership_revenue.py`; `membership_report_history.py` recovers counts-only
  lifecycle intervals, and `membership_report_scope.py` applies RBAC to report rows.
  `report_schedule_rules.py` validates conditions and resolves current staff recipients;
  `report_condition_metrics.py` declares threshold columns. Saved report preferences reuse
  `models_saved_views.SavedView` through `views_report_views.py` and
  `serializers_report_views.py`; `serializers_report_views_filters.py` shares the filter
  allow-list with schedules. The frontend report panel uses `ServerReportViews.tsx` and
  `SelectedReportPreview.tsx` for server preferences and selected-column previews.
- `backend/apps/integrations/` — Telegram/email/Slack/Mattermost/native-push delivery, encrypted FCM/APNs
  credentials + device registrations, `dispatch_email` choke point + `EmailLog` outbox + Celery task,
  webhook (auth via `X-Telegram-Bot-Api-Secret-Token` vs `TELEGRAM_WEBHOOK_SECRET`, fail-closed),
  `PlatformEmailSettings`, `DailyEmailCounter`, staff-notification recipient matrix.
  Email `dispatch.py` explicitly exports `dispatch_policy.py`, `dispatch_outbox.py` and
  `dispatch_delivery.py`; `email_preferences.py` owns unsubscribe/suppression checks.
  `delivery_views.py` and `suppression_views.py` expose audited scoped delivery controls;
  `admin_suppression.py` provides superadmin-only, platform-mail suppression.
  `webhook_schema.py` owns v2 event schemas (`docs/webhooks-v2.md`).
  F3's bounded templates live in `email_templates_registry_research.py`; domain
  adapters use `notifications_research.py` for on-commit staff and owner email delivery.
- `backend/apps/updates/` — singleton platform update state, audited superadmin controls, and the
  `update_control` management command used by the privileged host scheduler. The web process never gets
  Docker-socket access; host scripts claim queued/automatic releases and report check/backup/result state.
- `backend/apps/backup/` - see [recovery source map](SOURCE-MAP-RECOVERY.md) for ownership and entry points.
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
- `backend/apps/tenant_migration/` - see [recovery source map](SOURCE-MAP-RECOVERY.md) for ownership and entry points.
- `backend/apps/inventory/` — `InventoryProduct`/`InventoryAsset`, `availability.py` (**the only place**
  available/reserved/issued/damaged/lost counts change: `reserve_for_request`, `issue_items`/`return_items`,
  `issue_available`/`return_to_available`, `consume_available`; row-locked, never-below-zero,
  `InsufficientStock`), `public_availability.py`, allowlist-only public serializers/views,
  `public_image_storage.py`, `seed_demo`.
  `availability_stock.py` observes locked availability writes for F3 STOCK crossings;
  `availability_transfers.py` owns transfer/stocktake quantity operations, re-exported
  through `availability_quantities.py` and the public availability barrel.
  `kit_serializers.py` validates bounded product/container component definitions;
  `kit_validators.py` applies that contract to control-panel model forms as well.
  `reorder_views.py` lists staff suggestions and calls procurement `services_drafts.py`.
- `makerspaces/capabilities.py` is the explicit compatibility barrel over
  `capability_definitions.py` (catalog) and `capability_validation.py` (dependencies).
- `hardware_requests/kit_checklists.py` freezes physical issue and return counts;
  `kit_preview.py` / `kit_views.py` provide scoped read-only capture previews.
  `serializers_handover.py` owns issue/return inputs, explicitly re-exported by
  `serializers.py`. Product/container definitions are JSON; snapshots hold opaque
  component UUIDs, labels and counts, so no embedded foreign IDs require remapping.

## Domain and frontend map

See [SOURCE-MAP-DOMAINS.md](SOURCE-MAP-DOMAINS.md) for hardware loans, payments,
printing, events, the frontend directories and connected device monitoring.
See also [SOURCE-MAP-CLIENT.md](SOURCE-MAP-CLIENT.md) for the standalone
frontend directory and browser/kiosk flow map.
See [SOURCE-MAP-CONSOLES.md](SOURCE-MAP-CONSOLES.md) for staff lists, saved views,
command-palette discovery and the connected-device console map.
Personal inbox, preferences, delivery history and suppression controls live in
`frontend/src/features/notifications/`; staff panel wrappers and MemberArea mount them.

Staff list preferences live in `operations/models_saved_views.py`, `serializers_saved_views.py` and
`views_saved_views.py`; cross-entity discovery is `admin_api/search.py`. Shared pagination/ordering
and entity authority live in `admin_api/list_options.py` and `staff_list_scope.py`.
Saved-view audit targets travel as inert source provenance in
`tenant_migration/audit_references_targets.py`, including after a preference is deleted.
Booking service windows live in `bookings/services_schedule.py` (F4 hours, buffers and cutoff);
`services_transitions.py` owns audited booking completion/cancellation behind explicit compatibility
exports. Member booking history and self-cancel are in `bookings/views_member.py`.
Staff booking lists, creation/member choices and actions live in the separate
`views_admin_booking_list.py`, `views_admin_booking_create.py` and `views_admin_booking_actions.py`
modules behind the `views_admin_bookings.py` barrel.
Booking editors get only machine type IDs/names from `bookings/views_admin_machine_types.py`,
under `MANAGE_BOOKINGS`; this does not grant Machines-console authority.

Booking-space and event handlers use explicit `views_admin_spaces.py` / `views_admin_events.py`
barrels over the corresponding `views_admin_space_list/detail.py` and `views_admin_event_list/detail.py`.
