"""Explicit provisioning and read-only retrieval for audit row-MAC keys."""

import base64
import secrets
import struct
from dataclasses import dataclass
from time import monotonic

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction

from apps.audit.models import AuditMacKey


_GLOBAL_SCOPE_ID = 0
_WRAP_DOMAIN = b"spaceworks-audit-mac-key-v1\x00"
_CUTOVER_DOMAIN = b"spaceworks-audit-cutover-v1\x00"
_CACHE_TTL_SECONDS = 60


class AuditMacKeyUnavailable(RuntimeError):
    pass


class AuditCutoverTampered(RuntimeError):
    """The stored attestation cutover does not match its MAC."""


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    key: bytes


class AuditMacKeyCache:
    """Short, process-local cache; concurrent misses may safely unwrap twice."""

    def __init__(self):
        self._entries = {}

    def get(self, scope_id):
        entry = self._entries.get(scope_id)
        if entry is None:
            return None
        if monotonic() >= entry.expires_at:
            self._entries.pop(scope_id, None)
            return None
        return entry.key

    def set(self, scope_id, key):
        self._entries[scope_id] = _CacheEntry(monotonic() + _CACHE_TTL_SECONDS, key)

    def invalidate(self, scope_id):
        self._entries.pop(scope_id, None)

    def clear(self):
        self._entries.clear()


audit_mac_key_cache = AuditMacKeyCache()


def _scope_id(makerspace_id):
    if makerspace_id is None:
        return _GLOBAL_SCOPE_ID
    if (
        isinstance(makerspace_id, bool)
        or not isinstance(makerspace_id, int)
        or makerspace_id < 1
    ):
        raise ValueError("makerspace_id must be a positive integer or None.")
    return makerspace_id


def _fernet():
    configured = getattr(settings, "AUDIT_MAC_MASTER_KEY", "")
    if not configured:
        raise ImproperlyConfigured("AUDIT_MAC_MASTER_KEY is not configured.")
    try:
        if isinstance(configured, str):
            configured = configured.encode("ascii")
        raw = base64.urlsafe_b64decode(configured)
        if len(raw) != 32:
            raise ValueError
        return Fernet(configured)
    except (TypeError, UnicodeError, ValueError) as exc:
        raise ImproperlyConfigured(
            "AUDIT_MAC_MASTER_KEY is not configured correctly."
        ) from exc


def _wrapped_payload(scope_id, key):
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("Audit MAC key must contain exactly 32 bytes.")
    return _WRAP_DOMAIN + struct.pack(">Q", scope_id) + key


def _wrap_key(scope_id, key):
    return _fernet_or_unavailable().encrypt(_wrapped_payload(scope_id, key))


def _fernet_or_unavailable():
    """Configuration problems must surface as AuditMacKeyUnavailable, not as a crash.

    record() only catches AuditMacKeyUnavailable, so letting ImproperlyConfigured escape
    would make a malformed key break every audited mutation -- the exact fail-closed
    behaviour this design removed -- and would crash the verifier instead of reporting
    KEY_UNAVAILABLE.
    """
    try:
        return _fernet()
    except ImproperlyConfigured as exc:
        raise AuditMacKeyUnavailable(
            "The audit MAC master key is not usable."
        ) from exc


def _unwrap_key(scope_id, wrapped_key):
    try:
        payload = _fernet_or_unavailable().decrypt(bytes(wrapped_key))
    except (InvalidToken, TypeError) as exc:
        raise AuditMacKeyUnavailable("The audit MAC key cannot be unwrapped.") from exc
    prefix_length = len(_WRAP_DOMAIN)
    expected_length = prefix_length + 8 + 32
    if len(payload) != expected_length or payload[:prefix_length] != _WRAP_DOMAIN:
        raise AuditMacKeyUnavailable("The audit MAC key has invalid wrapped metadata.")
    stored_scope = struct.unpack(">Q", payload[prefix_length : prefix_length + 8])[0]
    if stored_scope != scope_id:
        raise AuditMacKeyUnavailable("The audit MAC key belongs to a different scope.")
    return payload[-32:]


def _cutover_mac(key, scope_id, value):
    import hashlib
    import hmac as _hmac

    if not isinstance(key, bytes) or len(key) != 32:
        raise AuditMacKeyUnavailable("The audit MAC key is not usable.")
    message = _CUTOVER_DOMAIN + struct.pack(">QQ", scope_id, value)
    return _hmac.new(key, message, hashlib.sha256).digest()


def audit_mac_configured():
    """Whether row-MAC attestation is switched on for this deployment.

    Attestation is opt-in, exactly like PII encryption: a deployment that has never set
    AUDIT_MAC_MASTER_KEY keeps working and writes honestly-unattested rows, rather than
    failing every audited mutation. Cheap and DB-free so record() can call it per write.
    """
    return bool(getattr(settings, "AUDIT_MAC_MASTER_KEY", ""))


def provision_audit_mac_key(makerspace_id=None):
    """Create one scope key explicitly; never called implicitly by audit.record()."""
    scope_id = _scope_id(makerspace_id)
    existing = AuditMacKey.objects.filter(makerspace_id=makerspace_id).first()
    if existing is not None:
        audit_mac_key_cache.invalidate(scope_id)
        return existing, False

    key = secrets.token_bytes(32)
    wrapped_key = _wrap_key(scope_id, key)
    # Everything already written for this scope predates attestation.
    from apps.audit.models import AuditLog

    attested_from_id = (
        AuditLog.objects.filter(makerspace_id=makerspace_id)
        .order_by("-pk")
        .values_list("pk", flat=True)
        .first()
        or 0
    )
    try:
        with transaction.atomic():
            key_row = AuditMacKey.objects.create(
                makerspace_id=makerspace_id,
                wrapped_key=wrapped_key,
                attested_from_id=attested_from_id,
                attested_from_mac=_cutover_mac(key, scope_id, attested_from_id),
            )
    except IntegrityError:
        key_row = AuditMacKey.objects.get(makerspace_id=makerspace_id)
        audit_mac_key_cache.invalidate(scope_id)
        return key_row, False
    audit_mac_key_cache.set(scope_id, key)
    return key_row, True


def get_audit_mac_key(makerspace_id=None):
    """Fetch and unwrap a provisioned key without writes, transactions, or row locks."""
    scope_id = _scope_id(makerspace_id)
    cached = audit_mac_key_cache.get(scope_id)
    if cached is not None:
        return cached
    try:
        key_row = AuditMacKey.objects.only("wrapped_key").get(
            makerspace_id=makerspace_id
        )
    except AuditMacKey.DoesNotExist as exc:
        scope = "global" if makerspace_id is None else f"makerspace {makerspace_id}"
        raise AuditMacKeyUnavailable(
            f"No audit MAC key has been provisioned for {scope}."
        ) from exc
    key = _unwrap_key(scope_id, key_row.wrapped_key)
    audit_mac_key_cache.set(scope_id, key)
    return key


def attested_from_id(makerspace_id=None):
    """The verified id from which this scope is attested, or None if it never was.

    Raises AuditMacKeyUnavailable when the key cannot be unwrapped and
    AuditCutoverTampered when the stored cutover does not match its MAC -- advancing the
    cutover is otherwise a one-UPDATE way to hide a stripped MAC.
    """
    import hmac as _hmac

    row = (
        AuditMacKey.objects.filter(makerspace_id=makerspace_id)
        .values_list("attested_from_id", "attested_from_mac")
        .first()
    )
    if row is None:
        return None
    value, stored_mac = row
    key = get_audit_mac_key(makerspace_id)
    if stored_mac is None:
        # Written before the cutover was bound. Trust nothing: treat as tampered rather
        # than silently accepting an unauthenticated cutover.
        raise AuditCutoverTampered("The attestation cutover carries no MAC.")
    expected = _cutover_mac(key, _scope_id(makerspace_id), int(value))
    if not _hmac.compare_digest(bytes(stored_mac), expected):
        raise AuditCutoverTampered("The attestation cutover MAC does not verify.")
    return int(value)


def advance_attestation_cutover(makerspace_id):
    """Mark every audit row this scope currently holds as pre-attestation.

    Used after a tenant import: imported rows carry no target MAC (semantic remapping
    rewrites the payload, so a source MAC cannot survive and `row_mac` is reconstructed
    as NULL). Without moving the cutover they would classify as MAC_MISSING, i.e. this
    deployment would accuse itself of stripping MACs it never wrote. They are honestly
    UNATTESTED instead: imported history was attested by the SOURCE deployment, if at all.
    """
    from apps.audit.models import AuditLog

    key_row = AuditMacKey.objects.filter(makerspace_id=makerspace_id).first()
    if key_row is None:
        return None
    cutover = (
        AuditLog.objects.filter(makerspace_id=makerspace_id)
        .order_by("-pk")
        .values_list("pk", flat=True)
        .first()
        or 0
    )
    if cutover > key_row.attested_from_id:
        key = get_audit_mac_key(makerspace_id)
        AuditMacKey.objects.filter(pk=key_row.pk).update(
            attested_from_id=cutover,
            attested_from_mac=_cutover_mac(key, _scope_id(makerspace_id), cutover),
        )
    return cutover
