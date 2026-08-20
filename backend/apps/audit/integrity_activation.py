"""Scope-registry and signing-key activation phases of whole-log verification."""

from apps.audit.anchors import AnchorError, anchors_match
from apps.audit.batch_format import canonical_payload_bytes
from apps.audit.batch_verification import AuditFailureClass, AuditIntegrityFailure
from apps.audit.models import AuditMacKey, AuditSigningKey
from apps.audit.signing import (
    AuditSigningKeyUnavailable,
    activation_envelope,
    deployment_identity,
)
from apps.ed25519 import Ed25519Error, encode_key, verify_bytes

from .integrity_rows import _verify_genesis_membership


def _verify_scope_registry():
    from apps.audit.keys import audit_mac_configured
    from apps.makerspaces.models import Makerspace

    mac_scopes = set(AuditMacKey.objects.values_list("makerspace_id", flat=True))
    if audit_mac_configured():
        expected = {None, *Makerspace.objects.values_list("pk", flat=True)}
        missing = expected - mac_scopes
        if missing:
            scope = sorted(missing, key=lambda value: -1 if value is None else value)[0]
            return AuditIntegrityFailure(
                AuditFailureClass.KEY_UNAVAILABLE,
                "An expected scope has no audit MAC key row.",
                scope,
            )
    signing_scopes = set(
        AuditSigningKey.objects.values_list("makerspace_id", flat=True)
    )
    for scope in mac_scopes:
        if scope not in signing_scopes:
            return AuditIntegrityFailure(
                AuditFailureClass.ACTIVATION_MISSING,
                "The MAC scope has no audit signing key or anchored cutover.",
                scope,
            )
    return None


def _verify_activation(key, sink):
    if key.activated_at is None:
        return AuditIntegrityFailure(
            AuditFailureClass.ACTIVATION_MISSING,
            "The scope signing key has no successfully anchored cutover.",
            key.makerspace_id,
        )
    activation = activation_envelope(key)
    try:
        if not isinstance(key.activation_payload, dict):
            raise Ed25519Error("The cutover payload shape is invalid.")
        if key.activation_payload.get("deployment_id") != deployment_identity():
            raise Ed25519Error("The cutover belongs to another deployment.")
        if key.activation_payload.get("public_key") != encode_key(bytes(key.public_key)):
            raise Ed25519Error("The cutover public key is inconsistent.")
        verify_bytes(
            canonical_payload_bytes(key.activation_payload),
            bytes(key.activation_signature),
            bytes(key.public_key),
        )
    except (AuditSigningKeyUnavailable, Ed25519Error) as exc:
        return AuditIntegrityFailure(
            AuditFailureClass.SIGNATURE,
            f"The cutover signature does not verify: {exc}",
            key.makerspace_id,
        )
    mac_row = AuditMacKey.objects.filter(makerspace_id=key.makerspace_id).first()
    stored_mac = (
        bytes(mac_row.attested_from_mac).hex()
        if mac_row is not None and mac_row.attested_from_mac is not None
        else None
    )
    if (
        mac_row is None
        or key.activation_payload.get("cutover_id") != mac_row.attested_from_id
        or key.activation_payload.get("cutover_mac") != stored_mac
    ):
        return AuditIntegrityFailure(
            AuditFailureClass.CUTOVER_MEMBERSHIP,
            "The current MAC cutover differs from the external cutover manifest.",
            key.makerspace_id,
        )
    identity = (
        activation["payload"]["deployment_id"],
        activation["payload"]["scope"],
        key.fingerprint,
        0,
    )
    try:
        external = sink.fetch(identity)
    except AnchorError as exc:
        return AuditIntegrityFailure(
            AuditFailureClass.ANCHOR_UNAVAILABLE, str(exc), key.makerspace_id
        )
    if external is None:
        return AuditIntegrityFailure(
            AuditFailureClass.ANCHOR_MISSING,
            "The cutover anchor is absent.",
            key.makerspace_id,
        )
    if not anchors_match(external, activation):
        return AuditIntegrityFailure(
            AuditFailureClass.ANCHOR_CONFLICT,
            "The cutover anchor conflicts with local state.",
            key.makerspace_id,
        )
    return _verify_genesis_membership(key)
