"""Target-side W8 exact-set validation and broker replacement."""

import base64
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from apps.backup.digests import sha256_file
from apps.backup.slice_merge_identity import decrypt_bytes, zeroize
from apps.backup.slice_merge_types import SliceMergeError
from apps.encryption import services
from apps.encryption.cache import dek_cache_disabled
from apps.encryption.models import MakerspaceEncryptionKey


@dataclass(frozen=True)
class TargetDekRow:
    row_identity: int
    makerspace_id: int
    version: int
    status: str
    broker_backend: str
    broker_key_id: str
    wrapped_dek: bytes
    dek_sha256: str


def install_target_deks(validated_slice):
    """Decrypt exactly the detailed W8 set and retain target-wrapped bytes only."""
    root = Path(validated_slice.root)
    records = validated_slice.manifest["sealed_deks"]
    if not isinstance(records, list):
        raise SliceMergeError("The W8 sealed key inventory is not a list.")
    expected = set()
    result = []
    broker = services.configured_broker()
    with dek_cache_disabled():
        for record in records:
            identity = _record_identity(record, validated_slice.component)
            if identity in expected:
                raise SliceMergeError("The W8 sealed key inventory contains a duplicate row.")
            expected.add(identity)
            sealed_path = _sealed_path(root, record)
            if (
                sealed_path.stat().st_size != record["size_bytes"]
                or sha256_file(sealed_path) != record["ciphertext_sha256"]
            ):
                raise SliceMergeError("A W8 sealed key ciphertext was substituted.")
            plaintext = decrypt_bytes(sealed_path, validated_slice.identity)
            dek = None
            wrapped = None
            try:
                payload = json.loads(plaintext.decode("utf-8"))
                _validate_payload(payload, record, validated_slice.component)
                dek = base64.b64decode(payload["dek_base64"], validate=True)
                if len(dek) != 32:
                    raise ValueError
                wrapped = broker.wrap_dek(
                    dek, validated_slice.component.makerspace_id_snapshot,
                    record["version"],
                )
                result.append(TargetDekRow(
                    row_identity=record["row_identity"],
                    makerspace_id=record["makerspace_id"],
                    version=record["version"],
                    status=record["status"],
                    broker_backend=broker.backend,
                    broker_key_id=wrapped.broker_key_id,
                    wrapped_dek=bytes(wrapped.wrapped_dek),
                    dek_sha256=hashlib.sha256(dek).hexdigest(),
                ))
            except Exception:
                raise SliceMergeError("A W8 key payload is invalid or cannot be rewrapped.") from None
            finally:
                if isinstance(dek, bytes):
                    mutable = bytearray(dek)
                    zeroize(mutable)
                zeroize(plaintext)
                wrapped = None
    if len(result) != len(records) or len({row.version for row in result}) != len(result):
        raise SliceMergeError("The W8 target key set is missing, duplicated, or extra.")
    if result and sum(row.status == MakerspaceEncryptionKey.Status.ACTIVE for row in result) != 1:
        raise SliceMergeError("The W8 target key set does not contain exactly one active DEK.")
    return tuple(result)


def verify_target_deks(rows, *, using="default"):
    expected = {(row.row_identity, row.version): row for row in rows}
    actual = list(MakerspaceEncryptionKey._base_manager.using(using).filter(
        pk__in=[row.row_identity for row in rows]
    ))
    if len(actual) != len(expected):
        raise SliceMergeError("The installed target DEK set is incomplete.")
    with dek_cache_disabled():
        for key in actual:
            row = expected.get((key.pk, key.version))
            if row is None or any((
                key.makerspace_id != row.makerspace_id,
                key.status != row.status,
                key.broker_backend != row.broker_backend,
                key.broker_key_id != row.broker_key_id,
                bytes(key.wrapped_dek) != row.wrapped_dek,
            )):
                raise SliceMergeError("An installed target DEK row was substituted.")
            plaintext = None
            try:
                plaintext = services.broker_for_backend(key.broker_backend).unwrap_dek(
                    key.wrapped_dek, key.makerspace_id, key.version
                )
                if hashlib.sha256(plaintext).hexdigest() != row.dek_sha256:
                    raise SliceMergeError("An installed target DEK does not unwrap correctly.")
            finally:
                if isinstance(plaintext, bytes):
                    zeroize(bytearray(plaintext))


def _record_identity(record, component):
    required = {
        "row_identity", "makerspace_id", "version", "status",
        "source_broker_backend", "source_broker_key_id",
        "source_wrapped_dek_sha256", "path", "size_bytes", "ciphertext_sha256",
    }
    if (
        not isinstance(record, dict) or set(record) != required
        or type(record["row_identity"]) is not int or record["row_identity"] <= 0
        or record["makerspace_id"] != component.makerspace_id_snapshot
        or type(record["version"]) is not int or record["version"] <= 0
        or record["status"] not in MakerspaceEncryptionKey.Status.values
        or record["source_broker_backend"] not in MakerspaceEncryptionKey.BrokerBackend.values
        or not isinstance(record["source_broker_key_id"], str)
        or not record["source_broker_key_id"]
        or not _is_digest(record["source_wrapped_dek_sha256"])
        or type(record["size_bytes"]) is not int or record["size_bytes"] <= 0
        or not _is_digest(record["ciphertext_sha256"])
    ):
        raise SliceMergeError("The W8 sealed key inventory is malformed.")
    return record["row_identity"], record["version"]


def _sealed_path(root, record):
    expected = f"keys/deks/{record['row_identity']}.json.age"
    if record["path"] != expected:
        raise SliceMergeError("The W8 sealed key path is invalid.")
    path = (root / expected).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise SliceMergeError("The W8 sealed key path is unsafe.") from None
    return path


def _validate_payload(payload, record, component):
    expected = {key: record[key] for key in (
        "row_identity", "makerspace_id", "version", "status",
        "source_broker_backend", "source_broker_key_id", "source_wrapped_dek_sha256",
    )}
    if (
        not isinstance(payload, dict)
        or set(payload) != {*expected, "dek_base64"}
        or any(payload.get(key) != value for key, value in expected.items())
        or payload["makerspace_id"] != component.makerspace_id_snapshot
    ):
        raise SliceMergeError("The W8 key payload does not match its exact inventory row.")


def _is_digest(value):
    return (
        isinstance(value, str) and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
