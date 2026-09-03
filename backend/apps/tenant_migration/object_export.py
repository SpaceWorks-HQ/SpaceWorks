"""Capture the canonical tenant object closure into the encrypted archive tree."""

import hashlib
import json
from pathlib import Path

from django.conf import settings

from apps.backup import storage
from apps.makerspaces.storage_key_collectors import (
    collect_private_object_keys,
    collect_public_image_keys,
)
from apps.evidence.models import EvidenceObjectRetentionState
from apps.evidence.retention_objects import retention_object_states
from apps.evidence.storage import staging_key


class SourceMigrationObjectError(RuntimeError):
    def __init__(self, source_key, detail="could not be read"):
        self.source_key = source_key
        super().__init__(f"Source object {source_key!r} {detail}.")


def capture_tenant_objects(root, makerspace, storage_modes):
    root = Path(root)
    closures = (
        (
            "private",
            settings.AWS_STORAGE_BUCKET_NAME,
            collect_private_object_keys(makerspace, include_coordination=False),
        ),
        (
            "public_image",
            settings.PUBLIC_IMAGE_BUCKET,
            collect_public_image_keys(makerspace, include_coordination=False),
        ),
    )
    records = []
    source_keys = set()
    evidence_states = retention_object_states(makerspace)
    for bucket_kind, bucket, keys in closures:
        for source_key in sorted(keys):
            if source_key in source_keys:
                raise SourceMigrationObjectError(
                    source_key, "is referenced from more than one bucket"
                )
            source_keys.add(source_key)
            retention = evidence_states.get(source_key)
            if retention and retention["status"] == EvidenceObjectRetentionState.Status.EXPIRING:
                raise SourceMigrationObjectError(
                    source_key, "is currently being expired; retry after the sweep"
                )
            if retention and retention["status"] == EvidenceObjectRetentionState.Status.EXPIRED:
                try:
                    storage.assert_object_absent(bucket, source_key)
                    storage.assert_object_absent(bucket, staging_key(source_key))
                except Exception as exc:
                    raise SourceMigrationObjectError(
                        source_key, "is marked expired but bytes still exist"
                    ) from exc
                records.append(
                    {
                        "bucket_kind": bucket_kind,
                        "source_key": source_key,
                        "size": 0,
                        "sha256": "",
                        "version_id": None,
                        "content_type": "",
                        "retention_state": "expired",
                        "object_expired_at": retention["object_expired_at"].isoformat(),
                        "expired_size_bytes": retention["expired_size_bytes"],
                    }
                )
                continue
            destination = root / object_member_path(bucket_kind, source_key)
            try:
                # There is no ObjectVersion ledger yet. Even for a versioned bucket,
                # Phase 5A's versioned GET pins the current version while the source is
                # quiesced. If a ledger is added, capture must read its recorded version
                # id instead of relying on quiescence to identify the intended head.
                captured = storage.download_object(
                    bucket,
                    source_key,
                    destination,
                    versioned=storage_modes[bucket_kind] == "versioned",
                )
            except Exception as exc:
                raise SourceMigrationObjectError(source_key, "is missing or unreadable") from exc
            records.append(
                {
                    "bucket_kind": bucket_kind,
                    "source_key": source_key,
                    "size": captured["size"],
                    "sha256": captured["sha256"],
                    "version_id": captured["version_id"] or None,
                    "content_type": captured.get("content_type") or "",
                }
            )
    manifest_path = root / "objects" / "manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    return records


def object_member_path(bucket_kind, source_key):
    directory = "private" if bucket_kind == "private" else "public"
    opaque = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
    return Path("objects", directory, opaque)
