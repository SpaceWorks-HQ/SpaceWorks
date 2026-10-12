# Kiosk offline continuity — phase 9d

The Station channel remains session-bound bearer authority, never a device identity.
An offline shell cannot unlock or look up people, requests or QR codes. Only a human
lease and selected work package obtained online can be restored on that browser.
Every physical effect still passes 9c's current server authorization and workflows.

## Storage and lifecycle

`spaceworks-kiosk-v1`, version 1, has `keys`, `records`, `evidence` stores. The scope
is makerspace/station/session/lease/actor IDs; it grants no server authority. Only
keys, opaque IDs, expiry and byte-accounting metadata are plaintext. Whole queue
records (including work packages, envelopes and lease) and evidence bytes use
AES-GCM-256, non-extractable structured-cloned CryptoKeys and random 96-bit IVs.
AAD binds database/version/scope/kind/record UUID. Unsupported browser storage,
CryptoKey cloning or Web Locks means online-only operation, never plaintext fallback.

Web Locks serialize storage mutations across windows/workers; a separate per-scope
replay lock serializes physical replay and reset. Photo+command writes share one IDB
transaction. Queue caps are 50 unacknowledged pending/failed commands across scopes
and 100 MiB encrypted evidence. Capture rejection drops no existing work.
Canvas decoding applies orientation, scales to at most 1600 pixels on the longest
edge and re-encodes JPEG at quality 0.8, stripping source metadata. Empty/over-limit
output blocks capture. No photo URL or unencrypted source bytes are persisted.

Expiry is the earliest session, lease, selected package or advertised command-age
deadline. Startup, foreground polling and worker activation prune expired scopes.
Explicit Station reset/lock/sign-out and acknowledged success destroy the key and
ciphertext together. Pending/failed work requires explicit destructive reset.
Idle with pending work prompts for reset; it does not silently discard evidence.
An offline browser cannot observe remote revocation until reconnecting.

## Replay and presentation

The earliest unfinished command per aggregate runs prepare → direct staging upload
→ execute. Execute receives the identical envelope; server evidence/result IDs
remain outside it. UUIDs never change after uncertain delivery. Persisted intermediate
states restart at prepare; duplicate server success counts as success. Retryable
network/429/503/claim contention gets exponential jittered backoff. Domain failures
retain their typed code and block their aggregate while independent work proceeds.
Borrower presence/membership/waiver 403s do not revoke the human operator; authoritative
401/403/410 and lease/station/session/permission revocation destroy the affected scope.
Presigned-storage 403 retries preparation; it does not erase Station authority.

Foreground startup, online events, Retry and a 15-second timer are the reliable replay
path. `navigator.onLine` is a hint; cold unlock also waits for the existing no-store
health endpoint to confirm backend reachability. Background Sync is opportunistic and uses
the same encrypted store/state machine, cookie and decrypted-in-memory lease, never
an unencrypted serialized HTTP queue. API base configuration is inside encrypted
state, so a worker needs no window or cached config.js.

Offline UI says Queued, with sequence and pending/failed count, until server success.
Only loaded reviewed requests and existing direct-loan returns are accepted by the
queue adapter. The 9b UI selects reviewed requests; new direct-handout item selection
and issue-then-return item identity mapping remain deferred (9c review decision).

## App shell

Vite bundles `src/sw.ts` and injects SHA-256 revisions of final index/JS/CSS/fonts/images/
WASM. The repository build plugin implements injectManifest without a new dependency:
`vite-plugin-pwa` was unavailable locally and registry access was sandbox-blocked.
The build verifier proves actual lazy kiosk chunks and scanner WASM are in `sw.js`.
The public static worker is removed. Kiosk navigation is network-first with a cached
build index fallback; non-kiosk navigation retains network behavior. Only manifest
static URLs are cached. API, Authorization, runtime config, evidence and cross-origin
storage responses never enter Cache Storage. Network navigation responses are not stored.
Activation deletes older SpaceWorks caches only; unrelated caches survive. Updates
do not call skipWaiting and wait until old clients/worker events finish. nginx marks
sw.js/index.html no-cache and hashed assets immutable.

Unit tests use real WebCrypto plus a bounded transaction/structuredClone IDB test
double. `node scripts/verify-pwa-browser.mjs` verifies real Chromium IDB key cloning,
encrypted capture, JPEG metadata stripping, the generated offline shell and simulated
replay. Real-stack workflows/revocation, Background Sync and update lifecycle QA remain
required at the coordinator/9e gate; the isolated smoke test does not replace them.
