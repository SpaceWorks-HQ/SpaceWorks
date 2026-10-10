# Stage 1 - phase 7d review against lane/7a

Reviewed phase-7d-offline-and-ui.md, phase-7-hardware-integration.md, reviews/stage1-p7.md and HANDOVER-CODEX.md section 7 against this worktree.

## Corrected stale facts and defects

- Depends on accepted 7a-7c, but this lane contains only 7a. Printer bindings/jobs/commands, telemetry precedence helper and label routes/models do not exist. Their UI cannot safely call guessed sibling APIs. Defer adapter components and QR child until the coordinator integrates 7b/7c.
- Device threshold is `offline_threshold_seconds`, not `offline_after_seconds`.
- No activation timestamp exists. For never-seen devices use the latest retained `enrolled` event (also reactivation), not `created_at` or deletable enrollment artifacts. Pending devices are excluded. No Device field migration needed.
- Existing heartbeat clears only `offline_since`; it neither audits recovery nor clears `offline_notified_at`. Replace with one locked activity hook, callable by future printer services.
- DeviceEvent choices do not reserve offline/recovery events. A choice alteration migration is needed in devices despite the plan's no-migration claim. Actual leaf is 0001_device_identity.
- Actual integrations leaf is 0025_webhook_channel. Choice changes affect EmailTemplate.stream plus NotificationPreference, NotificationDeliveryLog, NotificationRecipient and ChatTemplate.feature; EmailLog.stream has no choices.
- Device notifications also require admin email-template stream authority/module maps and the frontend recipient label, omitted from the file table. Chat feature-to-stream already falls back to the identical `devices` name; no fablab registry growth needed.
- Staff email fallback lacks the membership active filter already used by push. Device alerts must filter inactive memberships; protect this in tests.
- Existing recipient lookup deliberately fails open to action fallback, while channel preference lookup fails closed. Preserve those contracts, with a separate fail-closed servability/module check in the device adapter.
- Gate policy now includes 7a anonymous enrollment declarations and is over the preferred size. Split HTTP/task/object catalogs behind explicit barrel imports, retaining every exported dictionary and guard path. Mechanical commits prohibited by lane instruction; all work remains unstaged.
- StaffTabContent lazy loaders/platform branches need extracting before adding the new panel. Actual QR parent is panels/QrTools.tsx.
- Staff 7a APIs require MANAGE_DEVICES exclusively. Until sibling bindings/selectors exist, Devices tab must require that action; showing a tab to manage_machines/manage_qr alone would violate backend/UI parity.
- Enrollment grants return token, purpose and expiry only; challenge is obtained by the device in proof-of-possession enrollment, not returned to staff. UI displays only the actual grant in ephemeral state.
- TanStack mutation results retain returned data in mutation cache. Enrollment-bearing requests must return void to TanStack, keeping only local modal state; gcTime alone is insufficient.
- Cleanup must bound both nonce and terminal enrollment deletes and emit typed per-tenant counts. Never purge DeviceEvent or audit history.
- Offline notification callbacks must capture edge-time snapshots, not re-query a device after recovery and relabel the old event. Re-check module/servability at delivery.
- Existing reports already contain plural devices vs singular device -> mobile and health-row coverage. Only offline failure classification needs changing.
- Shared registries are already split: module_registry_catalog.py, classification_domain/platform.py, references_core.py and unique_values_core.py. No new model/module/action/capability/env setting introduced here, so existing export/projection/user-reference/authority catalogs remain valid; field-name snapshot and digest stay unchanged. New state-edge typed audit references are unioned through audit_references_meta_devices_7d.py.
- Task cadence of one minute requires external beatless cron at one minute for one-minute detection, unlike command docstring's 15-minute example.
- Plan requests generated OpenAPI/client files and commits, but lane instructions prohibit both. Coordinator must regenerate and commit.
- Review destination in main checkout contradicts edit-only-worktree instruction and sandbox. Saved this review at docs/stage1-p7d.md for coordinator to copy to the requested stage1-p7d.md.
- Django/dependencies and frontend node_modules are absent here; database tests cannot be run. codex doctor runs but reports configuration/home resolution failure and provider endpoints unreachable; an independent CLI review cannot run. Coordinator runs full gated verification.

## Section 7 defect-class checklist

User-only audit actors preserved; no new models/module/capability/action/settings; no changes to restore/import authority; string UUID audit metadata preserved; trigger tests use savepoints; historical module defaults respected; no API-client registry changes; existing pk routes/origin scopes retained; row locks avoid nullable select_related. Notifications carry only device identity/state/timestamps, never keys/tokens/nonces. Existing opt-in module/deployment tombstone and source gates retained.

Proceed with the independently implementable 7d behavior; adapter UI integration remains a dependency gap, not an owner product decision.

Choice migrations were written explicitly because Django is unavailable; the coordinator must run makemigrations --check and regenerate if needed. No historical migrations were edited.

Additional review findings during implementation:
- Existing nonce pruning can delete a nonce during the last accepted integer timestamp second when TTL equals twice skew. Scheduled cleanup retains a one-second grace beyond stored expiry; removed unbounded request-time pruning. Existing 7a skew/auth contract is unchanged.
- Reactivation must clear prior last-seen/offline markers or a freshly re-enrolled device immediately appears offline from its revoked incarnation. Completion now resets the observation window for non-rotation enrollments.
- Existing membership Role enum has no MEMBER; test recipients use the protected member role/custom membership vocabulary.

- Existing email-template schemas omitted error responses. Updated affected staff stream endpoints to document boundary, authentication, scope and source-gate errors, including device module-off 400.
