"""Independently derived, non-disclosing facts for the Lane D outer manifest."""

import hashlib
import json
from pathlib import Path

from apps.backup.digests import sha256_file
from apps.backup.recipients import fingerprint_for

from .tenant_dump_outer_manifest_validation import PAYLOAD_MEMBER


def encrypted_member_fact(path):
    path = Path(path)
    size = path.stat().st_size
    return {
        "path": PAYLOAD_MEMBER,
        "sha256": sha256_file(path),
        "size": size,
    }


def recipient_fingerprint_facts(recipients):
    return sorted(fingerprint_for(value) for value in recipients)


def source_build_fact(path=Path("/app/BUILD_INFO.json")):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        source_hash = value["source_hash"]
        if not isinstance(source_hash, str) or not source_hash:
            raise ValueError
    except (
        KeyError,
        OSError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        source_hash = "unknown"
    return {"source_hash": source_hash}


def compatibility_facts(capture, contents, policy_digest, source_pii_mode):
    return {
        "catalog_sha256": capture.catalog_digest,
        "content_ledger_count": len(contents),
        "content_ledger_sha256": _canonical_digest(contents),
        "derivation_policy_sha256": policy_digest,
        "source_pii_mode": source_pii_mode,
    }


def _canonical_digest(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
