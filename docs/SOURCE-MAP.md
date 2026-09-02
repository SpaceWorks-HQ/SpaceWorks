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
  grants/rotating refresh families, Google/Apple social identities + nonce/JWKS verification, and the
  Auth & RBAC module: thin `rbac.py` import surface/coordinator over `rbac_actions.py`,
  `rbac_memberships.py`, `rbac_organizations.py`, and `rbac_superadmin.py` (`can(...)`, action-based
  `actions_for_membership`/`makerspaces_for_action`/`scope_by_action`, makerspace scoping, superadmin
  hide/archive exclusion).
- `backend/apps/makerspaces/` — `Makerspace` model (tenant root; unique `slug`; `frontend_domain`, module
  flags, `resource_limit_overrides`, `archived_at`, `superadmin_access_enabled`), bootstrap views, dynamic
  CORS, module guards, `module_registry.py` (canonical module definitions — all module lists derive from
  it), `platform.py` (origin helpers), `limits.py` (fair-use quotas), `lifecycle.py` (archive/purge barrel
  over `lifecycle_archive.py`, `lifecycle_purge.py` and `lifecycle_storage.py`),
  `origin_scope.py` (browser origin→tenant guard), `provisioning.py`/`hosting.py`, `secrets.py`.
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
  object-store/HTTP collector protocols behind the `anchors.py` barrel.
- `backend/apps/evidence/` — immutable evidence photos, S3 storage helpers, signed upload/view URLs gated by
  per-makerspace `UPLOAD_EVIDENCE` + active status.
  `retention_models.py` owns the optional per-makerspace `EvidenceRetentionPolicy` override and per-photo
  `EvidenceObjectRetentionState`, re-exported by
  `models.py`; both use normal primary keys plus unique one-to-ones so they can travel through tenant
  migration. `retention_policy.py` is the single source of truth for the effective window and candidate/
  preview query. `services_retention.py` owns the bounded idempotent sweep: it observes deployment recovery
  and each tenant source gate, removes both final and staging bytes, credits confirmed storage and audits a
  terminal expired state without mutating the `EvidencePhoto` row. `sweep_evidence_retention()` is the
  single sweep entry point, `tasks.py` is its Celery/scheduled-task adapter, and `views_retention.py` exposes
  the policy and preview API.
- `backend/apps/boxes/` — `QrCode`/`Box` payloads, immutable `BoxScan`/`QrScanEvent`, `qr_render.py`
  (namespaced standalone SVG shared by QR-print + batch ZIP), QR rebind. Camera scanner at
  `frontend/src/components/ui/QrScanner.tsx` (native `BarcodeDetector` + `zxing-wasm` fallback).
- `backend/apps/admin_api/` — staff REST surface: makerspaces, inventory CRUD + per-makerspace category CRUD
  (`EDIT_INVENTORY`), bulk import, staff/membership + role management, user restrict/restore, API-client
  issuance (`api_client_views.py`) and access requests (`api_key_request_views.py`), audit reads, warranty,
  email-log, notification-recipient, FabLab report views.
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
- `backend/apps/backup/` — deployment backup + restore (Phase 5A/Lane E). `outer_manifest.py` owns the
  signed readable manifest, `artifact_ledger.py` + `models_artifact_ledger.py` own durable component and
  recipient custody, `activation.py` owns the access-switch/activation transition, and
  `artifact_protocol.py`/`promotion.py`/`reconciliation.py` own staged upload and the single availability
  transaction. `services.py` is the stable barrel over archive/access/lease/run lifecycle modules;
  `models_runs.py` + `runs.py` own scheduled-run cohort and coverage proofs, while `services_runs.py`
  orchestrates their serialized builds. `archive_metadata.py` owns stable build/settings manifest facts;
  `backup_control_preflight.py` remains the E9b restore validator behind the `restore_preflight.py`
  compatibility surface. Archive builder, `restore_diff`, the global quarantine
  `middleware.py` + `route_policy.py`, `recovery.py`, `object_restore.py`,
  `operation_lock.py`, and the privileged host scripts (`scripts/restore.sh`, `scripts/import-backup.sh`)
  that mirror `apps/updates`. Project JWT classes (`accounts/tokens.py`, `token_guard.py`) stamp
  `auth_generation`. `custody.py` is the makerspace-first/recipient-PK serialization boundary;
  `tenant_exit_custody.py` derives Lane D's independent tenant-only floor, while
  `tenant_exit_custody_alarms.py` reuses the decision-19b recipient selectors and parameterized durable
  dispatcher for its retryable outbox. The `host_*` modules own H1's marker, consume-only capability socket,
  signed grant, run ledger, supervisor and atomic pointer; `database_grants.py` is its independent
  PostgreSQL role boundary. `cloud_environment.py` captures host-rendered Cloud Compose interpolation into
  durable static configuration without consulting later ambient shells; only the root-only
  `scripts/init-cloud-environment.py` renderer invokes Compose.
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
  `tenant_dump_model_catalog.py` + `tenant_dump_field_snapshot.py` +
  `tenant_dump_authority.py`/`tenant_dump_catalog.py` (Lane D's deny-by-default source catalog), and
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
- `backend/apps/machines/` — machine registry and service workflows. Machine-role authorization keeps a
  thin `role_scope.py` import surface over `role_scope_resolution.py` (including the identity-sensitive
  `EXEMPT`/`NOTHING` sentinels), `role_scope_grants.py`, and `role_scope_queries.py`; scope mutations remain
  in `role_scope_services.py`.
- `backend/apps/events/` — the separable events module. `models.py` is the stable explicit re-export barrel
  over `models_event.py`, `models_registration.py`, `models_attendance.py`, `models_feedback.py`,
  `models_certificates.py`, `models_series.py`, `models_calendar.py`, `models_collaborators.py` and
  `organizer_models.py`; those focused files are the schema sources for events/occurrences, approval and
  waitlist registrations, immutable check-in history and PIN credentials, feedback, certificate artifacts,
  recurring series, member feed credentials, makerspace collaboration and organization attribution.
  `services.py` remains the audited transactional boundary for one-off event and registration mutations,
  delegating lifecycle and registration-state transitions to `services_lifecycle.py`,
  `services_registration.py` and `services_registration_state.py`. The other `services_*` modules own the
  corresponding series/recurrence/collaboration, calendar/feed, badge, check-in/offline-sync/station,
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
  `frontend/src/features/auth/` + `members/MemberAuthPanel.tsx` — provider-config-driven social/member auth.
  `frontend/src/features/printing|bookings|forms|...` — feature slices. `frontend/src/lib/`,
  `components/ui/`, `types/`, `generated/api.ts`.
- `frontend/src/features/events/` — the standalone anonymous PIN-station route. Its
  `EventCheckInStationPage.tsx` exchanges the event-scoped PIN, then reuses the offline roster/sync API,
  IndexedDB state and operator UI owned by `features/staff/eventCheckInOfflineApi.ts`,
  `eventCheckInOfflineStore.ts` and `OfflineCheckInOperator.tsx`.
- `frontend/src/features/organizations/` — public organization presentation and invitation redemption:
  `PublicOrganizationPage.tsx` renders the public profile and paginated cross-makerspace event catalogue,
  `OrganizationInvitationRedeemPage.tsx` binds a single-use invitation after member sign-in, and
  `publicOrganizationsApi.ts` owns their TanStack Query keys and public API calls. Staff profile,
  membership, invitation and event-organizer controls remain under `frontend/src/features/staff/`.
