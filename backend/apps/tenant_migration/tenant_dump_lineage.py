"""Canonical digest and lineage rules for `spaceworks-tenant-dump-v1`."""

import hashlib
import json

from .tenant_dump_catalog import CATALOG_SCHEMA_SHA256
from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_manifest import verify_envelope_custody_manifest


FORMAT = "spaceworks-tenant-dump-v1"
DERIVATION_POLICY_VERSION = 4


def canonical_digest(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def object_ledger(entries):
    normalized = []
    for entry in entries:
        normalized.append(
            {
                "bucket_kind": entry["bucket_kind"],
                "key": entry.get("original_key", entry.get("source_key")),
                "version_id": entry.get("version_id") or None,
                "size": int(entry["size"]),
                "sha256": entry["sha256"],
                "content_type": entry.get("content_type") or "",
            }
        )
    return tuple(sorted(normalized, key=lambda item: (item["bucket_kind"], item["key"])))


def derivation_policy_digest(*, source_encryption_mode):
    return canonical_digest(
        {
            "format": FORMAT,
            "policy_version": DERIVATION_POLICY_VERSION,
            "catalog_digest": CATALOG_SCHEMA_SHA256,
            "source_encryption_mode": bool(source_encryption_mode),
            "companion_slice": False,
        }
    )


def verify_artifact_lineage(capture, manifest):
    if manifest.get("format") != FORMAT:
        raise TenantDumpVerificationError("The Lane D artifact format is invalid.")
    if str(manifest.get("capture_id")) != str(capture.pk):
        raise TenantDumpVerificationError("The Lane D artifact names another capture.")
    lineage = manifest.get("lineage")
    if not isinstance(lineage, dict):
        raise TenantDumpVerificationError("The Lane D artifact has no lineage record.")
    expected = {
        "database_image_sha256": capture.database_image_sha256,
        "object_ledger_sha256": capture.object_ledger_sha256,
        "derivation_policy_sha256": capture.derivation_policy_sha256,
    }
    if any(lineage.get(key) != value for key, value in expected.items()):
        raise TenantDumpVerificationError("The Lane D artifact lineage does not match its capture.")
    if manifest.get("contents") != capture.content_ledger:
        raise TenantDumpVerificationError(
            "The Lane D artifact content ledger does not match its capture."
        )
    forbidden = {"companion_slice", "companion_slice_id", "lossless_slice"}
    if forbidden & set(manifest):
        raise TenantDumpVerificationError("A tenant-exit artifact cannot name a companion slice.")
    verify_envelope_custody_manifest(capture, manifest)
    return True
