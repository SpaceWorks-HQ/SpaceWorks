"""Whole-log verification across rows, batch chains, and independent anchors."""

import hmac

from django.db.models import Exists, OuterRef

from apps.audit.anchors import AnchorError, anchors_match, configured_sink
from apps.audit.batch_format import canonical_payload_bytes, genesis_entry
from apps.audit.batch_format import scope_name
from apps.audit.batch_verification import (
    AuditFailureClass,
    AuditIntegrityFailure,
    verify_batch_local,
)
from apps.audit.batches import AuditBatchError, batch_envelope
from apps.audit.models import (
    AuditBatch,
    AuditBatchLeaf,
    AuditLog,
    AuditMacKey,
    AuditSigningKey,
)
from apps.audit.signing import (
    AuditSigningKeyUnavailable,
    activation_envelope,
    deployment_identity,
)
from apps.audit.verification import AuditMacStatus, classify_audit_row
from apps.ed25519 import Ed25519Error, encode_key, verify_bytes


def _verify_rows():
    batched = AuditBatchLeaf.objects.filter(audit_log_id=OuterRef("pk"))
    rows = AuditLog.objects.annotate(_is_batched=Exists(batched)).order_by("pk")
    for row in rows.iterator(chunk_size=2_000):
        status = classify_audit_row(row, verify_batch=False)
        if row._is_batched and status in {
            AuditMacStatus.UNATTESTED,
            AuditMacStatus.MAC_MISSING,
        }:
            status = AuditMacStatus.MISMATCH
        failure_class = {
            AuditMacStatus.MISMATCH: AuditFailureClass.ROW_MAC_MISMATCH,
            AuditMacStatus.MAC_MISSING: AuditFailureClass.ROW_MAC_MISSING,
            AuditMacStatus.KEY_UNAVAILABLE: AuditFailureClass.KEY_UNAVAILABLE,
        }.get(status)
        if failure_class:
            return AuditIntegrityFailure(
                failure_class,
                f"Audit row {row.pk} classified as {status.value}.",
                row.makerspace_id,
                audit_log_id=row.pk,
            )
    return None


def _verify_genesis_membership(key):
    stored = key.activation_payload.get("genesis_rows")
    if not isinstance(stored, list):
        return _failure(key, "The cutover manifest has no valid genesis membership.")
    try:
        expected = {int(entry["audit_log_id"]): entry for entry in stored}
    except (KeyError, TypeError, ValueError):
        return _failure(key, "The cutover manifest membership shape is invalid.")
    if len(expected) != len(stored):
        return _failure(key, "The cutover manifest repeats an audit row id.")
    current = {
        row.pk: row
        for row in AuditLog.objects.filter(makerspace_id=key.makerspace_id)
    }
    for audit_log_id, expected_entry in expected.items():
        row = current.get(audit_log_id)
        try:
            matches = row is not None and genesis_entry(row) == expected_entry
        except (TypeError, ValueError):
            matches = False
        if not matches:
            return _failure(
                key,
                "A row visible at cutover is absent or differs from its manifest.",
                audit_log_id,
            )
    for row in current.values():
        if row.row_mac is None and row.pk not in expected:
            return _failure(
                key,
                "An un-MAC'd row was not present in the anchored cutover manifest.",
                row.pk,
            )
    return None


def _failure(key, detail, audit_log_id=None):
    return AuditIntegrityFailure(
        AuditFailureClass.CUTOVER_MEMBERSHIP,
        detail,
        key.makerspace_id,
        audit_log_id=audit_log_id,
    )


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


def _verify_batches(key, sink):
    expected_seq = 1
    previous_root = None
    batches = AuditBatch.objects.filter(makerspace_id=key.makerspace_id).order_by(
        "batch_seq"
    )
    for batch in batches:
        if batch.batch_seq != expected_seq or not _continues(batch, previous_root):
            return AuditIntegrityFailure(
                AuditFailureClass.CHAIN_CONTINUITY,
                "batch_seq or prev_batch_root does not continue the scope chain.",
                key.makerspace_id,
                batch.batch_seq,
            )
        failure = verify_batch_local(batch)
        if failure:
            return failure
        try:
            envelope = batch_envelope(batch)
        except AuditBatchError as exc:
            return AuditIntegrityFailure(
                AuditFailureClass.SIGNATURE,
                str(exc),
                key.makerspace_id,
                batch.batch_seq,
            )
        identity = (
            deployment_identity(),
            envelope["payload"]["scope"],
            key.fingerprint,
            batch.batch_seq,
        )
        try:
            external = sink.fetch(identity)
        except AnchorError as exc:
            return AuditIntegrityFailure(
                AuditFailureClass.ANCHOR_UNAVAILABLE,
                str(exc),
                key.makerspace_id,
                batch.batch_seq,
            )
        if external is None or not anchors_match(external, envelope):
            failure_class = (
                AuditFailureClass.ANCHOR_MISSING
                if external is None
                else AuditFailureClass.ANCHOR_CONFLICT
            )
            return AuditIntegrityFailure(
                failure_class,
                "The batch anchor is absent or conflicts with local state.",
                key.makerspace_id,
                batch.batch_seq,
            )
        previous_root = bytes(batch.merkle_root)
        expected_seq += 1

    # The local chain being contiguous proves nothing about its TAIL: an attacker who can
    # bypass the triggers can delete the newest batch and its leaves and leave a perfectly
    # consistent prefix. The anchor is the only witness that the batch existed, so ask it.
    scope_label = scope_name(key.makerspace_id)
    try:
        orphan = sink.fetch(
            (deployment_identity(), scope_label, key.fingerprint, expected_seq)
        )
    except AnchorError:
        return AuditIntegrityFailure(
            AuditFailureClass.ANCHOR_UNAVAILABLE,
            "The anchor could not be read, so the local tail cannot be trusted.",
            key.makerspace_id,
            expected_seq,
        )
    if orphan is not None:
        return AuditIntegrityFailure(
            AuditFailureClass.BATCH_MISSING,
            "An anchored batch is absent locally, so local batches were removed.",
            key.makerspace_id,
            expected_seq,
        )
    return None


def _continues(batch, previous_root):
    if previous_root is None:
        return batch.prev_batch_root is None
    return batch.prev_batch_root is not None and hmac.compare_digest(
        previous_root, bytes(batch.prev_batch_root)
    )


def verify_audit_integrity(*, sink=None):
    """Return the first failure across rows, local chains, signatures, and anchors."""
    failure = _verify_rows()
    if failure:
        return failure
    try:
        sink = sink or configured_sink()
    except AnchorError as exc:
        return AuditIntegrityFailure(AuditFailureClass.ANCHOR_UNAVAILABLE, str(exc))
    failure = _verify_scope_registry()
    if failure:
        return failure
    for key in AuditSigningKey.objects.order_by("makerspace_id"):
        failure = _verify_activation(key, sink) or _verify_batches(key, sink)
        if failure:
            return failure
    return None
