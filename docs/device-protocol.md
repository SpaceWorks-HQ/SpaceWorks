# Device protocol v1 — enrollment and signed requests

Enrolled devices (printers, label printers; module `devices`) authenticate with an **Ed25519** key
they generated themselves. A device is never a user account. The reference implementation and the
vectors below live in `backend/apps/devices/protocol.py`; `backend/tests/devices/test_protocol.py`
pins them.

## Encodings

- **Public key** — canonical padded standard base64 of the raw 32-byte key.
- **Signature** — canonical padded standard base64 of the raw 64-byte signature.
- **Nonce / challenge** — canonical *unpadded* base64url. A nonce carries 16–64 random bytes; the
  server challenge is 32 bytes. Non-canonical encodings (padding, stray bits) are refused.
- **Framing** — every signed message is a sequence of fields, each a 4-byte big-endian length followed
  by the field's bytes (UTF-8 for text). Framing makes field boundaries unambiguous.

## Enrollment (proof of possession)

1. A staff member with `manage_devices` calls `POST /api/v1/admin/makerspace/{makerspace_id}/devices`
   (`{kind, name, offline_threshold_seconds?}`) or, for an existing device,
   `POST /api/v1/admin/devices/{pk}/enrollments`. The response carries `enrollment_id`, `device_id`,
   `purpose` (`enroll` for a pending device, `rotate` for an active one, `reactivate` for a revoked
   one), the one-time `token` and `expires_at` (`DEVICE_ENROLLMENT_TTL_SECONDS`, default 900). The token
   is shown once and stored only as a SHA-256 digest; issuing a new enrollment revokes any unconsumed one.
2. The device calls `POST /api/v1/device/enrollments/{enrollment_id}/challenge` with
   `{token, public_key}` and receives `{challenge, expires_at}`.
3. The device signs the enrollment message and calls
   `POST /api/v1/device/enrollments/{enrollment_id}/complete` with
   `{token, public_key, challenge, signature}`.

Enrollment message fields, in order: `spaceworks-device-enrollment`, `v1`, enrollment UUID, makerspace
id (decimal), device UUID, purpose, candidate-key fingerprint (lowercase SHA-256 hex of the raw key),
raw challenge bytes.

Completion activates the device (or swaps its key during rotation), increments `key_version` and
consumes the enrollment, atomically. Until then the old key stays authoritative. Errors: `400`
malformed input or module disabled · `403` wrong token / unknown enrollment / failed proof (deliberately
indistinguishable) · `409` key already bound to another device, or rotation reused the current key ·
`410` enrollment used, revoked or expired · `423` the tenant is frozen for migration.

## Signed requests

Headers: `X-Device-Id` (canonical lowercase UUID), `X-Device-Key-Version` (current positive integer),
`X-Device-Signature-Version: v1`, `X-Device-Timestamp` (Unix seconds),
`X-Device-Nonce`, `X-Device-Signature`.

Request message fields, in order: `spaceworks-device-request`, `v1`, uppercase HTTP method, the **exact
raw request target including the query string** (as sent on the request line — never re-ordered or
re-encoded), decimal timestamp, nonce, lowercase SHA-256 hex of the exact body bytes.

The server rejects a timestamp outside `DEVICE_SIGNATURE_MAX_SKEW_SECONDS` (default 300) and claims each
nonce exactly once per device key (`DEVICE_NONCE_TTL_SECONDS`, default 86400, must be at least twice the
skew). It reads the raw target from the server (`RAW_URI`/`REQUEST_URI`, or ASGI `raw_path`); a deployment
whose server exposes neither fails closed. Failures are `401` with
`WWW-Authenticate: SpaceWorks-Device-v1`; a revoked or rotated key, a stale `key_version`, a replay and a
tampered body all fail the same way.

7a defines one signed route: `POST /api/v1/device/heartbeat` (empty body) → `{device_id, makerspace_id,
status, key_version, last_seen_at}`.

## Rotation, revocation, restore

- **Rotate** — staff issue a new enrollment for an active device; the device completes it with a NEW key.
  Old-key signatures stop working the moment `key_version` advances.
- **Revoke** — `POST /api/v1/admin/devices/{pk}/revoke` blocks the device immediately. Only a staff-issued
  `reactivate` enrollment plus fresh proof brings it back.
- **Tenant move / full restore** — no device key, enrollment or nonce survives. Devices arrive pending and
  must enroll again; `key_version` is kept and bumped so no old signature can ever match.

## Version compatibility

`X-Device-Signature-Version` is mandatory; anything other than `v1` is refused. A future `v2` will get a
new domain string, so a v1 signature can never validate as v2.

## Test vectors

Private key = the 32-byte seed `000102…1f`; public key `A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=`,
fingerprint `56475aa75463474c0285df5dbf2bcab73da651358839e9b77481b2eab107708c`.

| | Inputs | Message SHA-256 | Signature |
|---|---|---|---|
| Request | `POST`, `/api/v1/device/heartbeat?b=2&a=1`, ts `1760000000`, nonce `AAECAwQFBgcICQoLDA0ODw`, body `{"status":"ok"}` | `e891fd5275c6f9ac8532c09b48c593e38a1ce1121d6f945643ec48c536b428fe` | `B70XDhmKjehFpaz9rxF6LooqOUD1IT2oXVCwQ2x63GWj2r5dscuK85hejYBVlr+kZXb7fPC1Kwffshkjq/26Bg==` |
| Enrollment | enrollment `00000000-0000-4000-8000-000000000001`, makerspace `7`, device `00000000-0000-4000-8000-000000000002`, `enroll`, challenge bytes `20…3f` (`ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8`) | `cdd60412027c85f820114e9fdd22bde4d86e56ea768298fbc664756228ff7244` | `vhJhxnQUqxdl/J2Nr+36t26m0r3iZ1ieUv7cuRqnoALo432jjM0lgjTu9S0m3d5DD95kV3w7ylqmh35d4n3YAg==` |
