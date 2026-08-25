"""Construction of the non-disclosing Lane D outer manifest."""

import hashlib
import json

from .tenant_dump_outer_manifest_validation import validate_outer_manifest


def build_outer_manifest(
    *,
    format,
    version,
    artifact_id,
    capture_id,
    outer_recipient_fingerprints,
    tenant_dek_recipient_fingerprints,
    encrypted_members,
    source_build,
    postgres_major,
    compatibility,
):
    """Build only the public component identities, counts, and digest facts."""
    manifest = {
        "format": format,
        "version": version,
        "artifact_id": str(artifact_id),
        "capture_id": str(capture_id),
        "outer_recipient_fingerprints": sorted(outer_recipient_fingerprints),
        "tenant_dek_recipient_fingerprints": sorted(
            tenant_dek_recipient_fingerprints
        ),
        "encrypted_members": [dict(item) for item in encrypted_members],
        "source_build": dict(source_build),
        "postgres_major": postgres_major,
        "compatibility": dict(compatibility),
    }
    validate_outer_manifest(manifest)
    return manifest


def canonical_manifest_bytes(manifest):
    validate_outer_manifest(manifest)
    return json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def outer_manifest_sha256(manifest):
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()
