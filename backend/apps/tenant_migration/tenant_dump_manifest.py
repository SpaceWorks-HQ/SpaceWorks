"""Fail-closed D4 manifest and content-ledger verification."""

from .tenant_dump_envelope import TENANT_DEKS_MEMBER
from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_pii import source_pii_mode


def verify_envelope_custody_manifest(capture, manifest):
    expected_mode = source_pii_mode(capture.source_encryption_mode)
    source = manifest.get("source")
    encryption = manifest.get("encryption")
    contents = manifest.get("contents")
    if not isinstance(source, dict) or not isinstance(encryption, dict):
        raise TenantDumpVerificationError(
            "The Lane D manifest lacks its D4 source-mode declaration."
        )
    if (
        manifest.get("source_pii_mode") != expected_mode
        or source.get("source_pii_mode") != expected_mode
        or encryption.get("source_pii_mode") != expected_mode
    ):
        raise TenantDumpVerificationError(
            "The Lane D manifest source PII mode does not match its capture."
        )
    findings = encryption.get("mapped_column_findings")
    inventory = encryption.get("retained_key_inventory")
    envelope = encryption.get("tenant_dek_envelope")
    if not _valid_findings(findings) or not isinstance(inventory, list):
        raise TenantDumpVerificationError(
            "The Lane D manifest encryption inventory is invalid."
        )
    ledger_entry = _key_ledger_entry(contents)
    if expected_mode == "plaintext":
        valid = (
            not inventory
            and findings["envelope_values"] == 0
            and envelope == {"path": TENANT_DEKS_MEMBER, "present": False}
            and ledger_entry == {"path": TENANT_DEKS_MEMBER, "present": False}
        )
    else:
        valid = (
            findings["plaintext_values"] == 0
            and _same_ciphertext_fact(envelope, ledger_entry)
            and _valid_key_inventory(inventory, capture.source_makerspace_id)
        )
    if not valid:
        raise TenantDumpVerificationError(
            "The Lane D manifest violates its source-mode DEK custody contract."
        )
    return True


def _key_ledger_entry(contents):
    if not isinstance(contents, list):
        raise TenantDumpVerificationError("The Lane D content ledger is invalid.")
    matches = [
        item
        for item in contents
        if isinstance(item, dict) and item.get("path") == TENANT_DEKS_MEMBER
    ]
    if len(matches) != 1:
        raise TenantDumpVerificationError(
            "The Lane D content ledger must declare the tenant DEK member once."
        )
    return matches[0]


def _valid_findings(value):
    fields = {
        "mapped_rows",
        "mapped_values",
        "empty_values",
        "envelope_values",
        "plaintext_values",
    }
    return (
        isinstance(value, dict)
        and set(value) == fields
        and all(type(value[name]) is int and value[name] >= 0 for name in fields)
        and value["mapped_values"]
        == value["empty_values"]
        + value["envelope_values"]
        + value["plaintext_values"]
    )


def _same_ciphertext_fact(envelope, ledger):
    fields = ("path", "size", "sha256")
    digest = envelope.get("sha256") if isinstance(envelope, dict) else None
    size = envelope.get("size") if isinstance(envelope, dict) else None
    return (
        isinstance(envelope, dict)
        and envelope.get("path") == TENANT_DEKS_MEMBER
        and type(size) is int
        and size > 0
        and isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        and ledger.get("present") is True
        and all(envelope.get(name) == ledger.get(name) for name in fields)
    )


def _valid_key_inventory(inventory, makerspace_id):
    required = {
        "source_key_row_id",
        "makerspace_id",
        "version",
        "status",
        "source_broker_backend",
        "source_broker_key_id",
        "source_wrapped_dek_sha256",
    }
    identities = set()
    for item in inventory:
        if not isinstance(item, dict) or set(item) != required:
            return False
        row_id = item["source_key_row_id"]
        version = item["version"]
        owner = item["makerspace_id"]
        status = item["status"]
        digest = item["source_wrapped_dek_sha256"]
        if (
            type(row_id) is not int
            or row_id <= 0
            or type(version) is not int
            or version <= 0
            or type(owner) is not int
            or owner != makerspace_id
            or not isinstance(status, str)
            or status not in {"active", "rotated"}
            or item["source_broker_backend"] not in {"local", "aws_kms"}
            or not isinstance(item["source_broker_key_id"], str)
            or not item["source_broker_key_id"]
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            return False
        identity = (row_id, version)
        if identity in identities:
            return False
        identities.add(identity)
    return True
