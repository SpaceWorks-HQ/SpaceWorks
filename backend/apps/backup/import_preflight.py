"""Side-effect-free validation for host-supplied deployment archives."""

from dataclasses import dataclass
import hmac
from pathlib import Path
import re

from apps.backup.archive_payload import CONTINUITY_KEYS
from apps.backup.digests import sha256_file
from apps.backup.management.commands.backup_preflight import build_info
from apps.backup.outer_manifest import PROTOCOL_VERSION, verify_outer_manifest
from apps.backup.postgres_client import server_major
from apps.backup.recipient_selection import BackupBuildError


DEPLOYMENT_FORMAT = "spaceworks-phase5a-v3"
LANE_D_FORMAT = "spaceworks-tenant-dump-v1"
OBSOLETE_MIGRATION_FORMAT = "spaceworks-tenant-migration-v1"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_POSTGRES_CLIENT_MAJOR = re.compile(r"PostgreSQL\)\s+(\d+)(?:\.\d+)?")


class ImportPreflightError(RuntimeError):
    """A safe, operator-visible import refusal with a stable reason code."""

    def __init__(self, reason, detail):
        self.reason = reason
        super().__init__(f"Import preflight refused [{reason}]: {detail}")


@dataclass(frozen=True)
class ImportPreflightResult:
    manifest: dict
    archive_sha256: str
    host_restore_gate: str


def host_restore_gate_status():
    # Lane E section 11: the producer/consumer host gate lands in a later phase.
    return "not configured"


def validate_import_preflight(
    *, encrypted_file, bundle, manifest_file, continuity_secrets_file,
    expected_sha256=None,
):
    """Validate an import without writing environment, database, or object state."""
    encrypted_path = Path(encrypted_file)
    try:
        if encrypted_path.stat().st_size <= 0:
            raise OSError
        archive_sha256 = sha256_file(encrypted_path)
    except OSError as exc:
        raise ImportPreflightError(
            "outer_digest", "the encrypted outer artifact is unreadable or empty."
        ) from exc
    if expected_sha256 is not None:
        if not isinstance(expected_sha256, str) or _DIGEST.fullmatch(
            expected_sha256
        ) is None:
            raise ImportPreflightError(
                "outer_digest", "the expected SHA-256 is not 64 lowercase hex characters."
            )
        if not hmac.compare_digest(archive_sha256, expected_sha256):
            raise ImportPreflightError(
                "outer_digest_mismatch", "the encrypted outer artifact digest differs."
            )

    manifest = _read_json_file(manifest_file, "manifest")
    _validate_format(manifest)
    _validate_signature(manifest)
    continuity_secrets = _read_json_file(
        continuity_secrets_file, "continuity-secret"
    )
    from apps.backup.import_preflight_bundle import validate_bundle

    validate_bundle(
        Path(bundle), manifest, manifest_file, continuity_secrets_file
    )
    _validate_continuity_secrets(continuity_secrets)
    _validate_target_compatibility(manifest)
    return ImportPreflightResult(
        manifest=manifest,
        archive_sha256=archive_sha256,
        host_restore_gate=host_restore_gate_status(),
    )


def _validate_format(manifest):
    if not isinstance(manifest, dict):
        raise ImportPreflightError(
            "format_unsupported", "the deployment archive manifest is not an object."
        )
    format_name = manifest.get("format")
    if format_name == LANE_D_FORMAT:
        raise ImportPreflightError(
            "format_lane_d", "a Lane D tenant dump is not a deployment archive."
        )
    if format_name == OBSOLETE_MIGRATION_FORMAT:
        raise ImportPreflightError(
            "format_obsolete", "the obsolete tenant-migration envelope is not importable."
        )
    if format_name != DEPLOYMENT_FORMAT:
        raise ImportPreflightError(
            "format_unsupported", "the deployment archive format is unsupported."
        )
    if manifest.get("protocol_version") != PROTOCOL_VERSION:
        raise ImportPreflightError(
            "format_version", "the Lane E compound protocol version is unsupported."
        )
    if manifest.get("scope") != "deployment" or manifest.get("age_encrypted") is not True:
        raise ImportPreflightError(
            "format_declaration", "the artifact is not an age-encrypted deployment archive."
        )
    _validate_compatibility_declarations(manifest)


def _validate_compatibility_declarations(manifest):
    try:
        sets = manifest["makerspace_sets"]
        identity = manifest["build_identity"]
        if (
            manifest["archive_id"] != manifest["artifact_id"]
            or manifest["snapshot_at"] != manifest["source_timestamp"]
            or manifest["build"] != identity["build"]
            or manifest["oci_digest"] != identity["oci_digest"]
            or manifest["covered_makerspace_ids"] != sets["readable_main"]
            or manifest["excluded_makerspace_ids"] != sets["sovereign"]
            or manifest["partial"] is not bool(sets["sovereign"])
            or manifest["recipient_fingerprints"]
            != manifest["main_component"]["recipient_fingerprints"]
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise ImportPreflightError(
            "format_declaration",
            "the compound manifest compatibility declarations are inconsistent.",
        ) from exc


def _validate_signature(manifest):
    try:
        verify_outer_manifest(manifest)
    except (BackupBuildError, KeyError, TypeError, ValueError) as exc:
        detail = (
            str(exc)
            if isinstance(exc, BackupBuildError)
            else "The outer archive signature is invalid."
        )
        reason = (
            "signer_identity"
            if "does not match the manifest signer" in detail
            else "manifest_signature"
        )
        raise ImportPreflightError(reason, detail) from exc


def _validate_continuity_secrets(values):
    if not isinstance(values, dict) or set(values) != set(CONTINUITY_KEYS):
        raise ImportPreflightError(
            "continuity_secret_names",
            "the continuity-secret name set is not exactly the required set.",
        )
    if any(
        not isinstance(value, str) or "\n" in value or "\r" in value
        for value in values.values()
    ):
        raise ImportPreflightError(
            "continuity_secret_value", "a continuity secret is not a single-line string."
        )


def _validate_target_compatibility(manifest):
    try:
        archived_build = manifest["build_identity"]["build"]["source_hash"]
        current_build = build_info()["source_hash"]
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise ImportPreflightError(
            "source_build", "source build compatibility facts are missing."
        ) from exc
    if not all(
        isinstance(value, str) and value
        for value in (archived_build, current_build)
    ):
        raise ImportPreflightError(
            "source_build", "source build compatibility facts are invalid."
        )
    if not hmac.compare_digest(archived_build, current_build):
        raise ImportPreflightError(
            "source_build", "archive and target source builds differ."
        )

    postgres = manifest.get("postgres")
    if not isinstance(postgres, dict):
        raise ImportPreflightError(
            "postgres_major", "PostgreSQL compatibility facts are missing."
        )
    source = postgres.get("source_server_major")
    client = postgres.get("client")
    client_match = _POSTGRES_CLIENT_MAJOR.search(client) if isinstance(client, str) else None
    try:
        target = server_major()
    except Exception as exc:
        raise ImportPreflightError(
            "postgres_major", "the target PostgreSQL major could not be read."
        ) from exc
    if (
        type(source) is not int
        or source not in {14, 15, 16, 17}
        or client_match is None
        or int(client_match.group(1)) != source
        or type(target) is not int
        or target not in {14, 15, 16, 17}
        or target != source
    ):
        raise ImportPreflightError(
            "postgres_major",
            "the archive pg_dump, source server, and target server majors must match.",
        )


def _read_json_file(path, label):
    from apps.backup.import_preflight_bundle import read_json_file

    return read_json_file(path, label)
