"""Snapshot-consistent archive construction; caller owns remote upload."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time

from django.apps import apps
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.backup import quiescence, storage
from apps.backup.digests import build_content_ledger, sha256_file
from apps.backup.models import ARCHIVE_PURGE_WARNING, BackupArchive, DeploymentRecoveryState
from apps.backup.settings_policy import POLICIES, Policy
from apps.backup.tenant_projection import project_dataset
from apps.data_export.datasets import DATASET_SPECS


class BackupBuildError(RuntimeError):
    pass


OBJECT_FIELD_NAMES = frozenset({
    "object_key", "image_key", "avatar_key", "cover_image_key", "copy_key",
})
CONTINUITY_KEYS = (
    "SECRET_KEY", "API_CLIENT_ENC_KEY", "PII_MASTER_KEY", "PII_MASTER_KEY_PREVIOUS",
    "PII_SEARCH_HASH_KEY", "HMAC_SECRET", "PUSH_TOKEN_HMAC_KEY", "CRON_SECRET",
)


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


def _snapshot_payload(archive, root, modes):
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT transaction_timestamp(), current_setting('server_version_num')")
            snapshot_at, server_version_num = cursor.fetchone()
            cursor.execute("SELECT pg_export_snapshot()")
            snapshot_id = cursor.fetchone()[0]
        if archive.scope == BackupArchive.Scope.DEPLOYMENT:
            _pg_dump(root / "database.dump", snapshot_id)
            object_keys = _object_closure()
            _write_continuity_keys(root / "keys" / "env.json")
        else:
            object_keys = _tenant_payload(archive.makerspace_id, root / "tenant")
        object_manifest = _capture_objects(root / "objects", object_keys, modes)
    return {
        "format": "spaceworks-phase5a-v2",
        "archive_id": str(archive.pk),
        "scope": archive.scope,
        "makerspace_id": archive.makerspace_id,
        "snapshot_at": snapshot_at.isoformat(),
        "postgres": {
            "source_server_major": int(server_version_num) // 10000,
            "client": _command_version("pg_dump") if archive.scope == BackupArchive.Scope.DEPLOYMENT else "not-used",
            "supported_source_majors": [14, 15, 16, 17],
        },
        "build": _build_info(),
        "oci_digest": os.environ.get("SPACEWORKS_OCI_DIGEST", ""),
        "settings": _settings_manifest(),
        "storage": {"consistency": modes, "objects": object_manifest},
        "age_encrypted": True,
        "purge_warning": ARCHIVE_PURGE_WARNING,
    }


def _pg_dump(destination, snapshot_id):
    env = _postgres_environment()
    command = [
        "pg_dump", "--format=custom", "--no-owner", "--no-acl",
        f"--snapshot={snapshot_id}", f"--file={destination}",
    ]
    subprocess.run(command, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _postgres_environment():
    database = settings.DATABASES["default"]
    env = os.environ.copy()
    mapping = {
        "PGDATABASE": database.get("NAME"),
        "PGUSER": database.get("USER"),
        "PGPASSWORD": database.get("PASSWORD"),
        "PGHOST": database.get("HOST"),
        "PGPORT": database.get("PORT"),
    }
    env.update({key: str(value) for key, value in mapping.items() if value not in (None, "")})
    return env


def drain_presigned_uploads(*, sleep=time.sleep):
    """Existing presigned writes cannot be revoked, so drain their bounded TTL."""
    seconds = max(0, int(settings.BACKUP_PRESIGN_DRAIN_SECONDS))
    if seconds:
        sleep(seconds)


def _tenant_payload(makerspace_id, root):
    root.mkdir(parents=True)
    object_keys = {"private": {}, "public_image": {}}
    referenced_users = set()
    external_references = []
    for label, (_path, predicate) in sorted(DATASET_SPECS.items()):
        model = apps.get_model(label)
        queryset = model.objects.filter(predicate.as_q(makerspace_id)).order_by(model._meta.pk.name)
        payload, references, included_pks = project_dataset(label, queryset, makerspace_id)
        included = queryset.filter(pk__in=included_pks)
        external_references.extend(references)
        destination = root / f"{label.lower().replace('.', '_')}.json"
        destination.write_text(payload, encoding="utf-8")
        _collect_model_objects(included, model, object_keys, fixed_makerspace_id=makerspace_id)
        for field in model._meta.fields:
            if field.remote_field and field.remote_field.model._meta.label == "accounts.User":
                referenced_users.update(included.values_list(field.attname, flat=True))
    User = apps.get_model("accounts.User")
    users = list(User.objects.filter(pk__in=referenced_users).values("id", "username"))
    _write_json(root / "global_user_references.json", users)
    _write_json(root / "external_references.json", external_references)
    return object_keys


def _object_closure():
    result = {"private": {}, "public_image": {}}
    for model in apps.get_models():
        _collect_model_objects(model._default_manager.all(), model, result)
    return result


def _collect_model_objects(queryset, model, result, fixed_makerspace_id=None):
    spec = DATASET_SPECS.get(model._meta.label)
    ownership_paths = spec[1].any_paths if spec else ()
    if not ownership_paths and any(
        field.name == "makerspace" for field in model._meta.concrete_fields
    ):
        ownership_paths = ("makerspace",)
    for field in model._meta.concrete_fields:
        if field.name not in OBJECT_FIELD_NAMES:
            continue
        if field.name == "copy_key":
            for key, kind, owner, module_key in queryset.exclude(copy_key="").values_list(
                "copy_key", "bucket_kind", "makerspace_id", "module_key"
            ):
                result[kind][str(key)] = {
                    "makerspace_id": owner, "module_key": module_key,
                }
            continue
        bucket_kind = "public_image" if field.name != "object_key" else "private"
        value_paths = [path if path in {"pk", "id"} else f"{path}_id" for path in ownership_paths]
        for values in queryset.exclude(**{field.name: ""}).values_list(field.name, *value_paths):
            key, *owners = values
            if key and not str(key).startswith("backup-archives/"):
                owner = fixed_makerspace_id or next((item for item in owners if item), None)
                result[bucket_kind][str(key)] = {
                    "makerspace_id": owner,
                    "module_key": _module_for_model(model._meta.label),
                }


def _capture_objects(root, object_keys, modes):
    manifest = []
    buckets = {"private": settings.AWS_STORAGE_BUCKET_NAME, "public_image": settings.PUBLIC_IMAGE_BUCKET}
    for kind, keys in object_keys.items():
        bucket = buckets[kind]
        for key, ownership in sorted(keys.items()):
            destination = root / kind / key
            item = storage.download_object(bucket, key, destination, versioned=modes[kind] == "versioned")
            manifest.append({"bucket_kind": kind, **ownership, **item})
    return manifest


def _module_for_model(label):
    return {
        "events.Event": "events",
        "bookings.BookableSpace": "bookings",
        "maintenance.MaintenanceLogDocument": "maintenance",
        "procurement.ToBuyReceipt": "procurement",
        "makerspaces.MemberProfile": "membership",
        "makerspaces.MemberProject": "membership",
        "machines.ServiceRequestFile": "machine_service",
    }.get(label, "")


def _storage_modes():
    return {
        "private": storage.ensure_versioning_or_quiescence(settings.AWS_STORAGE_BUCKET_NAME),
        "public_image": storage.ensure_versioning_or_quiescence(settings.PUBLIC_IMAGE_BUCKET),
    }


def _set_backup_quiescence(enabled):
    with transaction.atomic():
        state = DeploymentRecoveryState.load()
        if enabled and state.mode != DeploymentRecoveryState.Mode.NORMAL:
            raise BackupBuildError("The deployment is already quiesced or quarantined.")
        if not enabled and state.active_restore_id:
            return
        state.mode = DeploymentRecoveryState.Mode.QUIESCED if enabled else DeploymentRecoveryState.Mode.NORMAL
        state.save(update_fields=("mode", "updated_at"))


def _write_continuity_keys(path):
    values = {name: os.environ.get(name, "") for name in CONTINUITY_KEYS}
    _write_json(path, values)


def _settings_manifest():
    result = {}
    for name, entry in POLICIES.items():
        if entry.policy == Policy.EXCLUDED:
            continue
        raw = os.environ.get(name, "")
        if entry.policy == Policy.EXACT_FINGERPRINT:
            fact = {"fingerprint": hashlib.sha256(raw.encode()).hexdigest()}
        elif entry.policy == Policy.CAPABILITY_PROBE:
            # Infrastructure credentials never enter the database-backed manifest.
            fact = {"configured": bool(raw)}
        else:
            fact = {"value": raw}
        result[name] = {
            "policy": entry.policy,
            "blocks_restore": entry.blocks_restore,
            **fact,
        }
    return result


def _build_info():
    path = Path("/app/BUILD_INFO.json")
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"git_sha": "unknown", "git_describe": "unknown", "built_at": "unknown", "source_hash": "unknown"}


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, default=str), encoding="utf-8")


def _command_version(command):
    return subprocess.run([command, "--version"], check=True, capture_output=True, text=True).stdout.strip()


def _require_binary(command):
    if shutil.which(command) is None:
        raise BackupBuildError(f"Required backup binary is missing: {command}.")
