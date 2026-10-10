# Lane 9d ? encrypted offline client and generated app shell

Branch lane/9d, based on lane/9c. All changes are unstaged. No commit, checkout,
merge, index mutation or backend database test was performed.

## Completed

- Step 0: audited the actual 9c replay model/services, 9b shell, migration leaves,
  parent/review plans and HANDOVER-CODEX section 7. Review: docs/stage1-p9d.md,
  the authorized worktree fallback for the main checkout's unwritable review path.
- Extracted shared IDB/key/AES-GCM mechanics. Legacy event database/version/stores,
  scopes and no-AAD blob wire format remain readable; event adapter owns semantics.
- Added encrypted kiosk queue/work/evidence with version/scope/kind/UUID AAD,
  non-extractable keys, random IVs, global 50-command/100 MiB evidence caps,
  atomic capture writes, cross-window/worker Web Locks, expiry and key/data wipe.
- Added pixel-only oriented JPEG normalization, maximum 1600px edge, bounded size,
  metadata stripping and memory release. No plaintext persisted photo/lease/remark.
- Added stable-ID prepare/upload/execute replay, persisted intermediate recovery,
  same-envelope execute, per-aggregate dependency blocking, jittered backoff,
  authority wipe and retained typed borrower/domain failures. Presigns are not stored.
- Integrated selected online work-package persistence, cached continuation, queued
  states, explicit reset/acknowledgement and cold-shell refusal. Idle prompts before
  discarding pending work. Existing no-store health confirms unlock reachability;
  onLine is only a hint. API base stays inside encrypted state for worker replay.
- Added session_id/actor_id to the existing human-lease response/schema, plus 400
  documentation. Existing lease service still writes the User-attributed audit.
- Vite bundles src/sw.ts and injects final SHA-256 index/chunk/WASM revisions;
  install verifies actual bytes, activation only removes old SpaceWorks caches,
  updates wait for old clients/events, and kiosk navigations use the public shell.
  API/auth/config/evidence/presigned responses never enter Cache Storage. Added
  opportunistic encrypted Background Sync, build verifier and nginx cache headers.
- Removed public/sw.js. Added KIOSK-OFFLINE.md and updated SOURCE-MAP ownership.
- Added unit tests plus isolated production-worker Chromium smoke verification.

## Checks actually run

- npm ci: PowerShell npm.ps1 execution policy refused it; npm.cmd ci --cache
  .npm-cache then failed EACCES fetching registry.npmjs.org/zxing-wasm.
- Dependency install attempt also could not fetch vite-plugin-pwa/fake-indexeddb.
  Existing main-checkout node_modules were READ/copied into this lane, allowing
  validation without changing dependencies or package-lock.json.
- npx.cmd --no-install tsc -b: exit 0 (also checked by npm build).
- npm.cmd test -- --reporter=dot: 77 files, 315 tests passed, exit 0. An existing
  jsdom ?Not implemented: navigation to another Document? diagnostic was non-failing.
- npm.cmd run build: exit 0; ?PWA verified: 91 revisioned shell/assets, kiosk
  navigation fallback, scanner WASM.?
- node scripts/verify-pwa-browser.mjs: exit 0; cold offline shell refusal, REAL
  browser non-extractable IDB key and encrypted command/photo capture, actual
  1600x800 JPEG without inserted EXIF marker, ordered same-envelope replay, and
  static-only cache verified against a SIMULATED replay server. No backend domain
  effect is tested by this smoke check. Chromium is required to rerun it.
- Python AST parsing: changed serializers/view and added backend test parsed.
  This is syntax validation, NOT a passing Django/database test.
- git diff --check: no whitespace errors. Every touched/new extant file <300 lines.
  Index remains empty; AGENTS.md/CLAUDE.md remain byte-identical and unedited.

## Coordinator work remaining

- Copy docs/stage1-p9d.md to the main checkout's reviews/stage1-p9d.md if desired.
- Run scripts/dev.sh test tests/hardware_requests/test_kiosk_offline_scope.py,
  existing kiosk/station/replay/evidence suites, Django checks and schema generation.
- Regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts for
  the additive lease DTO/schema fields. They are intentionally untouched here.
- Perform external Stage-4 review and real-stack owner QA/9e outage/revocation/
  Background Sync/update checks. codex doctor failed config/home resolution and
  provider reachability in this sandbox; no external gate is claimed passed.
- Stage/commit remains the coordinator's job; no merge or push was attempted.

## Migrations, skips and owner decisions

- No migration/model/module/feature/settings change. Actual leaves inspected:
  hardware_requests/0025_kiosk_replay, makerspaces/0074_station_operator_leases.
- Dependency deviation: vite-plugin-pwa was unavailable locally and registry access
  denied. A small repository Vite injectManifest plugin generates/verifies the
  worker without new dependencies. npm lock file is unchanged.
- INVARIANTS.md already exceeds the task's any-touched-file 300-line ceiling.
  New rules live in docs/KIOSK-OFFLINE.md, linked by SOURCE-MAP; no unrelated
  3,000-line doc split or AGENTS/CLAUDE edit was attempted.
- New prospective direct-handout selection/issue-then-return item mapping is not
  advertised: 9b supplies reviewed-request selection only, and 9c requires existing
  server item IDs. Queue adapter supports reviewed requests and loaded existing
  direct-loan returns. No empty resolution list is invented as return-all.
- No owner decision blocks the delivered reviewed-handover scope. Before expanding
  prospective direct item handouts, choose the client/product-to-item ID contract
  already identified by stage1-p9c. Failed replay resolution remains phase 9e.
- Temporary npm/browser artifacts are ignored. Automatic policy blocked recursive
  cleanup; no files outside this lane were edited.

## Defects noticed outside phase 9d

- 9b advertises a 900-second work-package command age while 9c defaults to eight
  hours. The client honors the narrower advertised limit; no server setting changed.
- Existing direct_loan_returns._return_scan_qr matches expected QR payloads without
  checking ACTIVE status. Preserved; coordinator should review that domain defect.

## File inventory

- .gitignore
- LANE-PROGRESS.md
- backend/apps/makerspaces/station_serializers.py
- backend/apps/makerspaces/station_views_public.py
- backend/tests/hardware_requests/test_kiosk_offline_scope.py
- docs/KIOSK-OFFLINE.md
- docs/SOURCE-MAP.md
- docs/stage1-p9d.md
- frontend/nginx.conf
- frontend/package.json
- frontend/public/sw.js
- frontend/scripts/kiosk-pwa.ts
- frontend/scripts/verify-pwa-browser.mjs
- frontend/scripts/verify-pwa-build.mjs
- frontend/src/App.kioskOffline.test.tsx
- frontend/src/App.tsx
- frontend/src/features/kiosk/KioskOfflineHandover.tsx
- frontend/src/features/kiosk/KioskOnlineHandover.tsx
- frontend/src/features/kiosk/KioskQueueStatus.tsx
- frontend/src/features/kiosk/KioskStationPage.offline.test.tsx
- frontend/src/features/kiosk/KioskStationPage.test.tsx
- frontend/src/features/kiosk/KioskStationPage.tsx
- frontend/src/features/kiosk/kioskApi.ts
- frontend/src/features/kiosk/kioskReplayApi.ts
- frontend/src/features/kiosk/kioskReplayClient.test.ts
- frontend/src/features/kiosk/kioskReplayClient.ts
- frontend/src/features/kiosk/kioskSession.ts
- frontend/src/features/kiosk/offlineEvidence.test.ts
- frontend/src/features/kiosk/offlineEvidence.ts
- frontend/src/features/kiosk/offlineQueueDb.ts
- frontend/src/features/kiosk/offlineQueueStore.test.ts
- frontend/src/features/kiosk/offlineQueueStore.ts
- frontend/src/features/kiosk/offlineQueueTypes.ts
- frontend/src/features/kiosk/offlineTestFixtures.ts
- frontend/src/features/kiosk/replayPolicy.ts
- frontend/src/features/kiosk/useKioskQueue.test.tsx
- frontend/src/features/kiosk/useKioskQueue.ts
- frontend/src/features/staff/eventCheckInOfflineStore.test.ts
- frontend/src/features/staff/eventCheckInOfflineStore.ts
- frontend/src/lib/encryptedIndexedDb.test.ts
- frontend/src/lib/encryptedIndexedDb.ts
- frontend/src/main.tsx
- frontend/src/sw.test.ts
- frontend/src/sw.ts
- frontend/src/swPolicy.ts
- frontend/src/test/memoryIndexedDb.ts
- frontend/tsconfig.node.json
- frontend/vite.config.ts

## Added test cases

frontend/src/App.kioskOffline.test.tsx
- opens a UUID Station shell while tenant bootstrap is unavailable
- preserves bootstrap gating for ordinary tenant routes

frontend/src/features/kiosk/KioskStationPage.offline.test.tsx
- cold offline shell refuses unlock, search and capture
- restores only the selected encrypted handover and presents pending work as Queued

frontend/src/features/kiosk/kioskReplayClient.test.ts
- recovers uncertain delivery with the SAME UUID/envelope; duplicate success skips execute
- blocks a failed aggregate's successor while independent handovers continue
- waits for claim contention without running its successor, then reuses stable server IDs
- resumes persisted preparing/uploading/executing states after a context closes
- wipes revoked authority but retains borrower presence/membership/waiver failures
- uploads decrypted evidence directly and keeps it out of the envelope and result
- supports PUT headers and treats storage 403 as a retryable expired presign

frontend/src/features/kiosk/offlineEvidence.test.ts
- bounds portrait/landscape dimensions and never upscales
- uses oriented decoded pixels, encodes fresh JPEG bytes and releases pixels
- blocks oversize/empty output and releases the decoded bitmap on failure

frontend/src/features/kiosk/offlineQueueStore.test.ts
- stores private work, envelopes, lease and image only as authenticated ciphertext
- atomically appends concurrent captures, retaining sequence and predecessor IDs
- enforces the 50-command cap without dropping an earlier capture
- blocks over-budget evidence before either command or photo commits
- expires at advertised command age, wipes keys/images, and cannot queue fresh work
- rejects ciphertext substitution across scopes and metadata tampering
- refuses missing scope metadata and unavailable Web Locks without plaintext fallback

frontend/src/features/kiosk/useKioskQueue.test.tsx
- does not treat onLine=true as proof that a cold Station can unlock
- keeps a cached handover in offline mode when the reachable backend is unhealthy

frontend/src/features/staff/eventCheckInOfflineStore.test.ts
- reads a pre-extraction version-one fixture encrypted without AAD
- preserves prefix wipe and expiry cleanup of keys and blobs
- refuses state whose encrypted expiry disagrees with plaintext pruning metadata

frontend/src/lib/encryptedIndexedDb.test.ts
- clones a non-extractable AES-256 key and uses fresh 96-bit IVs
- destroys scoped keys and ciphertext together, preserving other scopes

frontend/src/sw.test.ts
- supports kiosk-only navigations, never expands offline support to staff/member pages
- caches only exact revisioned static assets, excluding API/auth/evidence/presigns

backend/tests/hardware_requests/test_kiosk_offline_scope.py
- test_operator_lease_exposes_exact_human_and_session_scope_no_store (NOT RUN)

frontend/src/features/kiosk/KioskStationPage.test.tsx: existing online tests now isolate the new offline/reachability hook; no existing behavior assertion removed.
