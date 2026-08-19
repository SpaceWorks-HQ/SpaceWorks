"""Per-scope audit signing keys, wrapped by the row-MAC master KEK."""

import struct

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.batch_format import (
    CUTOVER_DOMAIN,
    FORMAT_VERSION,
    canonical_payload_bytes,
    genesis_entry,
    genesis_membership,
    scope_name,
)
from apps.audit.canonical import canonical_timestamp
from apps.audit.keys import (
    AuditMacKeyUnavailable,
    _fernet_or_unavailable,
    _scope_id,
    attested_from_id,
)
from apps.audit.models import AuditMacKey, AuditSigningKey
from apps.ed25519 import (
    Ed25519Error,
    encode_key,
    fingerprint_public_key,
    generate_keypair,
    sign_bytes,
    verify_bytes,
)


_WRAP_DOMAIN = b"spaceworks-audit-signing-key-v1\x00"


class AuditSigningKeyUnavailable(RuntimeError):
    pass


def deployment_identity():
    value = str(getattr(settings, "AUDIT_ATTESTATION_DEPLOYMENT_ID", "")).strip()
    if not value or len(value) > 128:
        raise AuditSigningKeyUnavailable(
            "AUDIT_ATTESTATION_DEPLOYMENT_ID must be a stable non-empty value."
        )
    return value


def _wrap_private_key(makerspace_id, private_key):
    scope_id = _scope_id(makerspace_id)
    payload = _WRAP_DOMAIN + struct.pack(">Q", scope_id) + private_key
    return _fernet_or_unavailable().encrypt(payload)


def private_key_material(row):
    try:
        payload = _fernet_or_unavailable().decrypt(bytes(row.wrapped_private_key))
    except Exception as exc:
        raise AuditSigningKeyUnavailable(
            "The audit signing private key cannot be unwrapped."
        ) from exc
    prefix = len(_WRAP_DOMAIN)
    if (
        len(payload) != prefix + 8 + 32
        or payload[:prefix] != _WRAP_DOMAIN
        or struct.unpack(">Q", payload[prefix : prefix + 8])[0]
        != _scope_id(row.makerspace_id)
    ):
        raise AuditSigningKeyUnavailable(
            "The audit signing key has invalid wrapped metadata."
        )
    private_key = payload[-32:]
    try:
        if not isinstance(row.activation_payload, dict):
            raise Ed25519Error("The activation payload shape is invalid.")
        if row.activation_payload.get("deployment_id") != deployment_identity():
            raise Ed25519Error("The activation belongs to another deployment.")
        if row.activation_payload.get("scope") != scope_name(row.makerspace_id):
            raise Ed25519Error("The activation belongs to another scope.")
        if fingerprint_public_key(bytes(row.public_key)) != row.fingerprint:
            raise Ed25519Error("The stored signer fingerprint is invalid.")
        if row.activation_payload.get("signer_fingerprint") != row.fingerprint:
            raise Ed25519Error("The activation signer fingerprint is inconsistent.")
        if row.activation_payload.get("public_key") != encode_key(bytes(row.public_key)):
            raise Ed25519Error("The activation public key is inconsistent.")
        probe = b"spaceworks-audit-signing-key-probe"
        verify_bytes(probe, sign_bytes(probe, private_key), bytes(row.public_key))
    except Ed25519Error as exc:
        raise AuditSigningKeyUnavailable(
            "The audit signing public and private keys do not match."
        ) from exc
    return private_key


def _activation_payload(makerspace_id, public_key, fingerprint, created_at):
    cutover_id = attested_from_id(makerspace_id)
    if cutover_id is None:
        raise AuditMacKeyUnavailable("The scope has no audit MAC cutover to anchor.")
    mac_row = AuditMacKey.objects.only("attested_from_mac").get(
        makerspace_id=makerspace_id
    )
    from apps.audit.models import AuditLog

    visible_rows = AuditLog.objects.filter(makerspace_id=makerspace_id).order_by("pk")
    return {
        "format_version": FORMAT_VERSION,
        "domain": CUTOVER_DOMAIN,
        "deployment_id": deployment_identity(),
        "scope": scope_name(makerspace_id),
        "batch_seq": 0,
        "cutover_id": cutover_id,
        "cutover_mac": bytes(mac_row.attested_from_mac).hex(),
        "genesis_rows": genesis_membership(visible_rows),
        "public_key": encode_key(public_key),
        "signer_fingerprint": fingerprint,
        "created_at": canonical_timestamp(created_at),
    }


def provision_signing_key(makerspace_id=None):
    existing = AuditSigningKey.objects.filter(makerspace_id=makerspace_id).first()
    if existing is not None:
        private_key_material(existing)
        return existing, False
    private_key, public_key = generate_keypair()
    fingerprint = fingerprint_public_key(public_key)
    created_at = timezone.now()
    payload = _activation_payload(
        makerspace_id, public_key, fingerprint, created_at
    )
    try:
        with transaction.atomic():
            row = AuditSigningKey.objects.create(
                makerspace_id=makerspace_id,
                wrapped_private_key=_wrap_private_key(makerspace_id, private_key),
                public_key=public_key,
                fingerprint=fingerprint,
                activation_payload=payload,
                activation_signature=sign_bytes(
                    canonical_payload_bytes(payload), private_key
                ),
                created_at=created_at,
            )
    except IntegrityError:
        row = AuditSigningKey.objects.get(makerspace_id=makerspace_id)
        private_key_material(row)
        return row, False
    return row, True


def activation_envelope(row):
    return {
        "payload": row.activation_payload,
        "signature": bytes(row.activation_signature).hex(),
        "public_key": encode_key(bytes(row.public_key)),
    }


def validate_genesis_database(row):
    """Refuse activation if its signed snapshot already differs from the database."""
    from apps.audit.models import AuditLog

    mac_row = AuditMacKey.objects.filter(makerspace_id=row.makerspace_id).first()
    if (
        mac_row is None
        or row.activation_payload.get("cutover_id") != mac_row.attested_from_id
        or row.activation_payload.get("cutover_mac")
        != (
            bytes(mac_row.attested_from_mac).hex()
            if mac_row.attested_from_mac is not None
            else None
        )
    ):
        raise AuditSigningKeyUnavailable(
            "The MAC cutover differs from the signed activation snapshot."
        )
    stored = row.activation_payload.get("genesis_rows")
    if not isinstance(stored, list):
        raise AuditSigningKeyUnavailable("The activation genesis membership is invalid.")
    try:
        expected = {int(entry["audit_log_id"]): entry for entry in stored}
    except (KeyError, TypeError, ValueError) as exc:
        raise AuditSigningKeyUnavailable(
            "The activation genesis membership is invalid."
        ) from exc
    if len(expected) != len(stored):
        raise AuditSigningKeyUnavailable("The activation repeats an audit row id.")
    current = {
        audit_row.pk: audit_row
        for audit_row in AuditLog.objects.filter(
            makerspace_id=row.makerspace_id
        )
    }
    for audit_log_id, entry in expected.items():
        audit_row = current.get(audit_log_id)
        if audit_row is None or genesis_entry(audit_row) != entry:
            raise AuditSigningKeyUnavailable(
                "The database differs from the signed activation snapshot."
            )
    if any(
        audit_row.row_mac is None and audit_row.pk not in expected
        for audit_row in current.values()
    ):
        raise AuditSigningKeyUnavailable(
            "A new un-MAC'd row is outside the signed activation snapshot."
        )
