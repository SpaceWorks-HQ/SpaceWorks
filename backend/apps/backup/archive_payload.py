"""Database and object-storage payload assembly for backup archives."""
import json
import os
import subprocess

from django.apps import apps
from django.conf import settings
from django.db import connection, transaction

from apps.backup import storage
from apps.backup.archive_metadata import (
    build_info as _build_info,
    settings_manifest as _settings_manifest,
)
from apps.backup.archive_objects import (
    NON_OBJECT_KEY_FIELDS,
    OBJECT_FIELD_NAMES,
    capture_objects as _capture_objects,
    collect_model_objects as _collect_model_objects,
    module_for_model as _module_for_model,
    object_closure as _object_closure,
)
from apps.backup.object_ownership import MAIN_COMPONENT, build_object_ownership_plan
from apps.backup.postgres_client import client_binary
from apps.backup.models import ARCHIVE_PURGE_WARNING, BackupArchive
from apps.backup.raw_projection import canonical_owner_q, no_decrypt_guard, raw_records
from apps.backup.tenant_projection import project_raw_dataset
from apps.data_export.datasets import DATASET_SPECS


CONTINUITY_KEYS = (
    "SECRET_KEY", "API_CLIENT_ENC_KEY", "PII_MASTER_KEY", "PII_MASTER_KEY_PREVIOUS",
    "PII_SEARCH_HASH_KEY", "HMAC_SECRET", "PUSH_TOKEN_HMAC_KEY", "CRON_SECRET",
    # The database carries AuditMacKey.wrapped_key, which is useless without the
    # master key that wrapped it -- so it travels with the other continuity secrets.
    "AUDIT_MAC_MASTER_KEY",
)


def _snapshot_payload(archive, root, modes, selected_recipients, *, compound_capture=None):
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT transaction_timestamp(), current_setting('server_version_num')")
            snapshot_at, server_version_num = cursor.fetchone()
            cursor.execute("SELECT pg_export_snapshot()")
            snapshot_id = cursor.fetchone()[0]
        if archive.scope == BackupArchive.Scope.DEPLOYMENT:
            if archive.backup_run_id:
                covered_makerspace_ids = sorted(
                    int(key)
                    for key, enabled in archive.backup_run.flag_snapshot.items()
                    if enabled is True
                )
            else:
                Makerspace = apps.get_model("makerspaces.Makerspace")
                covered_makerspace_ids = list(
                    Makerspace.objects.order_by("pk").values_list("pk", flat=True)
                )
            _pg_dump(root / "database.dump", snapshot_id)
            if compound_capture is None:
                object_keys = _object_closure()
                object_plan = None
            else:
                compound_capture.prepare_from_snapshot()
                object_plan = build_object_ownership_plan(
                    item.makerspace_id for item in compound_capture.frozen_slices
                )
                object_keys = object_plan.closure(MAIN_COMPONENT)
            _write_continuity_keys(root / "keys" / "env.json")
        else:
            covered_makerspace_ids = [archive.makerspace_id]
            object_keys = _tenant_payload(archive.makerspace_id, root / "tenant")
        object_manifest = _capture_objects(root / "objects", object_keys, modes)
        if compound_capture is not None:
            object_plan.bind_component(
                MAIN_COMPONENT, root / "objects", object_manifest
            )
            compound_capture.capture_from_snapshot(
                tenant_payload=_tenant_payload,
                capture_objects=_capture_objects,
                write_json=_write_json,
                object_plan=object_plan,
            )
    return {
        "format": "spaceworks-phase5a-v3",
        "archive_id": str(archive.pk),
        "backup_run_id": (
            str(archive.backup_run_id) if archive.backup_run_id else None
        ),
        "scope": archive.scope,
        "makerspace_id": archive.makerspace_id,
        "recipients": selected_recipients,
        "covered_makerspace_ids": covered_makerspace_ids,
        "excluded_makerspace_ids": [],
        "partial": False,
        "snapshot_at": snapshot_at.isoformat(),
        "postgres": {
            "source_server_major": int(server_version_num) // 10000,
            "client": _command_version(client_binary("pg_dump"))
            if archive.scope == BackupArchive.Scope.DEPLOYMENT
            else "not-used",
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
        # The server's own client major, not PATH's newest: a 1.16 archive from
        # pg_dump 17 is unreadable by the pg_restore the restore path runs.
        client_binary("pg_dump"), "--format=custom", "--no-owner", "--no-acl",
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


def _tenant_payload(makerspace_id, root):
    # The guard ends with raw row/object-key projection. Future DEK rewrap belongs
    # after this context because it is the separately authorized unwrap phase.
    with no_decrypt_guard():
        root.mkdir(parents=True)
        object_keys = {"private": {}, "public_image": {}}
        referenced_users = set()
        external_references = []
        for label, (_path, predicate) in sorted(DATASET_SPECS.items()):
            model = apps.get_model(label)
            queryset = model.objects.filter(canonical_owner_q(predicate, makerspace_id)).order_by(
                model._meta.pk.name
            )
            records = raw_records(queryset, model)
            payload, references, included_pks = project_raw_dataset(
                label, model, records, makerspace_id
            )
            included = queryset.filter(pk__in=included_pks)
            external_references.extend(references)
            destination = root / f"{label.lower().replace('.', '_')}.json"
            destination.write_text(payload, encoding="utf-8")
            _collect_model_objects(
                included, model, object_keys, fixed_makerspace_id=makerspace_id
            )
            for field in model._meta.fields:
                if (
                    field.remote_field
                    and field.remote_field.model._meta.label == "accounts.User"
                ):
                    referenced_users.update(
                        included.values_list(field.attname, flat=True)
                    )
        User = apps.get_model("accounts.User")
        users = list(
            User.objects.filter(pk__in=referenced_users).values("id", "username")
        )
        _write_json(root / "global_user_references.json", users)
        _write_json(root / "external_references.json", external_references)
        return object_keys


def _storage_modes():
    return {
        "private": storage.ensure_versioning_or_quiescence(settings.AWS_STORAGE_BUCKET_NAME),
        "public_image": storage.ensure_versioning_or_quiescence(settings.PUBLIC_IMAGE_BUCKET),
    }


def _write_continuity_keys(path):
    values = {name: os.environ.get(name, "") for name in CONTINUITY_KEYS}
    _write_json(path, values)


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, default=str), encoding="utf-8")


def _command_version(command):
    return subprocess.run([command, "--version"], check=True, capture_output=True, text=True).stdout.strip()
