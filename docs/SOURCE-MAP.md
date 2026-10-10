# SpaceWorks source map

> **This is the file-layout half of `CLAUDE.md` / `AGENTS.md`.** It was split out when that file crossed
> the harness's memory-file size limit; nothing was dropped in the move. It has no `AGENTS.md`-style twin —
> both names of that document point at this one path, so edit it in place.
>
> Paths drift. If this disagrees with the tree, the tree wins — fix this file in the same commit.

## Current source map (real paths)

Cloud surfaces: `accounts/views_social.py` explicitly exports the nonce/login views in
`views_social_login.py` and identity management in `views_social_identities.py`, with shared
verification/error helpers in `views_social_helpers.py`. `integrations/health.py` explicitly exports
`health_status.py` rollups and `health_chat.py` destination/legacy delivery summaries. The
read-only scheduler control page lives in `operations/admin_scheduling.py`.
The shared reminder foundation is `operations/models_reminders.py`,
`reminder_registry.py`, `reminder_services.py`, `reminder_sweeper.py` and
`tasks_reminders.py`; consumer registrations are explicit and initially empty.
Queries use `accounts/rbac.py:scope_for_scheduled_work`; see
[reminder-schedules.md](reminder-schedules.md) for UTC, claims and migration rules.

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
  the closed theme JSON for control forms and API writes.
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
- `backend/apps/updates/` — singleton platform update state, audited superadmin controls, and the
  `update_control` management command used by the privileged host scheduler. The web process never gets
  Docker-socket access; host scripts claim queued/automatic releases and report check/backup/result state.
- `backend/apps/backup/` — deployment backup + restore (Phase 5A/Lane E). `outer_manifest.py` owns the
  signed readable manifest, `artifact_ledger.py` + `models_artifact_ledger.py` own durable component and
  recipient custody, `activation.py` owns the access-switch/activation transition, and
  `artifact_protocol.py`/`promotion.py`/`reconciliation.py` own staged upload and the single availability
  transaction. `services.py` is the stable barrel over archive/access/lease/run lifecycle modules;
  `models_runs.py` + `runs.py` own scheduled-run cohort and coverage proofs, while `services_runs.py`
  orchestrates their serialized builds. Offsite destinations: `models_offsite.py` (destination +
  upload journal), `offsite_client.py` (S3 byte primitives), `offsite_enqueue.py` (eligibility + journal rows), `offsite_push.py` (fan-out + read-back
  verification), `offsite_retention.py`, `offsite_reverify.py` (periodic re-read), `offsite_restore.py` (create-only rehydration),
  `tasks_offsite.py`, `views_offsite.py`, `services_offsite.py` (shared API/admin retirement and probes)
  and the `fetch_offsite_archive` command. `views_recipients.py` explicitly re-exports enrollment and
  lifecycle views; `views_recipients_common.py` owns their scoped lookups and error contracts. `module_gate.py` owns
  the `backup` module key; `views_custody.py` is its read-only custody status.
  `archive_metadata.py` owns stable build/settings manifest facts;
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

## Domain and frontend map

See [SOURCE-MAP-DOMAINS.md](SOURCE-MAP-DOMAINS.md) for hardware loans, payments,
printing, events, the frontend directories and connected device monitoring.
See also [SOURCE-MAP-frontend.md](SOURCE-MAP-frontend.md) for the standalone
frontend directory and browser/kiosk flow map.
