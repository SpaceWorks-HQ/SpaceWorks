"""Shared canonical facts used by the E5 outer manifest and E7 source proof."""

import hashlib
import json

from apps.backup.digests import sha256_file
from apps.backup.outer_manifest_validation import component_id
from apps.backup.recipients import fingerprint_for


def component_ciphertext_ledger(capture, detailed_manifest, root):
    main_path = root / "database.dump"
    main = {
        "component_id": component_id(capture.capture_id, "main"),
        "kind": "main",
        "path": "database.dump",
        "size_bytes": main_path.stat().st_size,
        "ciphertext_sha256": sha256_file(main_path),
        "schema_catalog_digest": capture.source_catalog_digest,
        "semantic_digest": digest_json(capture.expected_main_ledger),
        "sequence_policy": "source-high-water-over-all-components",
        "recipient_fingerprints": sorted(
            fingerprint_for(value) for value in capture.platform_recipients
        ),
    }
    slices = [{
        "component_id": item["component_id"],
        "kind": "slice",
        "makerspace_id": item["makerspace_id"],
        "ciphertext_path": item["path"],
        "size_bytes": item["size_bytes"],
        "ciphertext_sha256": item["ciphertext_sha256"],
        "recipient_fingerprints": sorted(item["recipient_fingerprints"]),
    } for item in capture.slice_entries]
    return [main, *slices]


def reservation_fence_ledger(capture):
    return capture.reservation_capture.manifest_facts()


def digest_json(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    ).encode("utf-8")).hexdigest()
