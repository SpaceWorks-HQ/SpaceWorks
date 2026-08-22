"""Guarded W8 source-DEK sealing from immutable snapshot enumeration."""

import base64
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import subprocess

from apps.backup.digests import sha256_bytes, sha256_file
from apps.backup.recipient_selection import BackupBuildError
from apps.encryption import services
from apps.encryption.cache import dek_cache_disabled
from apps.encryption.models import MakerspaceEncryptionKey

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StagedDekRow:
    row_identity: int
    makerspace_id: int
    version: int
    status: str
    broker_backend: str
    broker_key_id: str
    wrapped_dek: bytes
    wrapped_dek_sha256: str


SUPPORTED_STATUSES = frozenset(MakerspaceEncryptionKey.Status.values)
SUPPORTED_BACKENDS = frozenset(MakerspaceEncryptionKey.BrokerBackend.values)


def enumerate_staged_deks(makerspace_id):
    """Freeze exact raw key rows while the caller owns the snapshot transaction."""
    fields = (
        "pk", "makerspace_id", "version", "status", "broker_backend",
        "broker_key_id", "wrapped_dek",
    )
    rows = MakerspaceEncryptionKey._base_manager.filter(
        makerspace_id=makerspace_id
    ).order_by("pk").values_list(*fields)
    result = []
    for values in rows:
        row_id, owner, version, status, backend, key_id, wrapped = values
        immutable_wrapped = bytes(wrapped)
        result.append(StagedDekRow(
            row_identity=row_id,
            makerspace_id=owner,
            version=version,
            status=status,
            broker_backend=backend,
            broker_key_id=key_id,
            wrapped_dek=immutable_wrapped,
            wrapped_dek_sha256=sha256_bytes(immutable_wrapped),
        ))
    return tuple(result)


def seal_staged_deks(staged_rows, recipients, root):
    """Unwrap only the frozen rows and stream each DEK directly into age."""
    if type(staged_rows) is not tuple or any(
        type(row) is not StagedDekRow for row in staged_rows
    ):
        raise BackupBuildError("W8 accepts only an immutable staged enumeration.")
    staged = staged_rows
    recipients = tuple(recipients)
    _validate_staging(staged)
    if not recipients or len(set(recipients)) != len(recipients):
        raise BackupBuildError("W8 requires one non-empty frozen recipient set.")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    sealed = []
    with dek_cache_disabled():
        for row in staged:
            destination = root / f"{row.row_identity}.json.age"
            command = ["age"]
            for recipient in recipients:
                command += ["-r", recipient]
            command += ["-o", str(destination)]
            dek = payload = None
            failed = False
            try:
                broker = services.broker_for_backend(row.broker_backend)
                dek = broker.unwrap_dek(
                    row.wrapped_dek, row.makerspace_id, row.version
                )
                if not isinstance(dek, bytes) or len(dek) != 32:
                    raise ValueError("invalid DEK shape")
                payload = _payload(row, dek)
                subprocess.run(
                    command,
                    input=payload,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                sealed.append(_sealed_record(row, destination))
            except Exception as exc:
                destination.unlink(missing_ok=True)
                failed = True
                # Identity and backend only. The exception's own message can
                # carry provider-side detail, so record its type and nothing
                # else -- a sealing failure must still be diagnosable.
                failure = (type(exc).__name__, row.row_identity, row.broker_backend)
            finally:
                dek = None
                payload = None
            if failed:
                logger.error(
                    "backup.dek_seal_failed exception=%s row_identity=%s backend=%s",
                    *failure,
                )
                # Raise after leaving the exception handler so the public error
                # has no retained __context__ carrying provider-sensitive values.
                raise BackupBuildError(
                    "A frozen tenant DEK could not be sealed to its recipients."
                )
    verify_sealed_dek_inventory(staged, sealed, root)
    return sealed


def _payload(row, dek):
    value = {
        "row_identity": row.row_identity,
        "makerspace_id": row.makerspace_id,
        "version": row.version,
        "status": row.status,
        "source_broker_backend": row.broker_backend,
        "source_broker_key_id": row.broker_key_id,
        "source_wrapped_dek_sha256": row.wrapped_dek_sha256,
        "dek_base64": base64.b64encode(dek).decode("ascii"),
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sealed_record(row, path):
    return {
        "row_identity": row.row_identity,
        "makerspace_id": row.makerspace_id,
        "version": row.version,
        "status": row.status,
        "source_broker_backend": row.broker_backend,
        "source_broker_key_id": row.broker_key_id,
        "source_wrapped_dek_sha256": row.wrapped_dek_sha256,
        "path": f"keys/deks/{row.row_identity}.json.age",
        "size_bytes": path.stat().st_size,
        "ciphertext_sha256": sha256_file(path),
    }


def _validate_staging(staged):
    identities = set()
    versions = set()
    for row in staged:
        identity = (row.row_identity, row.makerspace_id)
        if identity in identities or row.version in versions:
            raise BackupBuildError("W8 staging contains a duplicate key row.")
        identities.add(identity)
        versions.add(row.version)
        valid = (
            # Positive, not merely int-typed: these are database primary keys, so
            # 0 or a negative value is a substituted row, not a real one.
            type(row.row_identity) is int
            and row.row_identity > 0
            and type(row.makerspace_id) is int
            and row.makerspace_id > 0
            and type(row.version) is int
            and row.version > 0
            and row.status in SUPPORTED_STATUSES
            and row.broker_backend in SUPPORTED_BACKENDS
            and isinstance(row.broker_key_id, str)
            and bool(row.broker_key_id)
            and isinstance(row.wrapped_dek, bytes)
            and bool(row.wrapped_dek)
            and sha256_bytes(row.wrapped_dek) == row.wrapped_dek_sha256
        )
        if not valid:
            raise BackupBuildError("W8 staging contains an unsupported or substituted key row.")


def verify_sealed_dek_inventory(staged_rows, sealed_rows, root):
    """Prove exact row equality and immutable ciphertext bytes before slice sealing."""
    staged = tuple(staged_rows)
    _validate_staging(staged)
    expected = {_identity(row): row for row in staged}
    actual = {}
    for record in sealed_rows:
        try:
            identity = (record["row_identity"], record["makerspace_id"])
        except (KeyError, TypeError) as exc:
            raise BackupBuildError("W8 sealed inventory is malformed.") from exc
        if identity in actual:
            raise BackupBuildError("W8 sealed inventory contains a duplicate row.")
        actual[identity] = record
    if set(actual) != set(expected):
        raise BackupBuildError("W8 sealed inventory is missing or has extra rows.")

    root = Path(root)
    for identity, row in expected.items():
        record = actual[identity]
        expected_metadata = {
            "version": row.version,
            "status": row.status,
            "source_broker_backend": row.broker_backend,
            "source_broker_key_id": row.broker_key_id,
            "source_wrapped_dek_sha256": row.wrapped_dek_sha256,
            "path": f"keys/deks/{row.row_identity}.json.age",
        }
        if any(record.get(name) != value for name, value in expected_metadata.items()):
            raise BackupBuildError("W8 sealed inventory contains a substituted row.")
        path = root / f"{row.row_identity}.json.age"
        try:
            size = path.stat().st_size
            digest = sha256_file(path)
        except OSError as exc:
            raise BackupBuildError("W8 sealed ciphertext is missing.") from exc
        if (
            record.get("size_bytes") != size
            or record.get("ciphertext_sha256") != digest
        ):
            raise BackupBuildError("W8 sealed ciphertext failed verification.")


def _identity(row):
    return row.row_identity, row.makerspace_id
