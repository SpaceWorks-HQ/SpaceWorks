"""Device wire protocol v1: canonical encodings and the two signed messages.

Every signed message is a sequence of length-framed fields -- a 4-byte big-endian
length followed by the field bytes -- starting with a domain string and the version.
Framing makes field boundaries unambiguous, and the two domains
(``spaceworks-device-request`` / ``spaceworks-device-enrollment``) make a signature
for one message type useless as the other. ``docs/device-protocol.md`` publishes the
same vectors as ``VECTORS`` below; ``tests/devices/test_protocol.py`` pins both.
"""

import base64
import binascii
import hashlib
import re

VERSION = "v1"
REQUEST_DOMAIN = b"spaceworks-device-request"
ENROLLMENT_DOMAIN = b"spaceworks-device-enrollment"
MIN_NONCE_BYTES = 16
MAX_NONCE_BYTES = 64

_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_BASE64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


class ProtocolError(ValueError):
    pass


def frame(*fields):
    out = bytearray()
    for field in fields:
        value = field.encode("utf-8") if isinstance(field, str) else bytes(field)
        out += len(value).to_bytes(4, "big") + value
    return bytes(out)


def sha256_hex(value):
    return hashlib.sha256(value).hexdigest()


def b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(value, *, label, min_length=1, max_length=None):
    """Decode canonical unpadded base64url; re-encoding must give back the input."""
    if not isinstance(value, str) or not _BASE64URL.match(value):
        raise ProtocolError(f"The {label} encoding is invalid.")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError(f"The {label} encoding is invalid.") from exc
    if b64url_encode(raw) != value:
        raise ProtocolError(f"The {label} encoding is not canonical.")
    if len(raw) < min_length or (max_length is not None and len(raw) > max_length):
        raise ProtocolError(f"The {label} has an invalid length.")
    return raw


def b64_encode(raw):
    return base64.b64encode(raw).decode("ascii")


def b64_decode(value, *, label, length):
    """Decode canonical padded standard base64 of an exact byte length."""
    if not isinstance(value, str) or not _BASE64.match(value):
        raise ProtocolError(f"The {label} encoding is invalid.")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError(f"The {label} encoding is invalid.") from exc
    if base64.b64encode(raw).decode("ascii") != value or len(raw) != length:
        raise ProtocolError(f"The {label} is not canonical.")
    return raw


def canonical_nonce(value):
    b64url_decode(value, label="nonce", min_length=MIN_NONCE_BYTES, max_length=MAX_NONCE_BYTES)
    return value


def request_message(*, method, raw_target, timestamp, nonce, body):
    """The bytes a device signs for one HTTP request."""
    return frame(
        REQUEST_DOMAIN, VERSION, method.upper(), raw_target, str(int(timestamp)),
        nonce, sha256_hex(body),
    )


def enrollment_message(*, enrollment_id, makerspace_id, device_id, purpose, fingerprint, challenge):
    """The bytes a device signs to prove possession during enrollment/rotation."""
    return frame(
        ENROLLMENT_DOMAIN, VERSION, str(enrollment_id), str(int(makerspace_id)),
        str(device_id), purpose, fingerprint, challenge,
    )


# Published test vectors. The private key is the 32-byte seed 0x00..0x1f; Ed25519 is
# deterministic, so the signatures are exact.
VECTOR_PRIVATE_SEED_HEX = bytes(range(32)).hex()
VECTORS = {
    "public_key": "A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=",
    "fingerprint": "56475aa75463474c0285df5dbf2bcab73da651358839e9b77481b2eab107708c",
    "request": {
        "method": "POST",
        "raw_target": "/api/v1/device/heartbeat?b=2&a=1",
        "timestamp": 1760000000,
        "nonce": "AAECAwQFBgcICQoLDA0ODw",
        "body": b'{"status":"ok"}',
        "message_sha256": "e891fd5275c6f9ac8532c09b48c593e38a1ce1121d6f945643ec48c536b428fe",
        "signature": (
            "B70XDhmKjehFpaz9rxF6LooqOUD1IT2oXVCwQ2x63GWj2r5dscuK85hejYBVlr+kZXb7fPC1Kwffshkjq/26Bg=="
        ),
    },
    "enrollment": {
        "enrollment_id": "00000000-0000-4000-8000-000000000001",
        "makerspace_id": 7,
        "device_id": "00000000-0000-4000-8000-000000000002",
        "purpose": "enroll",
        "challenge": bytes(range(32, 64)),
        "challenge_b64url": "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8",
        "message_sha256": "cdd60412027c85f820114e9fdd22bde4d86e56ea768298fbc664756228ff7244",
        "signature": (
            "vhJhxnQUqxdl/J2Nr+36t26m0r3iZ1ieUv7cuRqnoALo432jjM0lgjTu9S0m3d5DD95kV3w7ylqmh35d4n3YAg=="
        ),
    },
}
