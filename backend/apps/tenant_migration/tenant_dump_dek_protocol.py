"""Key-free parent/helper request protocol for Lane D DEK sealing."""

import base64
import json

from apps.backup.dek_rewrap import StagedDekRow, validate_staged_deks
from apps.backup.recipient_selection import BackupBuildError
from apps.encryption.models import MakerspaceEncryptionKey


class TenantDekProtocolError(RuntimeError):
    pass


def encode_helper_request(rows, tenant_dek_recipients):
    """Encode only source-wrapped bytes and public recipients for the helper."""
    rows = tuple(rows)
    recipients = _validate_recipients(tenant_dek_recipients)
    _validate_rows(rows)
    value = {
        "protocol": "spaceworks-lane-d-dek-helper-v1",
        "tenant_dek_recipients": list(recipients),
        "rows": [
            {
                "row_identity": row.row_identity,
                "makerspace_id": row.makerspace_id,
                "version": row.version,
                "status": row.status,
                "broker_backend": row.broker_backend,
                "broker_key_id": row.broker_key_id,
                "wrapped_dek_base64": base64.b64encode(row.wrapped_dek).decode("ascii"),
                "wrapped_dek_sha256": row.wrapped_dek_sha256,
            }
            for row in rows
        ],
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def decode_helper_request(payload):
    try:
        value = json.loads(payload)
        if value.get("protocol") != "spaceworks-lane-d-dek-helper-v1":
            raise ValueError
        recipients = _validate_recipients(value["tenant_dek_recipients"])
        rows = tuple(_decode_row(item) for item in value["rows"])
        _validate_rows(rows)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise TenantDekProtocolError("The Lane D DEK helper request is invalid.") from None
    return rows, recipients


def _decode_row(item):
    wrapped = base64.b64decode(item["wrapped_dek_base64"], validate=True)
    return StagedDekRow(
        row_identity=item["row_identity"],
        makerspace_id=item["makerspace_id"],
        version=item["version"],
        status=item["status"],
        broker_backend=item["broker_backend"],
        broker_key_id=item["broker_key_id"],
        wrapped_dek=wrapped,
        wrapped_dek_sha256=item["wrapped_dek_sha256"],
    )


def _validate_rows(rows):
    if type(rows) is not tuple or any(
        type(row) is not StagedDekRow for row in rows
    ):
        raise TenantDekProtocolError("The Lane D DEK helper inventory is invalid.")
    try:
        validate_staged_deks(rows)
    except BackupBuildError:
        raise TenantDekProtocolError(
            "The Lane D DEK helper inventory is invalid."
        ) from None
    if any(
        row.status
        not in {
            MakerspaceEncryptionKey.Status.ACTIVE,
            MakerspaceEncryptionKey.Status.ROTATED,
        }
        for row in rows
    ):
        raise TenantDekProtocolError(
            "The Lane D DEK helper inventory is invalid."
        )


def _validate_recipients(recipients):
    recipients = tuple(recipients)
    if (
        not recipients
        or any(not isinstance(item, str) or not item for item in recipients)
        or len(recipients) != len(set(recipients))
    ):
        raise TenantDekProtocolError(
            "The Lane D tenant DEK recipient set is invalid."
        )
    return recipients
