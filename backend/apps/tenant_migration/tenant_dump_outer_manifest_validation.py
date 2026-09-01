"""Strict structural validation for the readable Lane D outer manifest."""

from .tenant_dump_errors import TenantDumpVerificationError


FORMAT = "spaceworks-tenant-dump-v1"
VERSION = 1
PAYLOAD_MEMBER = "payload.age"
OUTER_MANIFEST_FIELDS = frozenset({
    "format",
    "version",
    "artifact_id",
    "capture_id",
    "outer_recipient_fingerprints",
    "tenant_dek_recipient_fingerprints",
    "encrypted_members",
    "source_build",
    "postgres_major",
    "compatibility",
})
ENCRYPTED_MEMBER_FIELDS = frozenset({"path", "sha256", "size"})
SOURCE_BUILD_FIELDS = frozenset({"source_hash"})
COMPATIBILITY_FIELDS = frozenset({
    "catalog_sha256",
    "content_ledger_count",
    "content_ledger_sha256",
    "derivation_policy_sha256",
    "source_pii_mode",
})


def validate_outer_manifest(manifest):
    """Refuse every field and nested shape outside the Lane D public schema."""
    try:
        if not isinstance(manifest, dict) or set(manifest) != OUTER_MANIFEST_FIELDS:
            raise ValueError
        if manifest["format"] != FORMAT or manifest["version"] != VERSION:
            raise ValueError
        if any(
            not isinstance(manifest[name], str) or not manifest[name]
            for name in ("artifact_id", "capture_id")
        ):
            raise ValueError
        _validate_fingerprints(manifest["outer_recipient_fingerprints"])
        _validate_fingerprints(manifest["tenant_dek_recipient_fingerprints"])
        members = manifest["encrypted_members"]
        if not isinstance(members, list) or len(members) != 1:
            raise ValueError
        member = members[0]
        if (
            not isinstance(member, dict)
            or set(member) != ENCRYPTED_MEMBER_FIELDS
            or member["path"] != PAYLOAD_MEMBER
            or type(member["size"]) is not int
            or member["size"] <= 0
            or not _is_sha256(member["sha256"])
        ):
            raise ValueError
        source_build = manifest["source_build"]
        if (
            not isinstance(source_build, dict)
            or set(source_build) != SOURCE_BUILD_FIELDS
            or not isinstance(source_build["source_hash"], str)
            or not source_build["source_hash"]
        ):
            raise ValueError
        postgres_major = manifest["postgres_major"]
        if type(postgres_major) is not int or not 10 <= postgres_major <= 99:
            raise ValueError
        _validate_compatibility(manifest["compatibility"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TenantDumpVerificationError(
            "The Lane D outer manifest structure is invalid."
        ) from exc
    return True


def _validate_fingerprints(values):
    if (
        not isinstance(values, list)
        or not values
        or values != sorted(set(values))
        or any(not isinstance(value, str) or not value for value in values)
    ):
        raise ValueError


def _validate_compatibility(value):
    if not isinstance(value, dict):
        raise ValueError
    if not value:
        return
    if set(value) != COMPATIBILITY_FIELDS:
        raise ValueError
    if (
        not _is_sha256(value["catalog_sha256"])
        or not _is_sha256(value["content_ledger_sha256"])
        or not _is_sha256(value["derivation_policy_sha256"])
        or type(value["content_ledger_count"]) is not int
        or value["content_ledger_count"] < 0
        or value["source_pii_mode"] not in {"plaintext", "encrypted"}
    ):
        raise ValueError


def _is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
