"""Source key material carried only inside the encrypted migration stream."""

from apps.encryption import services
from apps.encryption.models import MakerspaceEncryptionKey


def collect_source_keys(makerspace):
    """Return ordered source-key records, with live DEKs held as bytes in memory."""
    records = []
    keys = MakerspaceEncryptionKey.objects.filter(makerspace=makerspace).order_by(
        "version"
    )
    for key in keys:
        record = {"version": key.version, "status": key.status}
        if key.status in {
            MakerspaceEncryptionKey.Status.ACTIVE,
            MakerspaceEncryptionKey.Status.ROTATED,
        }:
            record["dek"] = services.unwrap_dek(key)
        elif key.status == MakerspaceEncryptionKey.Status.DISABLED:
            # DISABLED is provenance only and must never be inserted at the target.
            # Its wrapped_dek, broker_backend and broker_key_id columns are non-null,
            # while readiness unwraps every retained row and unwrap_dek rejects a
            # disabled row. A target tombstone would therefore be permanently
            # unready rather than merely degraded.
            record.update(metadata_only=True, insert_at_target=False)
        else:
            raise RuntimeError("An encryption key has an unsupported status.")
        records.append(record)
    return records
