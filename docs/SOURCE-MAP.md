# SpaceWorks source map

> **This is the file-layout half of `CLAUDE.md` / `AGENTS.md`.** It was split out when that file crossed
> the harness's memory-file size limit; nothing was dropped in the move. It has no `AGENTS.md`-style twin —
> both names of that document point at this one path, so edit it in place.
>
> Paths drift. If this disagrees with the tree, the tree wins — fix this file in the same commit.

## Current source map (real paths)

- `backend/config/` — Django project (`settings.py`, `urls.py`, wsgi/asgi). All API routes under `/api/`.
  `config/admin_access.py` holds the `/control/` gating, CSP middleware, and the hidden-scope drift-guard
  registries (`NESTED_MAKERSPACE_LOOKUPS`, `GLOBAL_ADMIN_MODELS`).
- `backend/apps/accounts/` — custom `User` model (`AUTH_USER_MODEL`), browser JWT auth, attested device
  grants/rotating refresh families, Google/Apple social identities + nonce/JWKS verification, and `rbac.py`
  (the Auth & RBAC module: `can(...)`, action-based `actions_for_membership`/`makerspaces_for_action`/
  `scope_by_action`, makerspace scoping, superadmin hide/archive exclusion).
- `backend/apps/makerspaces/` — `Makerspace` model (tenant root; unique `slug`; `frontend_domain`, module
  flags, `resource_limit_overrides`, `archived_at`, `superadmin_access_enabled`), bootstrap views, dynamic
  CORS, module guards, `module_registry.py` (canonical module definitions — all module lists derive from
  it), `platform.py` (origin helpers), `limits.py` (fair-use quotas), `lifecycle.py` (archive/purge barrel
  over `lifecycle_archive.py`, `lifecycle_purge.py` and `lifecycle_storage.py`),
  `origin_scope.py` (browser origin→tenant guard), `provisioning.py`/`hosting.py`, `secrets.py`.
- `backend/apps/organizations/` — `Organization` (platform entity, creatable before any makerspace, NOT a
  module_registry key), `OrganizationMakerspace` (the many-to-many link, at most one `owner` per space) and
  `OrganizationMembership` (org-level `granted_actions`). Authority is resolved in `accounts/rbac.py`, never
  mirrored into `MakerspaceMembership`; `accounts/org_payload.py` projects it into the auth payload.
- `backend/apps/apiclients/` — `ApiClient` (client_id + Fernet-encrypted HMAC secret), `ApiKeyRequest`, and
  `scope_registry.py`/`scope_registry_routes.py` — the single source of truth for which protected route each
  scope authorizes, keyed on the versioned `view_name`. `checks.py` is the deployment-time guard that a
  widened `HMAC_PROTECTED_PATH_PREFIXES` has no unregistered routes. Verification itself lives in
  `apps/inventory/middleware.py`.
- `backend/apps/audit/` — append-only `AuditLog` + `audit.record(...)` (Postgres-trigger immutable), with
  signing/batch models in `models_signing.py`, verification phases behind the `integrity.py` barrel, and
  object-store/HTTP collector protocols behind the `anchors.py` barrel.
- `backend/apps/evidence/` — immutable evidence photos, S3 storage helpers, signed upload/view URLs gated by
  per-makerspace `UPLOAD_EVIDENCE` + active status.
- `backend/apps/boxes/` — `QrCode`/`Box` payloads, immutable `BoxScan`/`QrScanEvent`, `qr_render.py`
  (namespaced standalone SVG shared by QR-print + batch ZIP), QR rebind. Camera scanner at
  `frontend/src/components/ui/QrScanner.tsx` (native `BarcodeDetector` + `zxing-wasm` fallback).
- `backend/apps/admin_api/` — staff REST surface: makerspaces, inventory CRUD + per-makerspace category CRUD
  (`EDIT_INVENTORY`), bulk import, staff/membership + role management, user restrict/restore, API-client
  issuance, audit reads, warranty, email-log, notification-recipient, FabLab report views.
- `backend/apps/operations/` — open operations/reporting: health, stock transfers (intra + true
  cross-makerspace), stocktake, adjustments, ledger, `report_registry.py` + `report_scope.py` + `reports_*`
  builders, CSV/XLSX exports, container APIs, QR print batches (`qr_zip.py`), dashboard, accountability.
  `views.py`/`services.py` are thin re-export barrels over `views_*`/`services_*`.
- `backend/apps/integrations/` — Telegram/email/Slack/Mattermost/native-push delivery, encrypted FCM/APNs
  credentials + device registrations, `dispatch_email` choke point + `EmailLog` outbox + Celery task,
  webhook (auth via `X-Telegram-Bot-Api-Secret-Token` vs `TELEGRAM_WEBHOOK_SECRET`, fail-closed),
  `PlatformEmailSettings`, `DailyEmailCounter`, staff-notification recipient matrix.
- `backend/apps/updates/` — singleton platform update state, audited superadmin controls, and the
  `update_control` management command used by the privileged host scheduler. The web process never gets
  Docker-socket access; host scripts claim queued/automatic releases and report check/backup/result state.
- `backend/apps/backup/` — deployment backup + restore (Phase 5A). Archive builder, `restore_diff`, the
  global quarantine `middleware.py` + `route_policy.py`, `recovery.py`, `object_restore.py`,
  `operation_lock.py`, and the privileged host scripts (`scripts/restore.sh`, `scripts/import-backup.sh`)
  that mirror `apps/updates`. Project JWT classes (`accounts/tokens.py`, `token_guard.py`) stamp
  `auth_generation`.
- `backend/apps/data_export/` — Space-Manager data export (Phase 4). Per-fidelity (`REDACTED`/`PORTABLE`)
  disposition registry over models, fields, datasets, traversals and the global-user reference closure, with
  **drift guards that refuse an unclassified model or field**. Its `guards._equal(subject, declared,
  actual)` is called with the *scanned* set passed as `declared`, so `extra=` in a failure means **scanned
  but not registered** — read the signature before deciding which side to fix.
- `backend/apps/tenant_migration/` — per-makerspace migration, managed → self-host (Phase 5B), in
  `SEPARABLE_APPS`. `source_gate.py` + `gate_locks.py`/`gate_runtime.py`/`gate_policy.py`/`middleware.py`/
  `task_gate.py` (the write-drain lock protocol and its AST coverage guards in `source_gate_guards.py`);
  `archive_envelope.py` + `object_export.py` (streamed into `age`); `admission.py` (the source-superadmin
  closure approval); `materialization.py` + `raw_repository.py` + `row_planning.py`/`row_dispositions.py`
  (one-shot insertion); `target_projection.py` + `unique_values.py` + `closure_references.py`;
  `verification.py` (pre-commit), audit-reference domains behind the `audit_references.py` barrel, and
  `target_cutover.py` (pre-activation + `IMPORTING → ACTIVE`);
  `receipts.py`/`receipt_crypto.py`/`cutover.py` (signed single-use handoff); `views_*.py` (superadmin REST).
- `backend/apps/inventory/` — `InventoryProduct`/`InventoryAsset`, `availability.py` (**the only place**
  available/reserved/issued/damaged/lost counts change: `reserve_for_request`, `issue_items`/`return_items`,
  `issue_available`/`return_to_available`, `consume_available`; row-locked, never-below-zero,
  `InsufficientStock`), `public_availability.py`, allowlist-only public serializers/views,
  `public_image_storage.py`, `seed_demo`.
- `backend/apps/hardware_requests/` — Hardware Request Workflow: `HardwareRequest`/`HardwareRequestItem`,
  `HardwareRequestItemAsset` through-model, immutable `ReturnEvent`/`RequesterAccountability`,
  `PublicToolLoan`, `PublicProblemReport`. `workflow.py` is the **single source of truth** for state
  transitions (atomic + row-locked + audited; also `assign_box`/`issue_request`/`return_items`);
  `permissions.py`, `exceptions.py` (workflow→HTTP map + `ErrorSerializer._EXCEPTION_MAP`),
  `notifications.py` (Telegram seam), public submit/verify/status views, `send_return_reminders` command.
- `backend/apps/payments/` — immutable multi-subject Payment authority, per-space raw credentials + managed
  Stripe Connect resolution, checkout/webhook settlement, reconciliation, native PaymentSheet intents.
- `backend/apps/printing/` — **TOMBSTONED** (Project B): only an `AppConfig` and an empty `models.py`, kept
  in `INSTALLED_APPS` so its historical migrations remain installed. 3D printing is now a `MachineType`
  inside `apps/machines/` — look there, not here.
- `backend/apps/roadmap/` — **TOMBSTONED**: `RoadmapItem` retained for migration history only. No URLs,
  serializers, admin surface or frontend; `tests/roadmap/test_removed_surfaces.py` asserts they stay removed.
- `backend/apps/warranty/`, `apps/machines/`, `apps/maintenance/`, `apps/events/`, `apps/bookings/`,
  `apps/forms_schema/`, `apps/encryption/`, `apps/procurement/`, `apps/notifications/`,
  `apps/operations/report_registry.py` — the FabLab + governance modules.
- `backend/tests/` — pytest behavior tests (external behavior, not implementation).
- `frontend/src/features/inventory/` — public catalog/detail/self-checkout + `ProductCard`/
  `AvailabilityBadge`. `frontend/src/features/staff/` — staff console panels; grouped nav via
  `staffAccess.ts` `TAB_GROUPS`, which does sidebar grouping AND permission derivation (**not**
  `StaffApp.tsx`; module gating and routing are the separate `staffTabs.ts`); capabilities from
  action-based `staffAccess.ts`; payment reconciliation and platform credential panels.
  `frontend/src/features/auth/` + `members/MemberAuthPanel.tsx` — provider-config-driven social/member auth.
  `frontend/src/features/printing|bookings|forms|...` — feature slices. `frontend/src/lib/`,
  `components/ui/`, `types/`, `generated/api.ts`.
