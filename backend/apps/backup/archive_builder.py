"""Snapshot-consistent archive construction; caller owns remote upload."""
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time

from django.conf import settings
from django.db import transaction

from apps.backup import quiescence, storage
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


class BackupBuildError(RuntimeError):
    pass


def build_archive(archive):
    if not settings.BACKUP_AGE_RECIPIENT:
        raise BackupBuildError("BACKUP_AGE_RECIPIENT is required before backups can run.")
    _require_binary("age")
    if archive.scope == BackupArchive.Scope.DEPLOYMENT:
        _require_binary("pg_dump")
    tempdir = tempfile.TemporaryDirectory(prefix="spaceworks-backup-")
    root = Path(tempdir.name, "bundle")
    root.mkdir()
    modes = _storage_modes()
    quiesced = "quiesced" in modes.values()
    workers_paused = False
    if quiesced:
        _set_backup_quiescence(True)
        try:
            workers_paused = quiescence.pause_worker_consumers()
            drain_presigned_uploads()
            quiescence.assert_workers_drained()
        except Exception:
            _set_backup_quiescence(False)
            quiescence.resume_worker_consumers(workers_paused)
            tempdir.cleanup()
            raise
    try:
        manifest = _snapshot_payload(archive, root, modes)
        manifest["contents"] = build_content_ledger(root)  # Built before manifest.json; intentionally excluded.
        _write_json(root / "manifest.json", manifest)
        encrypted = Path(tempdir.name, f"{archive.id}.tar.age")
        plain = Path(tempdir.name, f"{archive.id}.tar")
        with tarfile.open(plain, "w") as bundle:
            bundle.add(root, arcname=".")
        subprocess.run(
            ["age", "-r", settings.BACKUP_AGE_RECIPIENT, "-o", str(encrypted), str(plain)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        plain.unlink()
        return encrypted, manifest, tempdir, sha256_file(encrypted)
    except (OSError, subprocess.CalledProcessError) as exc:
        tempdir.cleanup()
        raise BackupBuildError("The age-encrypted archive could not be built.") from exc
    finally:
        if quiesced:
            _set_backup_quiescence(False)
            quiescence.resume_worker_consumers(workers_paused)


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
