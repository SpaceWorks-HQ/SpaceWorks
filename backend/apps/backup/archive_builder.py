"""Snapshot-consistent archive construction; caller owns remote upload."""
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time

from django.conf import settings
from django.db import connection, transaction

from apps.backup import quiescence, recipients, storage
from apps.backup.archive_payload import (
    CONTINUITY_KEYS,
    OBJECT_FIELD_NAMES,
    _build_info,
    _capture_objects,
    _collect_model_objects,
    _command_version,
    _module_for_model,
    _object_closure,
    _pg_dump,
    _postgres_environment,
    _settings_manifest,
    _snapshot_payload,
    _storage_modes,
    _tenant_payload,
    _write_continuity_keys,
    _write_json,
)
from apps.backup.digests import build_content_ledger, sha256_file
from apps.backup.models import BackupArchive, DeploymentRecoveryState
from apps.backup.recipient_selection import BackupBuildError


def build_archive(archive):
    selected_recipients = recipients.selection_for(archive)
    _require_binary("age")
    if archive.scope == BackupArchive.Scope.DEPLOYMENT:
        _require_binary("pg_dump")
    tempdir = tempfile.TemporaryDirectory(prefix="spaceworks-backup-")
    try:
        root = Path(tempdir.name, "bundle")
        quiescence_enabled = False
        workers_paused = False
        try:
            root.mkdir()
            modes = _storage_modes()
            quiesced = "quiesced" in modes.values()
            if quiesced:
                _set_backup_quiescence(True)
                quiescence_enabled = True
                workers_paused = quiescence.pause_worker_consumers()
                drain_presigned_uploads()
                quiescence.assert_workers_drained()
            manifest = _snapshot_payload(
                archive, root, modes, selected_recipients
            )
            manifest["contents"] = build_content_ledger(root)
            _write_json(root / "manifest.json", manifest)
            encrypted = Path(tempdir.name, f"{archive.id}.tar.age")
            plain = Path(tempdir.name, f"{archive.id}.tar")
            with tarfile.open(plain, "w") as bundle:
                bundle.add(root, arcname=".")
            if _selection_at_read_committed(archive) != manifest["recipients"]:
                raise BackupBuildError(
                    "Archive recipient selection changed before encryption."
                )
            args = ["age"]
            for entry in manifest["recipients"]:
                args += ["-r", entry["public_recipient"]]
            args += ["-o", str(encrypted), str(plain)]
            subprocess.run(
                args,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            plain.unlink()
            return encrypted, manifest, tempdir, sha256_file(encrypted)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise BackupBuildError(
                "The age-encrypted archive could not be built."
            ) from exc
        finally:
            if quiescence_enabled:
                _set_backup_quiescence(False)
                quiescence.resume_worker_consumers(workers_paused)
    except BaseException:
        tempdir.cleanup()
        raise


def _selection_at_read_committed(archive):
    with transaction.atomic(durable=True):
        with connection.cursor() as cursor:
            cursor.execute(
                "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY"
            )
        return recipients.selection_for(archive)


def drain_presigned_uploads(*, sleep=time.sleep):
    """Existing presigned writes cannot be revoked, so drain their bounded TTL."""
    seconds = max(0, int(settings.BACKUP_PRESIGN_DRAIN_SECONDS))
    if seconds:
        sleep(seconds)


def _set_backup_quiescence(enabled):
    with transaction.atomic():
        state = DeploymentRecoveryState.load()
        if enabled and state.mode != DeploymentRecoveryState.Mode.NORMAL:
            raise BackupBuildError("The deployment is already quiesced or quarantined.")
        if not enabled and state.active_restore_id:
            return
        state.mode = DeploymentRecoveryState.Mode.QUIESCED if enabled else DeploymentRecoveryState.Mode.NORMAL
        state.save(update_fields=("mode", "updated_at"))


def _require_binary(command):
    if shutil.which(command) is None:
        raise BackupBuildError(f"Required backup binary is missing: {command}.")
