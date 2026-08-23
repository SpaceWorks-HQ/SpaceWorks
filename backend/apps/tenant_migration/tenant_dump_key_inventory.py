"""Exact immutable-image key inventory for the Lane D nested envelope."""

from apps.backup.dek_rewrap import (
    StagedDekRow,
    enumerate_staged_deks,
    validate_staged_deks,
)
from apps.backup.recipient_selection import BackupBuildError
from apps.encryption.models import MakerspaceEncryptionKey

from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_pii import ENCRYPTED, PLAINTEXT


RETAINED_STATUSES = frozenset(
    {
        MakerspaceEncryptionKey.Status.ACTIVE,
        MakerspaceEncryptionKey.Status.ROTATED,
    }
)


def enumerate_immutable_source_keys(makerspace_id, *, using):
    """Read wrapped-key bytes only from the restored immutable source image."""
    try:
        rows = enumerate_staged_deks(makerspace_id, using=using)
        validate_staged_deks(rows)
    except BackupBuildError:
        raise TenantDumpVerificationError(
            "The immutable Lane D source-key inventory is invalid."
        ) from None
    return rows


def retained_key_rows(source_rows, *, mode):
    """Select exactly the live decrypt-capable source rows for portability."""
    source_rows = tuple(source_rows)
    _validate_rows(source_rows)
    retained = tuple(
        sorted(
            (row for row in source_rows if row.status in RETAINED_STATUSES),
            key=lambda row: (row.makerspace_id, row.version, row.row_identity),
        )
    )
    if mode == PLAINTEXT:
        if retained:
            raise TenantDumpVerificationError(
                "A plaintext Lane D source has retained encryption-key rows."
            )
        return ()
    if mode != ENCRYPTED:
        raise TenantDumpVerificationError(
            "The Lane D source PII mode is invalid."
        )
    return retained


def require_exact_retained_key_set(source_rows, candidate_rows):
    """Reject missing, duplicate, extra, disabled-as-live or substituted rows."""
    source_rows = tuple(source_rows)
    candidate_rows = tuple(candidate_rows)
    _validate_rows(source_rows)
    _validate_rows(candidate_rows)
    expected = {
        _identity(row): row
        for row in source_rows
        if row.status in RETAINED_STATUSES
    }
    actual = {}
    for row in candidate_rows:
        identity = _identity(row)
        if identity in actual:
            raise TenantDumpVerificationError(
                "The retained Lane D key inventory contains a duplicate row."
            )
        actual[identity] = row
    if set(actual) != set(expected):
        raise TenantDumpVerificationError(
            "The retained Lane D key inventory is missing or has extra rows."
        )
    for identity, expected_row in expected.items():
        actual_row = actual[identity]
        if actual_row.status not in RETAINED_STATUSES or actual_row != expected_row:
            raise TenantDumpVerificationError(
                "The retained Lane D key inventory contains a substituted row."
            )
    return tuple(
        sorted(
            expected.values(),
            key=lambda row: (row.makerspace_id, row.version, row.row_identity),
        )
    )


def manifest_key_inventory(rows):
    """Return broker-independent non-secret facts; never wrapped or plaintext bytes."""
    return [
        {
            "source_key_row_id": row.row_identity,
            "makerspace_id": row.makerspace_id,
            "version": row.version,
            "status": row.status,
            "source_broker_backend": row.broker_backend,
            "source_broker_key_id": row.broker_key_id,
            "source_wrapped_dek_sha256": row.wrapped_dek_sha256,
        }
        for row in rows
    ]


def _validate_rows(rows):
    if type(rows) is not tuple or any(type(row) is not StagedDekRow for row in rows):
        raise TenantDumpVerificationError(
            "Lane D accepts only an immutable source-key enumeration."
        )
    try:
        validate_staged_deks(rows)
    except BackupBuildError:
        raise TenantDumpVerificationError(
            "The Lane D source-key enumeration is invalid."
        ) from None


def _identity(row):
    return row.row_identity, row.makerspace_id, row.version
