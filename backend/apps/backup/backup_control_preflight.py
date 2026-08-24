"""Preflight routing for legacy and compound deployment restore paths."""

import json
import os
from pathlib import Path
import shutil

from django.conf import settings
from django.core.management.base import CommandError
from django.db import connections

from apps.backup import storage
from apps.backup.digests import (
    ArchiveDigestError,
    SUPPORTED_ARCHIVE_FORMATS,
    verify_content_ledger,
)
from apps.backup.import_preflight import (
    ImportPreflightError,
    validate_import_preflight,
)
from apps.backup.models import BackupArchive, RestoreOperation
from apps.backup.restore_services import set_stage


def run_restore_preflight(
    restore_id,
    manifest_path,
    *,
    current_oci_digest,
    bundle_path,
    encrypted_file,
    decrypted_bundle,
    continuity_secrets,
    build_info,
    check_setting_policies,
):
    restore = RestoreOperation.objects.select_related("archive").get(pk=restore_id)
    archive = restore.archive
    if archive.status != BackupArchive.Status.AVAILABLE or not archive.age_encrypted:
        raise CommandError(
            "The selected archive is not a completed age-encrypted deployment backup."
        )
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandError("The authenticated archive manifest is unreadable.") from exc
    if (
        manifest.get("format") not in SUPPORTED_ARCHIVE_FORMATS
        or manifest.get("scope") != BackupArchive.Scope.DEPLOYMENT
        or manifest.get("archive_id") != str(archive.pk)
        or manifest.get("age_encrypted") is not True
        or type(manifest.get("partial")) is not bool
    ):
        raise CommandError(
            "The authenticated archive manifest does not match the restore intent."
        )
    if manifest["partial"]:
        return _compound_handoff(
            archive,
            manifest,
            encrypted_file=encrypted_file,
            decrypted_bundle=decrypted_bundle,
            manifest_path=manifest_path,
            continuity_secrets=continuity_secrets,
        )
    _validate_legacy(
        restore,
        manifest,
        bundle_path=bundle_path,
        current_oci_digest=current_oci_digest,
        build_info=build_info,
        check_setting_policies=check_setting_policies,
    )
    if restore.stage == RestoreOperation.Stage.CLAIMED:
        set_stage(restore_id, RestoreOperation.Stage.PREFLIGHT)
    return "preflight-ok"


def _compound_handoff(
    archive, manifest, *, encrypted_file, decrypted_bundle, manifest_path,
    continuity_secrets,
):
    if not all((encrypted_file, decrypted_bundle, continuity_secrets)):
        raise CommandError(
            "The scripts/restore.sh legacy path cannot hand off this compound archive: "
            "encrypted artifact, decrypted bundle, and continuity-secret inputs are required."
        )
    try:
        result = validate_import_preflight(
            encrypted_file=encrypted_file,
            bundle=decrypted_bundle,
            manifest_file=manifest_path,
            continuity_secrets_file=continuity_secrets,
            expected_sha256=archive.archive_sha256 or None,
        )
    except ImportPreflightError as exc:
        raise CommandError(str(exc)) from exc
    if result.manifest != manifest:
        raise CommandError("The compound coordinator received a different manifest.")
    return "compound-coordinator-ready"


def _validate_legacy(
    restore, manifest, *, bundle_path, current_oci_digest, build_info,
    check_setting_policies,
):
    if bundle_path:
        try:
            verify_content_ledger(
                bundle_path,
                manifest.get("contents"),
                require_ledger=manifest.get("format") in {
                    "spaceworks-phase5a-v2", "spaceworks-phase5a-v3",
                },
            )
        except ArchiveDigestError as exc:
            raise CommandError(str(exc)) from exc
    source_major = manifest.get("postgres", {}).get("source_server_major")
    with connections["default"].cursor() as cursor:
        cursor.execute("SHOW server_version_num")
        target_major = int(cursor.fetchone()[0]) // 10000
    if (
        type(source_major) is not int
        or source_major not in {14, 15, 16, 17}
        or target_major < source_major
    ):
        raise CommandError(
            f"Unsupported PostgreSQL restore: source={source_major}, target={target_major}."
        )
    ops = Path(settings.BACKUP_OPS_DIR)
    if not ops.is_dir() or not os.access(ops, os.R_OK | os.W_OK | os.X_OK):
        raise CommandError(
            "The shared host operation mount is unavailable; legacy in-place restore is excluded."
        )
    for command in ("age", "pg_restore", "pg_dump"):
        if shutil.which(command) is None:
            raise CommandError(f"Required restore binary is missing: {command}.")
    archived_build = manifest.get("build", {})
    current_build = build_info()
    if archived_build.get("source_hash") != current_build.get("source_hash"):
        raise CommandError("Archive and running image build identities do not match.")
    archived_oci = manifest.get("oci_digest") or ""
    current_oci = current_oci_digest or os.environ.get("SPACEWORKS_OCI_DIGEST", "")
    if archived_oci and current_oci and archived_oci != current_oci:
        raise CommandError("Archive and running OCI digests do not match.")
    check_setting_policies(manifest.get("settings", {}))
    for bucket in (settings.AWS_STORAGE_BUCKET_NAME, settings.PUBLIC_IMAGE_BUCKET):
        try:
            storage.client().head_bucket(Bucket=bucket)
        except Exception as exc:
            raise CommandError(
                f"Object-storage capability probe failed for bucket {bucket}."
            ) from exc
