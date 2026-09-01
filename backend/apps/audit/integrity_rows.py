"""Audit-row and cutover-membership phases of whole-log verification."""

from django.db.models import Exists, OuterRef

from apps.audit.batch_format import genesis_entry
from apps.audit.batch_verification import AuditFailureClass, AuditIntegrityFailure
from apps.audit.models import AuditBatchLeaf, AuditLog
from apps.audit.verification import AuditMacStatus, classify_audit_row


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
