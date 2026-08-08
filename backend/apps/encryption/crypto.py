"""Versioned AES-256-GCM envelopes for scoped PII values."""

import base64
import binascii
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from apps.encryption.brokers.base import require_dek

_PREFIX = "pii:gcm:v1:"
_NONCE_BYTES = 12
_TAG_BYTES = 16


class PiiError(Exception):
    """Base exception whose text is safe to return outside the trust boundary."""


class PiiUnavailable(PiiError):
    def __init__(self, message="Protected data is temporarily unavailable."):
        super().__init__(message)


class PiiMalformedEnvelope(PiiUnavailable):
    def __init__(self):
        super().__init__("Protected data is unavailable.")


class PiiAuthenticationFailed(PiiUnavailable):
    def __init__(self):
        super().__init__("Protected data is unavailable.")


class PiiKeyUnavailable(PiiUnavailable):
    def __init__(self):
        super().__init__("Protected data is unavailable.")


class UnmappedPiiModel(PiiUnavailable):
    """A ScopedPiiModelMixin subclass reached save() with no registered fields.

    This is the fail-closed backstop for the gap that otherwise fails OPEN: an
    unregistered mapped model takes the plain-save branch, skipping encryption, the
    blind index and the write fence, and stores plaintext with nothing raised. The
    separability system check refuses startup in this state, so reaching here means
    checks were bypassed (``--skip-checks``, or a registry mutated at runtime) —
    refuse the write rather than silently store PII in the clear.
    """


class LegacyPlaintextRejected(PiiUnavailable):
    def __init__(self):
        super().__init__("Protected data is unavailable.")


def is_envelope(raw) -> bool:
    if isinstance(raw, bytes):
        return raw.startswith(_PREFIX.encode("ascii"))
    return isinstance(raw, str) and raw.startswith(_PREFIX)


def aad(makerspace_id, table, pk, field) -> bytes:
    return f"makerspace:{makerspace_id}:{table}:{pk}:{field}".encode("utf-8")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    if not value or not isinstance(value, str):
        raise PiiMalformedEnvelope()
    if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in value):
        raise PiiMalformedEnvelope()
    try:
        raw = value.encode("ascii")
        return base64.b64decode(raw + b"=" * (-len(raw) % 4), altchars=b"-_", validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise PiiMalformedEnvelope() from exc


def parse_envelope(raw):
    if not isinstance(raw, str) or not raw.startswith(_PREFIX):
        raise PiiMalformedEnvelope()
    parts = raw.split(":")
    if len(parts) != 6 or parts[:3] != ["pii", "gcm", "v1"]:
        raise PiiMalformedEnvelope()
    try:
        version = int(parts[3])
    except (TypeError, ValueError) as exc:
        raise PiiMalformedEnvelope() from exc
    if version < 1:
        raise PiiMalformedEnvelope()
    nonce, ciphertext = _decode(parts[4]), _decode(parts[5])
    if len(nonce) != _NONCE_BYTES or len(ciphertext) < _TAG_BYTES:
        raise PiiMalformedEnvelope()
    return version, nonce, ciphertext


def encrypt(plaintext, dek, *, key_version, makerspace_id, table, pk, field):
    """Encrypt bytes and return an ASCII envelope; genuine empties remain empty."""
    if plaintext == b"" or plaintext == "":
        return plaintext
    if not isinstance(plaintext, bytes) or key_version < 1:
        raise PiiUnavailable()
    try:
        nonce = secrets.token_bytes(_NONCE_BYTES)
        ciphertext = AESGCM(require_dek(dek)).encrypt(
            nonce, plaintext, aad(makerspace_id, table, pk, field)
        )
    except PiiError:
        raise
    except Exception as exc:
        raise PiiUnavailable() from exc
    return f"{_PREFIX}{key_version}:{_encode(nonce)}:{_encode(ciphertext)}"


def decrypt(envelope, dek, *, makerspace_id, table, pk, field):
    """Authenticate and decrypt an envelope using the supplied version's DEK."""
    if envelope == b"" or envelope == "":
        return envelope
    _, nonce, ciphertext = parse_envelope(envelope)
    try:
        return AESGCM(require_dek(dek)).decrypt(
            nonce, ciphertext, aad(makerspace_id, table, pk, field)
        )
    except InvalidTag as exc:
        raise PiiAuthenticationFailed() from exc
    except PiiError:
        raise
    except Exception as exc:
        raise PiiUnavailable() from exc


def decrypt_with_key_loader(envelope, *, makerspace_id, table, pk, field, load_dek):
    """Decrypt an envelope after loading precisely the version it declares."""
    if envelope == b"" or envelope == "":
        return envelope
    version, _, _ = parse_envelope(envelope)
    try:
        dek = load_dek(version)
    except PiiUnavailable:
        raise
    except Exception as exc:
        raise PiiKeyUnavailable() from exc
    return decrypt(
        envelope, dek, makerspace_id=makerspace_id, table=table, pk=pk, field=field
    )
