"""Shared canonical facts used by the E5 outer manifest and E7 source proof."""

import hashlib
import json

from apps.backup.digests import sha256_file
from apps.backup.outer_manifest_validation import component_id
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.recipients import fingerprint_for
from apps.backup.user_closure import user_closure_digest


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


def closure_digest_from_slice_ledgers(unsealed_slices):
    """Rebuild the canonical closure digest from the plaintext slice ledgers."""
    entries = []
    for item in unsealed_slices:
        try:
            values = json.loads(
                (item.plaintext / "user-closure-ledger.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackupBuildError(
                "A sovereign user-closure ledger is unreadable."
            ) from exc
        if not isinstance(values, list):
            raise BackupBuildError("A sovereign user-closure ledger is malformed.")
        for value in values:
            if not isinstance(value, dict) or set(value) != {
                "disposition", "source_user_pk", "reason_code"
            }:
                raise BackupBuildError(
                    "A sovereign user-closure ledger is malformed."
                )
            entries.append((
                value["disposition"],
                value["source_user_pk"],
                value["reason_code"],
            ))
    return user_closure_digest(entries)


def digest_json(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    ).encode("utf-8")).hexdigest()
